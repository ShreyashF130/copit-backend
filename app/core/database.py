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
        
        # Ensure Supabase pooler requirements are met
        if "?" not in db_url:
            db_url += "?sslmode=require"
        elif "sslmode=require" not in db_url:
            db_url += "&sslmode=require"

        # Highly optimized SSL context for Cloud Poolers
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        retries = 3
        for i in range(retries):
            try:
                logger.info(f"🔌 Booting Database Pool (Attempt {i+1}/{retries})...")
                
                self.pool = await asyncpg.create_pool(
                    dsn=db_url,
                    min_size=2,              # 🚨 LOWERED: Only open 2 connections on boot to save CPU.
                    max_size=20,             # 🚨 MAX: Scale up to 20 only when users actually start buying.
                    statement_cache_size=0,  # Mandatory for Supabase PgBouncer
                    timeout=30.0,            # Max time to wait for the boot connections
                    command_timeout=15.0,    
                    max_inactive_connection_lifetime=300,
                    ssl=ctx                  # Inject the optimized SSL context
                )
                logger.info("✅ DB Pool Established. Ready for traffic.")
                return 

            except Exception as e:
                logger.error(f"⚠️ Connection Failed: {str(e)}")
                if i < retries - 1:
                    logger.info("🔄 Retrying in 2 seconds...")
                    await asyncio.sleep(2)
                else:
                    logger.critical("🔥 Final Network Timeout. Check URL encoding and Supabase status.")
                    raise e 

    async def disconnect(self):
        if self.pool:
            logger.info("🛑 Closing Database Pool...")
            await self.pool.close()

db = Database()