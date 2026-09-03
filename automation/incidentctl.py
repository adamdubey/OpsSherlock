#!/usr/bin/env python3
"""Policy-controlled incident automation for the OpsSherlock local lab.

The lab harness may know the injected scenario for evaluation, but detection,
AI diagnosis, and remediation authorization do not use hidden expected RCA.
"""
import argparse
import datetime as dt
import json
import pathlib
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
POLICY = json.loads((ROOT / "automation" / "policy.json").read_text())
ARTIFACTS = ROOT / "artifacts" / "incidents"
PROM = "http://localhost:9090"
GATEWAY = "http://localhost:8080"


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def timeline_event(timeline, phase, status, detail, **extra):
    row = {"timestamp": now(), "phase": phase, "status": status, "detail": detail}
    row.update(extra)
    timeline.append(row)
    print(f"[{phase}] {status}: {detail}")


def prom_query(expr):
    params = urllib.parse.urlencode({"query": expr})
    try:
        with urllib.request.urlopen(f"{PROM}/api/v1/query?{params}", timeout=5) as r:
            return json.loads(r.read().decode()).get("data", {}).get("result", [])
    except Exception:
        return []


def scalar(result, default=0.0):
    if not result:
        return default
    try:
        return float(result[0]["value"][1])
    except Exception:
        return default


def detect(timeout=45):
    """Detect user-visible degradation from telemetry only."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        p95 = scalar(prom_query(
            'histogram_quantile(0.95, sum by (le) (rate(checkout_request_duration_seconds_bucket[1m])))'
        ))
        errors = scalar(prom_query(
            'sum(rate(http_server_requests_total{status=~"5.."}[1m]))'
        ))
        down = prom_query('up{job="baker-street"} == 0')
        fault = scalar(prom_query('max(checkout_fault_active)'))
        if p95 >= 0.75:
            return {"trigger": "checkout_p95", "value": p95, "threshold": 0.75}
        if errors > 0:
            return {"trigger": "http_5xx_rate", "value": errors, "threshold": 0}
        if down:
            return {"trigger": "service_down", "series": down}
        if fault > 0:
            return {"trigger": "checkout_fault_metric", "value": fault, "threshold": 0}
        time.sleep(2)
    return None


def newest_incident(before=None):
    candidates = [p for p in ARTIFACTS.glob("*/incident.json") if not before or p.stat().st_mtime >= before]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def run_investigator(scenario, timeline):
    started = time.time()
    cmd = [
        "docker", "compose", "--profile", "tools", "run", "--rm", "--build",
        "agent", "python", "investigator.py", "--scenario", scenario,
    ]
    proc = subprocess.run(cmd, cwd=ROOT, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"investigator exited with status {proc.returncode}")
    path = newest_incident(started - 1)
    if not path:
        raise RuntimeError("investigator completed but no incident artifact was created")
    record = json.loads(path.read_text())
    timeline_event(timeline, "investigation", "complete", "AI investigation artifact created", incident_id=record["id"])
    return path, record


def capture_evidence(incident_id, phase, timeline):
    """Capture Grafana screenshots without making evidence collection incident-critical."""
    cmd = [
        "docker", "compose", "--profile", "tools", "run", "--rm", "--build",
        "publisher", "--incident", incident_id, "--phase", phase,
    ]
    proc = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True)
    manifest_path = ARTIFACTS / incident_id / "evidence" / f"{phase}-manifest.json"
    if proc.returncode == 0 and manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        captured = sum(1 for x in manifest.get("screenshots", []) if x.get("status") == "captured")
        timeline_event(timeline, "evidence", "captured", f"Captured {captured} Grafana screenshots", phase_name=phase)
        return manifest
    detail = (proc.stderr or proc.stdout or f"publisher exited {proc.returncode}").strip()[-800:]
    timeline_event(timeline, "evidence", "warning", "Grafana screenshot capture failed; incident response continues", phase_name=phase)
    return {"phase": phase, "status": "error", "error": detail}


def authorize(diagnosis):
    action = diagnosis.get("remediation_action", "none")
    confidence = float(diagnosis.get("confidence", 0) or 0)
    rule = POLICY["allowed_actions"].get(action)
    if not rule:
        return {"approved": False, "action": action, "reason": "action is not allowlisted"}
    if confidence < POLICY["minimum_confidence"]:
        return {
            "approved": False,
            "action": action,
            "reason": f"confidence {confidence:.2f} is below {POLICY['minimum_confidence']:.2f}",
        }
    affected = str(diagnosis.get("affected_service", "")).lower()
    if affected not in [x.lower() for x in rule["affected_services"]]:
        return {"approved": False, "action": action, "reason": f"affected service {affected!r} is inconsistent with policy"}
    hay = json.dumps(diagnosis).lower()
    missing = [term for term in rule.get("required_terms", []) if term.lower() not in hay]
    if missing:
        return {"approved": False, "action": action, "reason": f"required diagnosis terms missing: {', '.join(missing)}"}
    return {"approved": True, "action": action, "reason": "allowlist, confidence, service, and evidence-term checks passed", "risk": rule["risk"]}


def execute_action(action):
    mapping = {
        "reset_checkout_fault": [sys.executable, "chaos/chaosctl.py", "repair", "checkout"],
        "reset_redis_proxy": [sys.executable, "chaos/chaosctl.py", "repair", "redis"],
        "reset_payments_proxy": [sys.executable, "chaos/chaosctl.py", "repair", "payments"],
        "reset_postgres_proxy": [sys.executable, "chaos/chaosctl.py", "repair", "postgres"],
        "restart_payments": [sys.executable, "chaos/chaosctl.py", "repair", "payments-service"],
    }
    cmd = mapping.get(action)
    if not cmd:
        raise RuntimeError(f"no executor for approved action: {action}")
    subprocess.run(cmd, cwd=ROOT, check=True)


def verify_recovery():
    cfg = POLICY["verification"]
    time.sleep(cfg.get("settle_seconds", 2))
    successes = []
    body = b'{"sku":"OPS-001","quantity":1,"payment_token":"tok_demo"}'
    for _ in range(int(cfg["checkout_requests"])):
        req = urllib.request.Request(
            f"{GATEWAY}/api/checkout",
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=cfg["request_timeout_seconds"]) as r:
                successes.append(200 <= r.status < 300)
        except Exception:
            successes.append(False)
        time.sleep(0.15)
    ratio = sum(successes) / len(successes)
    return {
        "requests": len(successes),
        "successes": sum(successes),
        "success_ratio": ratio,
        "required_ratio": cfg["minimum_success_ratio"],
        "pass": ratio >= cfg["minimum_success_ratio"],
    }


def fallback_reset():
    subprocess.run([sys.executable, "chaos/chaosctl.py", "reset"], cwd=ROOT, check=True)


def persist(path, record, timeline, automation):
    record["automation"] = automation
    record["timeline"] = timeline
    path.write_text(json.dumps(record, indent=2))

    outdir = path.parent
    (outdir / "timeline.json").write_text(json.dumps(timeline, indent=2))
    lines = ["# Incident timeline", ""]
    for row in timeline:
        lines.append(f"- **{row['timestamp']}** — `{row['phase']}` / **{row['status']}** — {row['detail']}")
    (outdir / "timeline.md").write_text("\n".join(lines) + "\n")

    post = outdir / "postmortem.md"
    existing = post.read_text() if post.exists() else ""
    appendix = f"""

