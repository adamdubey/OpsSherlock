import json
import logging
import os
import time
import uuid
from contextvars import ContextVar

from fastapi import FastAPI, Request
from opentelemetry import propagate, trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import SpanKind, Status, StatusCode
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from starlette.responses import Response

request_id_ctx = ContextVar("request_id", default="-")
_httpx_instrumented = False


class JsonFormatter(logging.Formatter):
    def format(self, record):
        span = trace.get_current_span()
        ctx = span.get_span_context() if span else None
        payload = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "level": record.levelname,
            "service": os.getenv("SERVICE_NAME", "unknown"),
            "request_id": request_id_ctx.get(),
            "trace_id": format(ctx.trace_id, "032x") if ctx and ctx.is_valid else "-",
            "span_id": format(ctx.span_id, "016x") if ctx and ctx.is_valid else "-",
            "message": record.getMessage(),
        }
        return json.dumps(payload, default=str)


def configure_logging():
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(os.getenv("LOG_LEVEL", "INFO"))


def configure_tracing(service_name: str):
    global _httpx_instrumented
    resource = Resource.create(
        {
            "service.name": service_name,
            "service.namespace": "baker-street",
            "deployment.environment.name": os.getenv("DEPLOYMENT_ENVIRONMENT", "local"),
            "service.version": os.getenv("SERVICE_VERSION", "0.5.0"),
        }
    )
    provider = TracerProvider(resource=resource)
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://alloy:4317")
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, insecure=True)))
    trace.set_tracer_provider(provider)
    if not _httpx_instrumented:
        HTTPXClientInstrumentor().instrument()
        _httpx_instrumented = True
    return trace.get_tracer(service_name)


REQUESTS = Counter(
    "http_server_requests_total", "HTTP requests", ["service", "method", "path", "status"]
)
LATENCY = Histogram(
    "http_server_request_duration_seconds",
    "HTTP request latency",
    ["service", "method", "path"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10),
)
IN_FLIGHT = Gauge("http_server_requests_in_flight", "In-flight HTTP requests", ["service"])


def install_platform(app: FastAPI, service_name: str):
    configure_logging()
    tracer = configure_tracing(service_name)
    log = logging.getLogger(service_name)

    @app.middleware("http")
    async def telemetry(request: Request, call_next):
        rid = request.headers.get("x-request-id") or str(uuid.uuid4())
        token = request_id_ctx.set(rid)
        start = time.perf_counter()
        status = 500
        IN_FLIGHT.labels(service_name).inc()
        parent = propagate.extract(dict(request.headers))
        span_name = f"{request.method} {request.url.path}"
        try:
            with tracer.start_as_current_span(span_name, context=parent, kind=SpanKind.SERVER) as span:
                span.set_attribute("http.request.method", request.method)
                span.set_attribute("url.path", request.url.path)
                span.set_attribute("server.address", service_name)
                span.set_attribute("baker_street.request_id", rid)
                try:
                    response = await call_next(request)
                    status = response.status_code
                    route = request.scope.get("route")
                    route_path = getattr(route, "path", request.url.path)
                    span.update_name(f"{request.method} {route_path}")
                    span.set_attribute("http.route", route_path)
                    span.set_attribute("http.response.status_code", status)
                    if status >= 500:
                        span.set_status(Status(StatusCode.ERROR))
                    response.headers["x-request-id"] = rid
                    ctx = span.get_span_context()
                    if ctx.is_valid:
                        response.headers["x-trace-id"] = format(ctx.trace_id, "032x")
                    return response
                except Exception as exc:
                    span.record_exception(exc)
                    span.set_status(Status(StatusCode.ERROR, str(exc)))
                    raise
                finally:
                    elapsed = time.perf_counter() - start
                    route = request.scope.get("route")
                    path = getattr(route, "path", request.url.path)
                    IN_FLIGHT.labels(service_name).dec()
                    REQUESTS.labels(service_name, request.method, path, str(status)).inc()
                    LATENCY.labels(service_name, request.method, path).observe(elapsed)
                    log.info(
                        "request method=%s path=%s status=%s duration_ms=%.1f",
                        request.method,
                        path,
                        status,
                        elapsed * 1000,
                    )
        finally:
            request_id_ctx.reset(token)

    @app.get("/health", tags=["platform"])
    async def health():
        return {"status": "ok", "service": service_name}

    @app.get("/metrics", include_in_schema=False)
    async def metrics():
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return tracer


def forwarded_headers(request_id: str | None = None):
    return {"x-request-id": request_id or request_id_ctx.get()}


def current_trace_id():
    ctx = trace.get_current_span().get_span_context()
    return format(ctx.trace_id, "032x") if ctx.is_valid else "-"
