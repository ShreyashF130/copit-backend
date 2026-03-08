




import logging
import json
import asyncio
import re
from app.core.database import db
from app.utils.state_manager import state_manager
from app.utils.whatsapp import (
    send_whatsapp_message, 
    send_interactive_message, 
    send_image_message
)

# Setup Industrial Logger
logger = logging.getLogger("drop_bot")
logger.setLevel(logging.INFO)

# ==============================================================================
# 1. HANDLERS (Single & Bulk)
# ==============================================================================
async def handle_web_handoff(phone, item_id, incoming_text="", referrer=None):
    logger.info(f"📦 START: Web Handoff for {phone} | Item: {item_id}")
    try:
        # 🚨 THE ZOMBIE KILLER (Idempotency Check)
        # Check if they literally just paid or are already in a checkout state
        current_state = await state_manager.get_state(phone)
        if current_state and current_state.get("state") in ["awaiting_screenshot", "payment_processing"]:
            logger.warning(f"🧟‍♂️ Zombie webhook detected for {phone}. Ignoring.")
            return # Silently exit without sending an error to the user!
        
        # 1. 🚨 THE FIX: Extract Quantity and Variant directly from the Next.js WhatsApp message
        qty_match = re.search(r"Quantity:\s*(\d+)", incoming_text)
        quantity = int(qty_match.group(1)) if qty_match else 1
        
        variant_match = re.search(r"📦 \*(.*?)\*", incoming_text)

        async with db.pool.acquire() as conn:
            item = await conn.fetchrow("""
                SELECT id, name, price, stock_count, image_url, description, shop_id 
                FROM items WHERE id = $1
            """, int(item_id))
        
        if not item:
            logger.error(f"❌ Item {item_id} NOT FOUND")
            await send_whatsapp_message(phone, "❌ Item discontinued or not found.")
            return

        # Safe stock check against the requested quantity
        if item['stock_count'] < quantity:
            logger.info(f"⚠️ Item {item_id} stock insufficient for requested qty: {quantity}")
            await send_whatsapp_message(phone, f"😢 Sorry, we only have {item['stock_count']} of *{item['name']}* left in stock.")
            return

        # 2. Process dynamic data
        full_item_name = variant_match.group(1) if variant_match else item['name']
        total_price = float(item['price']) * quantity

        # 3. 🚨 THE FIX: Bypass 'awaiting_qty' entirely. Save everything and move to checkout.
        await state_manager.update_state(phone, {
            "state": "active", 
            "item_id": item['id'],
            "name": full_item_name,
            "price": float(item['price']),
            "shop_id": item['shop_id'],
            "qty": quantity,
            "total": total_price,
            "is_bulk": False,
            "referrer": referrer
        })
        logger.info(f"✅ State Set: Extracted {quantity}x {full_item_name}. Moving to Address.")

        # 4. Give the user immediate visual confirmation of their cart
        if item.get('image_url'):
            await send_image_message(
                phone, 
                item['image_url'], 
                f"Great! You are ordering {quantity}x *{full_item_name}*.\n💰 Total: ₹{total_price}"
            )
        else:
            await send_whatsapp_message(
                phone, 
                f"Great! You are ordering {quantity}x *{full_item_name}*.\n💰 Total: ₹{total_price}"
            )

        # 5. Instantly trigger the address check logic
        await check_address_before_payment(phone)

    except Exception as e:
        logger.error(f"🔥 CRITICAL ERROR in handle_web_handoff: {e}", exc_info=True)
        await send_whatsapp_message(phone, "❌ System Error. Please try again.")

        
