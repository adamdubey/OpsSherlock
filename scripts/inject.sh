#!/usr/bin/env bash
set -euo pipefail
scenario="${1:-checkout_latency}"
case "$scenario" in
  checkout_latency)
    curl -fsS -X POST http://localhost:8001/admin/fault/checkout_latency >/dev/null
    for _ in $(seq 1 15); do
      curl -fsS -X POST http://localhost:8080/api/checkout \
        -H 'content-type: application/json' \
        -d '{"sku":"OPS-001","quantity":1,"payment_token":"tok_demo"}' >/dev/null &
      sleep 0.15
    done
    wait || true
    echo "Injected: $scenario (traffic flowed gateway → checkout → dependencies)"
    ;;
  *) echo "Unknown scenario: $scenario" >&2; exit 1 ;;
esac
