"""
Phylax - AI-Powered Surveillance Video Platform
FastAPI application entry point.

Mounts all routers, configures CORS and static file serving,
and initializes the database on startup.
"""

import os as _os
# Suppress noisy OpenCV FFmpeg/TLS stderr warnings globally.
# These messages (stream timeouts, TLS close failures) are normal for IP camera streams.
_os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")
_os.environ.setdefault("OPENCV_FFMPEG_LOGLEVEL", "-8")  # AV_LOG_QUIET
_os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "hwaccel;none"

import asyncio

if not hasattr(asyncio, "to_thread"):
    import contextvars
    import functools
    async def to_thread(func, *args, **kwargs):
        loop = asyncio.get_running_loop()
        ctx = contextvars.copy_context()
        func_call = functools.partial(ctx.run, func, *args, **kwargs)
        return await loop.run_in_executor(None, func_call)
    asyncio.to_thread = to_thread

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.staticfiles import StaticFiles

from config import ALLOWED_HOSTS, CORS_ORIGINS, EXPOSE_API_DOCS, THUMBNAIL_DIR, FRAME_DIR, VIDEO_DIR
from database import init_db
from routers import videos, analysis, search, stream, cameras, camera_map
from services.security_service import (
    apply_security_headers,
    get_client_ip,
    is_rate_limited,
    request_is_authorized,
    security_error,
)

# -- Logging Setup --
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# -- FastAPI App --
app = FastAPI(
    title="Phylax API",
    description="AI-powered surveillance video analysis platform using Gemma4:e2b",
    version="1.0.0",
    docs_url="/docs" if EXPOSE_API_DOCS else None,
    redoc_url="/redoc" if EXPOSE_API_DOCS else None,
    openapi_url="/openapi.json" if EXPOSE_API_DOCS else None,
)

if ALLOWED_HOSTS and "*" not in ALLOWED_HOSTS:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)

# -- CORS Middleware (allow frontend dev server) --
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in CORS_ORIGINS if origin.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def security_middleware(request, call_next):
    if request.method == "OPTIONS":
        response = await call_next(request)
        apply_security_headers(response)
        return response

    if is_rate_limited(get_client_ip(request)):
        return security_error(429, "Too many requests")

    if request.url.path != "/api/health" and not request_is_authorized(request):
        return security_error(401, "Authentication required", authenticate=True)

    response = await call_next(request)
    apply_security_headers(response)
    return response


# -- Mount Static Files --
# Serve thumbnails at /thumbnails/<filename>
app.mount("/thumbnails", StaticFiles(directory=str(THUMBNAIL_DIR)), name="thumbnails")
# Serve frame images at /frames/<video_id>/<filename>
app.mount("/frames", StaticFiles(directory=str(FRAME_DIR)), name="frames")

# -- Mount Routers --
app.include_router(videos.router)
app.include_router(analysis.router)
app.include_router(search.router)
app.include_router(stream.router)
app.include_router(cameras.router)
app.include_router(camera_map.router)


# -- Startup Event --
@app.on_event("startup")
async def on_startup():
    """Initialize the database schema on application start."""
    logger.info("Initializing Phylax database...")
    await init_db()

    from services.maintenance_service import cleanup_runtime_artifacts, run_periodic_cleanup
    cleanup_runtime_artifacts()
    asyncio.create_task(run_periodic_cleanup())
    
    # Start configured cameras
    from services.camera_service import start_camera_manager
    asyncio.create_task(start_camera_manager())

    logger.info("Phylax is ready!")


# -- Health Check --
@app.get("/api/health")
async def health_check():
    """Simple health check endpoint."""
    return {"status": "ok", "service": "Phylax"}


# -- Run with Uvicorn (for development) --
if __name__ == "__main__":
    import uvicorn
    from config import API_HOST, API_PORT

    reload_enabled = _os.environ.get("PHYLAX_RELOAD", "0").lower() in {"1", "true", "yes"}
    uvicorn.run("main:app" if reload_enabled else app, host=API_HOST, port=API_PORT, reload=reload_enabled)
