
# from fastapi import APIRouter, Request, HTTPException
# import razorpay
# import json
# import os
# from app.core.database import db

# router = APIRouter()


# RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID")
# RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET")
# client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))

# @router.post("/webhooks/razorpay")   
# async def razorpay_webhook(request: Request):
#     # 1. GET THE SIGNATURE & BODY
#     signature = request.headers.get('x-razorpay-signature')
#     body_bytes = await request.body()
#     body_str = body_bytes.decode()

#     # 2. VERIFY SIGNATURE (Security Check)
#     # This ensures the request actually came from Razorpay, not a hacker.
#     try:
#         client.utility.verify_webhook_signature(body_str, signature, "YOUR_WEBHOOK_SECRET")
#     except Exception as e:
#         print(f"⚠️ Webhook Signature Verification Failed: {e}")
#         raise HTTPException(status_code=400, detail="Invalid Signature")

#     # 3. PARSE DATA
#     event = json.loads(body_str)
    
#     # We only care if payment is "captured" (successful)
#     if event['event'] == 'payment.captured':
#         payment = event['payload']['payment']['entity']
        
#         # Extract Metadata (This is what we passed from Frontend)
#         notes = payment['notes'] 
#         amount = payment['amount'] / 100 # Convert paise to Rupees
        
#         order_type = notes.get('type')  # 'credit_topup' or 'subscription'
#         shop_id = int(notes.get('shop_id'))

#         print(f"💰 Payment Recieved: ₹{amount} for {order_type} (Shop {shop_id})")

#         async with db.pool.acquire() as conn:
            
#             # CASE A: WALLET TOP-UP
#             if order_type == 'credit_topup':
#                 await conn.execute("""
#                     UPDATE shops 
#                     SET wallet_balance = wallet_balance + $1 
#                     WHERE id = $2
#                 """, amount, shop_id)
#                 print(f"✅ Wallet updated for Shop {shop_id}")

#             # CASE B: PRO SUBSCRIPTION
#             elif order_type == 'subscription':
#                 # Check if already Pro to extend date, or start fresh
#                 # (Simple version: Just set/reset expiry to 30 days from now)
#                 await conn.execute("""
#                     UPDATE shops 
#                     SET plan_type = 'pro', 
#                         subscription_expiry = NOW() + INTERVAL '30 days' 
#                     WHERE id = $1
#                 """, shop_id)
#                 print(f"✅ Pro Plan activated for Shop {shop_id}")

#             # 4. LOG TRANSACTION 
#             await conn.execute("""
#                 INSERT INTO transactions (shop_id, amount, type, payment_id, status)
#                 VALUES ($1, $2, $3, $4, 'success')
#             """, shop_id, amount, order_type.upper(), payment['id'])

#     return {"status": "ok"}





# @router.post("/payment/create")
# async def create_payment_order(request: Request):
#     data = await request.json()
#     amount_rupees = data.get('amount')

#     shop_id = data.get('shop_id', 0) 
#     payment_type = data.get('type') 

#     if not amount_rupees:
#         raise HTTPException(status_code=400, detail="Amount is required")

#     try:
#         # 1. Create Razorpay Order
#         order_data = {
#             "amount": int(amount_rupees * 100), # Convert to Paise
#             "currency": "INR",
#             # If shop_id is 0, we treat this as a 'New User Acquisition'
#             "receipt": f"rcpt_{payment_type}_{shop_id}",
#             "notes": {
#                 "shop_id": shop_id,
#                 "type": payment_type,
#                 "is_new_user": "true" if shop_id == 0 else "false"
#             }
#         }
        
#         order = client.order.create(data=order_data)
        
#         return {
#             "status": "success",
#             "order_id": order['id'],
#             "amount": order['amount'],
#             "key_id": RAZORPAY_KEY_ID 
#         }
#     except Exception as e:
#         print(f"Razorpay Error: {e}")
#         raise HTTPException(status_code=500, detail="Internal Payment Failure")
    

# # ... existing imports ...
# from fastapi import APIRouter, Request, HTTPException
# from app.core.database import db

# # router is already defined in your code
# # router = APIRouter()

# # ----------------------------------------------------------------------
# # ⚠️ NEW SECURE ENDPOINT: Get Real Order Details
# # ----------------------------------------------------------------------
# @router.get("/order/{order_id}")
# async def get_secure_order_details(order_id: int):
#     """
#     Fetches the TRUE amount and VPA for an order.
#     Prevents users from manipulating the URL to pay less.
#     """
#     async with db.pool.acquire() as conn:
#         # 1. Get Order Amount & Shop ID
#         order = await conn.fetchrow("""
#             SELECT id, total_amount, shop_id, status 
#             FROM orders WHERE id = $1
#         """, order_id)
        
#         if not order:
#             raise HTTPException(status_code=404, detail="Order not found")

#         # 2. Get Shop's UPI ID (VPA)
#         shop = await conn.fetchrow("""
#             SELECT name, upi_id FROM shops WHERE id = $1
#         """, order['shop_id'])
        
#         # Fallback VPA if shop hasn't set one
#         vpa = shop['upi_id'] if shop and shop['upi_id'] else "shop@upi"
#         shop_name = shop['name'] if shop else "Merchant"

#     return {
#         "order_id": order['id'],
#         "amount": float(order['total_amount']), # 🔒 Source of Truth
#         "vpa": vpa,                             # 🔒 Source of Truth
#         "shop_name": shop_name,
#         "status": order['status']
#     }




from fastapi import APIRouter, Request, HTTPException
import razorpay
import json
import os
from app.core.database import db

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
    Prevents users from manipulating the URL to pay less.
    """
    async with db.pool.acquire() as conn:
        # 1. Get Order Amount & Shop ID
        order = await conn.fetchrow("""
            SELECT id, total_amount, shop_id, status 
            FROM orders WHERE id = $1
        """, order_id)
        
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")

        # 2. Get Shop's UPI ID (VPA)
        shop = await conn.fetchrow("""
            SELECT name, upi_id FROM shops WHERE id = $1
        """, order['shop_id'])
        
        # Fallback VPA if shop hasn't set one
        vpa = shop['upi_id'] if shop and shop['upi_id'] else "shop@upi"
        shop_name = shop['name'] if shop else "Merchant"

    return {
        "order_id": order['id'],
        "amount": float(order['total_amount']), # 🔒 Source of Truth
        "vpa": vpa,                             # 🔒 Source of Truth
        "shop_name": shop_name,
        "status": order['status']
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

