#!/usr/bin/env bash
set -euo pipefail
base="${BASE_URL:-http://localhost:8080}"
echo "Checking gateway readiness..."
curl -fsS "$base/ready" | grep -q 'ready'
echo "Listing catalog..."
curl -fsS "$base/api/catalog" >/dev/null
echo "Creating checkout..."
response=$(curl -fsS -X POST "$base/api/checkout" -H 'content-type: application/json' -d '{"sku":"OPS-001","quantity":1,"payment_token":"tok_demo"}')
order_id=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])' <<<"$response")
echo "Reading order $order_id..."
curl -fsS "$base/api/orders/$order_id" >/dev/null
echo "Baker Street Commerce smoke test passed."
