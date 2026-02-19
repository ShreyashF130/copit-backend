from fastapi import APIRouter, HTTPException, Depends, Header
from app.core.database import db
from app.utils.whatsapp import send_whatsapp_message # Reuse your existing utility
import os
router = APIRouter()


ADMIN_SECRET_PASSWORD = os.getenv("ADMIN_SECRET_KEY")

# 🔒 SECURITY: Simple API Key for now (Or use proper JWT Auth)
async def verify_admin(x_admin_secret: str = Header(...)):
    if x_admin_secret != ADMIN_SECRET_PASSWORD:
        raise HTTPException(status_code=401, detail="Unauthorized")

@router.post("/dashboard/verify-order")
async def verify_payment(data: dict, authorized: bool = Depends(verify_admin)):
    order_id = data.get("order_id")
    decision = data.get("decision")
    
    # 1. Reuse your Python Logic
    async with db.pool.acquire() as conn:
        order = await conn.fetchrow("SELECT customer_phone FROM orders WHERE id = $1", order_id)
        if not order: raise HTTPException(404, "Order not found")

        if decision == "APPROVE":
            await conn.execute("UPDATE orders SET payment_status = 'paid', status = 'processing' WHERE id = $1", order_id)
            msg = f"🎉 Payment Verified! Order #{order_id} confirmed."
        else:
            await conn.execute("UPDATE orders SET payment_status = 'failed', status = 'cancelled' WHERE id = $1", order_id)
            msg = f"⚠️ Payment Rejected for Order #{order_id}."
            
        # 2. Send WhatsApp (Using your existing robust Python utility)
        await send_whatsapp_message(order['customer_phone'], msg)
        
    return {"status": "success"}