async def handle_bulk_handoff(phone, ref_string):
    logger.info(f"🛒 START: Bulk Handoff for {phone}")
    try:
        # Robust Parsing
        pairs = re.findall(r'(\d+):(\d+)', ref_string)
        
        if not pairs:
            logger.warning(f"⚠️ No valid ID:Qty pairs in: {ref_string}")
            await send_whatsapp_message(phone, "❌ Could not load cart items.")
            return

        cart_items = []
        subtotal = 0
        shop_id = None
        hero_img = None 

        async with db.pool.acquire() as conn:
            for item_id_str, qty_str in pairs:
                item_id = int(item_id_str)
                qty = int(qty_str)
                
                item = await conn.fetchrow("SELECT name, price, image_url, shop_id FROM items WHERE id = $1", item_id)
                
                if item:
                    line_total = float(item['price']) * qty
                    subtotal += line_total
                    shop_id = item['shop_id']
                    if not hero_img: hero_img = item['image_url']
                    
                    cart_items.append({
                        "name": item['name'],
                        "qty": qty,
                        "price": float(item['price'])
                    })

        if not cart_items:
            await send_whatsapp_message(phone, "❌ Items no longer available.")
            return

        await state_manager.set_state(phone, {
            "state": "active", "cart": cart_items, "total": subtotal, 
            "subtotal": subtotal, "shop_id": shop_id, "is_bulk": True
        })

        msg = f"🧾 *Order Summary*\n------------------\n"
        for i in cart_items:
            msg += f"• {i['name']} x{i['qty']}\n"
        msg += f"------------------\n💰 *Final Total: ₹{subtotal}*"

        if hero_img: await send_image_message(phone, hero_img, msg)
        else: await send_whatsapp_message(phone, msg)

        await check_address_before_payment(phone)

    except Exception as e:
        logger.error(f"🔥 CRITICAL ERROR in handle_bulk_handoff: {e}", exc_info=True)
        await send_whatsapp_message(phone, "❌ Error processing cart.")

