import asyncpg
import os
import ssl 
class Database:
    def __init__(self):
        self.pool = None

    async def connect(self):
        # This tells asyncpg: "Yes, I trust the server, just connect securely."
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

        print("🔌 Connecting to DB...")
        
        self.pool = await asyncpg.create_pool(
            os.getenv("DATABASE_URL"),
            min_size=1,
            max_size=20,
            statement_cache_size=0,
            ssl=ssl_context,  # <--- CRITICAL ADDITION
            timeout=30        # <--- Give it more time (default is 10s)
        )
        print("✅ DB Connected")

    async def disconnect(self):
        if self.pool:
            await self.pool.close()

db = Database()