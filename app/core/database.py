import asyncpg
import os
import asyncio
import ssl
import logging

logger = logging.getLogger("db_init")

class Database:
    def __init__(self):
        self.pool = None

    async def connect(self):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        # 🚨 MANDATORY CHECK: You must use the transaction pooler port.
        db_url = os.getenv("DATABASE_URL")
        if "5432" in db_url:
            logger.warning("⚠️ WARNING: You are connecting to port 5432. For high traffic, use the PgBouncer/Pooler URL (usually port 6543).")

        retries = 3
        for i in range(retries):
            try:
                logger.info(f"🔌 Connecting to DB (Attempt {i+1}/{retries})...")
                
                self.pool = await asyncpg.create_pool(
                    dsn=db_url,
                    min_size=5,             # 🚨 FIX: Keep 5 connections warm. 1 is too slow for web traffic.
                    max_size=30,            # 🚨 FIX: Allow enough burst capacity for simultaneous checkouts.
                    statement_cache_size=0, # Excellent. Required for PgBouncer/Supabase poolers.
                    ssl=ctx,
                    command_timeout=15.0,   # 🚨 FIX: Lowered from 60. If a query takes 60s, your app is already dead. Fail fast.
                    max_queries=50000,      # 🚨 FIX: Recycle connections periodically to prevent memory leaks.
                    max_inactive_connection_lifetime=300 # 🚨 FIX: Automatically drop connections that the cloud provider silently killed.
                )
                logger.info("✅ DB Pool Established and Warmed Up.")
                return 

            except Exception as e:
                logger.error(f"⚠️ Connection Failed: {e}")
                if i < retries - 1:
                    logger.info("🔄 Retrying in 2 seconds...")
                    await asyncio.sleep(2)
                else:
                    logger.critical("🔥 All connection attempts failed. Check credentials and firewall.")
                    raise e 

    async def disconnect(self):
        if self.pool:
            logger.info("🛑 Closing Database Pool...")
            await self.pool.close()

db = Database()