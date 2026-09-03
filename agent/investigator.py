import argparse
import datetime as dt
import json
import os
import pathlib
import time

import requests

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


def _attr_map(attrs):
    out = {}
    for item in attrs or []:
        value = item.get("value", {})
        for key in ("stringValue", "intValue", "doubleValue", "boolValue"):
            if key in value:
                out[item.get("key")] = value[key]
                break
    return out


def tempo_traces(logs, limit=8):
    """Fetch exact recent traces using trace IDs already observed in centralized logs."""
    trace_ids = []
    if isinstance(logs, list):
        for row in logs:
            try:
                payload = json.loads(row.get("line", "{}"))
            except Exception:
                continue
            tid = payload.get("trace_id")
            if tid and tid != "-" and tid not in trace_ids:
                trace_ids.append(tid)
            if len(trace_ids) >= limit:
                break

    summaries = []
    for trace_id in trace_ids:
        try:
            r = requests.get(f"{TEMPO}/api/v2/traces/{trace_id}", timeout=8)
            if r.status_code == 404:
                continue
            r.raise_for_status()
            doc = r.json().get("trace", {})
            spans = []
            for rs in doc.get("resourceSpans", []):
                resource = _attr_map(rs.get("resource", {}).get("attributes", []))
                service = resource.get("service.name", "unknown")
                for scope in rs.get("scopeSpans", []):
                    for span in scope.get("spans", []):
                        start_ns = int(span.get("startTimeUnixNano", 0) or 0)
                        end_ns = int(span.get("endTimeUnixNano", 0) or 0)
                        attrs = _attr_map(span.get("attributes", []))
                        spans.append({
                            "service": service,
                            "name": span.get("name"),
                            "duration_ms": round((end_ns - start_ns) / 1_000_000, 2) if end_ns >= start_ns else None,
                            "http_url": attrs.get("http.url"),
                            "http_status": attrs.get("http.status_code") or attrs.get("http.response.status_code"),
                            "db_system": attrs.get("db.system"),
                            "db_operation": attrs.get("db.operation.name"),
                            "peer_service": attrs.get("peer.service"),
                        })
            spans.sort(key=lambda x: x.get("duration_ms") or 0, reverse=True)
            summaries.append({"trace_id": trace_id, "slowest_spans": spans[:12]})
        except Exception as exc:
            summaries.append({"trace_id": trace_id, "error": str(exc)})
    return summaries

def docker_status():
    try:
        import docker

        client = docker.from_env()
        out = {}
        watched = ["checkout", "catalog", "gateway", "payments", "orders", "redis", "postgres", "toxiproxy"]
        for c in client.containers.list(all=True):
            if any(name in c.name for name in watched):
                out[c.name] = {"status": c.status, "image": c.image.tags[:2]}
        return out
    except Exception as exc:
        return {"error": str(exc)}


def ask_ollama(evidence):
    prompt = f"""You are OpsSherlock, a cautious SRE incident investigator.
Analyze only the evidence supplied. Do not invent facts.
Correlate metrics, centralized logs, recent distributed trace summaries, and container status.
The incident was intentionally injected, but you are NOT told which scenario was used. Infer the most likely failing component and mechanism from telemetry only.
Return JSON with keys: affected_service, root_cause, confidence (0-1), evidence (array), remediation, remediation_action, safety_note.
The remediation_action must be exactly one of: none, reset_checkout_fault, reset_redis_proxy, reset_payments_proxy, reset_postgres_proxy, restart_payments.
Choose none unless the telemetry strongly supports a specific reversible action.

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


def load_scenario(name):
    registry = json.loads((ROOT / "chaos" / "scenarios.json").read_text())
    if name not in registry:
        raise SystemExit(f"unknown scenario: {name}")
    return registry[name]


def score(diagnosis, scenario):
    expected = scenario["expected"]
    hay = json.dumps(diagnosis).lower()
    service_terms = [expected["affected_service"].lower()]
    keywords = [x.lower() for x in expected.get("keywords", [])]
    service_ok = any(term in hay for term in service_terms)
    matched = [term for term in keywords if term in hay]
    required = 1 if len(keywords) <= 2 else 2
    root_ok = len(matched) >= required
    return {
        "service_match": service_ok,
        "root_cause_match": root_ok,
        "matched_keywords": matched,
        "required_keyword_matches": required,
        "pass": service_ok and root_ok,
    }

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--scenario", default="checkout_latency")
    args = p.parse_args()
    scenario = load_scenario(args.scenario)

    logs = loki_logs()
    evidence = {
        "captured_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "metrics": {name: prom_query(q) for name, q in QUERIES.items()},
        "centralized_logs": logs,
        "recent_traces": tempo_traces(logs),
        "containers": docker_status(),
    }
    diagnosis = ask_ollama(evidence)
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
    trace_lines = []
    for t in trace_rows[:6] if isinstance(trace_rows, list) else []:
        if not isinstance(t, dict):
            continue
        slow = t.get("slowest_spans", [])
        if slow:
            top = slow[0]
            trace_lines.append(
                f"- `{t.get('trace_id')}` — slowest: {top.get('service')} / {top.get('name')} — {top.get('duration_ms')} ms"
            )
        else:
            trace_lines.append(f"- `{t.get('trace_id')}` — trace details unavailable")
    trace_text = "\n".join(trace_lines) or "- No trace summaries available."

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
