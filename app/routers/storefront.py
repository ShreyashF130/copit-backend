from fastapi import APIRouter
from app.core.database import db
from fastapi import APIRouter, Query
from app.core.database import db
from app.utils.shiprocket import get_shiprocket_token, check_serviceability

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




@router.get("/check-pincode")
async def check_pincode(shop_id: int, pincode: str):
    async with db.pool.acquire() as conn:
        # 1. Get Shop Credentials & Pickup Pincode
        # (Note: You need to store the Seller's Pickup Pincode in the 'shops' table for this to work accurately)
        # For now, we assume you might have added 'pickup_pincode' to shops table, or we use a default.
        shop = await conn.fetchrow("""
            SELECT shiprocket_email, shiprocket_password, pickup_address 
            FROM shops WHERE id = $1
        """, shop_id)
        
        if not shop or not shop['shiprocket_email']:
            return {"status": "error", "message": "Seller shipping not configured."}

        # 2. Authenticate
        token = get_shiprocket_token(shop['shiprocket_email'], shop['shiprocket_password'])
        if not token:
            return {"status": "error", "message": "Service unavailable."}
            
        # 3. Check Serviceability
        # We assume a default pickup pincode if not in DB, e.g., '400050' (Mumbai). 
        # Ideally, fetch this from the shop's saved pickup address details in Shiprocket or DB.
        # Let's assume you add a column 'pickup_pincode' to your shops table later.
        seller_pincode = "400001" # REPLACE THIS with actual seller pincode logic
        
        result = check_serviceability(token, seller_pincode, pincode, weight=0.5, cod=True)
        
        return result