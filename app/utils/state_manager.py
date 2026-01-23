from datetime import datetime, timedelta


class StateManager:
    def __init__(self):
        # 🧠 RAM Storage with Time Tracking
        self.store = {}

    async def get_state(self, phone):
        return self.store.get(phone, {})

    async def set_state(self, phone, data):
        # Inject timestamp if not present
        if "last_updated" not in data:
            data["last_updated"] = datetime.now()
        self.store[phone] = data

    async def update_state(self, phone, new_data):
        current = self.store.get(phone, {})
        if not isinstance(current, dict):
            current = {}
        
        # Merge Data
        current.update(new_data)
        
        # 🕒 UPDATE TIMESTAMP (Critical for Recovery Loop)
        current["last_updated"] = datetime.now()
        
        self.store[phone] = current

    async def clear_state(self, phone):
        if phone in self.store:
            del self.store[phone]

    async def get_stale_carts(self, minutes=30):
        """
        Retrieves users who have abandoned a valuable cart.
        Logic: Active Cart + Stuck in Checkout + Silent for X mins + Not Nudged yet.
        """
        stale_users = []
        now = datetime.now()
        min_threshold = timedelta(minutes=minutes)
        max_threshold = timedelta(hours=24) # Don't spam after 24 hours

        snapshot = list(self.store.items()) 

        for phone, data in snapshot:
            # 1. BASIC CHECKS (Must have cart, must be stuck, must not be nudged)
            if (data.get("cart") 
                and data.get("state") in ["awaiting_payment_method", "awaiting_address", "awaiting_screenshot", "awaiting_qty"]
                and not data.get("nudged")):
                
                last_active = data.get("last_updated") # Standardize key name
                
                # 2. TIMESTAMP PARSING (Handle both String and Datetime objects)
                if isinstance(last_active, str):
                    try:
                        last_active = datetime.fromisoformat(last_active)
                    except ValueError:
                        continue # Skip bad data
                
                if not isinstance(last_active, datetime):
                    continue # Skip missing timestamp

                # 3. TIME CALCULATION
                time_diff = now - last_active
                
                # If they are in the "Sweet Spot" (Silent for 30m, but less than 24h)
                if time_diff > min_threshold and time_diff < max_threshold:
                    stale_users.append(phone)
                        
        return stale_users
    
state_manager = StateManager()

