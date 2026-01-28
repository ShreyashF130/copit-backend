from app.utils.whatsapp import send_whatsapp_message, send_interactive_message,send_image_message
from app.utils.state_manager import state_manager
import uuid
import json
import asyncio
from app.core.database import db
import asyncio
import logging


async def finalize_order(phone, data, addr_id):
    """
    FINALIZER:
    1. Fetches Address & Shop Settings.
    2. Saves Order (Pending or COD).
    3. Routes to Razorpay, UPI, or COD Confirmation.
    """
    shop_id = data.get("shop_id")
    total_amount = float(data.get("total", 0))
    payment_method = data.get("payment_method", "pay_cod")
    
    # 1. FETCH ADDRESS & SHOP CREDENTIALS IN ONE GO
    async with db.pool.acquire() as conn:
        addr = await conn.fetchrow("SELECT * FROM addresses WHERE id = $1", int(addr_id))
        
        shop = await conn.fetchrow("""
            SELECT name, plan_type, active_payment_method, 
                   razorpay_key_id, razorpay_key_secret, upi_id 
            FROM shops WHERE id = $1
        """, int(shop_id))

    if not addr:
        await send_whatsapp_message(phone, "❌ Critical Error: Address not found.")
        return

    # Construct Address String
    full_addr_str = addr['full_address']
    if not full_addr_str:
        parts = [addr['house_no'], addr['area'], addr['city'], addr['pincode']]
        full_addr_str = ", ".join([p for p in parts if p])

    # 2. DETERMINE INITIAL STATUS
    # If Online, we save as 'PENDING_PAYMENT' first.
    status_text = "COD" if payment_method == "pay_cod" else "PENDING_PAYMENT"

    # 3. PREPARE PAYLOAD
    order_payload = {
        "phone": phone,
        "item_name": data.get("name", "Unknown Item"),
        "qty": int(data.get("qty", 1)),
        "total": total_amount,
        "payment_method": "COD" if payment_method == "pay_cod" else "ONLINE",
        "shop_id": shop_id,
        "address": full_addr_str,
        "pincode": addr['pincode'],
        "city": addr['city'],
        "state": addr['state'],
        "status": status_text
    }

    # 4. SAVE TO DB
    order_id = await save_order_to_db(order_payload)
    
    if not order_id:
        await send_whatsapp_message(phone, "❌ Database Error. Please retry.")
        return

    # 5. ROUTING LOGIC (The Brain 🧠)

    # --- CASE A: CASH ON DELIVERY ---
    if payment_method == "pay_cod":
        msg = (
            f"🎉 *Order Placed Successfully!* 🎉\n"
            f"🆔 Order #{order_id}\n"
            f"📦 Item: {order_payload['item_name']} (x{order_payload['qty']})\n"
            f"💰 Total: ₹{total_amount}\n"
            f"📍 Ship To: {order_payload['city']}\n\n"
            "We will update you when it ships! 🚚"
        )
        await send_whatsapp_message(phone, msg)
        await state_manager.clear_state(phone)
        
        # Trigger Upsell if enabled
        # await trigger_upsell_flow(phone, shop_id, order_id) 
        return

    # --- CASE B: ONLINE PAYMENT ---
    elif payment_method == "pay_online":
        
        # LOGIC: Can we use Razorpay?
        # Must be PRO plan + Razorpay Selected + Keys Exist
        use_razorpay = (
            (shop['plan_type'] == 'pro') and 
            (shop['active_payment_method'] == 'razorpay') and 
            shop['razorpay_key_id'] and 
            shop['razorpay_key_secret']
        )

        # SUB-CASE B1: RAZORPAY AUTOMATION 🤖
        if use_razorpay:
            try:
                import razorpay
                rzp = razorpay.Client(auth=(shop['razorpay_key_id'], shop['razorpay_key_secret']))
                
                link_data = {
                    "amount": int(total_amount * 100), # Paise
                    "currency": "INR",
                    "description": f"Order #{order_id}",
                    "customer": {"contact": phone},
                    "notify": {"sms": True, "email": False},
                    "callback_url": "https://copit.in/payment-success", # Optional
                    "callback_method": "get"
                }
                
                payment_link = rzp.payment_link.create(link_data)
                short_url = payment_link['short_url']
                
                msg = (
                    f"💳 *Complete Your Payment*\n"
                    f"🆔 Order #{order_id}\n"
                    f"💰 Amount: ₹{total_amount}\n\n"
                    f"👇 *Tap to Pay Securely:*\n{short_url}\n\n"
                    f"_(Order confirms automatically after payment)_"
                )
                await send_whatsapp_message(phone, msg)
                
                # Save Link ID to State (for verification later if needed)
                await state_manager.update_state(phone, {"payment_link_id": payment_link['id']})
                return

            except Exception as e:
                print(f"🔥 Razorpay Failed: {e}")
                # Fallback to UPI if Razorpay crashes
        
        # SUB-CASE B2: MANUAL UPI (The Fallback) 🏦
        if shop['upi_id']:
            # Replace with your actual base URL
            base_url = "https://copit.in" 
            pay_url = f"{base_url}/pay/manual?shop={shop_id}&amount={total_amount}&order={order_id}"
            
            msg = (
                f"🏦 *Direct Payment Link*\n"
                f"Amount: ₹{total_amount}\n\n"
                f"👇 *Tap to Pay via UPI:*\n{pay_url}\n\n"
                f"⚠️ *Important:* After paying, please send a *Screenshot* here to confirm."
            )
            
            # Update state to wait for screenshot
            await state_manager.set_state(phone, {
                "state": "awaiting_screenshot", 
                "order_id": order_id,
                "shop_id": shop_id
            })
            await send_whatsapp_message(phone, msg)
        else:
            await send_whatsapp_message(phone, "❌ Seller has not set up payments. Please choose COD.")


