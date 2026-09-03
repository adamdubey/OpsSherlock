#!/usr/bin/env python3
"""Capture reproducible Grafana evidence for an OpsSherlock incident."""

import argparse
import datetime as dt
import json
import os
import pathlib
import time
from urllib.parse import urlencode

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

GRAFANA = os.getenv("GRAFANA_URL", "http://grafana:3000").rstrip("/")
ROOT = pathlib.Path("/app")
DASHBOARDS = [
    ("incident-investigation", "incident-investigation", "incident-investigation"),
    ("baker-street-overview", "baker-street-overview", "baker-street-overview"),
]
GRAFANA_FAILURE_TEXT = "Grafana has failed to load its application files"


def ms(ts: dt.datetime) -> int:
    return int(ts.timestamp() * 1000)


def assert_grafana_booted(page, timeout_ms: int = 30_000) -> None:
    page.wait_for_selector("body", state="attached", timeout=timeout_ms)
    body_text = page.locator("body").inner_text()
    if GRAFANA_FAILURE_TEXT in body_text:
        raise RuntimeError("Grafana frontend failed to load its application files")


def capture_dashboard(page, *, url: str, target: pathlib.Path, settle_seconds: float) -> None:
    print(f"loading {url}")
    response = page.goto(url, wait_until="domcontentloaded", timeout=30_000)
    if response is None:
        raise RuntimeError("Grafana navigation returned no HTTP response")
    if not response.ok:
        raise RuntimeError(f"Grafana returned HTTP {response.status}")

    assert_grafana_booted(page)
    try:
        page.wait_for_load_state("networkidle", timeout=15_000)
    except PlaywrightTimeoutError:
        # Grafana dashboards may keep background requests active.
        pass

    time.sleep(settle_seconds)
    assert_grafana_booted(page)
    page.screenshot(path=str(target), full_page=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--incident", required=True)
    parser.add_argument("--phase", required=True, choices=["investigation", "recovery", "final"])
    parser.add_argument("--lookback-minutes", type=int, default=15)
    parser.add_argument("--settle-seconds", type=float, default=5)
    args = parser.parse_args()

    outdir = ROOT / "artifacts" / "incidents" / args.incident / "evidence"
    outdir.mkdir(parents=True, exist_ok=True)

    end = dt.datetime.now(dt.timezone.utc)
    start = end - dt.timedelta(minutes=args.lookback_minutes)
    manifest = {
        "captured_at": end.isoformat(),
        "phase": args.phase,
        "grafana_url": GRAFANA,
        "window": {"from": start.isoformat(), "to": end.isoformat()},
        "screenshots": [],
    }

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1600, "height": 1000},
            device_scale_factor=1,
            locale="en-US",
            timezone_id="UTC",
        )
        page = context.new_page()
        page.on("pageerror", lambda exc: print(f"[browser page error] {exc}"))
        page.on(
            "console",
            lambda msg: print(f"[browser console:{msg.type}] {msg.text}")
            if msg.type in {"error", "warning"}
            else None,
        )
        page.on(
            "requestfailed",
            lambda request: print(
                f"[browser request failed] {request.method} {request.url} {request.failure}"
            ),
        )

        for uid, slug, label in DASHBOARDS:
            params = urlencode({"orgId": 1, "from": ms(start), "to": ms(end), "kiosk": ""})
            url = f"{GRAFANA}/d/{uid}/{slug}?{params}"
            filename = f"{args.phase}-{label}.png"
            target = outdir / filename
            try:
                capture_dashboard(page, url=url, target=target, settle_seconds=args.settle_seconds)
                manifest["screenshots"].append(
                    {
                        "dashboard_uid": uid,
                        "label": label,
                        "file": f"evidence/{filename}",
                        "status": "captured",
                    }
                )
                print(f"captured {target}")
            except (PlaywrightError, RuntimeError) as exc:
                if target.exists():
                    target.unlink()
                manifest["screenshots"].append(
                    {
                        "dashboard_uid": uid,
                        "label": label,
                        "file": f"evidence/{filename}",
                        "status": "error",
                        "error": str(exc),
                    }
                )
                print(f"warning: could not capture {label}: {exc}")

        context.close()
        browser.close()

    manifest_path = outdir / f"{args.phase}-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
