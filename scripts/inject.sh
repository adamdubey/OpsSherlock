#!/usr/bin/env bash
set -euo pipefail
scenario="${1:-checkout_latency}"
case "$scenario" in
  checkout_latency)
    curl -fsS -X POST http://localhost:8001/admin/fault/checkout_latency >/dev/null
    for _ in $(seq 1 15); do
      curl -fsS http://localhost:8001/checkout >/dev/null &
      sleep 0.15
    done
    wait || true
    echo "Injected: $scenario"
    ;;
  *) echo "Unknown scenario: $scenario" >&2; exit 1 ;;
esac
