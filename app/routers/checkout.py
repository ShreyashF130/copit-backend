from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import uuid
import json
from datetime import datetime, timedelta, timezone
from app.core.database import db

# Setup Logging
import logging
logger = logging.getLogger("uvicorn.error")

router = APIRouter()

class CheckoutRequest(BaseModel):
    phone: str

class AddressSubmit(BaseModel):
    session_id: str
    address: dict

# --- 1. SHARED FUNCTION (Called by Webhook) ---
async def create_checkout_url(phone: str) -> str:
    # 1. Generate UUID
    session_uuid = str(uuid.uuid4())
    
    # 2. Calculate Expiry (10 Minutes from NOW in UTC)
    # ⚠️ CRITICAL FIX: Use timezone.utc explicitly
    expiry_time = (datetime.now(timezone.utc) + timedelta(minutes=10)).timestamp()
    
    # 3. Create the Payload
    token_payload = f"{session_uuid}::{expiry_time}"

    # 4. Save to DB
    try:
        async with db.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO users (phone_number, magic_token) 
                VALUES ($1, $2)
                ON CONFLICT (phone_number) 
                DO UPDATE SET magic_token = $2
            """, phone, token_payload)
        
        logger.info(f"✅ Generated Token for {phone}: {session_uuid}")
    except Exception as e:
        logger.error(f"🔥 DB Insert Error: {e}")
        return "Error_Generating_Link"
    
    # 5. Return URL 
    return f"https://copit.in/checkout/{session_uuid}" 

# --- 2. API ENDPOINTS ---

@router.post("/generate-link")
async def generate_checkout_link(request: CheckoutRequest):
    url = await create_checkout_url(request.phone)
    return {"url": url}

@router.get("/session/{session_id}")
async def get_session_data(session_id: str):
    logger.info(f"🔍 Searching for Session: {session_id}")
    
    clean_id = session_id.strip()
    search_pattern = f"{clean_id}::%"

    async with db.pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT phone_number, saved_addresses, magic_token
            FROM users 
            WHERE magic_token LIKE $1
        """, search_pattern)
    
    if not row:
        logger.warning(f"❌ Session NOT FOUND for ID: {clean_id}")
        # Allow 404 to trigger retry on frontend
        raise HTTPException(status_code=404, detail="Link invalid or used")

    # 2. Extract & Check Expiry
    magic_token = row['magic_token']
    try:
        parts = magic_token.split("::")
        if len(parts) != 2: raise ValueError("Invalid Token")
            
        _, expiry_str = parts
        expiry_ts = float(expiry_str)
        
        # ⚠️ CRITICAL FIX: Compare against UTC
        current_ts = datetime.now(timezone.utc).timestamp()
        
        # Add 30-second buffer for clock skew
        if current_ts > (expiry_ts + 30):
            logger.warning(f"⏳ Link EXPIRED. Current: {current_ts} > Expiry: {expiry_ts}")
            raise HTTPException(status_code=400, detail="Link expired")
            
    except ValueError as e:
        logger.error(f"🔥 Token Corruption: {e}")
        raise HTTPException(status_code=400, detail="Token corrupted")

    # 3. Return Data
    phone = row['phone_number']
    saved_address = None
    if row['saved_addresses']:
        data = row['saved_addresses']
        saved_address = json.loads(data) if isinstance(data, str) else data

    return {
        "phone_masked": "******" + phone[-4:], 
        "saved_address": saved_address
    }

@router.post("/confirm-address")
async def confirm_address(data: AddressSubmit):
    clean_id = data.session_id.strip()
    search_pattern = f"{clean_id}::%"

    async with db.pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT phone_number, magic_token 
            FROM users 
            WHERE magic_token LIKE $1
        """, search_pattern)
        
        if not row:
            raise HTTPException(status_code=400, detail="Invalid Session")
        
        # Check Expiry
        _, expiry_str = row['magic_token'].split("::")
        if datetime.now(timezone.utc).timestamp() > (float(expiry_str) + 30):
            raise HTTPException(status_code=400, detail="Link expired")
        
        phone = row['phone_number']
        
        # ⚠️ STRUCTURAL FIX: Save to Addresses Table directly
        addr = data.address
        await conn.execute("""
            INSERT INTO addresses (user_id, pincode, house_no, area, landmark, city, state, is_default, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, TRUE, NOW())
        """, phone, addr.get("pincode"), addr.get("house_no"), addr.get("area"), 
             addr.get("landmark"), addr.get("city"), addr.get("state"))

        # Clear Token
        await conn.execute("UPDATE users SET magic_token = NULL WHERE phone_number = $1", phone)
    
    # Return Deep Link with TRIGGER TEXT
    whatsapp_link = f"https://wa.me/91YOUR_BOT_NUMBER?text=Address_Confirmed_for_{clean_id}"
    
    return {"redirect_url": whatsapp_link}