# ==============================================================================
# 2. CHECK & FINALIZE
# ==============================================================================
async def check_address_before_payment(phone):
    logger.info(f"📍 Checking Address for {phone}")
    try:
        async with db.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT id, house_no, area, city, pincode FROM addresses 
                WHERE user_id = $1 ORDER BY created_at DESC LIMIT 1
            """, phone)

        if row:
            addr_id = row['id']
            display = f"{row['house_no']}, {row['area']}, {row['city']} - {row['pincode']}"
            await send_interactive_message(phone, f"📍 *Confirm Delivery:*\n{display}", [
                {"id": f"CONFIRM_ADDR_{addr_id}", "title": "✅ Yes, Ship Here"},
                {"id": "CHANGE_ADDR", "title": "✏️ Change Address"}
            ])
        else:
            await send_interactive_message(phone, "📍 *Shipping Address Required*", 
                                           [{"id": "CHANGE_ADDR", "title": "➕ Add Address"}])
    except Exception as e:
        logger.error(f"🔥 Address Check Error: {e}", exc_info=True)

async def finalize_order(phone, data, addr_id):
    logger.info(f"🏁 Finalizing Order for {phone} | Addr: {addr_id}")
    
    if not addr_id:
        await check_address_before_payment(phone)
        return

    try:
        shop_id = data.get("shop_id")
        total_amount = float(data.get("total", 0))
        pay_raw = data.get("payment_method", "pay_cod")
        payment_method = "COD" if pay_raw == "pay_cod" else "ONLINE"

        async with db.pool.acquire() as conn:
            # 1. ⚠️ THE FIX: Fetch active_payment_method and razorpay keys
            addr = await conn.fetchrow("SELECT * FROM addresses WHERE id = $1", int(addr_id))
            shop = await conn.fetchrow("""
                SELECT name, upi_id, active_payment_method, razorpay_key_id 
                FROM shops WHERE id = $1
            """, int(shop_id))

            if not addr:
                await send_whatsapp_message(phone, "❌ Address Error. Try again.")
                return

            full_addr = f"{addr['house_no']}, {addr['area']}, {addr['city']} - {addr['pincode']}"

            # 2. Schema Mapping
            if data.get("is_bulk"):
                item_list = [f"{i['name']} (x{i['qty']})" for i in data.get("cart", [])]
                final_item_name = ", ".join(item_list)[:500] 
                final_qty = sum(i['qty'] for i in data.get("cart", []))
            else:
                final_item_name = data.get("name", "Item")
                final_qty = int(data.get("qty", 1))

            # Set payment status (Online is pending until proven otherwise)
            pay_status = 'cod_pending' if payment_method == "COD" else 'awaiting_proof'

            # 3. DB Insert
            logger.info("💾 Inserting Order...")
            order_id = await conn.fetchval("""
                INSERT INTO orders (
                    customer_phone, item_name, quantity, total_amount, payment_method, 
                    delivery_address, delivery_pincode, delivery_city, delivery_state,
                    shop_id, status, payment_status, delivery_status, referrer
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, 'PENDING', $11, 'processing', $12)
                RETURNING id
            """, 
            phone, final_item_name, final_qty, total_amount, payment_method,
            full_addr, addr['pincode'], addr['city'], addr['state'],
            shop_id, pay_status, data.get("referrer")
            )
            logger.info(f"✅ Order Created: ID {order_id}")

            order = await conn.fetchrow("""
                        SELECT o.*, s.shiprocket_email, s.shiprocket_password, s.pickup_address, s.name as shop_name, s.slug as shop_slug 
                        FROM orders o
                        JOIN shops s ON o.shop_id = s.id
                        WHERE o.id = $1
                    """, order_id)
        # =========================================================
        # 4. ⚠️ THE ROUTING FIX (Razorpay vs Manual)
        # =========================================================
        if payment_method == "COD":
            msg = (
                f"🎉 *Order #{order_id} Confirmed!*\n\n"
                f"📦 *Item:* {order['item_name']}\n"
                f"🚚 *Shipping to:* {order['delivery_city']}\n"
                f"💵 *Payment:* Cash on Delivery (COD)\n\n"
                f"⚠️ *Important:* Please keep *₹{order['total_amount']}* ready at the time of delivery.\n\n"
                f"🛍️ *Explore more from {order['shop_name']}:*\n"
                f"https://copit.in/shop/{order['shop_slug']}"
            )
            await send_whatsapp_message(phone, msg)
            await state_manager.clear_state(phone)
            
        else: # ONLINE PAYMENT
            
            # Check if shop uses Razorpay AND has configured their keys
            uses_razorpay = shop and shop.get('active_payment_method') == 'razorpay' and shop.get('razorpay_key_id')
            
            if uses_razorpay:
                # --- RAZORPAY FLOW (PRO) ---
                pay_url = f"https://copit.in/pay/online?order={order_id}"
                msg = f"💳 *Pay Securely via Razorpay:*\n{pay_url}\n\n👇 Tap the link to pay. Your order will auto-confirm once successful."
                await send_whatsapp_message(phone, msg)
                
                # We DO NOT wait for a screenshot. Clear the state. The Razorpay Webhook handles the rest.
                await state_manager.clear_state(phone)
                
            else:
                # --- MANUAL UPI FLOW (FREE/DEFAULT) ---
                pay_url = f"https://copit.in/pay/manual?order={order_id}"
                msg = f"💳 *Pay Here:* {pay_url}\n\n👇 Tap the link to pay securely.\n⚠️ *Important:* Send the [Transaction Id or Screenshot] here to confirm your order."
                await send_whatsapp_message(phone, msg)
                
                asyncio.create_task(schedule_image_deletion(order_id))
                await state_manager.update_state(phone, {"state": "awaiting_screenshot", "order_id": order_id})

    except Exception as e:
        logger.error(f"🔥 Finalize Error: {e}", exc_info=True)
        await send_whatsapp_message(phone, "❌ Error saving order. Please contact support.")
# ==============================================================================
# 3. UTILS & HELPERS
# ==============================================================================
async def handle_selection_drilldown(phone, text_or_id, current_data):
    pass # Drilldown logic placeholder

async def validate_coupon(shop_id, code):
    async with db.pool.acquire() as conn:
        return await conn.fetchrow("SELECT * FROM coupons WHERE shop_id = $1 AND code = $2 AND is_active = TRUE", shop_id, code.upper())

async def save_order_to_db(data):
    # Used for Upsells
    async with db.pool.acquire() as conn:
        return await conn.fetchval("""
            INSERT INTO orders (customer_phone, item_name, quantity, total_amount, payment_method, shop_id, status)
            VALUES ($1, $2, $3, $4, $5, $6, 'PENDING') RETURNING id
        """, data['phone'], data['item_name'], data['qty'], data['total'], data['payment_method'], data['shop_id'])

async def schedule_image_deletion(order_id: int):
    """
    Waits 30 mins and clears screenshot data for privacy/storage.
    """
    await asyncio.sleep(1800) # 30 Minutes
    try:
        async with db.pool.acquire() as conn:
            # Assumes 'screenshot_id' column exists. If not, this is safe to remove/ignore.
            await conn.execute("UPDATE orders SET screenshot_id = NULL WHERE id = $1", order_id)
            logger.info(f"🧹 Cleaned up screenshot for Order #{order_id}")
    except Exception as e:
        logger.error(f"⚠️ Image Deletion Failed: {e}")