import json # 🚨 THE FIX: Required to parse Postgres JSONB
from fastapi import APIRouter, Query, HTTPException
from app.core.database import db
from app.utils.crypto import decrypt_data
from app.utils.shiprocket import get_shiprocket_token, check_serviceability

router = APIRouter()

@router.get("/storefront/{slug}")
async def get_storefront(slug: str):
    async with db.pool.acquire() as conn:
        # 1. Fetch Shop Details
        shop = await conn.fetchrow("""
            SELECT id, name, phone_number, plan_type, logo_url, slug, username, return_policy, instagram_handle
            FROM shops 
            WHERE slug = $1 OR username = $1
        """, slug)
        
        if not shop:
            return {"status": "error", "message": "Shop not found"}

        shop_id = shop['id']
        
        # 🚨 FIX 1: Removed 'AND stock_count > 0'. 
        # If we filter by stock here, complex items with 0 base stock but high variant stock get permanently hidden.
        items = await conn.fetch("""
            SELECT id, name, price, image_url, category, description, stock_count, attributes
            FROM items 
            WHERE shop_id = $1
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
        item_dict['stock_count'] = item_dict.get('stock_count') or 0
        
        # 🚨 FIX 2: The JSONB Parser
        # asyncpg returns JSONB as a raw string. We MUST parse it into a Python dict 
        # so FastAPI sends actual JSON to Next.js instead of a stringified mess.
        attr = item_dict.get('attributes')
        if isinstance(attr, str):
            try:
                item_dict['attributes'] = json.loads(attr)
            except Exception:
                item_dict['attributes'] = {}
        elif attr is None:
            item_dict['attributes'] = {}
            
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
        seller_pincode = "400001" 
        
        result = check_serviceability(token, seller_pincode, pincode, weight=0.5, cod=True)
        return result


@router.get("/storefront/{shop_slug}/products/{product_slug}")
async def get_public_item(shop_slug: str, product_slug: str):
    async with db.pool.acquire() as conn:
        # 1. Validate the Shop
        shop = await conn.fetchrow("""
            SELECT id, name, phone_number, logo_url, slug, instagram_handle 
            FROM shops WHERE slug = $1 OR username = $1
        """, shop_slug)
        
        if not shop:
            raise HTTPException(status_code=404, detail="Shop not found")

        # 2. 🚨 THE FIX: Explicitly name public columns. Never use SELECT *.
        item = await conn.fetchrow("""
            SELECT id, name, price, description, category, image_url, stock_count, attributes, slug 
            FROM items 
            WHERE shop_id = $1 AND slug = $2
        """, shop['id'], product_slug)

        if not item:
            raise HTTPException(status_code=404, detail="Item not found")

        # 3. Fetch 4 "More from this shop" items
        more_items = await conn.fetch("""
            SELECT id, name, price, image_url, slug
            FROM items 
            WHERE shop_id = $1 AND id != $2
            LIMIT 4
        """, shop['id'], item['id'])

    # 4. 🚨 THE FIX: Bulletproof Serialization
    item_dict = dict(item)
    
    # Guard against NULL stock in the database
    item_dict['stock_count'] = item_dict.get('stock_count') or 0
    
    # Safely Parse Postgres JSONB string into a Python Dictionary
    attr = item_dict.get('attributes')
    if isinstance(attr, str):
        try:
            item_dict['attributes'] = json.loads(attr)
        except Exception:
            item_dict['attributes'] = {}
    elif attr is None:
        item_dict['attributes'] = {}

    return {
        "status": "success",
        "shop": dict(shop),
        "item": item_dict,
        "more_items": [dict(i) for i in more_items]
    }