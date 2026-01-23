from fastapi import APIRouter
from app.core.database import db

router = APIRouter()

@router.get("/storefront/{shop_id}")
async def get_storefront(shop_id: int):
    async with db.pool.acquire() as conn:
        # 1. Fetch Shop Details
        shop = await conn.fetchrow("""
            SELECT id, name, phone_number, plan_type, logo_url
            FROM shops WHERE id = $1
        """, shop_id)
        
        if not shop:
            return {"status": "error", "message": "Shop not found"}

        # 2. Fetch Active Products
        # Ensuring we get stock_quantity and attributes so the frontend doesn't show "Sold Out"
        items = await conn.fetch("""
            SELECT id, name, price, image_url, category, description, stock_quantity, attributes
            FROM items 
            WHERE shop_id = $1 AND stock_quantity > 0
            ORDER BY category, name
        """, shop_id)

        # 3. Fetch ONLY Public 4-5 Star Reviews
        reviews = await conn.fetch("""
            SELECT rating, comment, customer_name, created_at 
            FROM reviews 
            WHERE shop_id = $1 AND is_public = TRUE 
            ORDER BY rating DESC, created_at DESC 
            LIMIT 5
        """, shop_id)

    # Convert Record objects to dicts explicitly
    items_list = []
    for i in items:
        item_dict = dict(i)
        items_list.append(item_dict)

    return {
        "status": "success",
        "shop": dict(shop),
        "products": items_list,
        "reviews": [dict(r) for r in reviews]
    }


# --- REVIEWS API ---

@router.get("/reviews/{shop_id}")
async def get_reviews(shop_id: int):
    async with db.pool.acquire() as conn:
        # Fetch all reviews
        rows = await conn.fetch("""
            SELECT id, rating, comment, customer_name, is_public, created_at, order_id
            FROM reviews 
            WHERE shop_id = $1 
            ORDER BY created_at DESC
        """, shop_id)
        
        # Fetch stats
        stats = await conn.fetchrow("""
            SELECT 
                COUNT(*) as total_count,
                COALESCE(AVG(rating), 0)::numeric(10,1) as avg_rating,
                COUNT(CASE WHEN rating >= 4 THEN 1 END) as positive_count
            FROM reviews WHERE shop_id = $1
        """, shop_id)

    return {
        "status": "success",
        "reviews": [dict(r) for r in rows],
        "stats": dict(stats)
    }