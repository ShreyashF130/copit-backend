import asyncpg
import os
import asyncio
import logging
import ssl

logger = logging.getLogger("db_init")

class Database:
    def __init__(self):
        self.pool = None

    async def connect(self):
        db_url = os.getenv("DATABASE_URL")
        
        # 1. Strip away any string-based SSL hacks that confuse uvloop
        db_url = db_url.replace("?sslmode=require", "").replace("&sslmode=require", "")
        
        # 2. Force the PgBouncer flag
        if "?" not in db_url:
            db_url += "?pgbouncer=true"
        elif "pgbouncer=true" not in db_url:
            db_url += "&pgbouncer=true"

        # 3. 🚨 THE UVLOOP KILLER: Force an unverified SSL context natively
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        logger.info("🔌 Booting Database Pool (Bypassing Uvloop Deadlock)...")
        
        try:
            self.pool = await asyncpg.create_pool(
                dsn=db_url,
                min_size=1,              
                max_size=15,             
                statement_cache_size=0,  
                timeout=60.0,            
                command_timeout=30.0,
                ssl=ctx                  # 🚨 INJECT THE BYPASS HERE
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