"""
Security helpers for deployments that expose Phylax beyond localhost.

The controls are intentionally dependency-free and opt-in so development stays
simple while production can be tightened with environment variables.
"""

from __future__ import annotations

import base64
import hmac
import time
from collections import defaultdict, deque
from typing import Optional

from fastapi import WebSocket
from fastapi.responses import JSONResponse
from starlette.requests import Request

from config import (
    PHYLAX_ALLOWED_CF_EMAILS,
    PHYLAX_API_TOKEN,
    PHYLAX_REQUIRE_CF_ACCESS,
    SECURITY_HTTPS_ONLY,
    SECURITY_MEDIA_RATE_LIMIT_REQUESTS,
    SECURITY_RATE_LIMIT_REQUESTS,
    SECURITY_RATE_LIMIT_WINDOW_SEC,
    SECURITY_TRUST_PROXY_HEADERS,
)

_rate_buckets: dict[str, deque[float]] = defaultdict(deque)


def apply_security_headers(response) -> None:
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
    response.headers.setdefault("Cache-Control", "no-store")
    if SECURITY_HTTPS_ONLY:
        response.headers.setdefault(
            "Strict-Transport-Security",
            "max-age=31536000; includeSubDomains; preload",
        )


def security_error(status_code: int, detail: str, *, authenticate: bool = False) -> JSONResponse:
    response = JSONResponse({"detail": detail}, status_code=status_code)
    if authenticate:
        response.headers["WWW-Authenticate"] = 'Basic realm="Phylax", charset="UTF-8"'
    apply_security_headers(response)
    return response


def get_client_ip(request: Request) -> str:
    if SECURITY_TRUST_PROXY_HEADERS:
        cf_ip = request.headers.get("cf-connecting-ip")
        if cf_ip:
            return cf_ip.strip()
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",", 1)[0].strip()
    return request.client.host if request.client else "unknown"


def is_rate_limited(client_ip: str, now: Optional[float] = None, *, path: str = "") -> bool:
    limit = _limit_for_path(path)
    if limit <= 0:
        return False

    now = now or time.time()
    window_start = now - max(1, SECURITY_RATE_LIMIT_WINDOW_SEC)
    bucket_key = f"{client_ip}|{_rate_scope_for_path(path)}"
    bucket = _rate_buckets[bucket_key]
    while bucket and bucket[0] < window_start:
        bucket.popleft()

    if len(bucket) >= limit:
        return True

    bucket.append(now)
    return False


def _limit_for_path(path: str) -> int:
    if _is_camera_media_path(path):
        return SECURITY_MEDIA_RATE_LIMIT_REQUESTS
    return SECURITY_RATE_LIMIT_REQUESTS


def _rate_scope_for_path(path: str) -> str:
    if _is_camera_media_path(path):
        return "media"
    return "api"


def _is_camera_media_path(path: str) -> bool:
    return path.startswith("/api/cameras/") and (
        path.endswith("/snapshot") or path.endswith("/stream")
    )


def request_is_authorized(request: Request) -> bool:
    return _cloudflare_access_ok(request.headers) and _api_token_ok(
        authorization=request.headers.get("authorization"),
        api_key=request.headers.get("x-api-key"),
        cookie_token=request.cookies.get("phylax_token"),
        query_token=request.query_params.get("access_token"),
    )


def websocket_is_authorized(websocket: WebSocket) -> bool:
    cookie_token = _cookie_value(websocket.headers.get("cookie", ""), "phylax_token")
    return _cloudflare_access_ok(websocket.headers) and _api_token_ok(
        authorization=websocket.headers.get("authorization"),
        api_key=websocket.headers.get("x-api-key"),
        cookie_token=cookie_token,
        query_token=websocket.query_params.get("access_token"),
    )


def _cloudflare_access_ok(headers) -> bool:
    if not PHYLAX_REQUIRE_CF_ACCESS:
        return True

    email = (headers.get("cf-access-authenticated-user-email") or "").strip().lower()
    jwt = (headers.get("cf-access-jwt-assertion") or "").strip()
    if not email and not jwt:
        return False

    allowed = {item.lower() for item in PHYLAX_ALLOWED_CF_EMAILS}
    if allowed and email not in allowed:
        return False

    return True


def _api_token_ok(
    *,
    authorization: Optional[str],
    api_key: Optional[str],
    cookie_token: Optional[str],
    query_token: Optional[str],
) -> bool:
    if not PHYLAX_API_TOKEN:
        return True

    candidates = [
        _bearer_token(authorization),
        _basic_password(authorization),
        api_key,
        cookie_token,
        query_token,
    ]
    return any(_constant_time_equals(candidate, PHYLAX_API_TOKEN) for candidate in candidates)


def _bearer_token(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "bearer" or not value:
        return None
    return value.strip()


def _basic_password(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "basic" or not value:
        return None
    try:
        decoded = base64.b64decode(value.strip()).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None
    _, _, password = decoded.partition(":")
    return password or None


def _cookie_value(cookie_header: str, name: str) -> Optional[str]:
    for part in cookie_header.split(";"):
        key, _, value = part.strip().partition("=")
        if key == name:
            return value
    return None


def _constant_time_equals(left: Optional[str], right: str) -> bool:
    if left is None:
        return False
    return hmac.compare_digest(left, right)
