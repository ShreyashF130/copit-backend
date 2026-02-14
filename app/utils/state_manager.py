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
        Returns a list of tuples: [(phone, data), (phone, data)...]
        """
        stale_users = []
        now = datetime.now()
        min_threshold = timedelta(minutes=minutes)
        max_threshold = timedelta(hours=24) 

        snapshot = list(self.store.items()) 

        for phone, data in snapshot:
            # 1. BASIC CHECKS
            if (data.get("cart") 
                and data.get("state") in ["awaiting_payment_method", "awaiting_address", "awaiting_screenshot", "awaiting_qty"]
                and not data.get("nudged")):
                
                last_active = data.get("last_updated")
                
                # 2. TIMESTAMP PARSING
                if isinstance(last_active, str):
                    try:
                        last_active = datetime.fromisoformat(last_active)
                    except ValueError:
                        continue 
                
                if not isinstance(last_active, datetime):
                    continue 

                # 3. TIME CALCULATION
                time_diff = now - last_active
                
                if time_diff > min_threshold and time_diff < max_threshold:
                    # FIX IS HERE 👇
                    stale_users.append((phone, data)) 
                        
        return stale_users