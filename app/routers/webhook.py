# from email import message
# from fastapi import APIRouter, Request, HTTPException
# import re
# import logging
# import json

# import os
# # 1. CORE & UTILS
# from app.core.database import db
# from app.routers.checkout import create_checkout_url
# from app.utils.state_manager import state_manager
# from app.utils.whatsapp import  send_whatsapp_message, send_interactive_message ,send_address_flow

# # 2. SERVICES (The Business Logic)
# from app.services.shop_service import get_seller_phone
# from app.utils.shiprocket import check_serviceability
# from fastapi.responses import PlainTextResponse 



# from app.services.order_service import (
#     check_address_before_payment, 
#     finalize_order, 
#     save_order_to_db,
#     handle_selection_drilldown,
#     handle_web_handoff, 
#     handle_bulk_handoff 
# )

# # Initialize Router
# router = APIRouter()
# logger = logging.getLogger(__name__)


# @router.post("/webhook")
# async def receive_message(request: Request):
#     try:
#         data = await request.json()
        
#         # 1. PARSING
#         # Standard Meta Payload Extraction
#         entry = data.get("entry", [{}])[0]
#         changes = entry.get("changes", [{}])[0]
#         val = changes.get("value", {})
        
#         # Filter: Ignore status updates (sent, delivered, read)
#         if "messages" not in val: 
#             return {"status": "ok"}
        
#         msg = val["messages"][0]
#         phone = msg["from"]
#         msg_type = msg.get("type")
        
#         # 2. GET USER STATE
#         current_data = await state_manager.get_state(phone)
#         if not isinstance(current_data, dict):
#             current_data = {}    
#         state = current_data.get("state")

#         # ============================================================
#         # A. INTERACTIVE MESSAGES (Button Clicks & FLOW REPLIES)
#         # ============================================================
#         if msg_type == "interactive":
#             interactive = msg["interactive"]
            
#             # 👇 [NEW] 1. HANDLE FLOW DATA SUBMISSION (The Capture)
#             if interactive["type"] == "nfm_reply":
#                 try:
#                     # A. Parse the JSON sent back by WhatsApp
#                     reply_json = json.loads(interactive["nfm_reply"]["response_json"])
                    
#                     # B. Extract Data
#                     pincode = reply_json.get("pincode")
#                     house_no = reply_json.get("house_no")
#                     area = reply_json.get("area")
#                     city = reply_json.get("city")
                    
#                     # C. INDUSTRIAL VALIDATION (Trust No One)
#                     if not pincode or len(str(pincode)) != 6:
#                         await send_whatsapp_message(phone, "❌ Invalid Pincode. Please enter a 6-digit code.")
#                         return {"status": "ok"}

#                     # D. SAVE TO DATABASE
#                     async with db.pool.acquire() as conn:
#                         # Ensure user exists first
#                         await conn.execute("INSERT INTO users (phone_number) VALUES ($1) ON CONFLICT DO NOTHING", phone)
                        
#                         # Insert Address
#                         addr_id = await conn.fetchval("""
#                             INSERT INTO addresses (user_id, pincode, house_no, area, city, is_default, created_at)
#                             VALUES ($1, $2, $3, $4, $5, TRUE, NOW())
#                             RETURNING id
#                         """, phone, pincode, house_no, area, city)

#                     # E. UPDATE STATE & MOVE TO PAYMENT
#                     await state_manager.update_state(phone, {"address_id": addr_id})
                    
#                     total = current_data.get("total", 0)
#                     btns = [
#                         {"id": "pay_online", "title": "Pay Online"}, 
#                         {"id": "pay_cod", "title": "Cash on Delivery"}
#                     ]
#                     await send_interactive_message(phone, f"✅ Address Saved!\n💰 *Total: ₹{total}*\nSelect Payment Method:", btns)
                    
#                 except Exception as e:
#                     logger.error(f"🔥 Flow Data Error: {e}", exc_info=True)
#                     await send_whatsapp_message(phone, "❌ Error saving address. Please try again.")
                
#                 return {"status": "ok"}

#             # 👇 2. HANDLE STANDARD BUTTON CLICKS
#             # (We only check button_reply if it's NOT a flow reply)
#             if interactive["type"] == "button_reply":
#                 selection_id = interactive["button_reply"]["id"]

