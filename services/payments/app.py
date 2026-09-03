import asyncio
import os
import random
import uuid
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from common.platform import install_platform

app=FastAPI(title="Baker Street Payments",version="1.0.0")
install_platform(app,"payments")
BASE_DELAY_MS=int(os.getenv("PAYMENT_DELAY_MS","60"))

class Authorization(BaseModel):
    amount_cents:int=Field(gt=0)
    currency:str="USD"
    token:str="tok_demo"

@app.get("/ready",tags=["platform"])
async def ready(): return {"status":"ready","provider":"mock"}

@app.post("/authorize")
async def authorize(body:Authorization):
    await asyncio.sleep(BASE_DELAY_MS/1000)
    if body.token == "tok_decline": raise HTTPException(402,"payment declined")
    return {"status":"authorized","authorization_id":f"auth_{uuid.uuid4().hex[:12]}","amount_cents":body.amount_cents}
