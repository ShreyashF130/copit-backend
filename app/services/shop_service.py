from app.core.database import db

async def get_seller_phone(shop_id):
    """
    Fetches the seller's phone number to notify them of an upsell.
    """
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT phone_number FROM shops WHERE id = $1", shop_id)
        return row['phone_number'] if row else None
    

async def get_seller_info(shop_id):
    async with db.pool.acquire() as conn:
        return await conn.fetchrow(
            "SELECT id, name, phone_number, upi_id, plan_type FROM shops WHERE id = $1", 
            shop_id
        )