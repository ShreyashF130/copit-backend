from fastapi import APIRouter, Request, HTTPException
import razorpay
import json
import os
from app.core.database import db
from datetime import datetime, timedelta
import logging

from app.utils.whatsapp import send_whatsapp_message
from app.utils.crypto import decrypt_data  # 🔐 ADDED ENCRYPTION UTILITY

router = APIRouter()

# Setup Platform Razorpay Client (For your own SaaS billing)
RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET")
client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
logger = logging.getLogger("drop_bot")

# ==============================================================================
# 1. 🔒 SECURE ENDPOINT: Get Real Order Details
# ==============================================================================
@router.get("/payment/order/{order_id}")
async def get_secure_order_details(order_id: int):
    """Fetches the TRUE amount and VPA for an order (For Manual UPI)"""
    async with db.pool.acquire() as conn:
        order = await conn.fetchrow("""
            SELECT id, total_amount, shop_id, status, created_at 
            FROM orders WHERE id = $1
        """, order_id)
        
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")

        created_at = order['created_at']
        if created_at.tzinfo:
            now = datetime.now(created_at.tzinfo)
        else:
            now = datetime.now()

        is_expired = False
        if now > (created_at + timedelta(minutes=15)):
            is_expired = True

        if order['status'] == 'completed':
            return {"status": "completed"}

        if is_expired and order['status'] == 'pending':
             await conn.execute("UPDATE orders SET status = 'cancelled' WHERE id = $1", order_id)
             return {"status": "expired"}

        shop = await conn.fetchrow("SELECT name, upi_id FROM shops WHERE id = $1", order['shop_id'])
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
# 2. PLATFORM PAYMENT CREATION (Sellers buying Pro Plan)
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
        logger.error(f"Platform Razorpay Error: {e}")
        raise HTTPException(status_code=500, detail="Internal Payment Failure")

# ==============================================================================
# 3. PLATFORM WEBHOOK (Sellers buying Pro Plan)
# ==============================================================================
@router.post("/webhooks/razorpay")   
async def razorpay_webhook(request: Request):
    signature = request.headers.get('x-razorpay-signature')
    body_bytes = await request.body()
    body_str = body_bytes.decode()

    try:
        webhook_secret = os.getenv("RAZORPAY_WEBHOOK_SECRET", "YOUR_WEBHOOK_SECRET")
        client.utility.verify_webhook_signature(body_str, signature, webhook_secret)
    except Exception as e:
        logger.error(f"⚠️ Platform Webhook Signature Failed: {e}")
        raise HTTPException(status_code=400, detail="Invalid Signature")

    event = json.loads(body_str)
    
    if event['event'] == 'payment.captured':
        payment = event['payload']['payment']['entity']
        notes = payment['notes'] 
        amount = payment['amount'] / 100 
        order_type = notes.get('type')  
        shop_id = int(notes.get('shop_id'))

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


# ==============================================================================
# 4. CUSTOMER PAYMENT CREATION (Customer paying a Shop)
# ==============================================================================
# ==============================================================================
# 4. CUSTOMER PAYMENT CREATION (Customer paying a Shop)
# ==============================================================================
@router.post("/payment/customer/create")
async def create_customer_order(request: Request):
    """Generates a Razorpay Order ID for a Customer paying a Shop"""
    data = await request.json()
    order_id = data.get('order_id')

    async with db.pool.acquire() as conn:
        order = await conn.fetchrow("""
            SELECT o.total_amount, o.status, o.payment_status, s.id as shop_id, s.razorpay_key_id, s.razorpay_key_secret 
            FROM orders o JOIN shops s ON o.shop_id = s.id WHERE o.id = $1
        """, int(order_id))

        if not order:
            raise HTTPException(status_code=404, detail="Order not found")
            
        # ⚠️ FIX 2: Check proper payment_status
        if order['payment_status'] == 'paid' or order['status'] in ['processing', 'shipped']:
            raise HTTPException(status_code=400, detail="Order already paid")
            
        if not order['razorpay_key_id'] or not order['razorpay_key_secret']:
            raise HTTPException(status_code=400, detail="Shop has not configured Razorpay")

        # 🔓 1. DECRYPT IN MEMORY (Safe)
        decrypted_key_id = decrypt_data(order['razorpay_key_id'])
        decrypted_key_secret = decrypt_data(order['razorpay_key_secret'])

        # 2. Initialize Shop's Razorpay Client
        shop_client = razorpay.Client(auth=(decrypted_key_id, decrypted_key_secret))
        
        try:
            rzp_order = shop_client.order.create({
                "amount": int(float(order['total_amount']) * 100),
                "currency": "INR",
                "receipt": f"order_{order_id}",
                "notes": {
                    "type": "customer_order",
                    "order_id": order_id,
                    "shop_id": order['shop_id']
                }
            })
            
            return {
                "order_id": rzp_order['id'],
                "amount": rzp_order['amount'],
                "key_id": decrypted_key_id # ✅ CORRECT: Returning decrypted public key
            }
        except Exception as e:
            logger.error(f"Customer Razorpay Creation Failed: {e}")
            raise HTTPException(status_code=500, detail="Failed to initiate gateway")


