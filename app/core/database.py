import asyncpg
import os

class Database:
    def __init__(self):
        self.pool = None

    async def connect(self):
       
        self.pool = await asyncpg.create_pool(
            os.getenv("DATABASE_URL"),
            min_size=1,
            max_size=20,
            statement_cache_size=0  # Disable statement caching
        )
        print("✅ DB Connected")

    async def disconnect(self):
        if self.pool:
            await self.pool.close()

db = Database()