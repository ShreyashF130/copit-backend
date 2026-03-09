import asyncpg
import os
import asyncio
import logging

logger = logging.getLogger("db_init")

class Database:
    def __init__(self):
        self.pool = None

    async def connect(self):
        # 1. Grab the raw pooler URL from Render (Port 6543)
        db_url = os.getenv("DATABASE_URL")
        
        # 2. 🚨 THE MAGIC FLAGS: Force asyncpg to talk to PgBouncer natively
        if "?" not in db_url:
            db_url += "?sslmode=require&pgbouncer=true"
        elif "pgbouncer=true" not in db_url:
            db_url += "&sslmode=require&pgbouncer=true"

        logger.info("🔌 Booting Database Pool for Loom Video...")
        
        try:
            # 3. Simple, native connection pool. No custom SSL contexts to freeze up.
            self.pool = await asyncpg.create_pool(
                dsn=db_url,
                min_size=1,              # Keep minimal to start fast
                max_size=15,             
                statement_cache_size=0,  # Mandatory for Supabase
                timeout=60.0,            # 60s tolerance for cold boots
                command_timeout=30.0
            )
            logger.info("✅ DB Pool Established. Ready for traffic.")
            
        except Exception as e:
            logger.critical(f"🔥 DB Boot Failed: {type(e).__name__} - {str(e)}")
            raise e

    async def disconnect(self):
        if self.pool:
            logger.info("🛑 Closing Database Pool...")
            await self.pool.close()

db = Database()