#                 # --- ADDRESS CONFIRMATION (Old Address) ---
#                 if selection_id.startswith("CONFIRM_ADDR_"):
#                     try:
#                         addr_id = int(selection_id.split("_")[-1])
#                         await state_manager.update_state(phone, {"address_id": addr_id})
                        
#                         total = current_data.get("total", 0)
#                         btns = [
#                             {"id": "pay_online", "title": "Pay Online"}, 
#                             {"id": "pay_cod", "title": "Cash on Delivery"}
#                         ]
#                         await send_interactive_message(phone, f"✅ Address Confirmed!\n💰 *Total: ₹{total}*\nSelect Payment Method:", btns)
#                     except ValueError:
#                         logger.error(f"Invalid Address ID: {selection_id}")
#                     return {"status": "ok"}

#                 # --- [UPDATED] CHANGE ADDRESS (Trigger Flow) ---
#                 if selection_id == "CHANGE_ADDR":
#                     # 🚀 RUTHLESS UPDATE: No more web links. Call the Flow.
#                     phone = message["from"]  # Extract sender phone
#                     checkout_link = create_checkout_url(phone)

#                     # B. Send the Reply
#                     response_text = (
#                         "Tap the link below to securely update your address:\n\n"
#                         f"🔗 {checkout_link}\n\n"
#                         "_This link expires in 24 hours._"
#                     )
#                     await send_whatsapp_message(phone, response_text)
                    
#                     # STOP here. Do not process further.
#                     return {"status": "success"}

#                 # --- PAYMENT SELECTION ---
#                 if selection_id in ["pay_online", "pay_cod"]:
#                     await state_manager.update_state(phone, {"payment_method": selection_id})
                    
#                     raw_addr_id = current_data.get("address_id")
                    
#                     # Logic: If address ID missing, force address flow
#                     if not raw_addr_id:
#                         await check_address_before_payment(phone)
#                         return {"status": "ok"}

#                     try:
#                         addr_id = int(raw_addr_id)
#                         await finalize_order(phone, current_data, addr_id)
#                     except (ValueError, TypeError):
#                         await check_address_before_payment(phone)
                    
#                     return {"status": "ok"}

#                 # --- CART RECOVERY ---
#                 if selection_id == "recover_checkout":
#                     await check_address_before_payment(phone)
#                     return {"status": "ok"}

#                 if selection_id == "recover_cancel":
#                     await state_manager.clear_state(phone)
#                     await send_whatsapp_message(phone, "❌ Cart cleared.")
#                     return {"status": "ok"}

#             return {"status": "ok"}
        
#         # ============================================================
#         # B. TEXT MESSAGES
#         # ============================================================
#         elif msg_type == "text":
#             text = msg["text"]["body"].strip()

#             # --- 1. BULK ORDER TRIGGER (Regex Match) ---
#             if "buy_bulk_" in text:
#                 match = re.search(r"buy_bulk_([\d:,]+)", text)
#                 if match:
#                     ref_string = match.group(0) 
#                     await handle_bulk_handoff(phone, ref_string)
#                 return {"status": "ok"}

#             # --- 2. SINGLE ITEM TRIGGER ---
#             if "buy_item_" in text:
#                 match = re.search(r"buy_item_(\d+)", text)
#                 if match:
#                     item_id = int(match.group(1))
#                     await handle_web_handoff(phone, item_id) 
#                 return {"status": "ok"}
            
#             # --- 3. REVIEWS ---
#             if text == "4-5 Stars":
#                 await state_manager.update_state(phone, {
#                     "rating": 5, 
#                     "state": "awaiting_review_comment",
#                     "review_mode": "public" 
#                 })
#                 await send_whatsapp_message(phone, "❤️ Thank you! Could you write a short review for our website?")
#                 return {"status": "ok"}

#             # --- 4. STATE: MANUAL ADDRESS INPUT (Fallback) ---
#             if state == "awaiting_manual_address":
#                 parts = [p.strip() for p in text.split(",")]
#                 if len(parts) >= 2:
#                     pincode, house_no = parts[0], parts[1]
#                     city = parts[2] if len(parts) > 2 else "India"
                    
