import asyncpg
import os
import asyncio
import ssl

class Database:
    def __init__(self):
        self.pool = None

    async def connect(self):
        # Create a simplified SSL context that creates less friction
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        retries = 3
        for i in range(retries):
            try:
                print(f"🔌 Connecting to DB (Attempt {i+1}/{retries})...")
                
                self.pool = await asyncpg.create_pool(
                    os.getenv("DATABASE_URL"),
                    min_size=1,
                    max_size=20,
                    statement_cache_size=0,
                    ssl=ctx,            # Use the relaxed SSL context
                    timeout=60,         # ⏳ INCREASED PATIENCE
                    command_timeout=60
                )
                print("✅ DB Connected")
                return # Exit loop on success
            
            except Exception as e:
                print(f"⚠️ Connection Failed: {e}")
                if i < retries - 1:
                    print("🔄 Retrying in 2 seconds...")
                    await asyncio.sleep(2)
                else:
                    print("🔥 All connection attempts failed. Check credentials.")
                    raise e # Crash only after 3 failed tries

    async def disconnect(self):
        if self.pool:
            await self.pool.close()

db = Database()




