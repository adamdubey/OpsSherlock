import os
import uuid
import psycopg
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from common.platform import install_platform

app=FastAPI(title="Baker Street Orders",version="1.0.0")
install_platform(app,"orders")
DATABASE_URL=os.getenv("DATABASE_URL","postgresql://baker:baker@postgres:5432/baker")

class OrderIn(BaseModel):
    sku:str
    quantity:int
    total_cents:int
    authorization_id:str

async def db(): return await psycopg.AsyncConnection.connect(DATABASE_URL)

@app.get("/ready",tags=["platform"])
async def ready():
    try:
        conn=await db(); cur=await conn.execute("SELECT 1"); await cur.fetchone(); await conn.close(); ok=True
    except Exception: ok=False
    return {"status":"ready" if ok else "degraded","postgres":ok}

@app.post("/orders",status_code=201)
async def create_order(body:OrderIn):
    oid=f"ord_{uuid.uuid4().hex[:12]}"
    conn=await db()
    try:
        await conn.execute("INSERT INTO orders(id,sku,quantity,total_cents,authorization_id,status) VALUES(%s,%s,%s,%s,%s,%s)",(oid,body.sku,body.quantity,body.total_cents,body.authorization_id,"confirmed"))
        await conn.commit()
    finally: await conn.close()
    return {"id":oid,"status":"confirmed",**body.model_dump()}

@app.get("/orders/{order_id}")
async def get_order(order_id:str):
    conn=await db()
    try:
        cur=await conn.execute("SELECT id,sku,quantity,total_cents,authorization_id,status,created_at FROM orders WHERE id=%s",(order_id,))
        row=await cur.fetchone()
    finally: await conn.close()
    if not row: raise HTTPException(404,"order not found")
    return {"id":row[0],"sku":row[1],"quantity":row[2],"total_cents":row[3],"authorization_id":row[4],"status":row[5],"created_at":row[6]}
