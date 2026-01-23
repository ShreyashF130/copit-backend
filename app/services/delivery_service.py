from app.core.database import db
from app.utils.shiprocket import get_shiprocket_token, check_shiprocket_status
from app.utils.whatsapp import send_whatsapp_message
import asyncio
from app.utils.state_manager import state_manager

async def delivery_watchdog_loop():
    print("🐶 Delivery Watchdog Started...")
    while True:
        try:
            async with db.pool.acquire() as conn:
                # 1. Find orders that are SHIPPED but not yet DELIVERED (and used Shiprocket)
                orders = await conn.fetch("""
                    SELECT o.id, o.shiprocket_shipment_id, o.customer_phone, o.shop_id,
                           s.shiprocket_email, s.shiprocket_password
                    FROM orders o
                    JOIN shops s ON o.shop_id = s.id
                    WHERE o.delivery_status = 'shipped' 
                      AND o.shipping_provider = 'Shiprocket'
                """)

                for order in orders:
                    # 2. Get Token (In production, cache this!)
                    token = get_shiprocket_token(order['shiprocket_email'], order['shiprocket_password'])
                    
                    if token:
                        # 3. Check Status
                        status = check_shiprocket_status(token, order['shiprocket_shipment_id'])
                        
                        if status == "DELIVERED":
                            print(f"🎉 Order #{order['id']} is Delivered!")
                            
                            # 4. Update Database
                            await conn.execute("""
                                UPDATE orders 
                                SET delivery_status = 'delivered', status = 'DELIVERED', is_review_requested = TRUE
                                WHERE id = $1
                            """, order['id'])
                            
                            # 5. TRIGGER REVIEW REQUEST (Strategy 3)
                            # We send a text message asking for a rating immediately.
                            
                            msg = (
                                f"📦 *Delivered!* We hope you love your order.\n\n"
                                f"⭐ How would you rate your experience?\n"
                                f"Reply with a number *1 to 5*."
                            )
                            send_whatsapp_message(order['customer_phone'], msg)
                            
                            # 6. Set State to Capture Rating
                            await state_manager.set_state(order['customer_phone'], {
                                "state": "awaiting_review_rating", 
                                "shop_id": order['shop_id'],
                                "order_id": order['id']
                            })

            # Sleep for 1 hour to avoid hitting API limits too hard
            await asyncio.sleep(3600) 
            
        except Exception as e:
            print(f"🔥 Watchdog Error: {e}")
            await asyncio.sleep(3600)