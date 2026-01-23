from fastapi import APIRouter, Request, HTTPException, BackgroundTasks, Body
from app.core.database import db
from app.schemas import BroadcastRequest, StatusUpdate
from app.utils.whatsapp import send_whatsapp_message
from app.utils.shiprocket import get_shiprocket_token, create_shiprocket_order, generate_shipping_label
import json
from fastapi import UploadFile, File
import pandas as pd
import io
from app.services.order_service import schedule_image_deletion

router = APIRouter()
COST_PER_MSG = 1.20



@router.get("/analytics/{shop_id}")
async def get_analytics(shop_id: int):
    async with db.pool.acquire() as conn:
        # 1. Headline Stats
        stats = await conn.fetchrow("""
            SELECT 
                COUNT(*) as total_orders,
                COALESCE(SUM(total_amount), 0) as total_revenue,
                COUNT(CASE WHEN status = 'PENDING' THEN 1 END) as pending_orders
            FROM orders 
            WHERE shop_id = $1 AND status != 'REJECTED'
        """, shop_id)
        
        # 2. Daily Graph Data (Using our SQL function)
        daily_sales = await conn.fetch("SELECT * FROM get_daily_sales($1)", shop_id)
        
        # 3. Top 3 Selling Items
        top_items = await conn.fetch("""
            SELECT item_name, COUNT(*) as qty_sold 
            FROM orders 
            WHERE shop_id = $1 
            GROUP BY item_name 
            ORDER BY qty_sold DESC 
            LIMIT 3
        """, shop_id)

        graph_data = []
        for r in daily_sales:
            graph_data.append({
                "day": r['day'].strftime("%Y-%m-%d"), # Fixes Date Object issues
                "total": float(r['total'])             # Fixes Decimal Object issues
            })
            
  
        return {
            "status": "success",
            "stats": dict(stats),
            "graph": graph_data,
            "top_items": [dict(r) for r in top_items]
        }
    

@router.post("/marketing/broadcast")
async def send_broadcast(payload: BroadcastRequest):
    async with db.pool.acquire() as conn:
        # 1. Check Wallet Balance & Ownership
        shop = await conn.fetchrow("SELECT wallet_balance, phone_number FROM shops WHERE id = $1", payload.shop_id)
        
        if not shop:
            raise HTTPException(status_code=404, detail="Shop not found")

        # 2. Calculate Cost
        total_cost = payload.limit * COST_PER_MSG
        
        if shop['wallet_balance'] < total_cost:
            raise HTTPException(status_code=400, detail="Insufficient wallet balance")

        # 3. FETCH TARGET AUDIENCE (The "Smart Priority" Logic)
        # We select DISTINCT phone numbers, ordered by their LAST order date.
        # This ensures we target "Active/Recent" customers first.
        targets = await conn.fetch("""
            SELECT DISTINCT ON (customer_phone) customer_phone, customer_name
            FROM orders 
            WHERE shop_id = $1 
            ORDER BY customer_phone, created_at DESC
            LIMIT $2
        """, payload.shop_id, payload.limit)

        if not targets:
            return {"status": "error", "message": "No customers found"}

        # 4. SEND MESSAGES (Async Loop)

        sent_count = 0
        for user in targets:
            sent_count += 1

        # 5. DEDUCT MONEY
        actual_cost = sent_count * COST_PER_MSG
        await conn.execute("""
            UPDATE shops 
            SET wallet_balance = wallet_balance - $1 
            WHERE id = $2
        """, actual_cost, payload.shop_id)

    return {
        "status": "success", 
        "count": sent_count, 
        "cost_deducted": actual_cost
    }


