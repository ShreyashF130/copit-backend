from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import uuid
import json
from datetime import datetime, timedelta
from app.core.database import db  # Using your existing connection

router = APIRouter()

# --- IN-MEMORY SESSION STORE (For the 3-month plan) ---
# We use this to map the "Random UUID" -> "Real Phone Number"
# Format: { "uuid_string": {"phone": "919876543210", "expires_at": datetime} }
checkout_sessions = {}

class CheckoutRequest(BaseModel):
    phone: str

class AddressSubmit(BaseModel):
    session_id: str
    address: dict

@router.post("/generate-link")
async def generate_checkout_link(request: CheckoutRequest):
    """
    Creates a temporary 24-hour link.
    """
    session_id = str(uuid.uuid4())
    
    # Store session in memory (State is lost if server restarts, but fine for MVP)
    checkout_sessions[session_id] = {
        "phone": request.phone,
        "expires_at": datetime.now() + timedelta(hours=24)
    }
    
    return {"url": f"https://copit.in/checkout/{session_id}"}

@router.get("/session/{session_id}")
async def get_session_data(session_id: str):
    """
    Frontend calls this to get the user's LAST SAVED address.
    """
    # 1. Validate Session
    session = checkout_sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Link expired or invalid")
    
    if datetime.now() > session["expires_at"]:
        del checkout_sessions[session_id]
        raise HTTPException(status_code=400, detail="Link expired")

    phone = session["phone"]

    # 2. Fetch 'saved_addresses' using YOUR Schema
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT saved_addresses 
            FROM users 
            WHERE phone_number = $1
        """, phone)
    
    saved_address = None
    if row and row['saved_addresses']:
        # Handle JSONB automatically
        data = row['saved_addresses']
        # If your JSONB is a string, parse it. If it's a dict, use it directly.
        if isinstance(data, str):
            saved_address = json.loads(data)
        else:
            saved_address = data

    return {
        "phone_masked": "******" + phone[-4:], 
        "saved_address": saved_address
    }

@router.post("/confirm-address")
async def confirm_address(data: AddressSubmit):
    # 1. Validate Session
    session = checkout_sessions.get(data.session_id)
    if not session:
        raise HTTPException(status_code=400, detail="Invalid Session")

    phone = session["phone"]
    
    # 2. UPSERT Logic for YOUR Schema
    # If user exists -> Update address. 
    # If user is new -> Insert phone + address.
    
    address_json = json.dumps(data.address)

    async with db.pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO users (phone_number, saved_addresses, created_at) 
            VALUES ($1, $2::jsonb, NOW())
            ON CONFLICT (phone_number) 
            DO UPDATE SET saved_addresses = $2::jsonb
        """, phone, address_json)
    
    # 3. Generate the WhatsApp Deep Link
    # This bounces them back to the specific chat context
    whatsapp_link = f"https://wa.me/91YOUR_BOT_NUMBER?text=Address_Confirmed_for_{data.session_id}"
    
    return {"redirect_url": whatsapp_link}