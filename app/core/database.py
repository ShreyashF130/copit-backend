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
        
        if "?" not in db_url:
            db_url += "?sslmode=require"
        elif "sslmode=require" not in db_url:
            db_url += "&sslmode=require"

        retries = 3
        for i in range(retries):
            try:
                logger.info(f"🔌 Booting Locked Pool (Attempt {i+1}/{retries})...")
                
                # 🚨 THE FIX: A pre-warmed, statically sized pool
                self.pool = await asyncpg.create_pool(
                    dsn=db_url,
                    min_size=15,             # 🚨 Boot 15 connections immediately on startup
                    max_size=15,             # 🚨 LOCK IT. Never try to spawn new ones under load.
                    statement_cache_size=0,  # Mandatory for Supabase PgBouncer
                    timeout=60.0,            # Give the server 60 seconds to establish the initial 15 connections
                    command_timeout=30.0,    
                    max_inactive_connection_lifetime=0 # 🚨 Stop aggressively dropping idle connections
                )
                logger.info("✅ DB Pool Locked and Loaded. 15 SSL Lanes Open.")
                return 

            except Exception as e:
                logger.error(f"⚠️ Connection Failed: {str(e)}")
                if i < retries - 1:
                    logger.info("🔄 Retrying in 2 seconds...")
                    await asyncio.sleep(2)
                else:
                    logger.critical("🔥 Hardware/Network Starvation.")
                    raise e 

    async def disconnect(self):
        if self.pool:
            logger.info("🛑 Closing Database Pool...")
            await self.pool.close()

db = Database()