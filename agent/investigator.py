import argparse
import datetime as dt
import json
import os
import pathlib
import time

import requests
import yaml

PROM = os.getenv("PROMETHEUS_URL", "http://prometheus:9090")
LOKI = os.getenv("LOKI_URL", "http://loki:3100")
TEMPO = os.getenv("TEMPO_URL", "http://tempo:3200")
OLLAMA = os.getenv("OLLAMA_URL", "http://ollama:11434")
MODEL = os.getenv("OLLAMA_MODEL", "qwen3:8b")
ROOT = pathlib.Path("/app")

QUERIES = {
    "checkout_p95": 'histogram_quantile(0.95, sum by (le) (rate(checkout_request_duration_seconds_bucket[1m])))',
    "checkout_rate": 'sum(rate(checkout_requests_total[1m]))',
    "fault_active": 'max(checkout_fault_active)',
    "service_error_rate": 'sum by (service) (rate(http_server_requests_total{status=~"5.."}[1m]))',
    "service_p95": 'histogram_quantile(0.95, sum by (service, le) (rate(http_server_request_duration_seconds_bucket[5m])))',
    "service_up": 'up{job="baker-street"}',
}


def prom_query(expr):
    try:
        r = requests.get(f"{PROM}/api/v1/query", params={"query": expr}, timeout=5)
        r.raise_for_status()
        return r.json()["data"]["result"]
    except Exception as exc:
        return {"error": str(exc)}


def loki_logs(minutes=10, limit=120):
    try:
        end = int(time.time() * 1_000_000_000)
        start = end - minutes * 60 * 1_000_000_000
        query = '{compose_project="opssherlock", service=~"gateway|catalog|checkout|payments|orders"} | json'
        r = requests.get(
            f"{LOKI}/loki/api/v1/query_range",
            params={"query": query, "start": start, "end": end, "limit": limit, "direction": "backward"},
            timeout=8,
        )
        r.raise_for_status()
        streams = r.json()["data"]["result"]
        lines = []
        for stream in streams:
            labels = stream.get("stream", {})
            for ts, line in stream.get("values", []):
                lines.append({"ts_ns": ts, "service": labels.get("service"), "line": line})
        return lines[:limit]
    except Exception as exc:
        return {"error": str(exc)}


def tempo_traces(limit=12):
    try:
        r = requests.get(
            f"{TEMPO}/api/search",
            params={"q": '{ resource.service.name = "checkout" }', "limit": limit},
            timeout=8,
        )
        r.raise_for_status()
        traces = r.json().get("traces", [])
        return [
            {
                "trace_id": t.get("traceID"),
                "root_service": t.get("rootServiceName"),
                "root_span": t.get("rootTraceName"),
                "duration_ms": t.get("durationMs"),
                "start_time_unix_nano": t.get("startTimeUnixNano"),
            }
            for t in traces[:limit]
        ]
    except Exception as exc:
        return {"error": str(exc)}


def docker_status():
    try:
        import docker

        client = docker.from_env()
        out = {}
        for c in client.containers.list():
            if any(name in c.name for name in ["checkout", "catalog", "gateway", "payments", "orders"]):
                out[c.name] = {"status": c.status, "image": c.image.tags[:2]}
        return out
    except Exception as exc:
        return {"error": str(exc)}


def ask_ollama(evidence, scenario):
    prompt = f"""You are OpsSherlock, a cautious SRE incident investigator.
Analyze only the evidence supplied. Do not invent facts.
Correlate metrics, centralized logs, recent distributed trace summaries, and container status.
Return JSON with keys: affected_service, root_cause, confidence (0-1), evidence (array), remediation, safety_note.
Scenario metadata is for labeling only; expected/ground-truth fields are NOT provided to you.

SCENARIO: {scenario['title']} ({scenario['severity']})
EVIDENCE:\n{json.dumps(evidence, indent=2)[:18000]}
"""
    payload = {"model": MODEL, "prompt": prompt, "stream": False, "format": "json"}
    try:
        r = requests.post(f"{OLLAMA}/api/generate", json=payload, timeout=180)
        r.raise_for_status()
        raw = r.json().get("response", "{}")
        return json.loads(raw)
    except Exception as exc:
        return {"error": str(exc), "root_cause": "model unavailable", "confidence": 0}


def score(diagnosis, scenario):
    expected = scenario["expected"]
    hay = json.dumps(diagnosis).lower()
    service_ok = expected["affected_service"].lower() in hay
    root_terms = ["latency", "checkout"]
    root_ok = all(t in hay for t in root_terms)
    return {"service_match": service_ok, "root_cause_match": root_ok, "pass": service_ok and root_ok}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--scenario", default="checkout_latency")
    args = p.parse_args()
    scenario = yaml.safe_load((ROOT / "scenarios" / f"{args.scenario}.yml").read_text())

    evidence = {
        "captured_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "metrics": {name: prom_query(q) for name, q in QUERIES.items()},
        "centralized_logs": loki_logs(),
        "recent_traces": tempo_traces(),
        "containers": docker_status(),
    }
    public_scenario = {k: v for k, v in scenario.items() if k != "expected"}
    diagnosis = ask_ollama(evidence, public_scenario)
    evaluation = score(diagnosis, scenario)

    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    incident_id = f"INC-{ts}-{args.scenario}"
    outdir = ROOT / "artifacts" / "incidents" / incident_id
    outdir.mkdir(parents=True, exist_ok=True)
    record = {
        "id": incident_id,
        "scenario": scenario,
        "evidence": evidence,
        "diagnosis": diagnosis,
        "evaluation": evaluation,
    }
    (outdir / "incident.json").write_text(json.dumps(record, indent=2))

    trace_rows = evidence.get("recent_traces", [])
    trace_text = "\n".join(
        f"- `{t.get('trace_id')}` — {t.get('root_service')} / {t.get('root_span')} — {t.get('duration_ms')} ms"
        for t in trace_rows[:6]
        if isinstance(t, dict)
    ) or "- No trace summaries available."

    md = f"""# {incident_id}: {scenario['title']}

**Severity:** {scenario['severity']}  
**Evaluation:** {'PASS' if evaluation['pass'] else 'FAIL'}  
**Model:** `{MODEL}`

## AI root-cause analysis

**Affected service:** {diagnosis.get('affected_service', 'unknown')}  
**Root cause:** {diagnosis.get('root_cause', 'unknown')}  
**Confidence:** {diagnosis.get('confidence', 0)}

## Evidence cited

""" + "\n".join(f"- {x}" for x in diagnosis.get("evidence", [])) + f"""

## Recent distributed traces

{trace_text}

## Recommended remediation

{diagnosis.get('remediation', 'n/a')}

## Ground truth

- Affected service: `{scenario['expected']['affected_service']}`
- Root cause: `{scenario['expected']['root_cause']}`
- Expected remediation: `{scenario['expected']['remediation']}`

## Evaluation

```json
{json.dumps(evaluation, indent=2)}
```

> Lab incident: this fault was intentionally injected and ground truth is known.
"""
    (outdir / "postmortem.md").write_text(md)
    print(json.dumps({"incident": incident_id, "evaluation": evaluation, "artifact": str(outdir)}, indent=2))


if __name__ == "__main__":
    main()
