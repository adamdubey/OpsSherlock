#!/usr/bin/env python3
"""Publish validated OpsSherlock incident evidence to a dedicated Git branch.

The source tree stays on ``main`` while public incident artifacts are persisted on
an ``evidence`` branch.  GitHub Pages checks out both branches and generates the
portal from the evidence archive.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
INCIDENTS = ROOT / "artifacts" / "incidents"
DEFAULT_BRANCH = os.getenv("EVIDENCE_BRANCH", "evidence")
DEFAULT_REMOTE = os.getenv("EVIDENCE_REMOTE", "origin")

REQUIRED_FILES = ("incident.json", "timeline.json", "postmortem.md")


class PublishError(RuntimeError):
    pass


def run(*args: str, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    command = [str(a) for a in args]
    result = subprocess.run(
        command,
        cwd=str(cwd or ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise PublishError(f"command failed: {' '.join(command)}\n{detail}")
    return result


def git(*args: str, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run("git", *args, cwd=cwd, check=check)


def ensure_git_repo() -> None:
    if git("rev-parse", "--is-inside-work-tree", check=False).returncode != 0:
        raise PublishError("run this command from inside the OpsSherlock Git repository")


def latest_incident() -> Path:
    candidates = [p for p in INCIDENTS.iterdir() if p.is_dir() and (p / "incident.json").exists()]
    if not candidates:
        raise PublishError("no local incidents found under artifacts/incidents")
    return max(candidates, key=lambda p: (p / "incident.json").stat().st_mtime)


def validate_incident(path: Path) -> dict:
    missing = [name for name in REQUIRED_FILES if not (path / name).is_file()]
    if missing:
        raise PublishError(f"{path.name}: missing required artifact(s): {', '.join(missing)}")

    try:
        incident = json.loads((path / "incident.json").read_text(encoding="utf-8"))
    except Exception as exc:
        raise PublishError(f"{path.name}: invalid incident.json: {exc}") from exc

    if incident.get("id") != path.name:
        raise PublishError(
            f"{path.name}: incident.json id is {incident.get('id')!r}; directory and incident id must match"
        )

    try:
        timeline = json.loads((path / "timeline.json").read_text(encoding="utf-8"))
    except Exception as exc:
        raise PublishError(f"{path.name}: invalid timeline.json: {exc}") from exc

    if not isinstance(timeline, (list, dict)):
        raise PublishError(f"{path.name}: timeline.json must contain a JSON object or array")

    evidence = path / "evidence"
    captured = 0
    manifest_errors: list[str] = []
    if evidence.exists():
        for manifest_path in sorted(evidence.glob("*-manifest.json")):
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except Exception as exc:
                raise PublishError(f"{path.name}: invalid {manifest_path.name}: {exc}") from exc
            for shot in manifest.get("screenshots", []):
                if shot.get("status") != "captured":
                    manifest_errors.append(f"{manifest_path.name}:{shot.get('label', 'unknown')}")
                    continue
                rel = shot.get("file")
                if not rel or not (path / rel).is_file():
                    raise PublishError(
                        f"{path.name}: manifest references missing screenshot: {rel or '<missing file field>'}"
                    )
                captured += 1

    return {
        "id": path.name,
        "rca_pass": bool(incident.get("evaluation", {}).get("pass")),
        "captured_screenshots": captured,
        "capture_errors": manifest_errors,
    }


def remote_branch_exists(remote: str, branch: str) -> bool:
    result = git("ls-remote", "--exit-code", "--heads", remote, branch, check=False)
    return result.returncode == 0


def create_worktree(worktree: Path, remote: str, branch: str) -> None:
    # Remove stale local evidence branch left by an interrupted publish only when
    # it has no attached worktree. The remote remains authoritative.
    git("fetch", remote, "--prune")

    if remote_branch_exists(remote, branch):
        local_exists = git("show-ref", "--verify", f"refs/heads/{branch}", check=False).returncode == 0
        if local_exists:
            git("branch", "-f", branch, f"{remote}/{branch}")
        else:
            git("branch", branch, f"{remote}/{branch}")
        git("worktree", "add", str(worktree), branch)
        return

    # First publish: create a clean orphan archive branch with no source-code history.
    git("worktree", "add", "--detach", str(worktree), "HEAD")
    git("checkout", "--orphan", branch, cwd=worktree)
    for child in list(worktree.iterdir()):
        if child.name == ".git":
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    (worktree / "incidents").mkdir(parents=True, exist_ok=True)
    (worktree / "README.md").write_text(
        "# OpsSherlock Evidence Archive\n\n"
        "This branch is managed by `make publish-evidence`. It stores public, reproducible "
        "incident artifacts consumed by the GitHub Pages publishing workflow.\n",
        encoding="utf-8",
    )


def copy_incident(source: Path, destination_root: Path) -> Path:
    destination = destination_root / "incidents" / source.name
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)
    return destination


def commit_and_push(worktree: Path, remote: str, branch: str, incident_id: str) -> bool:
    git("add", "incidents", "README.md", cwd=worktree)
    status = git("status", "--porcelain", cwd=worktree).stdout.strip()
    if not status:
        print(f"evidence unchanged: {incident_id} is already published")
        return False

    git("commit", "-m", f"evidence: publish {incident_id}", cwd=worktree)
    git("push", "-u", remote, branch, cwd=worktree)
    return True


def trigger_pages() -> None:
    gh = shutil.which("gh")
    if not gh:
        print("note: GitHub CLI not found; run the 'Deploy incident portal' workflow manually.")
        return

    auth = run(gh, "auth", "status", check=False)
    if auth.returncode != 0:
        print("note: GitHub CLI is not authenticated; run the Pages workflow manually.")
        return

    result = run(gh, "workflow", "run", "pages.yml", "--ref", "main", check=False)
    if result.returncode == 0:
        print("Pages workflow dispatched on main.")
    else:
        print("note: evidence was pushed, but automatic Pages dispatch failed:")
        print((result.stderr or result.stdout).strip())
        print("Run the 'Deploy incident portal' workflow manually in GitHub Actions.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--incident", help="incident id to publish; defaults to newest local incident")
    parser.add_argument("--branch", default=DEFAULT_BRANCH)
    parser.add_argument("--remote", default=DEFAULT_REMOTE)
    parser.add_argument("--no-trigger", action="store_true", help="do not dispatch the Pages workflow with gh")
    parser.add_argument("--validate-only", action="store_true", help="validate evidence but do not touch Git")
    args = parser.parse_args()

    try:
        source = INCIDENTS / args.incident if args.incident else latest_incident()
        if not source.is_dir():
            raise PublishError(f"incident not found: {source}")

        summary = validate_incident(source)
        print(
            f"validated {summary['id']}: "
            f"RCA={'PASS' if summary['rca_pass'] else 'FAIL'}, "
            f"screenshots={summary['captured_screenshots']}, "
            f"capture_errors={len(summary['capture_errors'])}"
        )

        if args.validate_only:
            return 0

        ensure_git_repo()
        if git("remote", "get-url", args.remote, check=False).returncode != 0:
            raise PublishError(f"Git remote {args.remote!r} does not exist")

        # Do not require a clean source worktree: generated incidents are ignored by Git
        # and publishing happens in a temporary worktree.
        with tempfile.TemporaryDirectory(prefix="opssherlock-evidence-") as temp:
            worktree = Path(temp) / "archive"
            try:
                create_worktree(worktree, args.remote, args.branch)
                destination = copy_incident(source, worktree)
                print(f"staged {destination.relative_to(worktree)} on branch {args.branch!r}")
                changed = commit_and_push(worktree, args.remote, args.branch, source.name)
            finally:
                if worktree.exists():
                    git("worktree", "remove", "--force", str(worktree), check=False)

        if changed and not args.no_trigger:
            trigger_pages()

        print(f"published evidence: {source.name} -> {args.remote}/{args.branch}")
        return 0
    except PublishError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