#                     async with db.pool.acquire() as conn:
#                         await conn.execute("INSERT INTO users (phone_number) VALUES ($1) ON CONFLICT DO NOTHING", phone)
#                         addr_id = await conn.fetchval("""
#                             INSERT INTO addresses (user_id, pincode, city, state, house_no, area, is_default)
#                             VALUES ($1, $2, $3, 'India', $4, 'Area', TRUE)
#                             RETURNING id
#                         """, phone, pincode, city, house_no)

#                     await state_manager.update_state(phone, {"state": "active", "address_id": addr_id}) 
#                     btns = [{"id": "pay_online", "title": "Pay Online"}, {"id": "pay_cod", "title": "Cash on Delivery"}]
#                     await send_interactive_message(phone, "✅ Address Saved! Select Payment Method:", btns)
#                 else:
#                     await send_whatsapp_message(phone, "⚠️ Format: *Pincode, House No, City*")
#                 return {"status": "ok"}

#             # --- 5. STATE: UPSELL DECISION ---
#             elif state == "awaiting_upsell_decision":
#                 user_reply = text.strip().lower()
#                 if user_reply in ["yes", "add", "ok", "y", "1"]:
#                     upsell_item = current_data.get('upsell_item', {})
#                     shop_id = current_data.get('shop_id')
#                     original_order_id = current_data.get('linked_order_id')
                    
#                     # Inherit address from previous order
#                     address_payload = {}
#                     if original_order_id:
#                         async with db.pool.acquire() as conn:
#                             prev = await conn.fetchrow("SELECT delivery_address, delivery_pincode, delivery_city, delivery_state FROM orders WHERE id = $1", original_order_id)
#                             if prev:
#                                 address_payload = {
#                                     "address": prev['delivery_address'],
#                                     "pincode": prev['delivery_pincode'],
#                                     "city": prev['delivery_city'],
#                                     "state": prev['delivery_state']
#                                 }

#                     new_order = {
#                         "phone": phone, "shop_id": shop_id,
#                         "total": upsell_item.get('price', 0),
#                         "item_name": upsell_item.get('name', 'Add-on'), 
#                         "qty": 1, "payment_method": "COD", "status": "COD",
#                         **address_payload
#                     }
#                     order_id = await save_order_to_db(new_order)
#                     await send_whatsapp_message(phone, f"🎉 Added {upsell_item.get('name')} for ₹{upsell_item.get('price')}.")
                    
#                     seller_phone = await get_seller_phone(shop_id)
#                     if seller_phone:
#                         await send_whatsapp_message(seller_phone, f"🔥 *UPSELL CONVERTED!* Order #{order_id}")
#                 else:
#                     await send_whatsapp_message(phone, "No problem! Your original order is processed. ✅")
                
#                 await state_manager.clear_state(phone)
#                 return {"status": "ok"}

#             # --- 6. STATE: DRILLDOWN (Category/Product Selection) ---
#             elif state == "awaiting_selection":
#                 await handle_selection_drilldown(phone, text, current_data)
#                 return {"status": "ok"}

#             # --- 7. STATE: QUANTITY & STOCK CHECK ---
#             elif state == "awaiting_qty" and text.isdigit():
#                 qty = int(text)
#                 raw_item_id = current_data.get('item_id')
                
#                 if not raw_item_id:
#                      await send_whatsapp_message(phone, "⚠️ Session Expired.")
#                      await state_manager.clear_state(phone)
#                      return {"status": "ok"}
                
#                 item_id = int(raw_item_id)
#                 if qty < 1:
#                     await send_whatsapp_message(phone, "⚠️ Min quantity is 1.")
#                     return {"status": "ok"}

#                 async with db.pool.acquire() as conn:
#                     # Fetch Stock
#                     row = await conn.fetchrow("SELECT stock_count, name, price FROM items WHERE id = $1", item_id)
#                     if not row:
#                         await send_whatsapp_message(phone, "❌ Item not found.")
#                         return {"status": "ok"}

#                     live_stock = row['stock_count'] 
#                     item_name = row['name']
#                     price = float(row['price'])

#                     if live_stock == 0:
#                         await send_whatsapp_message(phone, f"😢 *{item_name} is SOLD OUT.*")
#                         await state_manager.clear_state(phone)
#                         return {"status": "ok"}

