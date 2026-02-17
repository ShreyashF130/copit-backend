from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import uuid
import json
import time
import urllib.parse
from app.core.database import db
import logging
import os

# Setup Logger
logger = logging.getLogger("uvicorn.error")
router = APIRouter()

class CheckoutRequest(BaseModel):
    phone: str

class AddressSubmit(BaseModel):
    session_id: str
    address: dict

# --- 1. GENERATE LINK (With Explicit Transaction) ---
async def create_checkout_url(phone: str) -> str:
    session_uuid = str(uuid.uuid4())
    expiry_ts = int(time.time() + 600) # 10 mins
    token_payload = f"{session_uuid}::{expiry_ts}"

    try:
        # ⚠️ FIX: Use 'transaction()' to ensure data is committed
        async with db.pool.acquire() as conn:
            async with conn.transaction():
                # Check if user exists first to debug
                exists = await conn.fetchval("SELECT phone_number FROM users WHERE phone_number = $1", phone)
                
                await conn.execute("""
                    INSERT INTO users (phone_number, magic_token) 
                    VALUES ($1, $2)
                    ON CONFLICT (phone_number) 
                    DO UPDATE SET magic_token = $2
                """, phone, token_payload)
                
        logger.info(f"✅ Token Saved for {phone}: {session_uuid} (User Exists: {bool(exists)})")
        return f"https://copit.in/checkout/{session_uuid}"
        
    except Exception as e:
        logger.error(f"🔥 DB Write Error: {e}")
        return "Error_Generating_Link"

# --- 2. VERIFY SESSION (Paranoid Debugging) ---
@router.get("/session/{session_id}")
async def get_session_data(session_id: str):
    # ⚠️ FIX: URL Decode & Clean
    try:
        decoded_id = urllib.parse.unquote(session_id)
        clean_id = decoded_id.strip().replace("/", "").replace('"', '')
    except:
        clean_id = session_id

    # The token in DB is "UUID::TIMESTAMP"
    # We search for "UUID::%"
    search_pattern = f"{clean_id}::%"

    logger.info(f"🔍 Lookup ID: {clean_id} | Pattern: {search_pattern}")

    async with db.pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT phone_number, saved_addresses, magic_token
            FROM users WHERE magic_token LIKE $1
        """, search_pattern)
    
    if not row:
        logger.error(f"❌ DB returned None for pattern: {search_pattern}")
        # Debug: Check if ANY token exists just to be sure
        # async with db.pool.acquire() as conn:
        #     debug = await conn.fetchval("SELECT count(*) FROM users")
        #     logger.info(f"DEBUG: Total users in DB: {debug}")
        raise HTTPException(status_code=404, detail="Link invalid or used")

    # Time Check
    try:
        parts = row['magic_token'].split("::")
        if len(parts) < 2: raise ValueError("Bad Format")
        
        expiry_ts = float(parts[1])
        now_ts = time.time()
        
        if now_ts > expiry_ts:
            logger.warning(f"⏳ Expired: {now_ts} > {expiry_ts}")
            raise HTTPException(status_code=400, detail="Link expired")
            
    except Exception as e:
        logger.error(f"🔥 Token Parse Error: {e}")
        raise HTTPException(status_code=400, detail="Token Error")

    # Success Return
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
    clean_id = urllib.parse.unquote(data.session_id).strip().replace("/", "")
    search_pattern = f"{clean_id}::%"

    async with db.pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow("SELECT phone_number FROM users WHERE magic_token LIKE $1", search_pattern)
            
            if not row:
                raise HTTPException(status_code=400, detail="Session Invalid")
            
            phone = row['phone_number']
            addr = data.address
            
            # Save Address
            await conn.execute("""
                INSERT INTO addresses (user_id, pincode, house_no, area, landmark, city, state, is_default, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, TRUE, NOW())
            """, phone, addr.get("pincode"), addr.get("house_no"), addr.get("area"), 
                 addr.get("landmark"), addr.get("city"), addr.get("state"))

            # Clear Token (Prevent Reuse)
            await conn.execute("UPDATE users SET magic_token = NULL WHERE phone_number = $1", phone)
    
    return {"redirect_url": f"https://wa.me/{os.getenv('BOT_NUMBER')}??text=Address_Confirmed_for_{clean_id}"}
    
    # return {"redirect_url": f"https://wa.me/{os.getenv('BOT_NUMBER')}?text=Address_Confirmed_for_{clean_id}"}