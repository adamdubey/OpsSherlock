#!/usr/bin/env python3

import json
import time
import urllib.error
import urllib.parse
import urllib.request


GATEWAY_URL = "http://localhost:8080"
PROMETHEUS_URL = "http://localhost:9090"
LOKI_URL = "http://localhost:3100"
TEMPO_URL = "http://localhost:3200"
ALLOY_URL = "http://localhost:12345"


def http_json(url: str, timeout: int = 5):
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode())


def wait_for_ready(
    url: str,
    service_name: str,
    attempts: int = 30,
    delay: float = 2.0,
) -> None:
    for _ in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                if response.status == 200:
                    print(f"  {service_name} ready")
                    return
        except (urllib.error.HTTPError, urllib.error.URLError):
            pass

        time.sleep(delay)

    raise AssertionError(f"{service_name} never became ready")


print("Generating a distributed checkout trace...")

payload = json.dumps(
    {
        "sku": "OPS-001",
        "quantity": 1,
        "payment_token": "tok_demo",
    }
).encode()

request = urllib.request.Request(
    f"{GATEWAY_URL}/api/checkout",
    data=payload,
    headers={
        "Content-Type": "application/json",
    },
    method="POST",
)

with urllib.request.urlopen(request, timeout=15) as response:
    response_body = json.loads(response.read().decode())

    trace_id = response.headers.get("x-trace-id")
    request_id = response.headers.get("x-request-id")

order_id = response_body.get("id")

assert trace_id, (
    "Checkout request succeeded but no x-trace-id header was returned"
)

if order_id:
    print(f"  order={order_id} trace_id={trace_id}")
else:
    print(f"  trace_id={trace_id}")
    print("  note: checkout response did not expose an order id")

if request_id:
    print(f"  request_id={request_id}")


print("Checking Prometheus...")

prom_query = urllib.parse.urlencode(
    {
        "query": 'http_server_requests_total{service="checkout"}',
    }
)

prometheus_response = http_json(
    f"{PROMETHEUS_URL}/api/v1/query?{prom_query}"
)

assert prometheus_response.get("status") == "success", (
    "Prometheus query failed"
)

prom_results = (
    prometheus_response
    .get("data", {})
    .get("result", [])
)

assert prom_results, (
    "Prometheus is reachable, but no checkout metrics were found"
)

print("  Prometheus query OK")


print("Checking Loki...")

wait_for_ready(
    f"{LOKI_URL}/ready",
    "Loki",
)


print("Checking Alloy...")

wait_for_ready(
    f"{ALLOY_URL}/-/ready",
    "Alloy",
)


print("Waiting for the exact trace to become readable in Tempo...")

tempo_trace_url = f"{TEMPO_URL}/api/v2/traces/{trace_id}"

trace_found = False

for _ in range(30):
    try:
        with urllib.request.urlopen(
            tempo_trace_url,
            timeout=5,
        ) as response:
            if response.status == 200:
                trace_payload = json.loads(
                    response.read().decode()
                )

                trace = trace_payload.get("trace")

                if trace:
                    trace_found = True
                    break

    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise

    except urllib.error.URLError:
        pass

    time.sleep(2)

assert trace_found, (
    f"Tempo is reachable, but trace {trace_id} was not found"
)

print(f"  Tempo trace OK ({trace_id})")


print("Checking centralized Baker Street logs in Loki...")

loki_query = (
    '{compose_project="opssherlock", '
    'service="checkout"}'
)

encoded_loki_query = urllib.parse.urlencode(
    {
        "query": loki_query,
        "limit": 100,
        "direction": "backward",
    }
)

logs_found = False

for _ in range(30):
    try:
        loki_response = http_json(
            f"{LOKI_URL}/loki/api/v1/query_range?"
            f"{encoded_loki_query}"
        )

        if loki_response.get("status") == "success":
            results = (
                loki_response
                .get("data", {})
                .get("result", [])
            )

            if results:
                logs_found = True
                break

    except (urllib.error.HTTPError, urllib.error.URLError):
        pass

    time.sleep(2)

assert logs_found, (
    "Loki is reachable, but no checkout logs were found"
)

print("  Loki checkout logs OK")


print()
print("Observability verification passed:")
print("metrics + logs + traces are live.")