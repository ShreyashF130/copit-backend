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

background_tasks = []

async def background_startup_sequence():
    logger.info("⏳ [BACKGROUND STAGE 1] Booting Database Connection Pool...")
    try:
        await db.connect()
        logger.info("✅ [BACKGROUND STAGE 1 COMPLETE] Database Connected Successfully.")
        
        logger.info("⏳ [BACKGROUND STAGE 2] Starting Background Engines...")
        background_tasks.append(asyncio.create_task(cart_recovery_loop()))
        background_tasks.append(asyncio.create_task(delivery_watchdog_loop()))
        logger.info("✅ [BACKGROUND STAGE 2 COMPLETE] Background Engines Running.")
    except Exception as e:
        logger.critical(f"🔥 Background Startup Failed: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):

    master_startup_task = asyncio.create_task(background_startup_sequence())
    
    logger.info("🚀 SYSTEM BOOT: FastAPI opening ports instantly to satisfy Render...")
    
   
    yield  

    logger.info("🔻 Initiating Graceful Shutdown...")
    master_startup_task.cancel()
    for task in background_tasks:
        task.cancel()
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