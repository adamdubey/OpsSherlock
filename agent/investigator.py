import argparse, datetime as dt, json, os, pathlib, requests, yaml

PROM = os.getenv("PROMETHEUS_URL", "http://prometheus:9090")
OLLAMA = os.getenv("OLLAMA_URL", "http://ollama:11434")
MODEL = os.getenv("OLLAMA_MODEL", "qwen3:8b")
ROOT = pathlib.Path("/app")

QUERIES = {
    "checkout_p95": 'histogram_quantile(0.95, sum by (le) (rate(checkout_request_duration_seconds_bucket[1m])))',
    "checkout_rate": 'sum(rate(checkout_requests_total[1m]))',
    "fault_active": 'max(checkout_fault_active)',
    "catalog_up": 'up{instance="catalog:8000"}',
    "checkout_up": 'up{job="checkout"}',
}

def prom_query(expr):
    try:
        r = requests.get(f"{PROM}/api/v1/query", params={"query": expr}, timeout=5)
        r.raise_for_status()
        result = r.json()["data"]["result"]
        return result
    except Exception as exc:
        return {"error": str(exc)}

def collect_logs():
    try:
        import docker
        client = docker.from_env()
        out = {}
        for c in client.containers.list():
            if any(name in c.name for name in ["checkout", "catalog", "gateway", "payments", "orders"]):
                out[c.name] = c.logs(tail=80).decode("utf-8", errors="replace")
        return out
    except Exception as exc:
        return {"error": str(exc)}

def ask_ollama(evidence, scenario):
    prompt = f"""You are OpsSherlock, a cautious SRE incident investigator.
Analyze only the evidence supplied. Do not invent facts.
Return JSON with keys: affected_service, root_cause, confidence (0-1), evidence (array), remediation, safety_note.
Scenario metadata is for labeling only; expected/ground-truth fields are NOT provided to you.

SCENARIO: {scenario['title']} ({scenario['severity']})
EVIDENCE:\n{json.dumps(evidence, indent=2)[:14000]}
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
        "logs": collect_logs(),
    }
    # Critical: do not send scenario['expected'] to the model.
    public_scenario = {k: v for k, v in scenario.items() if k != "expected"}
    diagnosis = ask_ollama(evidence, public_scenario)
    evaluation = score(diagnosis, scenario)

    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    incident_id = f"INC-{ts}-{args.scenario}"
    outdir = ROOT / "artifacts" / "incidents" / incident_id
    outdir.mkdir(parents=True, exist_ok=True)
    record = {"id": incident_id, "scenario": scenario, "evidence": evidence, "diagnosis": diagnosis, "evaluation": evaluation}
    (outdir / "incident.json").write_text(json.dumps(record, indent=2))

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
