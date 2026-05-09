"""
Centralized configuration for the Phylax application.
All constants and environment-variable overrides are defined here.
"""

import os
from pathlib import Path


def _env_first(*names: str, default: str = "") -> str:
    for name in names:
        value = os.environ.get(name)
        if value not in (None, ""):
            return value
    return default


def _env_flag(*names: str, default: str = "0") -> bool:
    return _env_first(*names, default=default).lower() in {"1", "true", "yes"}


def _env_csv(*names: str, default: str = "") -> list:
    raw = _env_first(*names, default=default)
    return [item.strip() for item in raw.split(",") if item.strip()]


# -- Base Paths --
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
VIDEO_DIR = DATA_DIR / "videos"
FRAME_DIR = DATA_DIR / "frames"
THUMBNAIL_DIR = DATA_DIR / "thumbnails"
MODEL_DIR = DATA_DIR / "models"
TEMP_DIR = DATA_DIR / "tmp"
DB_PATH = DATA_DIR / "phylax.db"

# Ensure directories exist at import time
for d in [DATA_DIR, VIDEO_DIR, FRAME_DIR, THUMBNAIL_DIR, TEMP_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# -- Ollama / Gemma4 Configuration --
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
MODEL_NAME = os.environ.get("MODEL_NAME", "gemma4:e4b")
VIDEO_ANALYSIS_MODEL_NAME = os.environ.get("VIDEO_ANALYSIS_MODEL_NAME", MODEL_NAME)
LIVE_ANALYSIS_MODEL_NAME = os.environ.get("LIVE_ANALYSIS_MODEL_NAME", "gemma4:e4b")
CAMERA_ANALYSIS_MODEL_NAME = os.environ.get("CAMERA_ANALYSIS_MODEL_NAME", LIVE_ANALYSIS_MODEL_NAME)
SEARCH_MODEL_NAME = os.environ.get("SEARCH_MODEL_NAME", "gemma4:e2b")
MODEL_TIMEOUT = float(os.environ.get("MODEL_TIMEOUT", "1800"))
LIVE_MODEL_TIMEOUT = float(os.environ.get("LIVE_MODEL_TIMEOUT", "90"))
CAMERA_MODEL_TIMEOUT = float(os.environ.get("CAMERA_MODEL_TIMEOUT", "90"))

# -- Image sizes for model inference --
VIDEO_ANALYSIS_WIDTH = int(os.environ.get("VIDEO_ANALYSIS_WIDTH", "448"))
VIDEO_ANALYSIS_HEIGHT = int(os.environ.get("VIDEO_ANALYSIS_HEIGHT", "252"))
LIVE_ANALYSIS_WIDTH = int(os.environ.get("LIVE_ANALYSIS_WIDTH", "448"))
LIVE_ANALYSIS_HEIGHT = int(os.environ.get("LIVE_ANALYSIS_HEIGHT", "252"))
CAMERA_ANALYSIS_WIDTH = int(os.environ.get("CAMERA_ANALYSIS_WIDTH", "320"))
CAMERA_ANALYSIS_HEIGHT = int(os.environ.get("CAMERA_ANALYSIS_HEIGHT", "180"))
CAMERA_DVR_SECONDS = int(os.environ.get("CAMERA_DVR_SECONDS", "300"))
CAMERA_DVR_FPS = float(os.environ.get("CAMERA_DVR_FPS", "2"))

# -- Runtime Cleanup Settings --
# Generated camera JPEGs are useful only for recent replay / QA context. Keep
# them bounded so long-running camera sessions do not fill the disk.
RUNTIME_CLEANUP_INTERVAL_SEC = int(os.environ.get("RUNTIME_CLEANUP_INTERVAL_SEC", "600"))
TEMP_FILE_RETENTION_SEC = int(os.environ.get("TEMP_FILE_RETENTION_SEC", str(6 * 60 * 60)))
LIVE_FRAME_DIR_RETENTION_SEC = int(os.environ.get("LIVE_FRAME_DIR_RETENTION_SEC", str(24 * 60 * 60)))
CAMERA_FRAME_RETENTION_SEC = int(os.environ.get("CAMERA_FRAME_RETENTION_SEC", str(24 * 60 * 60)))
QA_CROP_RETENTION_SEC = int(os.environ.get("QA_CROP_RETENTION_SEC", str(6 * 60 * 60)))
LOG_RETENTION_SEC = int(os.environ.get("LOG_RETENTION_SEC", str(7 * 24 * 60 * 60)))
LOG_MAX_BYTES = int(os.environ.get("LOG_MAX_BYTES", str(20 * 1024 * 1024)))
CACHE_FILE_RETENTION_SEC = int(os.environ.get("CACHE_FILE_RETENTION_SEC", str(24 * 60 * 60)))

# -- Video Analysis Settings --
# Interval (in seconds) between frames sent to the AI for comparison
FRAME_ANALYSIS_INTERVAL = int(os.environ.get("FRAME_ANALYSIS_INTERVAL", "10"))
LIVE_FRAME_ANALYSIS_INTERVAL = float(os.environ.get("LIVE_FRAME_ANALYSIS_INTERVAL", "3"))
CAMERA_FRAME_ANALYSIS_INTERVAL = float(os.environ.get("CAMERA_FRAME_ANALYSIS_INTERVAL", "4"))
CAMERA_ANALYSIS_MIN_INTERVAL = float(os.environ.get("CAMERA_ANALYSIS_MIN_INTERVAL", "2"))
CAMERA_ANALYSIS_MAX_INTERVAL = float(os.environ.get("CAMERA_ANALYSIS_MAX_INTERVAL", "30"))
CAMERA_BACKFILL_MAX_FRAMES = int(os.environ.get("CAMERA_BACKFILL_MAX_FRAMES", "3"))
CAMERA_AI_MAX_CONCURRENCY = int(os.environ.get("CAMERA_AI_MAX_CONCURRENCY", "1"))
CAMERA_AI_NUM_CTX = int(os.environ.get("CAMERA_AI_NUM_CTX", "1024"))
CAMERA_AI_NUM_PREDICT = int(os.environ.get("CAMERA_AI_NUM_PREDICT", "120"))
CAMERA_AI_TEMPERATURE = float(os.environ.get("CAMERA_AI_TEMPERATURE", "0"))
CAMERA_AI_USE_OPTIONS = os.environ.get("CAMERA_AI_USE_OPTIONS", "0").lower() in {"1", "true", "yes"}
CAMERA_AI_DEFAULT_ENABLED = _env_flag("CAMERA_AI_DEFAULT_ENABLED", default="1")
CAMERA_REVIEW_BUFFER_SIZE = int(os.environ.get("CAMERA_REVIEW_BUFFER_SIZE", "20"))
CAMERA_REVIEW_HISTORY_LIMIT = int(os.environ.get("CAMERA_REVIEW_HISTORY_LIMIT", "300"))
CAMERA_ROUTINE_EVENT_MIN_INTERVAL = float(os.environ.get("CAMERA_ROUTINE_EVENT_MIN_INTERVAL", "30"))

# Maximum upload file size in bytes (default 500 MB)
MAX_UPLOAD_SIZE = int(os.environ.get("MAX_UPLOAD_SIZE", str(500 * 1024 * 1024)))

# -- Server Settings --
API_HOST = os.environ.get("API_HOST", "127.0.0.1")
API_PORT = int(os.environ.get("API_PORT", "8000"))
CORS_ORIGINS = os.environ.get(
    "CORS_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000,http://127.0.0.1:3000",
).split(",")

# -- Security Settings --
# Defaults keep local development frictionless. Set these values before exposing
# the app through Cloudflare or any public endpoint.
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "")
ALLOWED_HOSTS = _env_csv("ALLOWED_HOSTS", default="*")
EXPOSE_API_DOCS = _env_flag("EXPOSE_API_DOCS", default="1")
PHYLAX_API_TOKEN = os.environ.get("PHYLAX_API_TOKEN", "")
PHYLAX_REQUIRE_CF_ACCESS = _env_flag("PHYLAX_REQUIRE_CF_ACCESS", default="0")
PHYLAX_ALLOWED_CF_EMAILS = _env_csv("PHYLAX_ALLOWED_CF_EMAILS", default="")
SECURITY_RATE_LIMIT_REQUESTS = int(os.environ.get("SECURITY_RATE_LIMIT_REQUESTS", "240"))
SECURITY_RATE_LIMIT_WINDOW_SEC = int(os.environ.get("SECURITY_RATE_LIMIT_WINDOW_SEC", "60"))
SECURITY_MEDIA_RATE_LIMIT_REQUESTS = int(os.environ.get("SECURITY_MEDIA_RATE_LIMIT_REQUESTS", "1800"))
SECURITY_TRUST_PROXY_HEADERS = _env_flag("SECURITY_TRUST_PROXY_HEADERS", default="1")
SECURITY_HTTPS_ONLY = _env_flag("SECURITY_HTTPS_ONLY", default="0")

