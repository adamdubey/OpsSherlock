import asyncio
import os
import time
import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from prometheus_client import Counter, Gauge, Histogram
from common.platform import install_platform, forwarded_headers

app=FastAPI(title="Baker Street Checkout",version="1.0.0")
install_platform(app,"checkout")
CATALOG_URL=os.getenv("CATALOG_URL","http://catalog:8000")
PAYMENTS_URL=os.getenv("PAYMENTS_URL","http://payments:8000")
ORDERS_URL=os.getenv("ORDERS_URL","http://orders:8000")
TIMEOUT=float(os.getenv("UPSTREAM_TIMEOUT_SECONDS","3"))
FAULT={"name":None,"delay_ms":0,"error_rate":0.0}
REQS=Counter("checkout_requests_total","Checkout requests",["path","status"])
LAT=Histogram("checkout_request_duration_seconds","Checkout latency",["path"])
FAULT_ACTIVE=Gauge("checkout_fault_active","Whether a demo fault is active",["fault"])

class CheckoutIn(BaseModel):
    sku:str="OPS-001"
    quantity:int=Field(default=1,ge=1,le=10)
    payment_token:str="tok_demo"

@app.get("/ready",tags=["platform"])
async def ready():
    checks={}
    async with httpx.AsyncClient(timeout=1.0) as client:
        for name,url in {"catalog":CATALOG_URL,"payments":PAYMENTS_URL,"orders":ORDERS_URL}.items():
            try: checks[name]=(await client.get(f"{url}/health")).status_code==200
            except Exception: checks[name]=False
    return {"status":"ready" if all(checks.values()) else "degraded","dependencies":checks}

async def do_checkout(body:CheckoutIn):
    if FAULT["delay_ms"]: await asyncio.sleep(FAULT["delay_ms"]/1000)
    headers=forwarded_headers()
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        product=(await client.get(f"{CATALOG_URL}/products/{body.sku}",headers=headers)); product.raise_for_status(); p=product.json()
        if p["stock"] < body.quantity: raise HTTPException(409,"insufficient stock")
        total=p["price_cents"]*body.quantity
        payment=(await client.post(f"{PAYMENTS_URL}/authorize",headers=headers,json={"amount_cents":total,"token":body.payment_token})); payment.raise_for_status(); pay=payment.json()
        order=(await client.post(f"{ORDERS_URL}/orders",headers=headers,json={"sku":body.sku,"quantity":body.quantity,"total_cents":total,"authorization_id":pay["authorization_id"]})); order.raise_for_status()
        return order.json()

@app.post("/checkout")
async def checkout_post(body:CheckoutIn):
    start=time.perf_counter()
    try:
        result=await do_checkout(body); REQS.labels("/checkout","200").inc(); return result
    except HTTPException: REQS.labels("/checkout","4xx").inc(); raise
    except Exception as exc: REQS.labels("/checkout","500").inc(); raise HTTPException(502,str(exc))
    finally: LAT.labels("/checkout").observe(time.perf_counter()-start)

@app.get("/checkout")
async def checkout_legacy():
    # Backwards compatible with OpsSherlock v0.1 smoke tests and scenarios.
    return await checkout_post(CheckoutIn())

@app.post("/admin/fault/{name}")
async def set_fault(name:str):
    FAULT_ACTIVE.labels("checkout_latency").set(0)
    if name!="checkout_latency": raise HTTPException(404,"unknown fault")
    FAULT.update({"name":name,"delay_ms":1800,"error_rate":0.0}); FAULT_ACTIVE.labels(name).set(1); return FAULT

@app.post("/admin/fault/reset")
async def reset_fault():
    FAULT_ACTIVE.labels("checkout_latency").set(0); FAULT.update({"name":None,"delay_ms":0,"error_rate":0.0}); return FAULT
