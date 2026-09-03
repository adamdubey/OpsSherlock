from fastapi import FastAPI
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from starlette.responses import Response
import time

app = FastAPI(title="OpsSherlock Inventory")
REQS = Counter("inventory_requests_total", "Inventory requests", ["path", "status"])
LAT = Histogram("inventory_request_duration_seconds", "Inventory latency", ["path"])

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/items")
def items():
    start = time.perf_counter()
    try:
        result = {"items": [{"sku": "OPS-001", "stock": 42}, {"sku": "AI-007", "stock": 7}]}
        REQS.labels("/items", "200").inc()
        return result
    finally:
        LAT.labels("/items").observe(time.perf_counter() - start)

@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
