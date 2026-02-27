from fastapi import APIRouter
from app.core.database import db
from fastapi import APIRouter, Query,HTTPException
from app.core.database import db
from app.utils.crypto import decrypt_data
from app.utils.shiprocket import get_shiprocket_token, check_serviceability


router = APIRouter()

@router.get("/storefront/{slug}")
async def get_storefront(slug: str):
    async with db.pool.acquire() as conn:
        # 1. Fetch Shop Details (Fixed the WHERE clause)
        shop = await conn.fetchrow("""
            SELECT id, name, phone_number, plan_type, logo_url, slug, username, return_policy
            FROM shops 
            WHERE slug = $1 OR username = $1
        """, slug)
        
        if not shop:
            return {"status": "error", "message": "Shop not found"}

        shop_id = shop['id']
        
        # 2. Fetch Active Products
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

    # Convert Record objects to dicts explicitly, with a failsafe for NULL stock
    items_list = []
    for i in items:
        item_dict = dict(i)
        item_dict['stock_quantity'] = item_dict.get('stock_quantity') or 0
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




from app.utils.crypto import decrypt_data

@router.get("/check-pincode")
async def check_pincode(shop_id: int, pincode: str):
    async with db.pool.acquire() as conn:
        shop = await conn.fetchrow("""
            SELECT shiprocket_email, shiprocket_password, pickup_address 
            FROM shops WHERE id = $1
        """, shop_id)
        
        if not shop or not shop['shiprocket_email']:
            return {"status": "error", "message": "Seller shipping not configured."}
        
        # 1. 🔓 Decrypt Password
        decrypted_password = decrypt_data(shop['shiprocket_password'])

        # 2. 🔑 Authenticate (USE THE DECRYPTED ONE)
        token = get_shiprocket_token(shop['shiprocket_email'], decrypted_password)
        if not token:
            return {"status": "error", "message": "Service unavailable."}
            
        # 3. Check Serviceability
        # Enterprise tip: Add 'pickup_pincode' to your shops table soon!
        seller_pincode = "400001" 
        
        result = check_serviceability(token, seller_pincode, pincode, weight=0.5, cod=True)
        return result


@router.get("/storefront/{shop_slug}/item/{item_slug}")
async def get_public_item(shop_slug: str, item_slug: str):
    async with db.pool.acquire() as conn:
        # 1. Validate the Shop
        shop = await conn.fetchrow("""
            SELECT id, name, phone_number, logo_url, slug 
            FROM shops WHERE slug = $1 OR username = $1
        """, shop_slug)
        
        if not shop:
            raise HTTPException(status_code=404, detail="Shop not found")

        # 2. Fetch the specific item using the item_slug AND shop_id
        item = await conn.fetchrow("""
            SELECT * FROM items 
            WHERE shop_id = $1 AND slug = $2
        """, shop['id'], item_slug)

        if not item:
            raise HTTPException(status_code=404, detail="Item not found")

        # 3. Fetch 4 "More from this shop" items
        more_items = await conn.fetch("""
            SELECT id, name, price, image_url, slug
            FROM items 
            WHERE shop_id = $1 AND id != $2 AND stock_quantity > 0
            LIMIT 4
        """, shop['id'], item['id'])

    return {
        "status": "success",
        "shop": dict(shop),
        "item": dict(item),
        "more_items": [dict(i) for i in more_items]
    }