from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import uuid
import json
import time # <--- The Fix: Use raw time, not datetime
from app.core.database import db
import logging
import os

logger = logging.getLogger("uvicorn.error")
router = APIRouter()

class CheckoutRequest(BaseModel):
    phone: str

class AddressSubmit(BaseModel):
    session_id: str
    address: dict

# --- 1. GENERATE LINK (Safe Logic) ---
async def create_checkout_url(phone: str) -> str:
    session_uuid = str(uuid.uuid4())
    
    # Expiry: Current Time + 600 seconds (10 mins)
    expiry_ts = int(time.time() + 600)
    
    token_payload = f"{session_uuid}::{expiry_ts}"

    try:
        async with db.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO users (phone_number, magic_token) 
                VALUES ($1, $2)
                ON CONFLICT (phone_number) 
                DO UPDATE SET magic_token = $2
            """, phone, token_payload)
    except Exception as e:
        logger.error(f"DB Error: {e}")
        return "Error"
    
    return f"https://copit.in/checkout/{session_uuid}"

# --- 2. VERIFY SESSION ---
@router.get("/session/{session_id}")
async def get_session_data(session_id: str):
    clean_id = session_id.strip()
    search_pattern = f"{clean_id}::%"

    async with db.pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT phone_number, saved_addresses, magic_token
            FROM users WHERE magic_token LIKE $1
        """, search_pattern)
    
    if not row:
        raise HTTPException(status_code=404, detail="Link invalid")

    # Time Check
    try:
        _, expiry_str = row['magic_token'].split("::")
        if time.time() > float(expiry_str):
            raise HTTPException(status_code=400, detail="Link expired")
    except:
        raise HTTPException(status_code=400, detail="Token Error")

    phone = row['phone_number']
    saved_address = None
    if row['saved_addresses']:
        data = row['saved_addresses']
        saved_address = json.loads(data) if isinstance(data, str) else data

    return {"phone": phone, "saved_address": saved_address}

# --- 3. SAVE ADDRESS ---
@router.post("/confirm-address")
async def confirm_address(data: AddressSubmit):
    clean_id = data.session_id.strip()
    search_pattern = f"{clean_id}::%"

    async with db.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT phone_number FROM users WHERE magic_token LIKE $1", search_pattern)
        if not row:
            raise HTTPException(status_code=400, detail="Invalid Session")
        
        phone = row['phone_number']
        addr = data.address
        
        # Insert into addresses table
        await conn.execute("""
            INSERT INTO addresses (user_id, pincode, house_no, area, landmark, city, state, is_default)
            VALUES ($1, $2, $3, $4, $5, $6, $7, TRUE)
        """, phone, addr.get("pincode"), addr.get("house_no"), addr.get("area"), 
             addr.get("landmark"), addr.get("city"), addr.get("state"))

        # Invalidate Token
        await conn.execute("UPDATE users SET magic_token = NULL WHERE phone_number = $1", phone)
    
    return {"redirect_url": f"https://wa.me/{os.getenv('BOT_NUMBER')}?text=Address_Confirmed_for_{clean_id}"}