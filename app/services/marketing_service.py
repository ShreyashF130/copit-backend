import asyncio
from app.core.database import db
from app.utils.state_manager import state_manager
from app.utils.whatsapp import send_whatsapp_message, send_image_message

async def trigger_upsell_flow(phone, shop_id, original_order_id):
    """
    Checks if shop has upsell enabled and sends the pitch.
    """
    # 1. Use the global DB pool
    async with db.pool.acquire() as conn:
        # Fetch Upsell Config
        shop = await conn.fetchrow("""
            SELECT upsell_item_id, upsell_discount, is_upsell_enabled 
            FROM shops WHERE id = $1
        """, shop_id)
        
        if not shop or not shop['is_upsell_enabled'] or not shop['upsell_item_id']:
            return # Upsell not active

        # Fetch Item Details
        item = await conn.fetchrow("SELECT name, price, image_url FROM items WHERE id = $1", shop['upsell_item_id'])
        
        if not item: return

        # 2. Calculate Deal
        original_price = float(item['price'])
        discount_percent = int(shop['upsell_discount'])
        discount_amount = (original_price * discount_percent) / 100
        offer_price = int(original_price - discount_amount)
        
        # 3. Wait 5 Seconds (Psychological Pause)
        await asyncio.sleep(5) 

        # 4. Send The Pitch
        msg = (
            f"🔥 *WAIT! Exclusive One-Time Offer* 🔥\n\n"
            f"Since you just ordered, you unlocked a deal on our Best Seller:\n"
            f"📦 *{item['name']}*\n"
            f"❌ ~~₹{original_price}~~\n"
            f"✅ *₹{offer_price}* (Only for you!)\n\n"
            f"👇 *Reply YES to add this to your shipment!*"
        )
        
        # If item has image, send it (using await)
        if item['image_url']:
            await send_image_message(phone, item['image_url'], caption=msg)
        else:
            await send_whatsapp_message(phone, msg)

        # 5. Set State to Capture 'YES'
        await state_manager.update_state(phone, {
            "state": "awaiting_upsell_decision",
            "shop_id": shop_id,
            "upsell_item": {
                "id": shop['upsell_item_id'],
                "name": item['name'],
                "price": offer_price
            },
            "linked_order_id": original_order_id
        })