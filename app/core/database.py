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
        
        # 1. Parse the hostname out of your Supabase URL
        parsed = urlparse(db_url)
        hostname = parsed.hostname
        
        # 2. 🚨 THE INDUSTRIAL FIX: Force IPv4 Resolution
        # We use Python's socket to resolve the strict IPv4 address.
        # This completely bypasses Render's broken IPv6 network routing.
        ipv4_address = socket.gethostbyname(hostname)
        logger.info(f"🔌 Network Bypass Active. Resolved {hostname} to IPv4: {ipv4_address}")

        # 3. Add Supabase PgBouncer flags to the DSN
        if "?" not in db_url:
            db_url += "?pgbouncer=true"
        elif "pgbouncer=true" not in db_url:
            db_url += "&pgbouncer=true"

        # 4. Because we are routing via raw IP, SSL hostname verification must be relaxed
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        try:
            # We pass the DSN, but explicitly OVERRIDE the host with our forced IPv4 address
            self.pool = await asyncpg.create_pool(
                dsn=db_url,
                host=ipv4_address,       # 🚨 OVERRIDE RENDER'S DNS HERE
                min_size=1,
                max_size=15,
                statement_cache_size=0,  # Mandatory for PgBouncer
                timeout=30.0,
                ssl=ctx
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