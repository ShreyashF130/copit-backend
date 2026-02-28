from fastapi import APIRouter, HTTPException, Depends, Header
from pydantic import BaseModel
import os
import secrets 
from app.core.database import db
from app.utils.whatsapp import send_whatsapp_message
from app.utils.crypto import encrypt_data, decrypt_data
from typing import Optional
from app.utils.shiprocket import get_shiprocket_token, create_shiprocket_order, generate_shipping_label
import json


router = APIRouter()

# 1. Strict Data Model (Validation)
class VerifyRequest(BaseModel):
    order_id: int
    decision: str  # "APPROVE" or "REJECT"

class ManualShipRequest(BaseModel):
    order_id: int
    courier_name: str
    tracking_url: str


class ResendRequest(BaseModel):
    order_id: int

class ShipOrderRequest(BaseModel):
    order_id: int
    weight:float = 0.5  # Default weight for serviceability check

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
    order = await conn.fetchrow("""
            SELECT o.customer_phone, s.name as shop_name, s.slug as shop_slug 
            FROM orders o 
            JOIN shops s ON o.shop_id = s.id 
            WHERE o.id = $1
        """, order_id)
    async with db.pool.acquire() as conn:
        order = await conn.fetchrow("SELECT customer_phone FROM orders WHERE id = $1", order_id)
        if not order: 
            raise HTTPException(404, "Order not found")

        if decision == "APPROVE":
            await conn.execute("UPDATE orders SET payment_status = 'paid', status = 'processing' WHERE id = $1", order_id)
            msg = (
                    f"🎉 *Payment Verified!*\n"
                    f"Your Order #{order_id} with {order['shop_name']} is confirmed. We are packing it now! 📦\n\n"
                    f"🛍️ *Explore more from our store:*\n"
                    f"https://copit.in/shop/{order['shop_slug']}"
                )
        else:
            await conn.execute("UPDATE orders SET payment_status = 'failed', status = 'cancelled' WHERE id = $1", order_id)
            msg = f"⚠️ Payment Rejected for Order #{order_id}."
            
        # 🚨 THE AWARE NOTIFICATION BLOCK
        try:
            await send_whatsapp_message(order['customer_phone'], msg)
            await conn.execute("UPDATE orders SET notification_status = 'sent' WHERE id = $1", order_id)
        except Exception as e:
            print(f"🔥 WhatsApp Delivery Failed for Order {order_id}: {e}")
            await conn.execute("UPDATE orders SET notification_status = 'failed' WHERE id = $1", order_id)
            
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


@router.post("/dashboard/resend-receipt")
async def resend_receipt(
    body: ResendRequest, 
    authorized: bool = Depends(verify_admin)
):
    async with db.pool.acquire() as conn:
        # 1. Fetch the order details
        order = await conn.fetchrow("""
            SELECT customer_phone, payment_status, status ,s.name as shop_name, s.slug as shop_slug
            FROM orders o
            JOIN shops s ON o.shop_id = s.id
            WHERE o.id = $1
        """, body.order_id)
        
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")
            
        # 2. Prevent sending receipts for unpaid orders
        if order['payment_status'] != 'paid' and order['status'] != 'PAID':
            raise HTTPException(status_code=400, detail="Order is not paid yet")

        msg = (
                    f"🎉 *Payment Verified!*\n"
                    f"Your Order #{body.order_id} with {order['shop_name']} is confirmed. We are packing it now! 📦\n\n"
                    f"🛍️ *Explore more from our store:*\n"
                    f"https://copit.in/shop/{order['shop_slug']}"
                )
        
        # 3. Try sending the message again
        try:
            await send_whatsapp_message(order['customer_phone'], msg)
            # ✅ SUCCESS: Clear the error from the dashboard
            await conn.execute("UPDATE orders SET notification_status = 'sent' WHERE id = $1", body.order_id)
            return {"status": "success"}
        except Exception as e:
            print(f"🔥 Resend Failed: {e}")
            raise HTTPException(status_code=500, detail="Failed to send WhatsApp message")
        

