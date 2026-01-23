import os
from dotenv import load_dotenv

load_dotenv()


WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID") 

if not WHATSAPP_TOKEN:
    print("⚠️ WARNING: WHATSAPP_TOKEN is missing!")