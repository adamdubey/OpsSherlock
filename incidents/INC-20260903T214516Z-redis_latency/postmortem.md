# INC-20260903T214516Z-redis_latency: Redis dependency latency

**Severity:** SEV-2  
**Evaluation:** FAIL  
**Model:** `qwen3:8b`  
**Agent version:** `0.6.0`

## Model run metadata

```json
{
  "model": "qwen3:8b",
  "done_reason": "stop",
  "total_duration_ns": 27218778638,
  "load_duration_ns": 4357384753,
  "prompt_eval_count": 2050,
  "prompt_eval_duration_ns": 12961715000,
  "eval_count": 159,
  "eval_duration_ns": 9856836000
}
```

## AI root-cause analysis

**Affected service:** unknown  
**Root cause:** unknown  
**Confidence:** 0

## Evidence cited



## Recent distributed traces

- `446309f82b97adad65c44f68be0d6e37` — slowest: catalog / GET /health — 0.23 ms
- `19b5636c1062e7e4cedfae6c08530060` — slowest: catalog / GET /health — 0.23 ms
- `6b62ab36c6fc5583aeab477e15ec9e66` — slowest: catalog / GET /metrics — 0.58 ms
- `b0b7793624983834e99f61c528f24d3e` — slowest: catalog / GET /metrics — 0.76 ms
- `76ef9552ffa057a8cb2da764268700aa` — slowest: catalog / GET /metrics — 1.79 ms
- `57f598dc269249dbd615177fa5a3536f` — slowest: catalog / GET /metrics — 2.76 ms

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
