# import os
# import requests
# from dotenv import load_dotenv

# # Load your .env file
# load_dotenv()

# # CONFIGURATION
# FLOW_ID = os.getenv("ADDRESS_FLOW_ID")  # Make sure this is the NEW Flow ID (v7.3)
# TOKEN = os.getenv("WHATSAPP_TOKEN")     # Your System User Token

# def force_publish():
#     print(f"🔥 Attempting to Force Publish Flow: {FLOW_ID}")
    
#     url = f"https://graph.facebook.com/v21.0/{FLOW_ID}/publish"
    
#     headers = {
#         "Authorization": f"Bearer {TOKEN}",
#         "Content-Type": "application/json"
#     }
    
#     # Send the POST request to publish
#     response = requests.post(url, headers=headers)
#     data = response.json()
    
#     # ANALYZE THE RESULT
#     if "success" in data and data["success"]:
#         print("\n✅ SUCCESS! The Flow is now PUBLISHED.")
#         print("👉 You can now restart your server and test it.")
#     elif "error" in data:
#         print("\n❌ FAILED TO PUBLISH.")
#         print(f"⚠️ Error Code: {data['error'].get('code')}")
#         print(f"⚠️ Error Type: {data['error'].get('type')}")
#         print(f"⚠️ Message: {data['error'].get('message')}")
#         print(f"⚠️ Details: {data['error'].get('error_user_msg', 'No user message')}")
#     else:
#         print("\n🤔 Unknown Response:")
#         print(data)

# if __name__ == "__main__":
#     force_publish()




import os
import requests
import asyncio
from dotenv import load_dotenv

load_dotenv()

PHONE_ID = os.getenv("PHONE_NUMBER_ID")
TOKEN = os.getenv("WHATSAPP_TOKEN")
# Put your OWN personal WhatsApp number here to test
RECIPIENT_PHONE = "917264824344" 

async def send_pulse_check():
    print(f"💓 Checking Pulse for Phone ID: {PHONE_ID}")
    
    url = f"https://graph.facebook.com/v21.0/{PHONE_ID}/messages"
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json"
    }
    
    # Try to send the standard "hello_world" template
    payload = {
        "messaging_product": "whatsapp",
        "to": RECIPIENT_PHONE,
        "type": "template",
        "template": {
            "name": "hello_world",
            "language": { "code": "en_US" }
        }
    }
    
    response = requests.post(url, headers=headers, json=payload)
    data = response.json()
    
    if "messages" in data:
        print("✅ PULSE DETECTED: You can send messages.")
        print("👉 The block is specific to FLOWS (likely Display Name or Category).")
    else:
        print("❌ CARDIAC ARREST: You cannot send ANY messages.")
        print(f"⚠️ Error: {data}")

if __name__ == "__main__":
    asyncio.run(send_pulse_check())