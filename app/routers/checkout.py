from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import uuid
import json
from datetime import datetime, timedelta
from app.core.database import db

router = APIRouter()

class CheckoutRequest(BaseModel):
    phone: str

class AddressSubmit(BaseModel):
    session_id: str
    address: dict

# --- 1. SHARED FUNCTION (Called by Webhook) ---
async def create_checkout_url(phone: str) -> str:
    """
    Generates a 10-minute, one-time-use link.
    Stores 'UUID::EXPIRY_TIMESTAMP' in the DB.
    """
    # 1. Generate UUID
    session_uuid = str(uuid.uuid4())
    
    # 2. Calculate Expiry (10 Minutes from now)
    expiry_time = (datetime.now() + timedelta(minutes=10)).timestamp()
    
    # 3. Create the "Trojan Token" (UUID + Expiry)
    # We store: "a4b3-99c2... :: 1709823423.5"
    token_payload = f"{session_uuid}::{expiry_time}"

    # 4. Save to DB
    async with db.pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO users (phone_number, magic_token) 
            VALUES ($1, $2)
            ON CONFLICT (phone_number) 
            DO UPDATE SET magic_token = $2
        """, phone, token_payload)
    
    # 5. Return URL (Only containing the UUID part)
    return f"https://copit.in/checkout/{session_uuid}" 

# --- 2. API ENDPOINTS ---

@router.post("/generate-link")
async def generate_checkout_link(request: CheckoutRequest):
    url = await create_checkout_url(request.phone)
    return {"url": url}

@router.get("/session/{session_id}")
async def get_session_data(session_id: str):
    """
    Validates the UUID and the Hidden Timestamp.
    """
    async with db.pool.acquire() as conn:
        # 1. Find the user who has a token STARTING with this UUID
        # We use the SQL 'LIKE' operator to match the prefix
        row = await conn.fetchrow("""
            SELECT phone_number, saved_addresses, magic_token
            FROM users 
            WHERE magic_token LIKE $1 || '::%'
        """, session_id)
    
    if not row:
        raise HTTPException(status_code=404, detail="Link invalid or used")

    # 2. Extract & Check Expiry
    magic_token = row['magic_token']
    try:
        # Split "UUID::TIMESTAMP"
        _, expiry_str = magic_token.split("::")
        expiry_ts = float(expiry_str)
        
        # RUTHLESS CHECK: Is it expired?
        if datetime.now().timestamp() > expiry_ts:
            # Optional: Clear the expired token from DB
            async with db.pool.acquire() as conn:
                await conn.execute("UPDATE users SET magic_token = NULL WHERE phone_number = $1", row['phone_number'])
            raise HTTPException(status_code=400, detail="Link expired")
            
    except ValueError:
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
    # 1. Validate Again (Double Security)
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT phone_number, magic_token 
            FROM users 
            WHERE magic_token LIKE $1 || '::%'
        """, data.session_id)
        
        if not row:
            raise HTTPException(status_code=400, detail="Invalid Session")
        
        # Check Expiry again
        _, expiry_str = row['magic_token'].split("::")
        if datetime.now().timestamp() > float(expiry_str):
            raise HTTPException(status_code=400, detail="Link expired")
        
        phone = row['phone_number']
        address_json = json.dumps(data.address)

        # 2. UPDATE ADDRESS & DESTROY TOKEN (Self-Destruct)
        # Setting magic_token = NULL ensures the link cannot be used again.
        await conn.execute("""
            UPDATE users 
            SET saved_addresses = $2::jsonb, magic_token = NULL 
            WHERE phone_number = $1
        """, phone, address_json)
    
    # 3. Return Deep Link
    whatsapp_link = f"https://wa.me/91YOUR_BOT_NUMBER?text=Address_Confirmed_for_{data.session_id}"
    
    return {"redirect_url": whatsapp_link}