async def save_order_to_db(data):
    """
    Inserts data using the Single-Item Schema.
    """
    async with db.pool.acquire() as conn:
        query = """
            INSERT INTO orders (
                customer_phone, 
                item_name, 
                quantity, 
                total_amount, 
                payment_method, 
                delivery_address, 
                delivery_pincode, 
                delivery_city, 
                delivery_state,
                shop_id,
                status,
                payment_status
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, 'pending')
            RETURNING id
        """
        
        # Use .get() with defaults to avoid KeyErrors
        order_id = await conn.fetchval(query,
            data['phone'],
            data['item_name'],
            data['qty'],
            data['total'],
            data['payment_method'],
            data['address'],
            data['pincode'],
            data['city'],
            data['state'],
            data['shop_id'],
            data['status'] # Passed from finalize_order
        )
        return order_id
    
async def check_address_before_payment(phone):
    async with db.pool.acquire() as conn:
        # 1. Check for Existing Address
        row = await conn.fetchrow("""
            SELECT id, full_address, pincode, city, house_no, area 
            FROM addresses 
            WHERE user_id = $1 
            ORDER BY created_at DESC LIMIT 1
        """, phone)

        if row:
            # [Existing Logic] Address Found -> Show Confirm Button
            addr_id = row['id']
            parts = [p for p in [row['house_no'], row['area'], row['city'], row['pincode']] if p]
            display_addr = ", ".join(parts) or row['full_address']

            msg = f"📍 *Confirm Delivery Address:*\n\n{display_addr}"
            btns = [
                {"id": f"CONFIRM_ADDR_{addr_id}", "title": "✅ Yes, Ship Here"},
                {"id": "CHANGE_ADDR", "title": "✏️ Change Address"}
            ]
            send_interactive_message(phone, msg, btns)
        
        else:
            # 🛡️ SECURITY FIX: Generate Magic Token
            token = str(uuid.uuid4()) # Generates random string like 'f47ac10b-58cc...'
            
            # Save token to DB so we can verify it later
            # We use UPSERT (Insert or Update) to ensure phone exists
            await conn.execute("""
                INSERT INTO users (phone_number, magic_token) 
                VALUES ($1, $2)
                ON CONFLICT (phone_number) 
                DO UPDATE SET magic_token = $2
            """, phone, token)

            # Generate Secure Link (NO PHONE NUMBER IN URL)
            # Replace with your actual Vercel domain
            web_link = f"https://your-site.vercel.app/mobile-address?token={token}"
            
            msg = (
                "🚚 *Shipping Details Needed*\n"
                "To ensure safe delivery, please fill your address securely:\n\n"
                f"🔗 *Click here:* {web_link}"
            )
            await send_whatsapp_message(phone, msg)