# ==============================================================================
# 5. UNIVERSAL CUSTOMER WEBHOOK (Customer Payment Auto-Verify)
# ==============================================================================
@router.post("/webhooks/razorpay/universal")   
async def universal_razorpay_webhook(request: Request):
    """ONE Webhook URL for ALL sellers to paste into their Razorpay Dashboards"""
    signature = request.headers.get('x-razorpay-signature')
    body_bytes = await request.body()
    body_str = body_bytes.decode()

    try:
        event = json.loads(body_str)
        if event['event'] != 'payment.captured':
            return {"status": "ignored"}

        payment = event['payload']['payment']['entity']
        notes = payment.get('notes', {})
        
        if notes.get('type') != 'customer_order':
            return {"status": "ignored"}
            
        shop_id = int(notes.get('shop_id'))
        db_order_id = int(notes.get('order_id'))

    except Exception as e:
        logger.error(f"Webhook Parsing Error: {e}")
        raise HTTPException(status_code=400, detail="Malformed payload")

    async with db.pool.acquire() as conn:
        # ⚠️ FIX 1: IDEMPOTENCY CHECK (Don't process the same order twice)
        order = await conn.fetchrow("SELECT payment_status, customer_phone FROM orders WHERE id = $1", db_order_id)
        if not order:
            return {"status": "ignored"}
            
        if order['payment_status'] == 'paid':
            logger.info(f"Webhook Duplicate Ignored: Order #{db_order_id} already paid.")
            return {"status": "ok"} # Tell Razorpay we got it, do nothing else.

        # Fetch Shop Secrets
        shop = await conn.fetchrow("SELECT razorpay_key_secret FROM shops WHERE id = $1", shop_id)
        if not shop or not shop['razorpay_key_secret']:
            raise HTTPException(status_code=404, detail="Shop misconfigured")

        # 🔓 DECRYPT THE SELLER'S WEBHOOK SECRET
        decrypted_secret = decrypt_data(shop['razorpay_key_secret'])

        # VERIFY SIGNATURE
        try:
            client = razorpay.Client(auth=("dummy", decrypted_secret))
            client.utility.verify_webhook_signature(body_str, signature, decrypted_secret)
        except Exception as e:
            logger.error(f"🔥 Invalid Signature for Shop {shop_id}: {e}")
            raise HTTPException(status_code=400, detail="Invalid Signature")
            
        # Auto-Approve Order in DB
        await conn.execute("""
            UPDATE orders 
            SET payment_status = 'paid', status = 'processing', transaction_id = $1
            WHERE id = $2
        """, payment['id'], db_order_id)

        # Notify Customer Instantly (Wrapped in try/except so it doesn't crash the webhook response)
        try:
            await send_whatsapp_message(
                order['customer_phone'], 
                f"🎉 *Payment Successful!*\n\nYour Order #{db_order_id} has been auto-verified via Razorpay and is now processing."
            )
        except Exception as wa_error:
            logger.error(f"Webhook WhatsApp Notification Failed: {wa_error}")
                    
    return {"status": "ok"}

