import json
import logging
import os
import time
import uuid
from contextvars import ContextVar

from fastapi import FastAPI, Request
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from starlette.responses import Response

request_id_ctx = ContextVar("request_id", default="-")

class JsonFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "level": record.levelname,
            "service": os.getenv("SERVICE_NAME", "unknown"),
            "request_id": request_id_ctx.get(),
            "message": record.getMessage(),
        }
        return json.dumps(payload, default=str)

def configure_logging():
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(os.getenv("LOG_LEVEL", "INFO"))

REQUESTS = Counter(
    "http_server_requests_total", "HTTP requests", ["service", "method", "path", "status"]
)
LATENCY = Histogram(
    "http_server_request_duration_seconds", "HTTP request latency", ["service", "method", "path"]
)

def install_platform(app: FastAPI, service_name: str):
    configure_logging()
    log = logging.getLogger(service_name)

    @app.middleware("http")
    async def telemetry(request: Request, call_next):
        rid = request.headers.get("x-request-id") or str(uuid.uuid4())
        token = request_id_ctx.set(rid)
        start = time.perf_counter()
        status = 500
        path = request.url.path
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["x-request-id"] = rid
            return response
        finally:
            elapsed = time.perf_counter() - start
            REQUESTS.labels(service_name, request.method, path, str(status)).inc()
            LATENCY.labels(service_name, request.method, path).observe(elapsed)
            log.info(f"request method={request.method} path={path} status={status} duration_ms={elapsed*1000:.1f}")
            request_id_ctx.reset(token)

    @app.get("/health", tags=["platform"])
    async def health():
        return {"status": "ok", "service": service_name}

    @app.get("/metrics", include_in_schema=False)
    async def metrics():
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

def forwarded_headers(request_id: str | None = None):
    return {"x-request-id": request_id or request_id_ctx.get()}