async def handle_web_handoff(phone, item_id, referrer=None):
    async with db.pool.acquire() as conn:
        item = await conn.fetchrow("SELECT * FROM items WHERE id = $1", item_id)
    
    if not item:
        await send_whatsapp_message(phone, "❌ Item discontinued or not found.")
        return

    
    # 1. Fix Attributes
    attrs = item.get('attributes')
    if isinstance(attrs, str):
        try:
            attrs = json.loads(attrs)
        except:
            attrs = {}
    elif attrs is None:
        attrs = {}

    # 2. Fix Options
    options = item.get('options')
    if isinstance(options, str):
        try:
            options = json.loads(options)
        except:
            options = []
    elif options is None:
        options = []
        
    # ============================================================

    # Now 'attrs' is guaranteed to be a Dict, so .get() will work
    has_variants = attrs.get('has_complex_variants', False)

    # Initialize State
    base_state = {
        "item_id": item['id'],
        "name": item['name'],
        "base_price": float(item['price']),
        "price": float(item['price']),
        "shop_id": item['shop_id'],
        "description": item.get('description', ''),
        "referrer": referrer,
        
        # Save parsed data
        "attributes": attrs,
        "options": options,
        
        # Flow Flags
        "has_variants": has_variants,
        "selected_options": {}, # e.g. {"Size": "M", "Color": "Red"}
        "current_step_index": 0 
    }

    # LOGIC A: COMPLEX VARIANTS (Step-by-Step)
    if has_variants and options:
        # Save state and trigger the first question (Drilldown)
        # We need to know WHICH question to ask first.
        # usually options is list of dicts: [{"name": "Size", "values": [...]}, ...]
        first_option = options[0]
        
        await state_manager.update_state(phone, {
            **base_state,
            "state": "awaiting_selection",
            "qty": 1
        })
        
        # Ask first question
        btn_rows = [{"id": f"VAR_{val[:20]}", "title": val} for val in first_option['values']]
        msg = f"🛒 *{item['name']}*\nSelect *{first_option['name']}*:"
        send_interactive_message(phone, msg, btn_rows)

    # LOGIC B: SIMPLE PRODUCT (Directly ask Quantity)
    else:
        # Go straight to Quantity
        await state_manager.update_state(phone, {
            **base_state,
            "state": "awaiting_qty",
            "qty": 1
        })

        # Send Product Image + Caption
        caption = (
            f"🛍️ *{item['name']}*\n"
            f"💰 Price: ₹{item['price']}\n\n"
            f"{item.get('description', '')}\n\n"
            "🔢 *Please reply with the Quantity* (e.g. 1, 2, 5)"
        )
        
        # If image exists, send it. Else text.
        img_url = item.get('image_url')
        if img_url and "http" in img_url:
            await send_image_message(phone, img_url, caption)
        else:
            send_whatsapp_message(phone, caption)


async def validate_coupon(shop_id, code):
    async with db.pool.acquire() as conn:
        coupon = await conn.fetchrow("""
            SELECT * FROM coupons 
            WHERE shop_id = $1 AND code = $2 AND is_active = TRUE
        """, shop_id, code.upper())
    return coupon



