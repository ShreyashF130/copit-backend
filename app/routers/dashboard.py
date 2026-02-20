from fastapi import APIRouter, HTTPException, Depends, Header
from pydantic import BaseModel
import os
import secrets 
from app.core.database import db
from app.utils.whatsapp import send_whatsapp_message
from app.utils.crypto import encrypt_data, decrypt_data
from typing import Optional



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





# 1. Define the Expected Data
class RazorpayKeysUpdate(BaseModel):
    shop_id: int
    razorpay_key_id: str
    razorpay_key_secret: str

# 2. The Settings Endpoint
@router.post("/dashboard/settings/razorpay")
async def update_razorpay_keys(
    data: RazorpayKeysUpdate,
    authorized: bool = Depends(verify_admin) # 🔒 Keep it protected!
):
    try:
        # 🔐 ENCRYPT THE KEYS IMMEDIATELY
        encrypted_key_id = encrypt_data(data.razorpay_key_id)
        encrypted_key_secret = encrypt_data(data.razorpay_key_secret)

        async with db.pool.acquire() as conn:
            # Check if shop exists
            shop = await conn.fetchrow("SELECT id FROM shops WHERE id = $1", data.shop_id)
            if not shop:
                raise HTTPException(status_code=404, detail="Shop not found")

            # Update Database with ENCRYPTED keys
            await conn.execute("""
                UPDATE shops 
                SET razorpay_key_id = $1, 
                    razorpay_key_secret = $2,
                    active_payment_method = 'razorpay'
                WHERE id = $3
            """, encrypted_key_id, encrypted_key_secret, data.shop_id)

        return {"status": "success", "message": "Razorpay keys encrypted and secured."}
        
    except Exception as e:
        print(f"🔥 Error saving keys: {e}")
        raise HTTPException(status_code=500, detail="Failed to secure keys")



class PaymentSettingsRequest(BaseModel):
    shop_id: int
    upi_id: Optional[str] = None
    rzp_key: Optional[str] = None
    rzp_secret: Optional[str] = None
    active_method: str

@router.post("/dashboard/settings/payment")
async def update_payment_settings(
    body: PaymentSettingsRequest, 
    authorized: bool = Depends(verify_admin)
):
    async with db.pool.acquire() as conn:
        
        # 1. Base update query for non-sensitive data
        updates = ["upi_id = $1", "active_payment_method = $2"]
        values = [body.upi_id, body.active_method]
        
        # 2. Only update & encrypt Razorpay keys IF the user actually typed them
        idx = 3
        if body.rzp_key:
            updates.append(f"razorpay_key_id = ${idx}")
            values.append(encrypt_data(body.rzp_key))
            idx += 1
            
        if body.rzp_secret:
            updates.append(f"razorpay_key_secret = ${idx}")
            values.append(encrypt_data(body.rzp_secret))
            idx += 1
            
        # Add shop_id to the end of values for the WHERE clause
        values.append(body.shop_id)
        
        query = f"""
            UPDATE shops 
            SET {', '.join(updates)}
            WHERE id = ${idx}
        """
        
        await conn.execute(query, *values)
        
    return {"status": "success"}