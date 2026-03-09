import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.core.database import db
from app.services.recovery_service import cart_recovery_loop
from app.services.delivery_service import delivery_watchdog_loop
from app.routers import checkout, webhook, admin, payment, storefront, dashboard
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("main")



@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(" [STAGE 1] Booting Database Connection Pool...")

    await db.connect()
    logger.info("✅ [STAGE 1 COMPLETE] Database Connected Successfully.")
    
    logger.info("⏳ [STAGE 2] Starting Background Engines...")
    recovery_task = asyncio.create_task(cart_recovery_loop())
    delivery_task = asyncio.create_task(delivery_watchdog_loop())
    logger.info("✅ [STAGE 2 COMPLETE] Background Engines Running.")
    
    logger.info("🚀 SYSTEM ONLINE: All Systems Go. Ready for Traffic.")
    
    yield  
    
    logger.info("🔻 Initiating Graceful Shutdown...")
    recovery_task.cancel()
    delivery_task.cancel()
    await db.disconnect()
    logger.info("🛑 Database Disconnected. Server Offline.")



app = FastAPI(
    title="CopIt Operations OS API",
    description="The centralized backend for CopIt's WhatsApp & Storefront infrastructure.",
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/docs",  
    redoc_url=None
)



app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(webhook.router)  
app.include_router(admin.router, prefix="/api") 
app.include_router(payment.router, prefix="/api")
app.include_router(storefront.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")
app.include_router(checkout.router) 


@app.get("/", tags=["System"])
async def root_health_check():
    """Render pings this endpoint to know if the server is alive."""
    return JSONResponse(
        content={
            "service": "CopIt Core API",
            "status": "online",
            "database": "connected" if db.pool else "disconnected"
        },
        status_code=200
    )