async def handle_bulk_handoff(phone, ref_string):
    print(f"🕵️ DEBUG: Processing Bulk Order: {ref_string}")
    
    try:
        # 1. Separate Items from Coupon
        coupon_code = None
        if "_COUPON:" in ref_string:
            parts = ref_string.split("_COUPON:")
            items_part = parts[0]
            coupon_code = parts[1].strip()
        else:
            items_part = ref_string

        # Clean up the items string
        raw_items = items_part.replace("buy_bulk_", "").split(",")
        
        cart_items = []
        subtotal = 0
        shop_id = None
        seller_phone = None
        summary_text = ""
        hero_image_url = None 

        async with db.pool.acquire() as conn:
            for entry in raw_items:
                if ":" not in entry: continue
                item_id, qty = map(int, entry.split(":"))
                
                # Fetch Item
                item = await conn.fetchrow("""
                    SELECT i.name, i.price, i.image_url, i.shop_id, s.phone_number, s.name as shop_name
                    FROM items i JOIN shops s ON i.shop_id = s.id 
                    WHERE i.id = $1
                """, item_id)
                
                if item:
                    line_total = float(item['price']) * qty
                    subtotal += line_total
                    shop_id = item['shop_id']
                    seller_phone = item['phone_number']
                    
                    if not hero_image_url and item['image_url']:
                        hero_image_url = item['image_url']
                    
                    cart_items.append({
                        "name": item['name'],
                        "qty": qty,
                        "price": float(item['price'])
                    })
                    summary_text += f"• {item['name']} x{qty}\n"

        if not cart_items:
            print("❌ Error: No valid items found")
            return

        # 2 Verify Coupon in Backend
        discount_amount = 0
        applied_coupon_code = None
        
        if coupon_code:
            # Re-use validate_coupon function
            coupon = await validate_coupon(shop_id, coupon_code)
            
            if coupon:
                applied_coupon_code = coupon['code']
                if coupon['discount_type'] == 'percent':
                    discount_amount = (subtotal * float(coupon['value'])) / 100
                else:
                    discount_amount = float(coupon['value'])
                print(f"✅ Coupon {coupon_code} Validated. Discount: ₹{discount_amount}")
            else:
                print(f"⚠️ Invalid Coupon Attempt: {coupon_code}")

        final_total = max(0, subtotal - discount_amount)

        # 3. Update State
        await state_manager.set_state(phone, {
            "state": "awaiting_payment_method", 
            "cart": cart_items,
            "total": final_total,          # The amount they must pay
            "subtotal": subtotal,          # Original amount
            "discount": discount_amount,   # Savings
            "shop_id": shop_id,
            "seller_phone": seller_phone,
            "applied_coupon": applied_coupon_code
        })

        # 4. Send Hero Image
        if hero_image_url:
            extra_count = len(cart_items) - 1 
            item_word = "item" if extra_count == 1 else "items"
            caption = f"🛒 Your selection looks ready! (+{extra_count} more {item_word})" if extra_count > 0 else "🛒 Your selection looks ready!"
            await send_image_message(phone, hero_image_url, caption=caption)

        # 5. Construct Summary Message
        buttons = [
            {"id": "pay_online", "title": "Pay Online"},
            {"id": "pay_cod", "title": "Cash on Delivery"}
        ]
        
        msg = (
            f"🧾 *Order Summary*\n"
            f"------------------\n"
            f"{summary_text}"
            f"------------------\n"
            f"📝 Subtotal: ₹{subtotal}\n"
        )
        
        if applied_coupon_code:
            msg += f"🏷️ Coupon ({applied_coupon_code}): -₹{discount_amount}\n"
            
        msg += (
            f"💰 *Final Total: ₹{final_total}*\n\n"
            f"Select payment method to confirm:"
        )
        
        await send_interactive_message(phone, msg, buttons)

    except Exception as e:
        print(f"🔥 CRITICAL ERROR in Bulk Handoff: {e}")
        await send_whatsapp_message(phone, "❌ Error processing cart. Please try again.")


# app/services/order_service.py



async def schedule_image_deletion(order_id: int):
    """
    Background task to clear screenshot references after 30 minutes
    to save storage space/privacy.
    """
    # Wait for 30 minutes
    await asyncio.sleep(1800) 
    
    # Use the modular DB connection
    async with db.pool.acquire() as conn:
        await conn.execute("UPDATE orders SET screenshot_id = NULL WHERE id = $1", order_id)
        
    print(f"🧹 Storage Purged: Order #{order_id}")


