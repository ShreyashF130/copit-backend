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
        
        # 🚨 FIX 1: DELETE the manual sslmode string hack! 
        # Do not append anything to the URL. The ssl=ctx object handles it perfectly.
        # We assume the clean pooler URL is passed directly from Render.

        # Highly optimized SSL context for Cloud Poolers
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        retries = 5 # 🚨 Increased retries to survive cold boots
        for i in range(retries):
            try:
                logger.info(f"🔌 Booting Database Pool (Attempt {i+1}/{retries})...")
                
                self.pool = await asyncpg.create_pool(
                    dsn=db_url,
                    min_size=2,              
                    max_size=20,             
                    statement_cache_size=0,  # Protects against PgBouncer crashes
                    timeout=60.0,            # 🚨 FIX 2: Raised to 60s for Supabase cold boots
                    command_timeout=15.0,    
                    max_inactive_connection_lifetime=300,
                    ssl=ctx                  # This explicitly handles the secure connection
                )
                logger.info("✅ DB Pool Established. Ready for traffic.")
                return 

            except Exception as e:
                # 🚨 FIX 3: Print the actual error TYPE so we aren't flying blind
                logger.error(f"⚠️ Connection Failed: {type(e).__name__} - {str(e)}")
                
                if i < retries - 1:
                    logger.info("🔄 Retrying in 5 seconds...")
                    await asyncio.sleep(5) # Give Supabase time to wake up
                else:
                    logger.critical("🔥 Final Network Timeout. Check Supabase Dashboard.")
                    raise e

    async def disconnect(self):
        if self.pool:
            logger.info("🛑 Closing Database Pool...")
            await self.pool.close()

db = Database()