# from fastapi import FastAPI
# from fastapi.middleware.cors import CORSMiddleware
# from contextlib import asynccontextmanager
# import asyncio
# import os


# from app.core.database import db
# from app.services.recovery_service import cart_recovery_loop
# from app.services.delivery_service import delivery_watchdog_loop

# from app.routers import checkout, webhook, admin, payment, storefront

# # 3. LIFESPAN (The On/Off Switch)
# @asynccontextmanager
# async def lifespan(app: FastAPI):
#     # Connect to DB
#     await db.connect()
    
#     # Turn on Background Engines
#     asyncio.create_task(cart_recovery_loop())
#     asyncio.create_task(delivery_watchdog_loop())
    
#     print("✅ System Online: All Systems Go")
#     yield
    
#     # C. Shutdown: Disconnect DB
#     await db.disconnect()

# # 4. INITIALIZE APP
# app = FastAPI(
#     title="DropBot API",
#     version="2.0.0",
#     lifespan=lifespan
# )

# # 5. SECURITY (CORS)
# base_url = os.getenv("PUBLIC_BASE_URL")
# origins = [base_url] if base_url else ["*"]

# app.add_middleware(
#     CORSMiddleware,
#     # allow_origins=["https://copit.in",           # Your Production Domain
#     #     "https://www.copit.in",       # With www
#     #     "http://localhost:3000"],# Local Dev 
#     allow_origins=["*"],
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )


# app.include_router(webhook.router)  
# app.include_router(admin.router, prefix="/api") 
# app.include_router(payment.router, prefix="/api")
# app.include_router(storefront.router, prefix="/api")
# app.include_router(checkout.router)

# @app.get("/")
# def health_check():
#     return {"status": "active", "environment": "production"}



from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import asyncio
import os

from app.core.database import db
from app.services.recovery_service import cart_recovery_loop
from app.services.delivery_service import delivery_watchdog_loop

# Import Routers
from app.routers import checkout, webhook, admin, payment, storefront,dashboard

# 3. LIFESPAN
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Connect DB
    try:
        await db.connect()
        print("✅ Database Connected")
        # Start Background Tasks
        asyncio.create_task(cart_recovery_loop())
        asyncio.create_task(delivery_watchdog_loop())
        print("✅ System Online: All Systems Go")
    except Exception as e:
        print(f"🔥 Startup Error: {e}")
    
    yield
    
    # Shutdown
    await db.disconnect()
    print("🔻 Database Disconnected")

# 4. INITIALIZE APP
app = FastAPI(
    title="DropBot API",
    version="2.0.0",
    lifespan=lifespan
)

# 5. SECURITY (CORS - THE NUCLEAR OPTION)
# We allow everything. No restrictions.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ⚠️ MANUAL OPTIONS HANDLER (Failsafe for aggressive browsers)
@app.options("/{rest_of_path:path}")
async def preflight_handler(request: Request, rest_of_path: str):
    response = JSONResponse(content={"message": "Preflight OK"})
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "*"
    return response

# 6. ROUTERS
app.include_router(webhook.router)  
app.include_router(admin.router, prefix="/api") 
app.include_router(payment.router, prefix="/api")
app.include_router(storefront.router, prefix="/api")
app.include_router(checkout.router) 
app.include_router(dashboard.router)

@app.get("/")
def health_check():
    return {"status": "active", "environment": "production", "cors": "unrestricted"}