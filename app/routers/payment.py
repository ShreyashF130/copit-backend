
from fastapi import APIRouter, Request, HTTPException
import razorpay
import json
import os
from app.core.database import db

router = APIRouter()


RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET")
client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))

@router.post("/webhooks/razorpay")   
async def razorpay_webhook(request: Request):
    # 1. GET THE SIGNATURE & BODY
    signature = request.headers.get('x-razorpay-signature')
    body_bytes = await request.body()
    body_str = body_bytes.decode()

    # 2. VERIFY SIGNATURE (Security Check)
    # This ensures the request actually came from Razorpay, not a hacker.
    try:
        client.utility.verify_webhook_signature(body_str, signature, "YOUR_WEBHOOK_SECRET")
    except Exception as e:
        print(f"⚠️ Webhook Signature Verification Failed: {e}")
        raise HTTPException(status_code=400, detail="Invalid Signature")

    # 3. PARSE DATA
    event = json.loads(body_str)
    
    # We only care if payment is "captured" (successful)
    if event['event'] == 'payment.captured':
        payment = event['payload']['payment']['entity']
        
        # Extract Metadata (This is what we passed from Frontend)
        notes = payment['notes'] 
        amount = payment['amount'] / 100 # Convert paise to Rupees
        
        order_type = notes.get('type')  # 'credit_topup' or 'subscription'
        shop_id = int(notes.get('shop_id'))

        print(f"💰 Payment Recieved: ₹{amount} for {order_type} (Shop {shop_id})")

        async with db.pool.acquire() as conn:
            
            # CASE A: WALLET TOP-UP
            if order_type == 'credit_topup':
                await conn.execute("""
                    UPDATE shops 
                    SET wallet_balance = wallet_balance + $1 
                    WHERE id = $2
                """, amount, shop_id)
                print(f"✅ Wallet updated for Shop {shop_id}")

            # CASE B: PRO SUBSCRIPTION
            elif order_type == 'subscription':
                # Check if already Pro to extend date, or start fresh
                # (Simple version: Just set/reset expiry to 30 days from now)
                await conn.execute("""
                    UPDATE shops 
                    SET plan_type = 'pro', 
                        subscription_expiry = NOW() + INTERVAL '30 days' 
                    WHERE id = $1
                """, shop_id)
                print(f"✅ Pro Plan activated for Shop {shop_id}")

            # 4. LOG TRANSACTION 
            await conn.execute("""
                INSERT INTO transactions (shop_id, amount, type, payment_id, status)
                VALUES ($1, $2, $3, $4, 'success')
            """, shop_id, amount, order_type.upper(), payment['id'])

    return {"status": "ok"}





@router.post("/payment/create")
async def create_payment_order(request: Request):
    data = await request.json()
    amount_rupees = data.get('amount')

    shop_id = data.get('shop_id', 0) 
    payment_type = data.get('type') 

    if not amount_rupees:
        raise HTTPException(status_code=400, detail="Amount is required")

    try:
        # 1. Create Razorpay Order
        order_data = {
            "amount": int(amount_rupees * 100), # Convert to Paise
            "currency": "INR",
            # If shop_id is 0, we treat this as a 'New User Acquisition'
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


