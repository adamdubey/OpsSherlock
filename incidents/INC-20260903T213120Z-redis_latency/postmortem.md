# INC-20260903T213120Z-redis_latency: Redis dependency latency

**Severity:** SEV-2  
**Evaluation:** FAIL  
**Model:** `qwen3:8b`  
**Agent version:** `0.6.0`

## Model run metadata

```json
{
  "model": "qwen3:8b",
  "done_reason": "stop",
  "total_duration_ns": 33398658140,
  "load_duration_ns": 4605367086,
  "prompt_eval_count": 2050,
  "prompt_eval_duration_ns": 13384359000,
  "eval_count": 203,
  "eval_duration_ns": 15364058000
}
```

## AI root-cause analysis

**Affected service:** unknown  
**Root cause:** unknown  
**Confidence:** 0

## Evidence cited



## Recent distributed traces

- `8d0a0548e7b5c20664b0136a8f0aca2b` — slowest: catalog / GET /health — 0.2 ms
- `87a647e85c097afadf02c653a5067eec` — slowest: catalog / GET /health — 0.25 ms
- `db2a76690653bc1ab291001128ff753c` — slowest: catalog / GET /metrics — 0.67 ms
- `addd2aa616c675d2c938f491c90a3002` — slowest: catalog / GET /metrics — 1.58 ms
- `f2f030eff91c174dde5cfaea19e66be4` — slowest: catalog / GET /metrics — 2.06 ms
- `3446f0057ae78f3ec046602a7bc38ea9` — slowest: catalog / GET /metrics — 2.28 ms

## Recommended remediation

n/a

## Ground truth

- Affected service: `catalog`
- Root cause: `Redis latency behind the catalog service`
- Expected remediation: `remove the Redis latency toxic and verify catalog recovery`

## Evaluation

```json
{
  "service_match": false,
  "root_cause_match": false,
  "matched_keywords": [],
  "required_keyword_matches": 2,
  "pass": false
}
```

> Lab incident: this fault was intentionally injected and ground truth is known.


## Automated response

- Detector: `checkout_p95`
- Proposed action: `none`
- Policy decision: `DENIED`
- Policy reason: action is not allowlisted
- Recovery verified: `False`
- Fallback reset used: `False`

See `timeline.json` for the machine-readable incident timeline.