# -- Public Camera Map Providers --
CAMERA_MAP_CACHE_TTL = int(os.environ.get("CAMERA_MAP_CACHE_TTL", "300"))
CAMERA_MAP_SOURCE_TIMEOUT = float(os.environ.get("CAMERA_MAP_SOURCE_TIMEOUT", "8"))
TDX_CLIENT_ID = os.environ.get("TDX_CLIENT_ID", "")
TDX_CLIENT_SECRET = os.environ.get("TDX_CLIENT_SECRET", "")
TDX_TOKEN_URL = os.environ.get(
    "TDX_TOKEN_URL",
    "https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token",
)
TDX_API_BASE_URL = os.environ.get(
    "TDX_API_BASE_URL",
    "https://tdx.transportdata.tw/api/basic",
)
TDX_FREEWAY_CCTV_URL = os.environ.get(
    "TDX_FREEWAY_CCTV_URL",
    "https://tdx.transportdata.tw/api/basic/v2/Road/Traffic/CCTV/Freeway",
)
FREEWAY_CCTV_INFO_URL = os.environ.get(
    "FREEWAY_CCTV_INFO_URL",
    "http://tisvcloud.freeway.gov.tw/cctv_info.xml.gz",
)
FREEWAY_CCTV_VALUE_URL = os.environ.get(
    "FREEWAY_CCTV_VALUE_URL",
    "http://tisvcloud.freeway.gov.tw/cctv_value.xml.gz",
)
TAICHUNG_CCTV_DATA_URL = os.environ.get(
    "TAICHUNG_CCTV_DATA_URL",
    "https://newdatacenter.taichung.gov.tw/api/v1/no-auth/resource.download?rid=6c9f5fd5-d74c-4450-9339-1a00e6cda2e6",
)
TAINAN_CCTV_DATA_URL = os.environ.get(
    "TAINAN_CCTV_DATA_URL",
    "https://trafficopendata.tainan.gov.tw/opendata/json/cctv/latest",
)
KEELUNG_CCTV_DATA_URL = os.environ.get(
    "KEELUNG_CCTV_DATA_URL",
    "https://www.klcg.gov.tw/wSite/public/Attachment/016/f1728008895657.csv",
)
THB_CCTV_DATA_URL = os.environ.get(
    "THB_CCTV_DATA_URL",
    "https://cctv-maintain.thb.gov.tw/opendataCCTVs.xml",
)
TWIPCAM_API_DOCS_URL = os.environ.get(
    "TWIPCAM_API_DOCS_URL",
    "https://www.twipcam.com/api/document",
)
TWIPCAM_CAM_LIST_URL = os.environ.get(
    "TWIPCAM_CAM_LIST_URL",
    "https://www.twipcam.com/api/v1/cam-list.json",
)
TWIPCAM_CAM_PAGE_BASE_URL = os.environ.get(
    "TWIPCAM_CAM_PAGE_BASE_URL",
    "https://www.twipcam.com/cam/",
)

# -- Supported Formats --
ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".webm", ".flv"}
