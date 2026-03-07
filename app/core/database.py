import asyncpg
import os
import asyncio
import logging

logger = logging.getLogger("db_init")

class Database:
    def __init__(self):
        self.pool = None

    async def connect(self):
        db_url = os.getenv("DATABASE_URL")
        
        # Ensure they added ?sslmode=require if it's missing
        if "?" not in db_url:
            db_url += "?sslmode=require"
        elif "sslmode=require" not in db_url:
            db_url += "&sslmode=require"

        retries = 3
        for i in range(retries):
            try:
                logger.info(f"🔌 Connecting to Pooler (Attempt {i+1}/{retries})...")
                
                self.pool = await asyncpg.create_pool(
                    dsn=db_url,
                    min_size=5,             
                    max_size=30,            
                    statement_cache_size=0, # 🚨 MANDATORY for PgBouncer/Supabase Pooler
                    command_timeout=15.0,   
                    max_inactive_connection_lifetime=300
                    # 🚨 Notice we deleted the custom 'ssl=ctx'. asyncpg will use the URL's sslmode.
                )
                logger.info("✅ DB Pool Established. Supabase accepted the connection.")
                return 

            except Exception as e:
                logger.error(f"⚠️ Connection Failed: {str(e)}")
                if i < retries - 1:
                    logger.info("🔄 Retrying in 2 seconds...")
                    await asyncio.sleep(2)
                else:
                    logger.critical("🔥 All connection attempts failed. Check URL Encoding!")
                    raise e 

    async def disconnect(self):
        if self.pool:
            logger.info("🛑 Closing Database Pool...")
            await self.pool.close()

db = Database()