#                     if qty > live_stock:
#                         await send_whatsapp_message(phone, f"⚠️ Only *{live_stock}* left. Type *{live_stock}* to buy all!")
#                         return {"status": "ok"}

#                 # Stock Valid -> Update State -> Address Flow
#                 await state_manager.update_state(phone, {
#                     "total": price * qty,
#                     "qty": qty,
#                     "name": item_name, 
#                     "price": price
#                 })
#                 await check_address_before_payment(phone)
#                 return {"status": "ok"}

#     except Exception as e:
#         logger.error(f"🔥 Webhook Error: {e}", exc_info=True)
        
#     return {"status": "ok"}    




# @router.get("/webhook")
# async def verify_webhook(request: Request):
#     """
#     Handle Meta's verification challenge.
#     """
#     # 1. Get query parameters
#     mode = request.query_params.get("hub.mode")
#     token = request.query_params.get("hub.verify_token")
#     challenge = request.query_params.get("hub.challenge")

#     # 2. Check if token matches YOUR secret (Define this in Meta Dashboard)
#     # RUTHLESS NOTE: Replace 'dropbot_secure_123' with whatever you typed in Meta.
#     MY_VERIFY_TOKEN = os.getenv("VERIFY_TOKEN") 

#     if mode == "subscribe" and token == MY_VERIFY_TOKEN:
#         print("✅ Webhook Verified!")
#         # 3. Return the challenge as PLAIN TEXT (Not JSON)
#         return PlainTextResponse(content=challenge, status_code=200)
    
#     # 4. If token is wrong, reject it.
#     raise HTTPException(status_code=403, detail="Verification failed")

# from fastapi import APIRouter, Request, HTTPException
# from fastapi.responses import PlainTextResponse 
# import re
# import logging
# import json
# import os

# # 1. CORE & UTILS
# from app.core.database import db
# from app.routers.checkout import create_checkout_url 
# from app.utils.state_manager import state_manager
# from app.utils.whatsapp import send_whatsapp_message, send_interactive_message, send_address_flow

# # 2. SERVICES
# from app.services.shop_service import get_seller_phone
# from app.utils.shiprocket import check_serviceability
# from app.services.order_service import (
#     check_address_before_payment, 
#     finalize_order, 
#     save_order_to_db,
#     handle_selection_drilldown,
#     handle_web_handoff, 
#     handle_bulk_handoff 
# )

# # Initialize Router
# router = APIRouter()
# logger = logging.getLogger(__name__)

# @router.post("/webhook")
# async def receive_message(request: Request):
#     try:
#         data = await request.json()
        
#         # 1. PARSING
#         entry = data.get("entry", [{}])[0]
#         changes = entry.get("changes", [{}])[0]
#         val = changes.get("value", {})
        
#         if "messages" not in val: 
#             return {"status": "ok"}
        
#         msg = val["messages"][0]
#         phone = msg["from"]
#         msg_type = msg.get("type")
        
#         # 2. GET USER STATE
#         current_data = await state_manager.get_state(phone)
#         if not isinstance(current_data, dict):
#             current_data = {}    
#         state = current_data.get("state")

#         # ============================================================
#         # A. INTERACTIVE MESSAGES
#         # ============================================================
#         if msg_type == "interactive":
#             interactive = msg["interactive"]
            
#             # --- HANDLE BUTTON CLICKS ---
#             if interactive["type"] == "button_reply":
#                 selection_id = interactive["button_reply"]["id"]

#                 # --- OLD ADDRESS CONFIRMATION ---
#                 if selection_id.startswith("CONFIRM_ADDR"):
#                     try:
#                         addr_id = int(selection_id.split("_")[-1])
#                         await state_manager.update_state(phone, {"address_confirmed": True, "address_id": addr_id})
                        
#                         total = current_data.get("total", 0)
#                         btns = [
#                             {"id": "pay_online", "title": "Pay Online"}, 
#                             {"id": "pay_cod", "title": "Cash on Delivery"}
#                         ]
#                         await send_interactive_message(phone, f"✅ Address Confirmed!\n💰 *Total: ₹{total}*\nSelect Payment Method:", btns)
#                     except:
#                         await check_address_before_payment(phone)
#                     return {"status": "ok"}

