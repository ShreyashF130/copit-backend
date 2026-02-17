from fastapi import APIRouter, HTTPException, Response
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

# --- 1. GENERATE LINK ---
async def create_checkout_url(phone: str) -> str:
    session_uuid = str(uuid.uuid4())
    expiry_ts = int(time.time() + 600) # 10 mins
    token_payload = f"{session_uuid}::{expiry_ts}"

    try:
        async with db.pool.acquire() as conn:
            # ⚠️ Clean phone number just in case
            clean_phone = phone.strip().replace("+", "").replace(" ", "")
            
            await conn.execute("""
                INSERT INTO users (phone_number, magic_token) 
                VALUES ($1, $2)
                ON CONFLICT (phone_number) 
                DO UPDATE SET magic_token = $2
            """, clean_phone, token_payload)
            
        logger.info(f"✅ Token Saved: {session_uuid} for {clean_phone}")
        return f"https://copit.in/checkout/{session_uuid}"
        
    except Exception as e:
        logger.error(f"🔥 DB Write Error: {e}")
        return "Error_Generating_Link"

# --- 2. VERIFY SESSION (FUZZY MATCH) ---
@router.get("/session/{session_id}")
async def get_session_data(session_id: str, response: Response):
    # Prevent Browser Caching
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    
    # Clean the ID
    clean_id = session_id.strip().replace("/", "").replace('"', '')
    
    # ⚠️ FUZZY SEARCH: Match UUID anywhere in the string
    # This handles "UUID::Time", "UUID", or " UUID "
    search_pattern = f"%{clean_id}%"

    logger.info(f"🔍 Searching DB for pattern: {search_pattern}")

    async with db.pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT phone_number, saved_addresses, magic_token
            FROM users 
            WHERE magic_token LIKE $1
        """, search_pattern)
    
    if not row:
        logger.error(f"❌ NOT FOUND. ID: {clean_id} not in DB.")
        raise HTTPException(status_code=404, detail="Link invalid or used")

    # Time Check logic
    try:
        magic_token = row['magic_token']
        if "::" in magic_token:
            _, expiry_str = magic_token.split("::")
            expiry_ts = float(expiry_str)
            if time.time() > expiry_ts:
                logger.warning(f"⏳ Expired. {time.time()} > {expiry_ts}")
                raise HTTPException(status_code=400, detail="Link expired")
    except Exception as e:
        logger.warning(f"⚠️ Token format warning: {e} (Allowing access)")

    phone = row['phone_number']
    saved_address = None
    if row['saved_addresses']:
        data = row['saved_addresses']
        try:
            saved_address = json.loads(data) if isinstance(data, str) else data
        except:
            saved_address = {}

    logger.info(f"✅ Session Found for {phone}")
    return {"phone": phone, "saved_address": saved_address}

# --- 3. CONFIRM ADDRESS ---
@router.post("/confirm-address")
async def confirm_address(data: AddressSubmit):
    clean_id = data.session_id.strip().replace("/", "")
    search_pattern = f"%{clean_id}%"

    async with db.pool.acquire() as conn:
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

        # Clear Token
        await conn.execute("UPDATE users SET magic_token = NULL WHERE phone_number = $1", phone)
    
    return {"redirect_url": f"https://wa.me/{os.getenv('BOT_NUMBER')}?text=Address_Confirmed_for_{clean_id}"}
    
    # return {"redirect_url": f"https://wa.me/{os.getenv('BOT_NUMBER')}?text=Address_Confirmed_for_{clean_id}"}