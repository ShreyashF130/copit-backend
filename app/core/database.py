import asyncpg
import os
import logging
import ssl

logger = logging.getLogger("db_init")

class Database:
    def __init__(self):
        self.pool = None

    async def connect(self):
        db_url = os.getenv("DATABASE_URL")
        
        # 1. Add Supabase PgBouncer flags securely
        db_url = db_url.replace("?sslmode=require", "").replace("&sslmode=require", "")
        if "?" not in db_url:
            db_url += "?pgbouncer=true"
        elif "pgbouncer=true" not in db_url:
            db_url += "&pgbouncer=true"

        # 2. Relaxed SSL context for containerized cloud poolers
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        logger.info("🔌 Booting Database Pool (Dynamic DNS + AWS Firewall Bypass)...")
        
        try:
            # 3. Notice we removed host=ipv4_address! 
            # It will dynamically resolve the correct AWS IP every time.
            self.pool = await asyncpg.create_pool(
                dsn=db_url,
                min_size=1,              
                max_size=15,             
                statement_cache_size=0,  
                timeout=60.0,            
                command_timeout=30.0,
                ssl=ctx,                 
                
                # AWS Firewall Fix remains to keep pipes fresh
                max_inactive_connection_lifetime=120.0 
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