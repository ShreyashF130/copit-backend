import asyncpg
import os
import logging

logger = logging.getLogger("db_init")

class Database:
    def __init__(self):
        self.pool = None

    async def connect(self):
        db_url = os.getenv("DATABASE_URL")
        
        # 1. Standard SSL & PgBouncer flags required by Supabase
        if "?" not in db_url:
            db_url += "?sslmode=require&pgbouncer=true"
        elif "pgbouncer=true" not in db_url:
            db_url += "&sslmode=require&pgbouncer=true"

        logger.info("🔌 Booting Database Pool (Native AsyncIO Mode)...")
        
        try:
            self.pool = await asyncpg.create_pool(
                dsn=db_url,
                min_size=1,              
                max_size=15,             
                statement_cache_size=0,  # Mandatory for Supabase PgBouncer
                timeout=60.0,            # 60s tolerance for cold boots
                command_timeout=30.0,    # Max time a single query can run
                
                # 🚨 THE AWS FIREWALL FIX: Recycle connections every 2 mins 
                # before the 5-minute AWS Load Balancer kills them silently.
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