# INC-20260903T211001Z-redis_latency: Redis dependency latency

**Severity:** SEV-2  
**Evaluation:** FAIL  
**Model:** `qwen3:8b`  
**Agent version:** `0.6.0`

## Model run metadata

```json
{
  "model": "qwen3:8b",
  "done_reason": "stop",
  "total_duration_ns": 23744798511,
  "load_duration_ns": 4620106211,
  "prompt_eval_count": 2050,
  "prompt_eval_duration_ns": 17157149000,
  "eval_count": 26,
  "eval_duration_ns": 1913150000
}
```

## AI root-cause analysis

**Affected service:** unknown  
**Root cause:** unknown  
**Confidence:** 0

## Evidence cited



## Recent distributed traces

- `6e51907d203799328575efeaef855f5e` — slowest: catalog / GET /health — 0.22 ms
- `19a13b441cce4c45d5806bf567fa93fc` — slowest: catalog / GET /metrics — 0.83 ms
- `b042fc752115d5cc362ec3997cab5de4` — trace details unavailable
- `820286410c45f98dc9fb74bd93131c28` — slowest: catalog / GET /metrics — 1.32 ms
- `1c991bcc6fdc51d7f6082d700ba693c2` — slowest: gateway / POST /api/checkout — 1418.52 ms
- `3c5007e48e41de8d57b96e900bd97078` — slowest: gateway / POST /api/checkout — 1481.89 ms

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
