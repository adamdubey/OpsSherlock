#!/usr/bin/env python3
import argparse
import json
import pathlib
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCENARIOS = json.loads((ROOT / "chaos" / "scenarios.json").read_text())
TOXI = "http://localhost:8474"
PROXIES = {
    "payments": {"listen": "0.0.0.0:8666", "upstream": "payments:8000"},
    "redis": {"listen": "0.0.0.0:8667", "upstream": "redis:6379"},
    "postgres": {"listen": "0.0.0.0:8668", "upstream": "postgres:5432"},
}


def request(method, url, body=None, ok=(200, 201, 204)):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            payload = r.read().decode()
            if r.status not in ok:
                raise RuntimeError(f"{method} {url}: HTTP {r.status}: {payload}")
            return json.loads(payload) if payload else None
    except urllib.error.HTTPError as exc:
        text = exc.read().decode()
        raise RuntimeError(f"{method} {url}: HTTP {exc.code}: {text}") from exc


def wait_toxi():
    for _ in range(30):
        try:
            request("GET", f"{TOXI}/proxies")
            return
        except Exception:
            time.sleep(1)
    raise RuntimeError("Toxiproxy API did not become ready on localhost:8474")


def setup():
    wait_toxi()
    existing = request("GET", f"{TOXI}/proxies") or {}
    for name, cfg in PROXIES.items():
        body = {"name": name, **cfg, "enabled": True}
        if name in existing:
            request("POST", f"{TOXI}/proxies/{name}", body)
        else:
            request("POST", f"{TOXI}/proxies", body)
    print("Chaos proxies ready: payments=:8666 redis=:8667 postgres=:8668")


def clear_toxics(proxy):
    toxics = request("GET", f"{TOXI}/proxies/{proxy}/toxics") or []
    for toxic in toxics:
        request("DELETE", f"{TOXI}/proxies/{proxy}/toxics/{toxic['name']}")


def reset():
    setup()
    for name, cfg in PROXIES.items():
        clear_toxics(name)
        request("POST", f"{TOXI}/proxies/{name}", {"name": name, **cfg, "enabled": True})
    try:
        urllib.request.urlopen(urllib.request.Request("http://localhost:8001/admin/fault/reset", data=b"", method="POST"), timeout=5).read()
    except Exception:
        pass
    subprocess.run(["docker", "compose", "up", "-d", "payments"], cwd=ROOT, check=False, stdout=subprocess.DEVNULL)
    print("Chaos state reset")


def generate_traffic(spec):
    n = int(spec.get("requests", 10))
    delay = int(spec.get("interval_ms", 150)) / 1000
    body = b'{"sku":"OPS-001","quantity":1,"payment_token":"tok_demo"}'
    successes = failures = 0
    for _ in range(n):
        req = urllib.request.Request("http://localhost:8080/api/checkout", data=body, method="POST", headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=8) as r:
                successes += int(200 <= r.status < 300)
        except Exception:
            failures += 1
        time.sleep(delay)
    print(f"Traffic complete: requests={n} success={successes} failed={failures}")


def inject(name):
    if name not in SCENARIOS:
        raise RuntimeError(f"unknown scenario: {name}")
    reset()
    scenario = SCENARIOS[name]
    inj = scenario["injector"]
    kind = inj["kind"]
    if kind == "checkout_fault":
        request("POST", f"http://localhost:8001/admin/fault/{inj['name']}", {})
    elif kind == "toxic":
        body = {
            "name": f"opssherlock_{name}",
            "type": inj["type"],
            "stream": inj.get("stream", "downstream"),
            "toxicity": 1.0,
            "attributes": inj.get("attributes", {}),
        }
        request("POST", f"{TOXI}/proxies/{inj['proxy']}/toxics", body)
    elif kind == "proxy_down":
        cfg = PROXIES[inj["proxy"]]
        request("POST", f"{TOXI}/proxies/{inj['proxy']}", {"name": inj["proxy"], **cfg, "enabled": False})
    elif kind == "container_stop":
        subprocess.run(["docker", "compose", "stop", inj["service"]], cwd=ROOT, check=True)
    else:
        raise RuntimeError(f"unsupported injector kind: {kind}")
    print(f"Injected {name}: {scenario['title']} [{scenario['severity']}/{scenario['difficulty']}]")
    generate_traffic(scenario.get("traffic", {}))


def status():
    wait_toxi()
    data = request("GET", f"{TOXI}/proxies")
    print(json.dumps(data, indent=2))


def list_scenarios():
    for name, s in SCENARIOS.items():
        print(f"{name:28} {s['severity']:5} {s['difficulty']:6} {s['title']}")


def main():
    p = argparse.ArgumentParser(description="OpsSherlock deterministic chaos controller")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("setup")
    sub.add_parser("reset")
    sub.add_parser("status")
    sub.add_parser("list")
    i = sub.add_parser("inject")
    i.add_argument("scenario")
    args = p.parse_args()
    try:
        {"setup": setup, "reset": reset, "status": status, "list": list_scenarios}.get(args.cmd, lambda: inject(args.scenario))()
    except Exception as exc:
        print(f"chaosctl: {exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
