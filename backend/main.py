"""
BackendTestForge — FastAPI Application Entry Point
"""

import logging

from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from backend.api.task_routes import router as task_router
from backend.api.ws_manager import ws_manager
from backend.config import config as app_config
from backend.models import init_db

# ── Logging ──

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ── Lifespan ──

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database on startup."""
    logger.info("Initializing database...")
    await init_db()
    logger.info("BackendTestForge started")
    yield
    logger.info("BackendTestForge shutting down")


# ── App ──

app = FastAPI(
    title="BackendTestForge",
    description="Multi-agent backend quality testing system",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — allow frontend dev server and production
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routes ──

app.include_router(task_router)


@app.get("/api/health")
async def health():
    """Health check."""
    return {"status": "ok", "version": "0.1.0"}


# ── WebSocket ──

@app.websocket("/api/ws/{task_id}")
async def websocket_endpoint(websocket: WebSocket, task_id: int):
    """WebSocket endpoint for real-time task progress."""
    await ws_manager.connect(task_id, websocket)
    try:
        while True:
            # Keep connection alive, receive pings
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        ws_manager.disconnect(task_id, websocket)
    except Exception as e:
        logger.warning(f"WebSocket error task={task_id}: {e}")
        ws_manager.disconnect(task_id, websocket)


# ── Entry ──

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "backend.main:app",
        host=app_config.SERVER_HOST,
        port=app_config.SERVER_PORT,
        reload=True,
    )