@router.post("/notify-order-update")
async def notify_order_update(update: StatusUpdate, background_tasks: BackgroundTasks):
    async with db.pool.acquire() as conn:
        order = await conn.fetchrow("""
            SELECT customer_phone, item_name, quantity, total_amount, shop_id 
            FROM orders WHERE id = $1
        """, update.order_id)
        
    if not order: return {"error": "Order not found"}

    # STOCK DECREMENT (Only on PAID)
    if update.new_status == "paid":
        async with db.pool.acquire() as conn:
            # Simple stock decrement (Enhancement: In future, decrement specific variant stock)
            await conn.execute("""
                UPDATE items SET stock_quantity = stock_quantity - $1 
                WHERE name = $2 AND shop_id = $3
            """, order['quantity'], order['item_name'].split('(')[0].strip(), order['shop_id'])
            
        background_tasks.add_task(schedule_image_deletion, update.order_id)

    messages = {
        "paid": f"✅ *Payment Verified!* Order #{update.order_id} is confirmed.",
        "shipped": f"🚀 *Shipped!* Order #{update.order_id} is on the way.",
        "delivered": f"🎁 *Delivered!* Order #{update.order_id} has arrived.",
        "rejected": f"❌ *Rejected.* Payment issue with Order #{update.order_id}. Contact seller."
    }
    
    msg_text = messages.get(update.new_status, f"Order #{update.order_id}: {update.new_status}")
    send_whatsapp_message(order['customer_phone'], msg_text)
    return {"status": "success"}



@router.post("/ship/manual")
async def ship_manual(
    order_id: int = Body(...), 
    courier_name: str = Body(...), 
    tracking_link: str = Body(...)
):
    async with db.pool.acquire() as conn:
        # 1. Update Order in DB & Return the Phone Number immediately
        # We use RETURNING to avoid a second query
        row = await conn.fetchrow("""
            UPDATE orders 
            SET status = 'SHIPPED', 
                shipping_status = 'shipped',
                shipping_provider = 'Manual',
                courier_name = $1,
                tracking_link = $2
            WHERE id = $3
            RETURNING customer_phone
        """, courier_name, tracking_link, order_id)
        
        # 2. Check if Order Existed
        if row:
            customer_phone = row['customer_phone']
            
            # 3. Send WhatsApp Notification
            msg = (
                f"🚚 *Order Dispatched!*\n"
                f"Courier: {courier_name}\n\n"
                f"👇 *Track your package here:*\n{tracking_link}"
            )
            
   
            send_whatsapp_message(customer_phone, msg)
            
            return {"status": "success", "message": "Manual shipment updated"}
            
    return {"status": "error", "message": "Order not found"}

@router.post("/ship/rocket")
async def ship_via_rocket(request: Request):
    data = await request.json()
    order_id = data.get('order_id')
    
    async with db.pool.acquire() as conn:
        # 1. Fetch Order & Shop
        order = await conn.fetchrow("SELECT * FROM orders WHERE id = $1", order_id)
        shop = await conn.fetchrow("SELECT * FROM shops WHERE id = $1", order['shop_id'])
        
        # 2. VALIDATION (Guardrails)
        if not order['delivery_pincode']:
            return {"status": "error", "message": "Missing Pincode! Edit order manually."}
        
        if not shop['shiprocket_email'] or not shop['shiprocket_password']:
             return {"status": "error", "message": "Seller missing Shiprocket credentials."}

        # 3. CONSTRUCT PAYLOAD
        ship_data = {
            "id": order['id'],
            "items": json.loads(order['items']),
            "total_amount": float(order['total_amount']),
            "status": order['status'],
            
            # The "Smart Address" Mapping
            "address": order['delivery_address'], 
            "city": order['delivery_city'],
            "pincode": order['delivery_pincode'],
            "state": order['delivery_state'],
            "customer_phone": order['customer_phone'],
            "customer_name": "Valued Customer",
            "pickup_location_name": shop.get('pickup_address', 'Primary')
        }

        # 4. EXECUTE SHIPMENT
        token = get_shiprocket_token(shop['shiprocket_email'], shop['shiprocket_password'])
        if not token: 
            return {"status": "error", "message": "Shiprocket Login Failed"}
        
        response = create_shiprocket_order(token, ship_data)
        
        # 5. GENERATE LABEL (The Ruthless Fix) 🚀
        if response.get('order_id'):
            shipment_id = response['shipment_id']
            awb_code = response.get('awb_code')
            
            # A. Call the Label API immediately
            label_res = generate_shipping_label(token, shipment_id)
            
            # B. Extract the PDF Link
            label_url = label_res.get('awb_print_url') if label_res else None
            
            # C. Save EVERYTHING to DB
            await conn.execute("""
                UPDATE orders SET 
                shipping_provider = 'Shiprocket',
                shiprocket_shipment_id = $1,
                shiprocket_order_id = $2,
                shipping_label_url = $3,  -- Saved for re-printing
                shipping_awb = $4,
                status = 'SHIPPED',
                delivery_status = 'shipped'
                WHERE id = $5
            """, shipment_id, response['order_id'], label_url, awb_code, order['id'])
            
            # D. Send WhatsApp Notification to Customer
            msg = (
                f"🚀 *Order Shipped!*\n"
                f"Tracking AWB: {awb_code}\n"
                f"Your package is on the way!"
            )
            # await send_whatsapp_message(order['customer_phone'], msg) 
            
            return {
                "status": "success", 
                "awb": awb_code, 
                "label_url": label_url # Return to Frontend to auto-open
            }
        else:
            # Pass the actual error message from Shiprocket
            return {"status": "error", "message": response.get('message', 'Unknown Error')}
        

