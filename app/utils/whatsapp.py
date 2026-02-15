import httpx
from app.core.config import WHATSAPP_TOKEN, PHONE_NUMBER_ID
import json
import requests
import os


# --- HELPER: CENTRALIZED SENDER ---
async def _send_to_meta(payload):
    """
    Internal helper to handle the actual HTTP request to Meta.
    Prevents code duplication across functions.
    """
    if not WHATSAPP_TOKEN or not PHONE_NUMBER_ID:
        print("🔥 ERROR: Missing WhatsApp Credentials in Config!")
        return None

    url = f"https://graph.facebook.com/v18.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, headers=headers, json=payload)
            
            # 🛑 LOGIC: 400+ Errors mean Meta rejected it
            if response.status_code >= 400:
                print(f"🔥 Facebook API Error ({response.status_code}): {response.text}")
                return None
                
            return response.json()
        except Exception as e:
            print(f"🔥 Connection Error: {e}")
            return None

# --- PUBLIC FUNCTIONS ---

async def send_whatsapp_message(phone, text):
    """
    Sends a simple text message.
    """
    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "text",
        "text": {"body": text}
    }
    await _send_to_meta(payload)


async def send_interactive_message(phone, body_text, buttons):
    """
    Sends a message with up to 3 buttons.
    """
    button_payloads = [
        {"type": "reply", "reply": {"id": btn["id"], "title": btn["title"]}} 
        for btn in buttons
    ]

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": phone,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body_text},
            "action": {"buttons": button_payloads}
        }
    }
    await _send_to_meta(payload)


async def send_image_message(phone, image_url, caption=None):
    """
    Sends an image with an optional caption.
    """
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": phone,
        "type": "image",
        "image": {"link": image_url}
    }
    
    if caption:
        payload["image"]["caption"] = caption

    await _send_to_meta(payload)


async def send_marketing_template(phone, image_url, offer_text):
    """
    Sends a marketing template (requires 'custom_promo' approved in Meta).
    """
    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "template",
        "template": {
            "name": "custom_promo", 
            "language": {"code": "en"},
            "components": [
                {
                    "type": "header",
                    "parameters": [{"type": "image", "image": {"link": image_url}}]
                },
                {
                    "type": "body",
                    "parameters": [{"type": "text", "text": offer_text}]
                }
            ]
        }
    }
    await _send_to_meta(payload)


async def send_delivery_template(phone, order_id):
    """
    Sends the 3-button review template (requires 'delivery_feedback_v3' approved).
    """
    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "template",
        "template": {
            "name": "delivery_feedback_v3",
            "language": {"code": "en"},
            "components": [
                {
                    "type": "body",
                    "parameters": [{"type": "text", "text": str(order_id)}]
                }
            ]
        }
    }
    await _send_to_meta(payload)


async def send_custom_payload(phone, payload):
    """
    Sends raw JSON payload (Used for special Flows or complicated messages).
    """
    # Just forward the payload to the helper, ensuring the 'to' field is set if missing
    if "to" not in payload:
        payload["to"] = phone
        
    await _send_to_meta(payload)

ADDRESS_FLOW_ID = os.getenv("ADDRESS_FLOW_ID")

async def send_address_flow(phone, flow_id=ADDRESS_FLOW_ID):
    """
    Sends the Native Address Form (WhatsApp Flow) to the user.
    Draft mode is enabled for testing.
    """

    # ... inside send_address_flow function ...
    print(f"DEBUG: Sending Flow ID: {flow_id}") # <--- ADD THIS

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": phone,
        "type": "interactive",
        "interactive": {
            "type": "flow",
            "header": {
                "type": "text",
                "text": "⚡ Fast Checkout"
            },
            "body": {
                "text": "Please fill your delivery details securely within WhatsApp."
            },
            "footer": {
                "text": "Secure by CopIt"
            },
            "action": {
                "name": "flow",
                "parameters": {
                    "flow_message_version": "3",
                    "flow_token": "unused_token",
                    "flow_id": flow_id,
                    "flow_cta": "Fill Address",
                    "flow_action": "navigate",
                    "flow_action_payload": {
                        "screen": "ADDRESS_SCREEN"
                    }
                }
            }
        }
    }
    await _send_to_meta(payload)