@router.post("/dashboard/ship-order")
async def process_shipment(
    body: ShipOrderRequest, 
    authorized: bool = Depends(verify_admin)
):
    async with db.pool.acquire() as conn:
        # 1. Fetch Order and Shop Details
        order = await conn.fetchrow("""
            SELECT o.*, s.shiprocket_email, s.shiprocket_password, s.pickup_address, s.name as shop_name , s.slug as shop_slug
            FROM orders o
            JOIN shops s ON o.shop_id = s.id
            WHERE o.id = $1
        """, body.order_id)

        if not order:
            raise HTTPException(status_code=404, detail="Order not found")
            
        if not order['shiprocket_email'] or not order['shiprocket_password']:
            raise HTTPException(status_code=400, detail="Seller has not configured Shiprocket credentials.")

        if order['delivery_status'] != 'processing':
            raise HTTPException(status_code=400, detail="Order is already shipped or not ready.")

        # 2. DECRYPT SHIPROCKET PASSWORD (Security First!)
        # Note: You MUST ensure the settings page encrypts this password before saving it.
        decrypted_password = decrypt_data(order['shiprocket_password'])

        # 3. Authenticate with Shiprocket
        token = get_shiprocket_token(order['shiprocket_email'], decrypted_password)
        if not token:
            raise HTTPException(status_code=500, detail="Shiprocket Login Failed. Check credentials.")

        # 4. Format Data for Shiprocket
        # We need to construct a dummy "items" list since our DB stores a flat string for item_name
        # In a strict Enterprise system, you'd store JSON line items.
        ship_data = dict(order)
        ship_data['items'] = [{
            "name": order['item_name'],
            "qty": order['quantity'],
            "price": order['total_amount'] / order['quantity'] if order['quantity'] > 0 else order['total_amount'],
            "weight": body.weight
        }]
        ship_data['pickup_location_name'] = order['pickup_address'] or "Primary"
        ship_data['customer_name'] = "Customer" # Can be updated if you collect names later

        # 5. Create Order in Shiprocket
        sr_response = create_shiprocket_order(token, ship_data)
        
        if sr_response.get("status_code") in [400, 422] or "error" in sr_response:
            # Extract Shiprocket's exact complaint (e.g., "Insufficient balance")
            error_msg = sr_response.get("message", "Shiprocket rejected the order.")
            
            if "balance" in error_msg.lower():
                raise HTTPException(status_code=402, detail="⚠️ Insufficient Shiprocket Wallet Balance. Please recharge your Shiprocket account.")
            elif "pincode" in error_msg.lower():
                raise HTTPException(status_code=400, detail="⚠️ Unserviceable Pincode. Courier cannot deliver here.")
            else:
                raise HTTPException(status_code=400, detail=f"Shiprocket Error: {error_msg}")

        shipment_id = sr_response.get("shipment_id")
        awb_code = sr_response.get("awb_code")
        
        if not shipment_id:
            raise HTTPException(status_code=500, detail="Shiprocket did not return a Shipment ID.")

        # 6. Generate Shipping Label PDF
        label_url = None
        label_res = generate_shipping_label(token, shipment_id)
        if label_res and label_res.get("label_created") == 1:
            label_url = label_res.get("label_url")

        # Create public tracking URL
        tracking_url = f"https://shiprocket.co/tracking/{awb_code}" if awb_code else None

        # 7. Update Database
        await conn.execute("""
            UPDATE orders 
            SET delivery_status = 'shipped', 
                awb_code = $1, 
                tracking_url = $2, 
                shipping_label_url = $3 
            WHERE id = $4
        """, awb_code, tracking_url, label_url, order['id'])

        # 8. Dispatch WhatsApp Notification
        if tracking_url:
            wa_msg = (
                f"🎉 *Great news! Your order has been shipped.*\n\n"
                f"📦 *Item:* {order['item_name']}\n"
                f"🏪 *From:* {order['shop_name']}\n\n"
                f"📍 *Track your package live here:*\n{tracking_url}\n\n"
                f"🛍️ *Shop again:*\n"
                f"https://copit.in/shop/{order['shop_slug']}"
            )
            try:
                await send_whatsapp_message(order['customer_phone'], wa_msg)
            except Exception as e:
                print(f"🔥 WhatsApp tracking dispatch failed: {e}")
                # We don't fail the API call if WA fails, but we should log it.

        return {
            "status": "success", 
            "awb": awb_code, 
            "label_url": label_url,
            "tracking_url": tracking_url
        }



@router.post("/dashboard/ship-manual")
async def process_manual_shipment(
    body: ManualShipRequest, 
    authorized: bool = Depends(verify_admin)
):
    async with db.pool.acquire() as conn:
        # 1. Update DB
        await conn.execute("""
            UPDATE orders 
            SET delivery_status = 'shipped', tracking_url = $1 
            WHERE id = $2
        """, body.tracking_url, body.order_id)

        # 2. Get customer info
        order = await conn.fetchrow("""
            SELECT o.customer_phone, o.item_name, s.name as shop_name 
            FROM orders o JOIN shops s ON o.shop_id = s.id 
            WHERE o.id = $1
        """, body.order_id)

        # 3. Send WhatsApp
        if order:
            wa_msg = (
                f"🎉 *Great news! Your order has been shipped.*\n\n"
                f"📦 *Item:* {order['item_name']}\n"
                f"🚚 *Courier:* {body.courier_name}\n"
                f"🏪 *From:* {order['shop_name']}\n\n"
                f"📍 *Track your package here:*\n{body.tracking_url}"
            )
            try:
                await send_whatsapp_message(order['customer_phone'], wa_msg)
            except Exception as e:
                print(f"WhatsApp dispatch failed: {e}")

    return {"status": "success"}