#                 # --- CHANGE ADDRESS (Web Link) ---
#                 if selection_id == "CHANGE_ADDR":
#                     checkout_link = await create_checkout_url(phone)
#                     response_text = (
#                         "Tap the link below to securely update your address:\n\n"
#                         f"🔗 {checkout_link}\n\n"
#                         "_This link expires in 10 minutes._"
#                     )
#                     await send_whatsapp_message(phone, response_text)
#                     return {"status": "ok"}

#                 # --- PAYMENT SELECTION ---
#                 if selection_id in ["pay_online", "pay_cod"]:
#                     await state_manager.update_state(phone, {"payment_method": selection_id})
                    
#                     # 1. Get Address ID (Try State first)
#                     addr_id = current_data.get("address_id")

#                     # 2. If missing (Web Flow case), fetch LATEST from DB
#                     if not addr_id:
#                         async with db.pool.acquire() as conn:
#                             addr_id = await conn.fetchval("""
#                                 SELECT id FROM addresses 
#                                 WHERE user_id = $1 
#                                 ORDER BY created_at DESC LIMIT 1
#                             """, phone)
                    
#                     # 3. If STILL missing, force them to add address
#                     if not addr_id:
#                         await check_address_before_payment(phone)
#                         return {"status": "ok"}

#                     # 4. Finalize
#                     await finalize_order(phone, current_data, addr_id)
#                     return {"status": "ok"}

#                 # --- RECOVER CHECKOUT ---
#                 if selection_id == "recover_checkout":
#                     await check_address_before_payment(phone)
#                     return {"status": "ok"}

#                 # --- CANCEL ---
#                 if selection_id == "recover_cancel":
#                     await state_manager.clear_state(phone)
#                     await send_whatsapp_message(phone, "❌ Cart cleared.")
#                     return {"status": "ok"}

#             return {"status": "ok"}
        
#         # ============================================================
#         # B. TEXT MESSAGES
#         # ============================================================
#         elif msg_type == "text":
#             text = msg["text"]["body"].strip()

#             # --- [NEW] ADDRESS CONFIRMATION RETURN ---
#             if "Address_Confirmed_for_" in text:
#                 logger.info(f"✅ Received Address Confirmation from {phone}")
                
#                 async with db.pool.acquire() as conn:
#                     addr_id = await conn.fetchval("""
#                         SELECT id FROM addresses 
#                         WHERE user_id = $1 
#                         ORDER BY created_at DESC LIMIT 1
#                     """, phone)

#                 await state_manager.update_state(phone, {
#                     "address_confirmed": True,
#                     "address_id": addr_id,
#                     "state": "awaiting_payment_method"
#                 })
                
#                 total = current_data.get("total", 0)
#                 btns = [
#                     {"id": "pay_online", "title": "Pay Online"}, 
#                     {"id": "pay_cod", "title": "Cash on Delivery"}
#                 ]
#                 await send_interactive_message(phone, f"✅ Address Updated Successfully!\n\n💰 *Total: ₹{total}*\nSelect Payment Method:", btns)
#                 return {"status": "ok"}

#             # --- BULK ORDER ---
#             if "buy_bulk_" in text:
#                 match = re.search(r"buy_bulk_([\d:,]+)", text)
#                 if match:
#                     await handle_bulk_handoff(phone, match.group(0))
#                 return {"status": "ok"}

#             # --- SINGLE ITEM ---
#             if "buy_item_" in text:
#                 match = re.search(r"buy_item_(\d+)", text)
#                 if match:
#                     await handle_web_handoff(phone, int(match.group(1))) 
#                 return {"status": "ok"}
            
#             # --- [RESTORED] REVIEWS ---
#             if text == "4-5 Stars":
#                 await state_manager.update_state(phone, {
#                     "rating": 5, 
#                     "state": "awaiting_review_comment",
#                     "review_mode": "public" 
#                 })
#                 await send_whatsapp_message(phone, "❤️ Thank you! Could you write a short review for our website?")
#                 return {"status": "ok"}

#             # --- MANUAL ADDRESS FALLBACK ---
#             if state == "awaiting_manual_address":
#                 parts = [p.strip() for p in text.split(",")]
#                 if len(parts) >= 2:
#                     pincode, house_no = parts[0], parts[1]
#                     city = parts[2] if len(parts) > 2 else "India"
                    
