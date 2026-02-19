from fastapi import APIRouter, HTTPException, Depends, Header
from pydantic import BaseModel
import os
import secrets 
from app.core.database import db
from app.utils.whatsapp import send_whatsapp_message

router = APIRouter()

# 1. Strict Data Model (Validation)
class VerifyRequest(BaseModel):
    order_id: int
    decision: str  # "APPROVE" or "REJECT"

# 2. Secure Gatekeeper
async def verify_admin(x_admin_secret: str = Header(..., alias="x-admin-secret")):
    # Load secret inside function to ensure env vars are loaded
    valid_secret = os.getenv("ADMIN_SECRET_KEY")
    
    if not valid_secret:
        # Failsafe: If server config is broken, lock the door.
        raise HTTPException(500, "Server Security Misconfiguration")

    # 🔒 SECURE COMPARISON (Prevents Timing Attacks)
    # Never use '==' for API Keys. Use compare_digest.
    if not secrets.compare_digest(x_admin_secret, valid_secret):
        raise HTTPException(status_code=401, detail="Unauthorized")

@router.post("/dashboard/verify-order")
async def verify_payment(
    body: VerifyRequest,  # <--- Use Pydantic Model here
    authorized: bool = Depends(verify_admin)
):
    # Now you can access data safely with dot notation
    order_id = body.order_id
    decision = body.decision
    
    async with db.pool.acquire() as conn:
        order = await conn.fetchrow("SELECT customer_phone FROM orders WHERE id = $1", order_id)
        if not order: 
            raise HTTPException(404, "Order not found")

        if decision == "APPROVE":
            await conn.execute("UPDATE orders SET payment_status = 'paid', status = 'processing' WHERE id = $1", order_id)
            msg = f"🎉 Payment Verified! Order #{order_id} confirmed."
        else:
            await conn.execute("UPDATE orders SET payment_status = 'failed', status = 'cancelled' WHERE id = $1", order_id)
            msg = f"⚠️ Payment Rejected for Order #{order_id}."
            
        # Send WhatsApp
        await send_whatsapp_message(order['customer_phone'], msg)
        
    return {"status": "success"}