async def send_order_confirmation(phone, order_id, data, method_text):
    if order_id == "ERROR":
        await send_whatsapp_message(phone, "❌ Database error. Please try again.")
        return
    base_url = "https://copit.in"
    shop_url = f"{base_url}/s/{data['shop_id']}" # Update domain
    
    msg = (
        f"✅ *Order Confirmed ({method_text})*\n"
        f"Order ID: #{order_id}\n"
        f"📦 We will notify you when shipped!\n\n"
        f"Browse more: {shop_url}"
    )
    await send_whatsapp_message(phone, msg)
    
    # Notify Seller
    seller_phone = data.get('seller_phone')
    if seller_phone:
        await send_whatsapp_message(seller_phone, f"🚨 *NEW ORDER!* (#{order_id})\nMethod: {method_text}")
    
    await state_manager.clear_state(phone)


async def get_address_string(addr_id):
    """
    Converts Address ID -> Full String for the 'orders' table
    """
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT house_no, area, city, pincode 
            FROM addresses WHERE id = $1
        """, int(addr_id))
        
        if row:
            return f"{row['house_no']}, {row['area']}, {row['city']} - {row['pincode']}"
        return "Address Not Found"
    



async def send_address_flow(phone):
    """
    RUTHLESS FALLBACK: 
    Since Meta Integrity blocked the Flow, we simply ASK the user to type it.
    """
    # 1. Update State to listen for the address
    await state_manager.update_state(phone, {
        "state": "awaiting_manual_address"
    })

    # 2. Send Simple Text Prompt
    msg = (
        "🚚 *Shipping Details Needed*\n\n"
        "Since this is your first order, please type your address below in this format:\n\n"
        "👉 *Pincode, House No, City*\n"
        "_(Example: 400050, Flat 101, Mumbai)_"
    )
    await send_whatsapp_message(phone, msg)


async def check_and_request_address(phone):
    async with db.pool.acquire() as conn:
        # RUTHLESS FIX: Join strictly on phone_number.
        # We assume addresses.user_id stores the phone number string.
        
        row = await conn.fetchrow("""
            SELECT a.id, a.full_address, a.pincode, a.city 
            FROM addresses a
            WHERE a.user_id = $1
            ORDER BY a.created_at DESC LIMIT 1
        """, phone)
        
        if row:
            # ✅ Address Found
            addr_id = row['id']
            # Handle potential NULLs gracefully
            full_addr = row['full_address'] or f"{row['house_no']}, {row['area']}, {row['city']} - {row['pincode']}"
            
            msg = f"📍 We found a saved address:\n\n*{full_addr}*\n\nShip to this address?"
            
            btns = [
                {"id": f"USE_OLD_ADDR_{addr_id}", "title": "✅ Yes, Ship Here"},
                {"id": "NEW_ADDR_FLOW", "title": "📝 Add New Address"}
            ]
            await send_interactive_message(phone, msg, btns)
        else:
            # ❌ No Address Found
            await send_address_flow(phone)



async def check_address_before_payment(phone):
    async with db.pool.acquire() as conn:
        # 1. Check for Existing Address
        row = await conn.fetchrow("""
            SELECT id, full_address, pincode, city, house_no, area 
            FROM addresses 
            WHERE user_id = $1 
            ORDER BY created_at DESC LIMIT 1
        """, phone)

        if row:
            # [Existing Logic] Address Found -> Show Confirm Button
            addr_id = row['id']
            parts = [p for p in [row['house_no'], row['area'], row['city'], row['pincode']] if p]
            display_addr = ", ".join(parts) or row['full_address']

            msg = f"📍 *Confirm Delivery Address:*\n\n{display_addr}"
            btns = [
                {"id": f"CONFIRM_ADDR_{addr_id}", "title": "✅ Yes, Ship Here"},
                {"id": "CHANGE_ADDR", "title": "✏️ Change Address"}
            ]
            await send_interactive_message(phone, msg, btns)
        
        else:
            # 🛡️ SECURITY FIX: Generate Magic Token
            token = str(uuid.uuid4()) # Generates random string like 'f47ac10b-58cc...'
            
            # Save token to DB so we can verify it later
            # We use UPSERT (Insert or Update) to ensure phone exists
            await conn.execute("""
                INSERT INTO users (phone_number, magic_token) 
                VALUES ($1, $2)
                ON CONFLICT (phone_number) 
                DO UPDATE SET magic_token = $2
            """, phone, token)

            # Generate Secure Link (NO PHONE NUMBER IN URL)
            # Replace with your actual Vercel domain
            web_link = f"https://your-site.vercel.app/mobile-address?token={token}"
            
            msg = (
                "🚚 *Shipping Details Needed*\n"
                "To ensure safe delivery, please fill your address securely:\n\n"
                f"🔗 *Click here:* {web_link}"
            )
            await send_whatsapp_message(phone, msg)


async def save_order_to_db(data):
    """
    Inserts data using the Single-Item Schema.
    """
    async with db.pool.acquire() as conn:
        query = """
            INSERT INTO orders (
                customer_phone, 
                item_name, 
                quantity, 
                total_amount, 
                payment_method, 
                delivery_address, 
                delivery_pincode, 
                delivery_city, 
                delivery_state,
                shop_id,
                status,
                payment_status
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, 'pending')
            RETURNING id
        """
        
        # Use .get() with defaults to avoid KeyErrors
        order_id = await conn.fetchval(query,
            data['phone'],
            data['item_name'],
            data['qty'],
            data['total'],
            data['payment_method'],
            data['address'],
            data['pincode'],
            data['city'],
            data['state'],
            data['shop_id'],
            data['status'] # Passed from finalize_order
        )
        return order_id

async def finalize_order(phone, data, addr_id):
    """
    RUTHLESS FINALIZER:
    1. Fetches Address & Shop Settings.
    2. Saves Order (Pending or COD).
    3. Routes to Razorpay, UPI, or COD Confirmation.
    """
    shop_id = data.get("shop_id")
    total_amount = float(data.get("total", 0))
    payment_method = data.get("payment_method", "pay_cod")
    
    # 1. FETCH ADDRESS & SHOP CREDENTIALS IN ONE GO
    async with db.pool.acquire() as conn:
        addr = await conn.fetchrow("SELECT * FROM addresses WHERE id = $1", int(addr_id))
        
        shop = await conn.fetchrow("""
            SELECT name, plan_type, active_payment_method, 
                   razorpay_key_id, razorpay_key_secret, upi_id 
            FROM shops WHERE id = $1
        """, int(shop_id))

    if not addr:
        await send_whatsapp_message(phone, "❌ Critical Error: Address not found.")
        return

    # Construct Address String
    full_addr_str = addr['full_address']
    if not full_addr_str:
        parts = [addr['house_no'], addr['area'], addr['city'], addr['pincode']]
        full_addr_str = ", ".join([p for p in parts if p])

    # 2. DETERMINE INITIAL STATUS
    # If Online, we save as 'PENDING_PAYMENT' first.
    status_text = "COD" if payment_method == "pay_cod" else "PENDING_PAYMENT"

    # 3. PREPARE PAYLOAD
    order_payload = {
        "phone": phone,
        "item_name": data.get("name", "Unknown Item"),
        "qty": int(data.get("qty", 1)),
        "total": total_amount,
        "payment_method": "COD" if payment_method == "pay_cod" else "ONLINE",
        "shop_id": shop_id,
        "address": full_addr_str,
        "pincode": addr['pincode'],
        "city": addr['city'],
        "state": addr['state'],
        "status": status_text
    }

    # 4. SAVE TO DB
    order_id = await save_order_to_db(order_payload)
    
    if not order_id:
        await send_whatsapp_message(phone, "❌ Database Error. Please retry.")
        return

    # 5. ROUTING LOGIC (The Brain 🧠)

    # --- CASE A: CASH ON DELIVERY ---
    if payment_method == "pay_cod":
        msg = (
            f"🎉 *Order Placed Successfully!* 🎉\n"
            f"🆔 Order #{order_id}\n"
            f"📦 Item: {order_payload['item_name']} (x{order_payload['qty']})\n"
            f"💰 Total: ₹{total_amount}\n"
            f"📍 Ship To: {order_payload['city']}\n\n"
            "We will update you when it ships! 🚚"
        )
        await send_whatsapp_message(phone, msg)
        await state_manager.clear_state(phone)
        
        # Trigger Upsell if enabled
        # await trigger_upsell_flow(phone, shop_id, order_id) 
        return

    # --- CASE B: ONLINE PAYMENT ---
    elif payment_method == "pay_online":
        
        # LOGIC: Can we use Razorpay?
        # Must be PRO plan + Razorpay Selected + Keys Exist
        use_razorpay = (
            (shop['plan_type'] == 'pro') and 
            (shop['active_payment_method'] == 'razorpay') and 
            shop['razorpay_key_id'] and 
            shop['razorpay_key_secret']
        )

        # SUB-CASE B1: RAZORPAY AUTOMATION 🤖
        if use_razorpay:
            try:
                import razorpay
                rzp = razorpay.Client(auth=(shop['razorpay_key_id'], shop['razorpay_key_secret']))
                
                link_data = {
                    "amount": int(total_amount * 100), # Paise
                    "currency": "INR",
                    "description": f"Order #{order_id}",
                    "customer": {"contact": phone},
                    "notify": {"sms": True, "email": False},
                    "callback_url": "https://copit.in/payment-success", # Optional
                    "callback_method": "get"
                }
                
                payment_link = rzp.payment_link.create(link_data)
                short_url = payment_link['short_url']
                
                msg = (
                    f"💳 *Complete Your Payment*\n"
                    f"🆔 Order #{order_id}\n"
                    f"💰 Amount: ₹{total_amount}\n\n"
                    f"👇 *Tap to Pay Securely:*\n{short_url}\n\n"
                    f"_(Order confirms automatically after payment)_"
                )
                await send_whatsapp_message(phone, msg)
                
                # Save Link ID to State (for verification later if needed)
                await state_manager.update_state(phone, {"payment_link_id": payment_link['id']})
                return

            except Exception as e:
                print(f"🔥 Razorpay Failed: {e}")
                # Fallback to UPI if Razorpay crashes
        
        # SUB-CASE B2: MANUAL UPI (The Fallback) 🏦
        if shop['upi_id']:
            # Replace with your actual base URL
            base_url = "https://copit.in" 
            pay_url = f"{base_url}/pay/manual?shop={shop_id}&amount={total_amount}&order={order_id}"
            
            msg = (
                f"🏦 *Direct Payment Link*\n"
                f"Amount: ₹{total_amount}\n\n"
                f"👇 *Tap to Pay via UPI:*\n{pay_url}\n\n"
                f"⚠️ *Important:* After paying, please send a *Screenshot* here to confirm."
            )
            
            # Update state to wait for screenshot
            await state_manager.set_state(phone, {
                "state": "awaiting_screenshot", 
                "order_id": order_id,
                "shop_id": shop_id
            })
            await send_whatsapp_message(phone, msg)
        else:
            await send_whatsapp_message(phone, "❌ Seller has not set up payments. Please choose COD.")


async def save_order_to_db(data):
    """
    Inserts data using the Single-Item Schema.
    """
    async with db.pool.acquire() as conn:
        query = """
            INSERT INTO orders (
                customer_phone, 
                item_name, 
                quantity, 
                total_amount, 
                payment_method, 
                delivery_address, 
                delivery_pincode, 
                delivery_city, 
                delivery_state,
                shop_id,
                status,
                payment_status
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, 'pending')
            RETURNING id
        """
        
        # Use .get() with defaults to avoid KeyErrors
        order_id = await conn.fetchval(query,
            data['phone'],
            data['item_name'],
            data['qty'],
            data['total'],
            data['payment_method'],
            data['address'],
            data['pincode'],
            data['city'],
            data['state'],
            data['shop_id'],
            data['status'] # Passed from finalize_order
        )
        return order_id





# Initialize a logger (Standard practice for production apps)
logger = logging.getLogger("drop_bot")

async def schedule_image_deletion(order_id: int, delay_seconds: int = 1800):
    """
    Background Task: Removes sensitive payment screenshot references after a delay.
    
    Args:
        order_id (int): The ID of the order to clean.
        delay_seconds (int): How long to wait before deletion (Default: 30 mins).
    """
    try:
        # 1. The Wait (Non-blocking)
        # We allow the verify process time to happen.
        await asyncio.sleep(delay_seconds)

        # 2. The Cleanup
        # We use the new 'db.pool' you set up.
        async with db.pool.acquire() as conn:
            # We set the screenshot_id to NULL to "forget" it.
            result = await conn.execute(
                "UPDATE orders SET screenshot_id = NULL WHERE id = $1", 
                order_id
            )

        # 3. Professional Logging
        # 'UPDATE 1' means 1 row was changed.
        if result == "UPDATE 1":
            logger.info(f"🧹 Storage Purged: Screenshot removed for Order #{order_id}")
        else:
            logger.info(f"⚠️ Storage Purged: Order #{order_id} was already clean or not found.")

    except Exception as e:
        # 🛡️ SAFETY NET: Background tasks usually fail silently. 
        # This ensures you see the error in your server logs.
        logger.error(f"🔥 cleanup_task_failed: Order #{order_id} - Error: {e}")



# app/services/order_service.py

# Ensure these imports exist at the top of your file:
# from app.core.database import db
# from app.utils.whatsapp import send_interactive_message, send_whatsapp_message
# from app.utils.state_manager import state_manager

async def handle_selection_drilldown(phone, text_or_id, current_data):
    """
    Handles navigation:
    1. User selects a Category -> Show Products.
    2. User selects a Product -> Show Details (Handoff).
    """
    selection_id = text_or_id.strip() # e.g., "CAT_ELECTRONICS" or "ITEM_55"

    # --------------------------------------------------------
    # SCENARIO A: User Selected a CATEGORY
    # --------------------------------------------------------
    if selection_id.startswith("CAT_"):
        category_name = selection_id.replace("CAT_", "")
        shop_id = current_data.get("shop_id")

        async with db.pool.acquire() as conn:
            # Fetch items in this category
            items = await conn.fetch("""
                SELECT id, name, price, description 
                FROM items 
                WHERE shop_id = $1 AND category = $2 AND stock_quantity > 0
                LIMIT 10
            """, shop_id, category_name)

        if not items:
            await send_whatsapp_message(phone, f"🚫 No items found in {category_name}.")
            return

        # Construct Product List
        # (Note: Interactive Lists are complex, simplified here as buttons for <3 items, 
        # or you can implement the full 'list' type payload helper)
        if len(items) <= 3:
            # Use Buttons for small lists
            btns = [{"id": f"ITEM_{i['id']}", "title": i['name'][:20]} for i in items]
            msg = f"📂 *{category_name}*\nSelect an item:"
            await send_interactive_message(phone, msg, btns)
        else:
            # For 4+ items, usually you'd send a "List Message" (requires extra helper),
            # OR just text with codes. Let's use a Text List for robustness/simplicity.
            msg = f"📂 *{category_name}*\n\n"
            for i in items:
                msg += f"• *{i['name']}* (₹{i['price']})\n   👉 Type *buy_item_{i['id']}*\n\n"
            
            await send_whatsapp_message(phone, msg)
        
        return

    # --------------------------------------------------------
    # SCENARIO B: User Selected an ITEM (via Button or List)
    # --------------------------------------------------------
    if selection_id.startswith("ITEM_"):
        try:
            item_id = int(selection_id.replace("ITEM_", ""))
            # Re-use your existing logic to show the product
            # (Assuming handle_web_handoff is in this same file or imported)
            await handle_web_handoff(phone, item_id)
        except ValueError:
            print(f"🔥 Error parsing Item ID: {selection_id}")
            
    # --------------------------------------------------------
    # SCENARIO C: Unknown Selection
    # --------------------------------------------------------
    else:
        # Fallback
        pass