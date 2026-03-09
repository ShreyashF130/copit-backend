import asyncpg
import os
import logging
import socket
import ssl
from urllib.parse import urlparse

logger = logging.getLogger("db_init")

class Database:
    def __init__(self):
        self.pool = None

    async def connect(self):
        db_url = os.getenv("DATABASE_URL")
        
        # 1. Parse the hostname to force IPv4
        parsed = urlparse(db_url)
        hostname = parsed.hostname
        
        # 2. 🚨 THE NETWORK BYPASS: Force Render to use IPv4
        ipv4_address = socket.gethostbyname(hostname)
        logger.info(f"🔌 Network Bypass: Resolved {hostname} to IPv4: {ipv4_address}")

        # 3. Add Supabase PgBouncer flags (Remove sslmode=require from string)
        db_url = db_url.replace("?sslmode=require", "").replace("&sslmode=require", "")
        if "?" not in db_url:
            db_url += "?pgbouncer=true"
        elif "pgbouncer=true" not in db_url:
            db_url += "&pgbouncer=true"

        # 4. 🚨 THE SSL BYPASS: Because we use a raw IP, we must disable hostname verification
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        logger.info("🔌 Booting Database Pool (IPv4 + AWS Firewall Bypass)...")
        
        try:
            self.pool = await asyncpg.create_pool(
                dsn=db_url,
                host=ipv4_address,       # OVERRIDE RENDER'S DNS
                min_size=1,              
                max_size=15,             
                statement_cache_size=0,  # Mandatory for Supabase PgBouncer
                timeout=60.0,            
                command_timeout=30.0,
                ssl=ctx,                 # OVERRIDE SSL
                
                # 🚨 THE AWS FIREWALL FIX: Recycle connections every 2 mins
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