from fastapi import APIRouter, Request, HTTPException
import razorpay
import json
import os
from app.core.database import db
from datetime import datetime, timedelta

router = APIRouter()

# Setup Razorpay Client
RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET")
client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))

# ==============================================================================
# 1. 🔒 SECURE ENDPOINT: Get Real Order Details (The Missing Piece)
# ==============================================================================
@router.get("/payment/order/{order_id}")
async def get_secure_order_details(order_id: int):
    """
    Fetches the TRUE amount and VPA for an order.
    Returns 'expired' if the order is older than 15 minutes.
    """
    async with db.pool.acquire() as conn:
        # 1. Get Order Data
        order = await conn.fetchrow("""
            SELECT id, total_amount, shop_id, status, created_at 
            FROM orders WHERE id = $1
        """, order_id)
        
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")

        # 2. ⏳ CHECK EXPIRY (15 Minutes)
        # Note: Ensure your DB timezone matches (UTC vs Local). usually comparing offset-naive is safest if consistent.
        # If created_at is naive, assume UTC.
        created_at = order['created_at']
        if created_at.tzinfo:
            now = datetime.now(created_at.tzinfo)
        else:
            now = datetime.now()

        is_expired = False
        if now > (created_at + timedelta(minutes=15)):
            is_expired = True

        # If already paid, it's not expired, it's 'completed'
        if order['status'] == 'completed':
            return {"status": "completed"}

        if is_expired and order['status'] == 'pending':
             # Optional: Auto-cancel in DB (Good hygiene)
             await conn.execute("UPDATE orders SET status = 'cancelled' WHERE id = $1", order_id)
             return {"status": "expired"}

        # 3. Get Shop Details
        shop = await conn.fetchrow("""
            SELECT name, upi_id FROM shops WHERE id = $1
        """, order['shop_id'])
        
        vpa = shop['upi_id'] if shop and shop['upi_id'] else "shop@upi"
        shop_name = shop['name'] if shop else "Merchant"

    return {
        "order_id": order['id'],
        "amount": float(order['total_amount']),
        "vpa": vpa,
        "shop_name": shop_name,
        "status": "active",
        "expires_in_seconds": int(((created_at + timedelta(minutes=15)) - now).total_seconds())
    }

# ==============================================================================
# 2. PAYMENT CREATION (Razorpay)
# ==============================================================================
@router.post("/payment/create")
async def create_payment_order(request: Request):
    data = await request.json()
    amount_rupees = data.get('amount')
    shop_id = data.get('shop_id', 0) 
    payment_type = data.get('type') 

    if not amount_rupees:
        raise HTTPException(status_code=400, detail="Amount is required")

    try:
        order_data = {
            "amount": int(amount_rupees * 100), # Convert to Paise
            "currency": "INR",
            "receipt": f"rcpt_{payment_type}_{shop_id}",
            "notes": {
                "shop_id": shop_id,
                "type": payment_type,
                "is_new_user": "true" if shop_id == 0 else "false"
            }
        }
        
        order = client.order.create(data=order_data)
        
        return {
            "status": "success",
            "order_id": order['id'],
            "amount": order['amount'],
            "key_id": RAZORPAY_KEY_ID 
        }
    except Exception as e:
        print(f"Razorpay Error: {e}")
        raise HTTPException(status_code=500, detail="Internal Payment Failure")

# ==============================================================================
# 3. WEBHOOK (Razorpay Success)
# ==============================================================================
@router.post("/webhooks/razorpay")   
async def razorpay_webhook(request: Request):
    signature = request.headers.get('x-razorpay-signature')
    body_bytes = await request.body()
    body_str = body_bytes.decode()

    # Verify Signature
    try:
        # NOTE: Make sure "YOUR_WEBHOOK_SECRET" matches your .env
        webhook_secret = os.getenv("RAZORPAY_WEBHOOK_SECRET", "YOUR_WEBHOOK_SECRET")
        client.utility.verify_webhook_signature(body_str, signature, webhook_secret)
    except Exception as e:
        print(f"⚠️ Webhook Signature Verification Failed: {e}")
        raise HTTPException(status_code=400, detail="Invalid Signature")

    event = json.loads(body_str)
    
    if event['event'] == 'payment.captured':
        payment = event['payload']['payment']['entity']
        notes = payment['notes'] 
        amount = payment['amount'] / 100 
        
        order_type = notes.get('type')  
        shop_id = int(notes.get('shop_id'))

        print(f"💰 Payment Recieved: ₹{amount} for {order_type} (Shop {shop_id})")

        async with db.pool.acquire() as conn:
            if order_type == 'credit_topup':
                await conn.execute("UPDATE shops SET wallet_balance = wallet_balance + $1 WHERE id = $2", amount, shop_id)
            elif order_type == 'subscription':
                await conn.execute("UPDATE shops SET plan_type = 'pro', subscription_expiry = NOW() + INTERVAL '30 days' WHERE id = $1", shop_id)

            await conn.execute("""
                INSERT INTO transactions (shop_id, amount, type, payment_id, status)
                VALUES ($1, $2, $3, $4, 'success')
            """, shop_id, amount, order_type.upper(), payment['id'])

    return {"status": "ok"}

