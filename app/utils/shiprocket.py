import json
import requests
from datetime import datetime

# 1. LOGIN (Standard)
def get_shiprocket_token(email, password):
    url = "https://apiv2.shiprocket.in/v1/external/auth/login"
    try:
        response = requests.post(url, json={"email": email, "password": password})
        if response.status_code == 200:
            return response.json().get('token')
        print(f"❌ Shiprocket Login Failed: {response.text}")
        return None
    except Exception as e:
        print(f"❌ Network Error: {e}")
        return None

# 2. CREATE ORDER (The "Smart" Version)
def create_shiprocket_order(token, order_data):
    url = "https://apiv2.shiprocket.in/v1/external/orders/create/ad-hoc"
    headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
    
    # A. ITEM PARSING & WEIGHT CALCULATION
    items_payload = []
    total_weight = 0.0
    
    # Handle if items are JSON string or List
    raw_items = order_data['items']
    if isinstance(raw_items, str):
        raw_items = json.loads(raw_items)
    
    for item in raw_items:
        qty = int(item.get('qty', 1))
        # Default to 0.5kg per item if weight is missing in DB
        w = float(item.get('weight', 0.5)) 
        total_weight += w * qty

        items_payload.append({
            "name": item['name'],
            "sku": item.get('sku', item['name'][:10]), 
            "units": qty,
            "selling_price": float(item['price']),
            "discount": "",
            "tax": "",
            "hsn": "" # Add HSN to your DB items table for GST compliance
        })

    # B. ADDRESS MAPPING (Crucial Fixes)
   
    pincode = order_data.get('delivery_pincode') or order_data.get('pincode')
    city = order_data.get('delivery_city') or order_data.get('city')
    state = order_data.get('delivery_state') or order_data.get('state')
    address_line = order_data.get('delivery_address') or order_data.get('address')

    # C. FAIL-SAFE: If pincode is missing, we cannot ship.
    if not pincode or len(str(pincode)) != 6:
        return {"error": "Invalid Pincode. Cannot Ship."}

    # D. PAYLOAD CONSTRUCTION
    payload = {
        "order_id": str(order_data['id']),
        "order_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        
        # ⚠️ Pickups fail if this name doesn't match the Seller's Dashboard EXACTLY
        "pickup_location": order_data.get('pickup_location_name', "Primary"),
        
        # Customer Details
        "billing_customer_name": order_data.get('customer_name', "Valued Customer"),
        "billing_last_name": "",
        "billing_address": address_line,
        "billing_city": city,        # ✅ Dynamic
        "billing_pincode": pincode,  # ✅ Dynamic
        "billing_state": state,      # ✅ Dynamic
        "billing_country": "India",
        "billing_email": order_data.get('customer_email', "noreply@copit.in"),
        "billing_phone": str(order_data['customer_phone']).replace("+91", "").strip(),
        
        "shipping_is_billing": True,
        "order_items": items_payload,
        "payment_method": "Prepaid" if order_data.get('status') == 'PAID' else "COD",
        "sub_total": float(order_data['total_amount']),
        "length": 10, "breadth": 10, "height": 10, 
        "weight": total_weight # ✅ Dynamic
    }

    try:
        response = requests.post(url, headers=headers, json=payload)
        return response.json()
    except Exception as e:
        return {"message": f"API Error: {str(e)}"}

# 3. GENERATE LABEL
def generate_shipping_label(token, shipment_id):
    url = "https://apiv2.shiprocket.in/v1/external/courier/generate/awb"
    headers = {'Authorization': f'Bearer {token}'}
    payload = {"shipment_id": [shipment_id]}
    
    try:
        response = requests.post(url, headers=headers, json=payload)
        return response.json()
    except Exception as e:
        return None

# 4. TRACK STATUS
def check_shiprocket_status(token, shipment_id):
    url = f"https://apiv2.shiprocket.in/v1/external/courier/track/shipment/{shipment_id}"
    headers = {'Authorization': f'Bearer {token}'}
    
    try:
        response = requests.get(url, headers=headers)
        data = response.json()
        
      
        if isinstance(data, dict):
         
             track_data = data.get('0', {}).get('tracking_data') or data.get('tracking_data')
             
             if track_data and 'shipment_track' in track_data:
                 return track_data['shipment_track'][0]['current_status'].upper()
                 
        return "UNKNOWN"
    except Exception as e:
        print(f"Tracking Error: {e}")
        return None