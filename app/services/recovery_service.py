import asyncio
from app.utils.state_manager import state_manager
from app.utils.whatsapp import send_interactive_message

async def cart_recovery_loop():
    print("🕵️ Cart Recovery Engine Started...")
    while True:
        try:
            # 1. Find users silent for 30 minutes
            stale_users = await state_manager.get_stale_carts(minutes=30)
            
            for phone, data in stale_users:
                print(f"⏰ Nudging abandoned cart: {phone}")
                
                # 2. Extract Data
                cart = data.get("cart", [])
                item_count = len(cart)
                total_val = data.get("total", 0)
                
                # Fallback calculation
                if total_val == 0:
                     total_val = sum(item['price'] * item['qty'] for item in cart)

                msg = (
                    f"👋 *You forgot something!* (Value: ₹{total_val})\n\n"
                    f"Your *{item_count} items* are reserved, but stock is low! 🏃\n\n"
                    f"🎁 *Special Offer:* Complete your order in the next 10 mins and get *5% OFF*.\n"
                    f"👇 Use Code: *COMEBACK5*"
                )
                
                # 3. INTERACTIVE BUTTONS
                buttons = [
                    {"id": "recover_checkout", "title": "Resume Checkout"},
                    {"id": "recover_cancel", "title": "Empty Cart"}
                ]
                
                send_interactive_message(phone, msg, buttons)
                
                # 4. Mark as nudged
                await state_manager.update_state(phone, {"nudged": True})
            
            # Sleep for 60 seconds before next scan
            await asyncio.sleep(60)
            
        except Exception as e:
            print(f"🔥 Recovery Loop Error: {e}")
            await asyncio.sleep(60)