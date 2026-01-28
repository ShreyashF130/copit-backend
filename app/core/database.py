import asyncpg
import os

class Database:
    def __init__(self):
        self.pool = None

    async def connect(self):
        print("🔌 Connecting to DB (Session Mode)...")
        try:
            self.pool = await asyncpg.create_pool(
                os.getenv("DATABASE_URL"),
                min_size=1,
                max_size=20,
                ssl="require",  # Standard SSL is fine for Session mode
                timeout=30
            )
            print("✅ DB Connected")
        except Exception as e:
            print(f"🔥 DB Connection Failed: {e}")
            raise e

    async def disconnect(self):
        if self.pool:
            await self.pool.close()

db = Database()