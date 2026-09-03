from fastapi import FastAPI, HTTPException
from prometheus_client import Counter, Gauge, Histogram, generate_latest, CONTENT_TYPE_LATEST
from starlette.responses import Response
import asyncio, httpx, os, time

app = FastAPI(title="OpsSherlock Checkout")
INVENTORY_URL = os.getenv("INVENTORY_URL", "http://inventory:8000")
FAULT = {"name": None, "delay_ms": 0, "error_rate": 0.0}
REQS = Counter("checkout_requests_total", "Checkout requests", ["path", "status"])
LAT = Histogram("checkout_request_duration_seconds", "Checkout latency", ["path"])
FAULT_ACTIVE = Gauge("checkout_fault_active", "Whether a demo fault is active", ["fault"])

@app.get("/health")
def health():
    return {"status": "ok", "fault": FAULT}

@app.get("/checkout")
async def checkout():
    started = time.perf_counter()
    try:
        if FAULT["delay_ms"]:
            await asyncio.sleep(FAULT["delay_ms"] / 1000)
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{INVENTORY_URL}/items")
            r.raise_for_status()
        REQS.labels("/checkout", "200").inc()
        return {"status": "accepted", "inventory": r.json(), "fault": FAULT["name"]}
    except Exception as exc:
        REQS.labels("/checkout", "500").inc()
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        LAT.labels("/checkout").observe(time.perf_counter() - started)

@app.post("/admin/fault/{name}")
def set_fault(name: str):
    for label in ["checkout_latency"]:
        FAULT_ACTIVE.labels(label).set(0)
    if name == "checkout_latency":
        FAULT.update({"name": name, "delay_ms": 1800, "error_rate": 0.0})
        FAULT_ACTIVE.labels(name).set(1)
    else:
        raise HTTPException(404, "unknown fault")
    return FAULT

@app.post("/admin/fault/reset")
def reset_fault():
    for label in ["checkout_latency"]:
        FAULT_ACTIVE.labels(label).set(0)
    FAULT.update({"name": None, "delay_ms": 0, "error_rate": 0.0})
    return FAULT

@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
