from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel
import uuid
import json
import logging
from datetime import datetime, timedelta, timezone
from app.core.database import db
import os


logger = logging.getLogger("uvicorn.error")
router = APIRouter()

class AddressSubmit(BaseModel):
    session_id: str
    address: dict

# --- 1. GENERATE LINK (Simple & Robust) ---
async def create_checkout_url(phone: str) -> str:
    session_uuid = str(uuid.uuid4())
    
    try:
        async with db.pool.acquire() as conn:
            # Clean phone
            clean_phone = phone.strip().replace("+", "").replace(" ", "")
            
            # Store ONLY the UUID. We use 'created_at' for expiry.
            # We force 'created_at = NOW()' on conflict to reset the timer.
            await conn.execute("""
                INSERT INTO users (phone_number, magic_token, created_at) 
                VALUES ($1, $2, NOW())
                ON CONFLICT (phone_number) 
                DO UPDATE SET magic_token = $2, created_at = NOW()
            """, clean_phone, session_uuid)
            
        logger.info(f"✅ Link Created for {clean_phone}: {session_uuid}")
        return f"https://copit.in/checkout/{session_uuid}"
        
    except Exception as e:
        logger.error(f"🔥 DB Error: {e}")
        return "Error_Generating_Link"

# --- 2. VERIFY SESSION (No Parsing Needed) ---
@router.get("/session/{session_id}")
async def get_session_data(session_id: str, response: Response):
    # Disable Caching
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    
    clean_id = session_id.strip().replace("/", "")
    logger.info(f"🔍 Lookup Session: {clean_id}")

    async with db.pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT phone_number, saved_addresses, created_at 
            FROM users WHERE magic_token = $1
        """, clean_id)
    
    if not row:
        logger.error(f"❌ Token Not Found: {clean_id}")
        raise HTTPException(status_code=404, detail="Link invalid or used")

    # Time Check (10 Minutes) using DB Timestamp
    created_at = row['created_at']
    # Ensure created_at is aware of timezone (Postgres returns aware datetime)
    now = datetime.now(created_at.tzinfo) 
    
    if now > (created_at + timedelta(minutes=10)):
        logger.warning(f"⏳ Token Expired. Age: {now - created_at}")
        raise HTTPException(status_code=400, detail="Link expired")

    # Success
    phone = row['phone_number']
    saved_address = None
    if row['saved_addresses']:
        data = row['saved_addresses']
        try:
            saved_address = json.loads(data) if isinstance(data, str) else data
        except:
            saved_address = {}

    return {"phone": phone, "saved_address": saved_address}

# --- 3. CONFIRM ADDRESS ---
@router.post("/confirm-address")
async def confirm_address(data: AddressSubmit):
    clean_id = data.session_id.strip().replace("/", "")

    async with db.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT phone_number FROM users WHERE magic_token = $1", clean_id)
        
        if not row:
            raise HTTPException(status_code=400, detail="Invalid Session")
        
        phone = row['phone_number']
        addr = data.address
        
        # Save Address
        await conn.execute("""
            INSERT INTO addresses (user_id, pincode, house_no, area, landmark, city, state, is_default, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, TRUE, NOW())
        """, phone, addr.get("pincode"), addr.get("house_no"), addr.get("area"), 
             addr.get("landmark"), addr.get("city"), addr.get("state"))

        # Invalidate Token
        await conn.execute("UPDATE users SET magic_token = NULL WHERE phone_number = $1", phone)
    
    return {"redirect_url": f"https://wa.me/{os.getenv('BOT_NUMBER')}?text=Address_Confirmed_for_{clean_id}"}