## Automated response

- Detector: `{automation.get('detection', {}).get('trigger', 'none')}`
- Proposed action: `{automation.get('authorization', {}).get('action', 'none')}`
- Policy decision: `{'APPROVED' if automation.get('authorization', {}).get('approved') else 'DENIED'}`
- Policy reason: {automation.get('authorization', {}).get('reason', 'n/a')}
- Recovery verified: `{automation.get('recovery', {}).get('pass', False)}`
- Fallback reset used: `{automation.get('fallback_used', False)}`

See `timeline.json` for the machine-readable incident timeline.
"""
    post.write_text(existing + appendix)


def main():
    parser = argparse.ArgumentParser(description="OpsSherlock automated incident response controller")
    parser.add_argument("--scenario", required=True, help="lab-only scenario name used for benchmark evaluation")
    parser.add_argument("--detect-timeout", type=int, default=45)
    parser.add_argument("--no-remediate", action="store_true")
    args = parser.parse_args()

    timeline = []
    automation = {"mode": "policy-controlled", "fallback_used": False}
    timeline_event(timeline, "detection", "waiting", "Monitoring Baker Street telemetry for an incident trigger")
    detection = detect(args.detect_timeout)
    if not detection:
        timeline_event(timeline, "detection", "timeout", "No qualifying incident signal detected")
        raise SystemExit(2)
    automation["detection"] = detection
    timeline_event(timeline, "detection", "triggered", f"Detected {detection['trigger']}", detection=detection)

    path, record = run_investigator(args.scenario, timeline)
    automation["evidence"] = {"investigation": capture_evidence(record["id"], "investigation", timeline)}
    diagnosis = record.get("diagnosis", {})
    decision = authorize(diagnosis)
    automation["authorization"] = decision
    timeline_event(timeline, "policy", "approved" if decision["approved"] else "denied", decision["reason"], action=decision.get("action"))

    if args.no_remediate or not decision["approved"]:
        automation["recovery"] = {"pass": False, "skipped": True}
        timeline_event(timeline, "remediation", "skipped", "No autonomous action executed")
        automation["evidence"]["final"] = capture_evidence(record["id"], "final", timeline)
        persist(path, record, timeline, automation)
        print(json.dumps({"incident": record["id"], "automation": automation}, indent=2))
        return

    timeline_event(timeline, "remediation", "started", f"Executing approved action {decision['action']}")
    execute_action(decision["action"])
    timeline_event(timeline, "remediation", "complete", f"Executed {decision['action']}")

    recovery = verify_recovery()
    automation["recovery"] = recovery
    if recovery["pass"]:
        timeline_event(timeline, "verification", "passed", f"Recovery verified: {recovery['successes']}/{recovery['requests']} synthetic checkouts succeeded")
    else:
        timeline_event(timeline, "verification", "failed", f"Recovery failed: {recovery['successes']}/{recovery['requests']} synthetic checkouts succeeded")
        if POLICY.get("fallback", {}).get("enabled"):
            fallback_reset()
            automation["fallback_used"] = True
            timeline_event(timeline, "rollback_guard", "executed", "Applied lab-wide chaos reset after failed recovery verification")
            fallback_verification = verify_recovery()
            automation["fallback_recovery"] = fallback_verification
            timeline_event(
                timeline,
                "rollback_guard",
                "passed" if fallback_verification["pass"] else "failed",
                f"Fallback recovery: {fallback_verification['successes']}/{fallback_verification['requests']} synthetic checkouts succeeded",
            )

    automation["evidence"]["recovery"] = capture_evidence(record["id"], "recovery", timeline)
    persist(path, record, timeline, automation)
    print(json.dumps({"incident": record["id"], "automation": automation, "artifact": str(path.parent)}, indent=2))


if __name__ == "__main__":
    main()
