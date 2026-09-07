from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.core.database import init_db
from app.routers.v1 import api_router
from contextlib import asynccontextmanager

from app.core.mongo import connect_to_mongo, close_mongo_connection
from app.services.job_scheduler import start_scheduler, stop_scheduler

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize DB
    await init_db()
    try:
        await connect_to_mongo()
    except Exception:
        # MongoDB chỉ phục vụ agent logs/token usage - thiếu Mongo (vd chưa
        # cấu hình Atlas) không được chặn toàn bộ API khởi động.
        import logging
        logging.getLogger(__name__).warning(
            "MongoDB connect failed at %s - agent logs sẽ không được lưu", settings.MONGO_URI,
            exc_info=True,
        )
    # Scheduled jobs: background loop quét job active đến hạn mỗi 60s
    # (tắt bằng env JOBS_SCHEDULER_ENABLED=false cho môi trường chỉ API).
    import os
    if os.getenv("JOBS_SCHEDULER_ENABLED", "true").lower() != "false":
        start_scheduler()
    yield
    # Shutdown logic
    await stop_scheduler()
    await close_mongo_connection()

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.ALLOWED_ORIGINS.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

# Include Routers
app.include_router(api_router, prefix=settings.API_V1_STR)

@app.get("/")
def read_root():
    return {"message": "Welcome to TradingAgents Backend API"}

@app.get(f"{settings.API_V1_STR}/health")
def health():
    return {"status": "ok"}
