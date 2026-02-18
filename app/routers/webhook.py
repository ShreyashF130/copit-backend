from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import PlainTextResponse 
import re
import logging
import json
import os

# 1. CORE & UTILS
from app.core.database import db
from app.routers.checkout import create_checkout_url 
from app.utils.state_manager import state_manager
from app.utils.whatsapp import (
    send_whatsapp_message, 
    send_interactive_message, 
    send_image_message
)

# 2. SERVICES
from app.services.order_service import (
    check_address_before_payment, 
    finalize_order, 
    save_order_to_db, 
    handle_selection_drilldown,
    handle_web_handoff, 
    handle_bulk_handoff 
)

router = APIRouter()
logger = logging.getLogger("drop_bot")

@router.post("/webhook")
async def receive_message(request: Request):
    try:
        data = await request.json()
        
        # 1. PARSING
        try:
            entry = data.get("entry", [{}])[0]
            changes = entry.get("changes", [{}])[0]
            val = changes.get("value", {})
            if "messages" not in val: return {"status": "ok"}
            msg = val["messages"][0]
            phone = msg["from"]
            msg_type = msg.get("type")
        except:
            return {"status": "ok"}
        
        # 2. STATE MANAGEMENT
        current_data = await state_manager.get_state(phone)
        if not isinstance(current_data, dict): current_data = {}    
        state = current_data.get("state")

        # ============================================================
        # A. IMAGE MESSAGES (PAYMENT PROOF)
        # ============================================================
        if msg_type == "image":
            # Only process images if we are waiting for payment proof
            if state == "awaiting_screenshot":
                order_id = current_data.get("order_id")
                image_id = msg['image']['id']
                
                logger.info(f"📸 Screenshot received for Order #{order_id}")

                async with db.pool.acquire() as conn:
                    # Fetch Seller Phone & Order Amount
                    row = await conn.fetchrow("""
                        SELECT s.phone_number, o.total_amount 
                        FROM orders o JOIN shops s ON o.shop_id = s.id 
                        WHERE o.id = $1
                    """, int(order_id))
                    
                    if row:
                        seller_phone = row['phone_number']
                        amount = row['total_amount']

                        # Update Order to 'needs_approval'
                        await conn.execute("""
                            UPDATE orders 
                            SET payment_status = 'needs_approval', 
                                screenshot_id = $1 
                            WHERE id = $2
                        """, image_id, int(order_id))

                        # Notify Customer
                        await send_whatsapp_message(phone, "✅ **Payment Proof Received!**\n\nWaiting for seller verification. You will receive a confirmation shortly.")
                        await state_manager.clear_state(phone)

                        # Notify Seller (Escrow Loop)
                        txt = f"🔔 *New Payment Verification*\nOrder: #{order_id}\nAmount: ₹{amount}\n\n👇 Is this valid?"
                        btns = [
                            {"id": f"VERIFY_YES_{order_id}", "title": "✅ Approve"},
                            {"id": f"VERIFY_NO_{order_id}", "title": "❌ Reject"}
                        ]
                        
                        # Send Image First, then Buttons
                        await send_image_message(seller_phone, image_id, "🔍 Customer Payment Proof") 
                        await send_interactive_message(seller_phone, txt, btns)

            return {"status": "ok"}

        # ============================================================
        # B. INTERACTIVE MESSAGES (BUTTONS)
        # ============================================================
        if msg_type == "interactive":
            interactive = msg["interactive"]
            
            if interactive["type"] == "button_reply":
                selection_id = interactive["button_reply"]["id"]
                logger.info(f"🔘 Button Clicked: {selection_id}")

                # --- SELLER VERIFICATION (YES/NO) ---
                if selection_id.startswith("VERIFY_"):
                    action, order_id_str = selection_id.split("_")[1], selection_id.split("_")[2]
                    order_id = int(order_id_str)

                    async with db.pool.acquire() as conn:
                        order = await conn.fetchrow("SELECT customer_phone FROM orders WHERE id = $1", order_id)
                        if not order: return {"status": "ok"}
                        
                        cust_phone = order['customer_phone']

                        if action == "YES":
                            await conn.execute("UPDATE orders SET payment_status = 'paid', status = 'processing' WHERE id = $1", order_id)
                            await send_whatsapp_message(phone, f"✅ Order #{order_id} marked as PAID.")
                            await send_whatsapp_message(cust_phone, f"🎉 *Payment Verified!* \nOrder #{order_id} is confirmed. We are packing it now! 📦")
                        else:
                            await conn.execute("UPDATE orders SET payment_status = 'failed', status = 'cancelled' WHERE id = $1", order_id)
                            await send_whatsapp_message(phone, f"❌ Order #{order_id} rejected.")
                            await send_whatsapp_message(cust_phone, f"⚠️ *Payment Rejected.*\nThe seller could not verify your payment for Order #{order_id}. Please contact support.")
                    return {"status": "ok"}

                # --- ADDRESS CONFIRMATION ---
                if selection_id.startswith("CONFIRM_ADDR"):
                    try:
                        addr_id = int(selection_id.split("_")[-1])
                        await state_manager.update_state(phone, {"address_confirmed": True, "address_id": addr_id})
                        
                        total = current_data.get("total", 0)
                        shop_id = current_data.get("shop_id")

                        # Check if Razorpay is enabled for this shop
                        has_razorpay = False
                        if shop_id:
                            async with db.pool.acquire() as conn:
                                shop = await conn.fetchrow("SELECT razorpay_key_id, active_payment_method FROM shops WHERE id = $1", int(shop_id))
                                if shop and shop['razorpay_key_id'] and shop['active_payment_method'] == 'razorpay':
                                    has_razorpay = True

                        # Show Payment Options
                        btns = [{"id": "pay_cod", "title": "Cash on Delivery"}]
                        if has_razorpay:
                            btns.insert(0, {"id": "pay_online", "title": "Pay Online (Gateway)"})
                        else:
                            btns.insert(0, {"id": "pay_online", "title": "Pay via UPI (Manual)"})

                        await send_interactive_message(phone, f"✅ Address Confirmed!\n💰 *Total: ₹{total}*\nSelect Payment Method:", btns)
                    except:
                        await check_address_before_payment(phone)
                    return {"status": "ok"}

                # --- CHANGE ADDRESS (WEB) ---
                if selection_id == "CHANGE_ADDR":
                    checkout_link = await create_checkout_url(phone)
                    await send_whatsapp_message(phone, f"Tap to update address:\n🔗 {checkout_link}\n_Link expires in 10 mins_")
                    return {"status": "ok"}

                # --- PAYMENT SELECTION ---
                if selection_id in ["pay_online", "pay_cod"]:
                    await state_manager.update_state(phone, {"payment_method": selection_id})
                    
                    addr_id = current_data.get("address_id")
                    if not addr_id:
                        async with db.pool.acquire() as conn:
                            addr_id = await conn.fetchval("SELECT id FROM addresses WHERE user_id = $1 ORDER BY created_at DESC LIMIT 1", phone)
                    
                    if addr_id:
                        await finalize_order(phone, current_data, addr_id)
                    else:
                        await check_address_before_payment(phone)
                    return {"status": "ok"}

                if selection_id == "recover_cancel":
                    await state_manager.clear_state(phone)
                    await send_whatsapp_message(phone, "❌ Cart cleared.")
                    return {"status": "ok"}

            return {"status": "ok"}
        
        # ============================================================
        # C. TEXT MESSAGES
        # ============================================================
        elif msg_type == "text":
            text = msg["text"]["body"].strip()

            # --- ADDRESS RETURN FROM WEB ---
            if "Address_Confirmed_for_" in text:
                async with db.pool.acquire() as conn:
                    addr_id = await conn.fetchval("SELECT id FROM addresses WHERE user_id = $1 ORDER BY created_at DESC LIMIT 1", phone)

                if addr_id:
                    await state_manager.update_state(phone, {"address_confirmed": True, "address_id": addr_id})
                    total = current_data.get("total", 0)
                    
                    # Logic to show correct payment buttons based on Shop Plan
                    shop_id = current_data.get("shop_id")
                    has_razorpay = False
                    if shop_id:
                        async with db.pool.acquire() as conn:
                            shop = await conn.fetchrow("SELECT razorpay_key_id, active_payment_method FROM shops WHERE id = $1", int(shop_id))
                            if shop and shop['razorpay_key_id'] and shop['active_payment_method'] == 'razorpay':
                                has_razorpay = True
                    
                    btns = [{"id": "pay_cod", "title": "Cash on Delivery"}]
                    if has_razorpay:
                        btns.insert(0, {"id": "pay_online", "title": "Pay Online (Gateway)"})
                    else:
                        btns.insert(0, {"id": "pay_online", "title": "Pay via UPI (Manual)"})

                    await send_interactive_message(phone, f"✅ Address Updated!\n💰 *Total: ₹{total}*\nSelect Payment:", btns)
                else:
                    await send_whatsapp_message(phone, "⚠️ Error verifying address. Please try again.")
                return {"status": "ok"}

            # --- UTR HANDLER (TEXT PROOF) ---
            if state == "awaiting_screenshot" and len(text) > 4:
                order_id = current_data.get("order_id")
                async with db.pool.acquire() as conn:
                    await conn.execute("UPDATE orders SET payment_status = 'needs_approval', transaction_id = $1 WHERE id = $2", text, int(order_id))
                    
                    # Notify Customer
                    await send_whatsapp_message(phone, "✅ **UTR Received.** Waiting for verification.")
                    await state_manager.clear_state(phone)

                    # Notify Seller
                    row = await conn.fetchrow("SELECT s.phone_number, o.total_amount FROM orders o JOIN shops s ON o.shop_id = s.id WHERE o.id = $1", int(order_id))
                    if row:
                        msg = f"🔔 *Manual Payment (UTR)*\nOrder: #{order_id}\nAmount: ₹{row['total_amount']}\nUTR: {text}\n\nVerify this?"
                        btns = [{"id": f"VERIFY_YES_{order_id}", "title": "✅ Approve"}, {"id": f"VERIFY_NO_{order_id}", "title": "❌ Reject"}]
                        await send_interactive_message(row['phone_number'], msg, btns)
                return {"status": "ok"}

            # --- BUYING FLOWS ---
            if "buy_bulk_" in text:
                await handle_bulk_handoff(phone, text)
                return {"status": "ok"}

            if "buy_item_" in text:
                match = re.search(r"buy_item_(\d+)", text)
                if match: await handle_web_handoff(phone, int(match.group(1))) 
                return {"status": "ok"}
            
            # --- QUANTITY ---
            if state == "awaiting_qty" and text.isdigit():
                qty = int(text)
                price = current_data.get('price', 0)
                await state_manager.update_state(phone, {"qty": qty, "total": price * qty})
                await check_address_before_payment(phone)
                return {"status": "ok"}

            # --- UPSELL ---
            if state == "awaiting_upsell_decision":
                user_reply = text.strip().lower()
                if user_reply in ["yes", "add", "ok", "y"]:
                    upsell_item = current_data.get('upsell_item', {})
                    new_order = {
                        "phone": phone, "shop_id": current_data.get('shop_id'),
                        "total": upsell_item.get('price', 0),
                        "item_name": upsell_item.get('name', 'Add-on'), 
                        "qty": 1, "payment_method": "COD"
                    }
                    await save_order_to_db(new_order)
                    await send_whatsapp_message(phone, "🎉 Add-on confirmed!")
                else:
                    await send_whatsapp_message(phone, "Order processed. ✅")
                await state_manager.clear_state(phone)
                return {"status": "ok"}

    except Exception as e:
        logger.error(f"🔥 Webhook Error: {e}", exc_info=True)
        
    return {"status": "ok"}    

@router.get("/webhook")
async def verify_webhook(request: Request):
    if request.query_params.get("hub.verify_token") == os.getenv("VERIFY_TOKEN"):
        return PlainTextResponse(request.query_params.get("hub.challenge"), 200)
    raise HTTPException(status_code=403, detail="Verification failed")