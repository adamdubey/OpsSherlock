import os
import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from common.platform import install_platform, forwarded_headers

app = FastAPI(title="Baker Street API Gateway", version="1.0.0")
install_platform(app, "gateway")
CATALOG_URL=os.getenv("CATALOG_URL","http://catalog:8000")
CHECKOUT_URL=os.getenv("CHECKOUT_URL","http://checkout:8000")
ORDERS_URL=os.getenv("ORDERS_URL","http://orders:8000")
TIMEOUT=float(os.getenv("UPSTREAM_TIMEOUT_SECONDS","3"))

async def proxy(method, url, request: Request, **kwargs):
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            r=await client.request(method,url,headers=forwarded_headers(request.headers.get("x-request-id")),**kwargs)
        payload = r.json() if r.content else {}
        return JSONResponse(status_code=r.status_code, content=payload)
    except Exception as exc:
        raise HTTPException(502, f"upstream failure: {exc}")

@app.get("/ready", tags=["platform"])
async def ready():
    checks={}
    async with httpx.AsyncClient(timeout=1.0) as client:
        for name,url in {"catalog":CATALOG_URL,"checkout":CHECKOUT_URL,"orders":ORDERS_URL}.items():
            try:
                r=await client.get(f"{url}/health"); checks[name]=r.status_code==200
            except Exception: checks[name]=False
    return {"status":"ready" if all(checks.values()) else "degraded","dependencies":checks}

@app.get("/api/catalog")
async def catalog(request: Request): return await proxy("GET",f"{CATALOG_URL}/products",request)

@app.get("/api/catalog/{sku}")
async def product(sku: str, request: Request): return await proxy("GET",f"{CATALOG_URL}/products/{sku}",request)

@app.post("/api/checkout")
async def checkout(payload: dict, request: Request): return await proxy("POST",f"{CHECKOUT_URL}/checkout",request,json=payload)

@app.get("/api/orders/{order_id}")
async def order(order_id: str, request: Request): return await proxy("GET",f"{ORDERS_URL}/orders/{order_id}",request)