#                     async with db.pool.acquire() as conn:
#                         await conn.execute("INSERT INTO users (phone_number) VALUES ($1) ON CONFLICT DO NOTHING", phone)
#                         addr_id = await conn.fetchval("""
#                             INSERT INTO addresses (user_id, pincode, house_no, city, state, is_default)
#                             VALUES ($1, $2, $3, $4, 'India', TRUE)
#                             RETURNING id
#                         """, phone, pincode, house_no, city)

#                     await state_manager.update_state(phone, {"state": "active", "address_confirmed": True, "address_id": addr_id}) 
#                     btns = [{"id": "pay_online", "title": "Pay Online"}, {"id": "pay_cod", "title": "Cash on Delivery"}]
#                     await send_interactive_message(phone, "✅ Address Saved! Select Payment Method:", btns)
#                 else:
#                     await send_whatsapp_message(phone, "⚠️ Format: *Pincode, House No, City*")
#                 return {"status": "ok"}

#             # --- UPSELL DECISION ---
#             elif state == "awaiting_upsell_decision":
#                 user_reply = text.strip().lower()
#                 if user_reply in ["yes", "add", "ok", "y", "1"]:
#                     upsell_item = current_data.get('upsell_item', {})
#                     shop_id = current_data.get('shop_id')
#                     original_order_id = current_data.get('linked_order_id')
                    
#                     # Inherit address from previous order
#                     address_payload = {}
#                     if original_order_id:
#                         async with db.pool.acquire() as conn:
#                             prev = await conn.fetchrow("SELECT delivery_address, delivery_pincode, delivery_city, delivery_state FROM orders WHERE id = $1", original_order_id)
#                             if prev:
#                                 address_payload = {
#                                     "address": prev['delivery_address'],
#                                     "pincode": prev['delivery_pincode'],
#                                     "city": prev['delivery_city'],
#                                     "state": prev['delivery_state']
#                                 }

#                     new_order = {
#                         "phone": phone, "shop_id": shop_id,
#                         "total": upsell_item.get('price', 0),
#                         "item_name": upsell_item.get('name', 'Add-on'), 
#                         "qty": 1, "payment_method": "COD", "status": "COD",
#                          **address_payload
#                     }
#                     order_id = await save_order_to_db(new_order)
#                     await send_whatsapp_message(phone, f"🎉 Added {upsell_item.get('name')} for ₹{upsell_item.get('price')}.")
                    
#                     seller_phone = await get_seller_phone(shop_id)
#                     if seller_phone:
#                         await send_whatsapp_message(seller_phone, f"🔥 *UPSELL CONVERTED!* Order #{order_id}")
#                 else:
#                     await send_whatsapp_message(phone, "No problem! Your original order is processed. ✅")
                
#                 await state_manager.clear_state(phone)
#                 return {"status": "ok"}

#             # --- [RESTORED] SELECTION DRILLDOWN ---
#             elif state == "awaiting_selection":
#                 await handle_selection_drilldown(phone, text, current_data)
#                 return {"status": "ok"}

#             # --- QTY & STOCK ---
#             elif state == "awaiting_qty" and text.isdigit():
#                 qty = int(text)
#                 raw_item_id = current_data.get('item_id')
#                 if not raw_item_id:
#                      await send_whatsapp_message(phone, "⚠️ Session Expired.")
#                      return {"status": "ok"}
                
#                 item_id = int(raw_item_id)
#                 async with db.pool.acquire() as conn:
#                     row = await conn.fetchrow("SELECT stock_count, name, price FROM items WHERE id = $1", item_id)
#                     if not row: return {"status": "ok"}
                    
#                     live_stock = row['stock_count'] 
#                     if qty > live_stock:
#                         await send_whatsapp_message(phone, f"⚠️ Only *{live_stock}* left.")
#                         return {"status": "ok"}

#                     item_name = row['name']
#                     price = float(row['price'])

#                 await state_manager.update_state(phone, {
#                     "total": price * qty,
#                     "qty": qty,
#                     "name": item_name, 
#                     "price": price
#                 })
#                 await check_address_before_payment(phone)
#                 return {"status": "ok"}

