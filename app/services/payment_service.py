
import os
from app.core.database import db
from app.utils.whatsapp import send_whatsapp_message
from app.utils.state_manager import state_manager
from app.services.order_service import save_order_to_db, send_order_confirmation

async def handle_payment_selection(phone, selection_id, current_data):
    print(f"💰 Handling Payment Selection: {selection_id} for {phone}")
    
    shop_id = current_data.get("shop_id")
    total_amount = current_data.get("total")
    
    # 1. Fetch Shop Credentials AND Status Columns
    async with db.pool.acquire() as conn:
        shop = await conn.fetchrow("""
            SELECT id, name, phone_number, 
                   plan_type, active_payment_method, 
                   razorpay_key_id, razorpay_key_secret, upi_id 
            FROM shops WHERE id = $1
        """, shop_id)
    
    # --- OPTION A: CASH ON DELIVERY (COD) ---
    if selection_id == "pay_cod":
        if current_data.get("address"):
             order_id = await save_order_to_db(phone, current_data, address=current_data["address"], status_text="COD")
             await send_order_confirmation(phone, order_id, current_data, "Cash on Delivery")
        else:
             await state_manager.set_state(phone, {"payment_method": "COD", "state": "awaiting_address"})
             send_whatsapp_message(phone, "📍 Please type your *Full Address* for delivery:")
        return

    # --- OPTION B: PAY ONLINE ---
    elif selection_id == "pay_online":
        
        # 1. DECISION LOGIC: STRICT CHECKS
        plan = (shop['plan_type'] or 'free').lower()
        method = (shop['active_payment_method'] or 'upi').lower()
        
        can_use_razorpay = (
            plan == 'pro' and               # Must be Pro
            method == 'razorpay' and        # Must have selected Razorpay in settings
            shop['razorpay_key_id'] and     # Must have Key ID
            shop['razorpay_key_secret']     # Must have Key Secret
        )

        # 2. EXECUTE RAZORPAY FLOW
        if can_use_razorpay:
            try:
                import razorpay
                client = razorpay.Client(auth=(shop['razorpay_key_id'], shop['razorpay_key_secret']))
                
                link_data = {
                    "amount": int(total_amount * 100), 
                    "currency": "INR",
                    "description": f"Order from {shop['name']}",
                    "customer": {"contact": phone, "name": "Valued Customer"},
                    "notify": {"sms": True, "email": False},
                    "callback_url": "https://your-domain.com/payment-success", 
                    "callback_method": "get"
                }
                
                payment_link = client.payment_link.create(link_data)
                short_url = payment_link['short_url']
                
                await state_manager.set_state(phone, {"payment_link_id": payment_link['id']})

                msg = (
                    f"💳 *Secure Payment Link*\n"
                    f"Amount: ₹{total_amount}\n\n"
                    f"👇 *Tap to pay securely via Card/UPI:*\n{short_url}\n\n"
                    f"⏳ *Order confirms automatically after payment!*"
                )
                send_whatsapp_message(phone, msg)
                
            except Exception as e:
                print(f"🔥 Razorpay Error: {e}")
                # Fallback to UPI if Razorpay crashes? Or just show error?
                send_whatsapp_message(phone, "❌ Payment Gateway Error. Please try COD.")

        # 3. EXECUTE UPI FLOW (For Free users OR Pro users who chose UPI)
        elif shop['upi_id']:
            base_url = "BASE_URL"  
            pay_url = f"{base_url}/pay/manual?shop={shop_id}&amount={total_amount}"
            
            msg = (
                f"🏦 *Direct Payment Link*\n"
                f"Amount: ₹{total_amount}\n\n"
                f"👇 *Tap to open GPay/PhonePe directly:*\n"
                f"{pay_url}\n\n"
                f"⚠️ *Important:* After paying, come back here and *send a screenshot*."
            )
            
            await state_manager.set_state(phone, {"state": "awaiting_screenshot"})
            send_whatsapp_message(phone, msg)
            
        else:
            send_whatsapp_message(phone, "❌ This shop accepts COD only right now. Please select COD.")

