import asyncio
import os
import uuid

from fastapi import FastAPI, HTTPException
from opentelemetry.trace import SpanKind
from pydantic import BaseModel, Field

from common.platform import install_platform

app = FastAPI(title="Baker Street Payments", version="1.1.0")
tracer = install_platform(app, "payments")
BASE_DELAY_MS = int(os.getenv("PAYMENT_DELAY_MS", "60"))


class Authorization(BaseModel):
    amount_cents: int = Field(gt=0)
    currency: str = "USD"
    token: str = "tok_demo"


@app.get("/ready", tags=["platform"])
async def ready():
    return {"status": "ready", "provider": "mock"}


@app.post("/authorize")
async def authorize(body: Authorization):
    with tracer.start_as_current_span("mock-provider authorize", kind=SpanKind.CLIENT) as span:
        span.set_attribute("peer.service", "mock-payment-provider")
        span.set_attribute("payment.amount_cents", body.amount_cents)
        span.set_attribute("payment.currency", body.currency)
        await asyncio.sleep(BASE_DELAY_MS / 1000)
        if body.token == "tok_decline":
            span.set_attribute("payment.result", "declined")
            raise HTTPException(402, "payment declined")
        span.set_attribute("payment.result", "authorized")
        return {
            "status": "authorized",
            "authorization_id": f"auth_{uuid.uuid4().hex[:12]}",
            "amount_cents": body.amount_cents,
        }
