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
        
        # Ensure standard SSL is requested natively
        if "?" not in db_url:
            db_url += "?sslmode=require"
        elif "sslmode=require" not in db_url:
            db_url += "&sslmode=require"

        # Standard container SSL context
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        logger.info("🔌 Booting Database Pool (Direct Metal Mode on Port 5432)...")
        
        try:
            self.pool = await asyncpg.create_pool(
                dsn=db_url,
                min_size=1,              
                max_size=10,             
                timeout=60.0,            
                command_timeout=30.0,
                ssl=ctx,
                
                # 🚨 THE HEARTBEAT: Pings the database every 60 seconds to keep the TCP socket alive permanently
                server_settings={'tcp_keepalives_idle': '60'} 
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