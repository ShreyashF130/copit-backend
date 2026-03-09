import asyncpg
import os
import logging

logger = logging.getLogger("db_init")

class Database:
    def __init__(self):
        self.pool = None

    async def connect(self):
        db_url = os.getenv("DATABASE_URL")
        
        # 1. Clean the URL and ensure pgbouncer flag is present
        db_url = db_url.replace("?sslmode=require", "").replace("&sslmode=require", "")
        if "?" not in db_url:
            db_url += "?pgbouncer=true"
        elif "pgbouncer=true" not in db_url:
            db_url += "&pgbouncer=true"

        logger.info("🔌 Booting Database Pool (Native asyncpg SSL Mode)...")
        
        try:
            # 2. 🚨 THE FIX: Use ssl='require' as a raw string. 
            # This bypasses the Python 'ssl' library bugs and lets the engine do the work.
            self.pool = await asyncpg.create_pool(
                dsn=db_url,
                min_size=1,              
                max_size=15,             
                statement_cache_size=0,  # Mandatory for Supabase PgBouncer
                timeout=60.0,            
                command_timeout=30.0,
                ssl='require',           # 🚨 THE MAGIC STRING
                server_settings={'tcp_keepalives_idle': '60'} # Keep AWS Load Balancer awake
            )
            logger.info("✅ DB Pool Established. Ready for traffic.")
            
        except Exception as e:
            logger.critical(f"🔥 DB Boot Failed: {type(e).__name__} - {str(e)}")
            raise e # Fails silently in the background, but logs the error

    async def disconnect(self):
        if self.pool:
            logger.info("🛑 Closing Database Pool...")
            await self.pool.close()

db = Database()