import json
import os

import redis.asyncio as redis
from fastapi import FastAPI, HTTPException
from opentelemetry import trace
from opentelemetry.trace import SpanKind

from common.platform import install_platform

app = FastAPI(title="Baker Street Catalog", version="1.1.0")
tracer = install_platform(app, "catalog")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
r = redis.from_url(REDIS_URL, decode_responses=True)
PRODUCTS = {
    "OPS-001": {"sku": "OPS-001", "name": "Observability Mug", "price_cents": 2400, "stock": 42},
    "AI-007": {"sku": "AI-007", "name": "Agentic SRE Hoodie", "price_cents": 7900, "stock": 17},
    "SRE-404": {"sku": "SRE-404", "name": "Pager Survival Kit", "price_cents": 4900, "stock": 9},
}


@app.get("/ready", tags=["platform"])
async def ready():
    try:
        with tracer.start_as_current_span("redis PING", kind=SpanKind.CLIENT) as span:
            span.set_attribute("db.system", "redis")
            span.set_attribute("server.address", "redis")
            ok = await r.ping()
    except Exception:
        ok = False
    return {"status": "ready" if ok else "degraded", "redis": bool(ok)}


@app.get("/products")
async def products():
    return {"products": list(PRODUCTS.values())}


@app.get("/items")
async def legacy_items():
    return {"items": [{"sku": p["sku"], "stock": p["stock"]} for p in PRODUCTS.values()]}


@app.get("/products/{sku}")
async def product(sku: str):
    with tracer.start_as_current_span("redis GET product", kind=SpanKind.CLIENT) as span:
        span.set_attribute("db.system", "redis")
        span.set_attribute("db.operation.name", "GET")
        span.set_attribute("baker_street.sku", sku)
        cached = await r.get(f"product:{sku}")
    if cached:
        trace.get_current_span().set_attribute("baker_street.cache", "hit")
        return {**json.loads(cached), "cache": "hit"}
    item = PRODUCTS.get(sku)
    if not item:
        raise HTTPException(404, "unknown sku")
    with tracer.start_as_current_span("redis SETEX product", kind=SpanKind.CLIENT) as span:
        span.set_attribute("db.system", "redis")
        span.set_attribute("db.operation.name", "SETEX")
        await r.setex(f"product:{sku}", 30, json.dumps(item))
    trace.get_current_span().set_attribute("baker_street.cache", "miss")
    return {**item, "cache": "miss"}