#     except Exception as e:
#         logger.error(f"🔥 Webhook Error: {e}", exc_info=True)
        
#     return {"status": "ok"}    

# @router.get("/webhook")
# async def verify_webhook(request: Request):
#     mode = request.query_params.get("hub.mode")
#     token = request.query_params.get("hub.verify_token")
#     challenge = request.query_params.get("hub.challenge")
#     MY_VERIFY_TOKEN = os.getenv("VERIFY_TOKEN") 
#     if mode == "subscribe" and token == MY_VERIFY_TOKEN:
#         return PlainTextResponse(content=challenge, status_code=200)
#     raise HTTPException(status_code=403, detail="Verification failed")









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
from app.utils.whatsapp import send_whatsapp_message, send_interactive_message, send_address_flow

# 2. SERVICES (All functions present)
from app.services.order_service import (
    check_address_before_payment, 
    finalize_order, 
    save_order_to_db, 
    handle_selection_drilldown,
    handle_web_handoff, 
    handle_bulk_handoff 
)

# Initialize Router
router = APIRouter()
logger = logging.getLogger(__name__)

@router.post("/webhook")
async def receive_message(request: Request):
    try:
        data = await request.json()
        entry = data.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        val = changes.get("value", {})
        
        if "messages" not in val: 
            return {"status": "ok"}
        
        msg = val["messages"][0]
        phone = msg["from"]
        msg_type = msg.get("type")
        
        current_data = await state_manager.get_state(phone)
        if not isinstance(current_data, dict):
            current_data = {}    
        state = current_data.get("state")

        # ============================================================
        # A. INTERACTIVE MESSAGES
        # ============================================================
        if msg_type == "interactive":
            interactive = msg["interactive"]
            
            # --- 1. HANDLE FLOW DATA (Legacy Support) ---
            if interactive["type"] == "nfm_reply":
                try:
                    reply_json = json.loads(interactive["nfm_reply"]["response_json"])
                    pincode = reply_json.get("pincode")
                    house_no = reply_json.get("house_no")
                    
                    if pincode:
                        async with db.pool.acquire() as conn:
                            await conn.execute("INSERT INTO users (phone_number) VALUES ($1) ON CONFLICT DO NOTHING", phone)
                            addr_id = await conn.fetchval("""
                                INSERT INTO addresses (user_id, pincode, house_no, is_default, created_at)
                                VALUES ($1, $2, $3, TRUE, NOW()) RETURNING id
                            """, phone, pincode, house_no)
                        
                        await state_manager.update_state(phone, {"address_id": addr_id})
                        await check_address_before_payment(phone) # Refresh view
                except:
                    pass
                return {"status": "ok"}

            # --- 2. HANDLE BUTTON CLICKS ---
            if interactive["type"] == "button_reply":
                selection_id = interactive["button_reply"]["id"]

                # --- OLD ADDRESS CONFIRMATION ---
                if selection_id.startswith("CONFIRM_ADDR"):
                    try:
                        addr_id = int(selection_id.split("_")[-1])
                        await state_manager.update_state(phone, {"address_confirmed": True, "address_id": addr_id})
                        
                        total = current_data.get("total", 0)
                        btns = [
                            {"id": "pay_online", "title": "Pay Online"}, 
                            {"id": "pay_cod", "title": "Cash on Delivery"}
                        ]
                        await send_interactive_message(phone, f"✅ Address Confirmed!\n💰 *Total: ₹{total}*\nSelect Payment Method:", btns)
                    except:
                        await check_address_before_payment(phone)
                    return {"status": "ok"}

                # --- CHANGE ADDRESS (Web Link) ---
                if selection_id == "CHANGE_ADDR":
                    checkout_link = await create_checkout_url(phone)
                    response_text = (
                        "Tap the link below to securely update your address:\n\n"
                        f"🔗 {checkout_link}\n\n"
                        "_This link expires in 10 minutes._"
                    )
                    await send_whatsapp_message(phone, response_text)
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

                # --- RECOVER CHECKOUT ---
                if selection_id == "recover_checkout":
                    await check_address_before_payment(phone)
                    return {"status": "ok"}

                # --- CANCEL ---
                if selection_id == "recover_cancel":
                    await state_manager.clear_state(phone)
                    await send_whatsapp_message(phone, "❌ Cart cleared.")
                    return {"status": "ok"}

            return {"status": "ok"}
        
        # ============================================================
        # B. TEXT MESSAGES
        # ============================================================
        elif msg_type == "text":
            text = msg["text"]["body"].strip()

            # --- [NEW] ADDRESS CONFIRMATION RETURN ---
            if "Address_Confirmed_for_" in text:
                logger.info(f"✅ Received Address Confirmation from {phone}")
                async with db.pool.acquire() as conn:
                    addr_id = await conn.fetchval("SELECT id FROM addresses WHERE user_id = $1 ORDER BY created_at DESC LIMIT 1", phone)
                
                await state_manager.update_state(phone, {"address_confirmed": True, "address_id": addr_id})
                btns = [{"id": "pay_online", "title": "Pay Online"}, {"id": "pay_cod", "title": "Cash on Delivery"}]
                await send_interactive_message(phone, f"✅ Address Updated!\n💰 Total: ₹{current_data.get('total', 0)}\nSelect Payment:", btns)
                return {"status": "ok"}

            # --- BULK ORDER ---
            if "buy_bulk_" in text:
                match = re.search(r"buy_bulk_([\d:,]+)", text)
                if match:
                    await handle_bulk_handoff(phone, match.group(0))
                return {"status": "ok"}

            # --- SINGLE ITEM ---
            if "buy_item_" in text:
                match = re.search(r"buy_item_(\d+)", text)
                if match:
                    await handle_web_handoff(phone, int(match.group(1))) 
                return {"status": "ok"}
            
            # --- MANUAL ADDRESS FALLBACK ---
            if state == "awaiting_manual_address":
                parts = [p.strip() for p in text.split(",")]
                if len(parts) >= 2:
                    pincode, house_no = parts[0], parts[1]
                    city = parts[2] if len(parts) > 2 else "India"
                    async with db.pool.acquire() as conn:
                        await conn.execute("INSERT INTO users (phone_number) VALUES ($1) ON CONFLICT DO NOTHING", phone)
                        addr_id = await conn.fetchval("""
                            INSERT INTO addresses (user_id, pincode, house_no, city, state, is_default)
                            VALUES ($1, $2, $3, $4, 'India', TRUE) RETURNING id
                        """, phone, pincode, house_no, city)
                    await state_manager.update_state(phone, {"state": "active", "address_confirmed": True, "address_id": addr_id}) 
                    btns = [{"id": "pay_online", "title": "Pay Online"}, {"id": "pay_cod", "title": "Cash on Delivery"}]
                    await send_interactive_message(phone, "✅ Address Saved! Select Payment:", btns)
                else:
                    await send_whatsapp_message(phone, "⚠️ Format: *Pincode, House No, City*")
                return {"status": "ok"}

            # --- UPSELL DECISION ---
            elif state == "awaiting_upsell_decision":
                user_reply = text.strip().lower()
                if user_reply in ["yes", "add", "ok", "y", "1"]:
                    upsell_item = current_data.get('upsell_item', {})
                    new_order = {
                        "phone": phone, "shop_id": current_data.get('shop_id'),
                        "total": upsell_item.get('price', 0),
                        "item_name": upsell_item.get('name', 'Add-on'), 
                        "qty": 1, "payment_method": "COD"
                    }
                    await save_order_to_db(new_order)
                    await send_whatsapp_message(phone, "🎉 Added add-on item!")
                await state_manager.clear_state(phone)
                return {"status": "ok"}

            # --- QTY & STOCK ---
            elif state == "awaiting_qty" and text.isdigit():
                qty = int(text)
                await state_manager.update_state(phone, {"qty": qty, "total": current_data.get('price', 0) * qty})
                await check_address_before_payment(phone)
                return {"status": "ok"}

    except Exception as e:
        logger.error(f"🔥 Webhook Error: {e}", exc_info=True)
        
    return {"status": "ok"}    

@router.get("/webhook")
async def verify_webhook(request: Request):
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")
    MY_VERIFY_TOKEN = os.getenv("VERIFY_TOKEN") 
    if mode == "subscribe" and token == MY_VERIFY_TOKEN:
        return PlainTextResponse(content=challenge, status_code=200)
    raise HTTPException(status_code=403, detail="Verification failed")