@router.post("/inventory/bulk-upload")
async def bulk_upload_items(
    shop_id: int, 
    file: UploadFile = File(...)
):
    print(f"📂 Processing file for Shop {shop_id}...")
    
    # 1. Read File
    contents = await file.read()
    try:
        if file.filename.endswith('.csv'):
            df = pd.read_csv(io.BytesIO(contents))
        elif file.filename.endswith(('.xls', '.xlsx')):
            df = pd.read_excel(io.BytesIO(contents))
        else:
            return {"status": "error", "message": "Only CSV or Excel files allowed"}
    except Exception as e:
        return {"status": "error", "message": f"File Error: {str(e)}"}

    # 2. Standardize Column Names (Lowercase & Strip spaces)
    df.columns = [c.lower().strip() for c in df.columns]

    # 3. Validate Required Columns
    required_cols = ['name', 'price', 'category'] 
    missing = [col for col in required_cols if col not in df.columns]
    
    if missing:
        return {"status": "error", "message": f"Missing columns: {missing}"}

    # 4. Insert Loop
    success_count = 0
    async with db.pool.acquire() as conn:
        for index, row in df.iterrows():
            try:
                # Basic cleanup
                name = str(row['name']).strip()
                price = float(row['price'])
                category = str(row['category']).strip()
                
                # Optional fields with defaults
                desc = str(row.get('description', ''))
                img = str(row.get('image_url', ''))
                
                # Handle NaN/Empty values safely
                if desc == 'nan': desc = ''
                if img == 'nan': img = ''
                
                # Stock 
                stock = int(row.get('stock', 0)) # Default to 0 if not provided

                # Insert into DB (Matching to Schema)
                await conn.execute("""
                    INSERT INTO items (
                        shop_id, name, price, category, 
                        description, image_url, stock_quantity
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                """, shop_id, name, price, category, desc, img, stock)
                
                success_count += 1
            except Exception as e:
                print(f"⚠️ Skipped Row {index}: {e}")
                continue

    return {
        "status": "success", 
        "message": f"Imported {success_count} items successfully!",
        "count": success_count
    }


@router.post("/reviews/toggle-public")
async def toggle_review_public(
    review_id: int = Body(...), 
    is_public: bool = Body(...)
):
    async with db.pool.acquire() as conn:
        await conn.execute("UPDATE reviews SET is_public = $1 WHERE id = $2", is_public, review_id)
    return {"status": "success"}

