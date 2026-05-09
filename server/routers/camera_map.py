"""
First-party public camera map router.

This router aggregates only public or licensed camera sources. It does not scan
the internet for arbitrary IP cameras and does not attempt to access private
surveillance systems.
"""

from __future__ import annotations

import asyncio
import csv
import gzip
import hashlib
import logging
from io import StringIO
import re
import time
from typing import Any, Optional
from urllib.parse import urljoin
import xml.etree.ElementTree as ET

import httpx
from fastapi import APIRouter, HTTPException, Query

from config import (
    CAMERA_MAP_CACHE_TTL,
    CAMERA_MAP_SOURCE_TIMEOUT,
    FREEWAY_CCTV_INFO_URL,
    FREEWAY_CCTV_VALUE_URL,
    KEELUNG_CCTV_DATA_URL,
    TAICHUNG_CCTV_DATA_URL,
    TAINAN_CCTV_DATA_URL,
    TDX_API_BASE_URL,
    TDX_CLIENT_ID,
    TDX_CLIENT_SECRET,
    TDX_FREEWAY_CCTV_URL,
    TDX_TOKEN_URL,
    THB_CCTV_DATA_URL,
    TWIPCAM_API_DOCS_URL,
    TWIPCAM_CAM_LIST_URL,
    TWIPCAM_CAM_PAGE_BASE_URL,
)

router = APIRouter(prefix="/api/camera-map", tags=["camera-map"])
logger = logging.getLogger(__name__)

_SOURCE_TIMEOUT = CAMERA_MAP_SOURCE_TIMEOUT
_camera_cache: dict[str, Any] = {"expires_at": 0.0, "items": []}
_detail_cache: dict[str, dict[str, Any]] = {}
_cache_lock = asyncio.Lock()
_tdx_token_cache: dict[str, Any] = {"access_token": "", "expires_at": 0.0}
_tdx_token_lock = asyncio.Lock()
_provider_runtime_status: dict[str, dict[str, Any]] = {}
_TWIPCAM_FREEWAY_PREFIXES = (
    "\u570b\u9053\u4e00\u865f",
    "\u570b\u9053\u4e8c\u865f",
    "\u570b\u9053\u4e09\u865f",
    "\u570b\u9053\u4e09\u7532",
    "\u570b\u9053\u56db\u865f",
    "\u570b\u9053\u4e94\u865f",
    "\u570b\u9053\u516d\u865f",
    "\u570b\u9053\u516b\u865f",
    "\u570b\u9053\u5341\u865f",
    "\u570b\u90531\u865f",
    "\u570b\u90532\u865f",
    "\u570b\u90533\u865f",
    "\u570b\u90533\u7532",
    "\u570b\u90534\u865f",
    "\u570b\u90535\u865f",
    "\u570b\u90536\u865f",
    "\u570b\u90538\u865f",
    "\u570b\u905310\u865f",
    "\u6c50\u4e94\u9ad8\u67b6",
    "\u4e94\u694a\u9ad8\u67b6",
    "\u65b0\u751f\u9ad8\u67b6",
)
_TWIPCAM_FREEWAY_NAME_RE = re.compile(
    r"^(?P<road>(?:\u570b\u9053(?:[\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u53410-9]+\u865f|\u4e09\u7532|3\u7532)|\u6c50\u4e94\u9ad8\u67b6|\u4e94\u694a\u9ad8\u67b6|\u65b0\u751f\u9ad8\u67b6))"
    r"(?:\s+(?P<mile>\d+(?:\.\d+)?K\+\d+))?"
    r"(?:\s+(?P<direction>\u5317\u5411|\u5357\u5411|\u6771\u5411|\u897f\u5411))?"
    r"(?:\s+(?P<section>.+))?$"
)

_PROVIDER_CATALOG: dict[str, dict[str, str]] = {
    "freeway": {
        "name": "Freeway Bureau, MOTC",
        "short_name": "Freeway",
        "scope": "nationwide",
        "license_name": "Open Government Data License, version 1.0",
        "source_page": "https://tdx.transportdata.tw/api-service/swagger/basic/7f07d940-91a4-495d-9465-1c9df89d709c#/Traffic-Freeway/CCTV_Freeway",
    },
    "thb": {
        "name": "Taiwan Highway Bureau",
        "short_name": "Highway Bureau",
        "scope": "nationwide",
        "license_name": "Open Government Data License, version 1.0",
        "source_page": "https://thbapp.thb.gov.tw/opendata/",
    },
    "taichung": {
        "name": "Taichung City Government",
        "short_name": "Taichung",
        "scope": "city",
        "license_name": "Open Government Data License, version 1.0",
        "source_page": "https://data.gov.tw/dataset/83750",
    },
    "tainan": {
        "name": "Tainan City Government",
        "short_name": "Tainan",
        "scope": "city",
        "license_name": "Open Government Data License, version 1.0",
        "source_page": "https://data.gov.tw/dataset/166140",
    },
    "keelung": {
        "name": "Keelung City Government",
        "short_name": "Keelung",
        "scope": "city",
        "license_name": "Open Government Data License, version 1.0",
        "source_page": "https://data.gov.tw/dataset/59458",
    },
}


def _provider_base(provider: str) -> dict[str, Any]:
    meta = _PROVIDER_CATALOG[provider]
    return {
        "provider": provider,
        "provider_name": meta["name"],
        "provider_label": meta["short_name"],
        "license_name": meta["license_name"],
        "source_page": meta["source_page"],
    }


def _set_provider_runtime_status(
    provider: str,
    *,
    available: bool,
    count: int = 0,
    error: Optional[str] = None,
) -> None:
    _provider_runtime_status[provider] = {
        "available": available,
        "count": count,
        "last_error": error,
        "updated_at": int(time.time()),
    }


def _parse_float(value: Any) -> Optional[float]:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result else None


def _pick_first(mapping: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = mapping.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _stable_source_id(*parts: Any) -> str:
    digest = hashlib.sha1(
        "|".join(str(part).strip() for part in parts if part is not None).encode("utf-8")
    ).hexdigest()
    return digest[:16]


def _normalize_status(
    raw_value: Any,
    *,
    has_stream: bool = False,
    zero_is_online: bool = False,
) -> str:
    value = str(raw_value or "").strip().lower()
    if zero_is_online and value == "0":
        return "online"
    if value in {"online", "ok", "active", "enabled", "1", "true", "normal"}:
        return "online"
    if value in {"offline", "down", "disabled", "false", "error", "fail"}:
        return "offline"
    if has_stream:
        return "online"
    return "unknown"


def _looks_like_snapshot_url(url: str) -> bool:
    lower = str(url or "").strip().lower()
    if not lower:
        return False
    if "/snapshot/" in lower:
        return True
    return any(lower.endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".gif", ".webp"))


def _looks_like_stream_url(url: str) -> bool:
    lower = str(url or "").strip().lower()
    if not lower:
        return False
    if any(token in lower for token in ("bmjpg", "mjpeg", ".m3u8", "rtsp://", "multipart/x-mixed-replace")):
        return True
    return not _looks_like_snapshot_url(lower)


def _is_twipcam_freeway_title(title: str) -> bool:
    return bool(title) and title.startswith(_TWIPCAM_FREEWAY_PREFIXES)


def _unwrap_json_list(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("data", "records", "result", "items", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
        for value in payload.values():
            if isinstance(value, list):
                return value
    raise HTTPException(status_code=502, detail="Unexpected open camera source response")


def _is_within_bounds(camera: dict[str, Any], bounds: Optional[dict[str, float]]) -> bool:
    if not bounds:
        return True

    lat = _parse_float(camera.get("lat"))
    lng = _parse_float(camera.get("lng"))
    if lat is None or lng is None:
        return False

    if lat > bounds["north_lat"] or lat < bounds["south_lat"]:
        return False

    west_lon = bounds["west_lon"]
    east_lon = bounds["east_lon"]
    if west_lon <= east_lon:
        return west_lon <= lng <= east_lon
    return lng >= west_lon or lng <= east_lon


def _decode_xml_payload(data: bytes) -> str:
    payload = gzip.decompress(data) if data[:2] == b"\x1f\x8b" else data
    return payload.decode("utf-8-sig", errors="replace")


def _tdx_credentials_configured() -> bool:
    return bool(TDX_CLIENT_ID and TDX_CLIENT_SECRET)


def _invalidate_tdx_token() -> None:
    _tdx_token_cache["access_token"] = ""
    _tdx_token_cache["expires_at"] = 0.0


async def _get_tdx_access_token(force_refresh: bool = False) -> str:
    now = time.time()
    cached_token = str(_tdx_token_cache.get("access_token") or "")
    cached_expires_at = float(_tdx_token_cache.get("expires_at") or 0.0)
    if not force_refresh and cached_token and cached_expires_at > now + 30:
        return cached_token

    if not _tdx_credentials_configured():
        raise HTTPException(
            status_code=502,
            detail="TDX freeway CCTV credentials not configured. Set TDX_CLIENT_ID and TDX_CLIENT_SECRET.",
        )

    async with _tdx_token_lock:
        now = time.time()
        cached_token = str(_tdx_token_cache.get("access_token") or "")
        cached_expires_at = float(_tdx_token_cache.get("expires_at") or 0.0)
        if not force_refresh and cached_token and cached_expires_at > now + 30:
            return cached_token

        try:
            async with httpx.AsyncClient(timeout=_SOURCE_TIMEOUT, follow_redirects=True) as client:
                response = await client.post(
                    TDX_TOKEN_URL,
                    data={
                        "grant_type": "client_credentials",
                        "client_id": TDX_CLIENT_ID,
                        "client_secret": TDX_CLIENT_SECRET,
                    },
                    headers={"content-type": "application/x-www-form-urlencoded"},
                )
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPError as exc:
            logger.warning("TDX token fetch failed: %s", exc)
            raise HTTPException(status_code=502, detail="Unable to authenticate with TDX freeway CCTV API") from exc

        access_token = str(payload.get("access_token") or "").strip()
        if not access_token:
            raise HTTPException(status_code=502, detail="TDX freeway CCTV API did not return an access token")

        expires_in = int(payload.get("expires_in") or 3600)
        _tdx_token_cache["access_token"] = access_token
        _tdx_token_cache["expires_at"] = time.time() + max(60, expires_in)
        return access_token


async def _fetch_json(url: str) -> Any:
    try:
        async with httpx.AsyncClient(timeout=_SOURCE_TIMEOUT, follow_redirects=True) as client:
            response = await client.get(url, headers={"accept": "application/json"})
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as exc:
        logger.warning("Camera map JSON fetch failed for %s: %s", url, exc)
        raise HTTPException(status_code=502, detail=f"Unable to fetch open camera source: {url}") from exc


async def _fetch_bytes(url: str) -> bytes:
    try:
        async with httpx.AsyncClient(timeout=_SOURCE_TIMEOUT, follow_redirects=True) as client:
            response = await client.get(url)
        response.raise_for_status()
        return response.content
    except httpx.HTTPError as exc:
        logger.warning("Camera map binary fetch failed for %s: %s", url, exc)
        raise HTTPException(status_code=502, detail=f"Unable to fetch open camera source: {url}") from exc


async def _fetch_text(url: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=_SOURCE_TIMEOUT, follow_redirects=True) as client:
            response = await client.get(url)
        response.raise_for_status()
        return response.text
    except httpx.HTTPError as exc:
        logger.warning("Camera map text fetch failed for %s: %s", url, exc)
        raise HTTPException(status_code=502, detail=f"Unable to fetch open camera source: {url}") from exc


async def _fetch_tdx_json(url: str, *, params: Optional[dict[str, Any]] = None) -> Any:
    token = await _get_tdx_access_token()
    headers = {
        "accept": "application/json",
        "authorization": f"Bearer {token}",
    }

    try:
        async with httpx.AsyncClient(timeout=_SOURCE_TIMEOUT, follow_redirects=True) as client:
            response = await client.get(url, headers=headers, params=params)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 401:
            _invalidate_tdx_token()
            refreshed_token = await _get_tdx_access_token(force_refresh=True)
            retry_headers = {
                "accept": "application/json",
                "authorization": f"Bearer {refreshed_token}",
            }
            try:
                async with httpx.AsyncClient(timeout=_SOURCE_TIMEOUT, follow_redirects=True) as client:
                    retry_response = await client.get(url, headers=retry_headers, params=params)
                retry_response.raise_for_status()
                return retry_response.json()
            except httpx.HTTPError as retry_exc:
                logger.warning("TDX CCTV retry fetch failed for %s: %s", url, retry_exc)
                raise HTTPException(status_code=502, detail=f"Unable to fetch TDX freeway CCTV source: {url}") from retry_exc

        logger.warning("TDX CCTV fetch failed for %s: %s", url, exc)
        raise HTTPException(status_code=502, detail=f"Unable to fetch TDX freeway CCTV source: {url}") from exc
    except httpx.HTTPError as exc:
        logger.warning("TDX CCTV fetch failed for %s: %s", url, exc)
        raise HTTPException(status_code=502, detail=f"Unable to fetch TDX freeway CCTV source: {url}") from exc


def _normalize_taichung_camera(item: dict[str, Any]) -> Optional[dict[str, Any]]:
    source_id = str(item.get("cctvid") or "").strip()
    if not source_id:
        return None

    lat = _parse_float(item.get("py"))
    lng = _parse_float(item.get("px"))
    if lat is None or lng is None:
        return None

    detail_url = str(item.get("url") or "").strip()
    status = _normalize_status(item.get("status"), has_stream=bool(detail_url), zero_is_online=True)

    return {
        **_provider_base("taichung"),
        "id": f"taichung:{source_id}",
        "source_id": source_id,
        "title": str(item.get("roadsection") or f"Taichung CCTV {source_id}").strip(),
        "lat": lat,
        "lng": lng,
        "country": "Taiwan",
        "region": "Taichung",
        "status": status,
        "detail_url": detail_url,
        "preview_url": None,
        "stream_url": None,
    }


def _normalize_tainan_camera(item: dict[str, Any]) -> Optional[dict[str, Any]]:
    title = _pick_first(item, "Location", "location")
    lat = _parse_float(_pick_first(item, "wgsy", "WGsy", "latitude", "Latitude"))
    lng = _parse_float(_pick_first(item, "wgsx", "WGSx", "longitude", "Longitude"))
    if lat is None or lng is None:
        return None

    preview_url = _pick_first(item, "url", "URL")
    source_id = _stable_source_id("tainan", title, lat, lng)

    return {
        **_provider_base("tainan"),
        "id": f"tainan:{source_id}",
        "source_id": source_id,
        "title": title or f"Tainan CCTV {source_id}",
        "lat": lat,
        "lng": lng,
        "country": "Taiwan",
        "region": "Tainan",
        "status": _normalize_status(None, has_stream=bool(preview_url)),
        "detail_url": preview_url or None,
        "preview_url": preview_url or None,
        "stream_url": None,
    }


def _normalize_keelung_camera(row: dict[str, Any]) -> Optional[dict[str, Any]]:
    source_id = _pick_first(row, "CCTVID", "cctvid")
    if not source_id:
        source_id = _stable_source_id(
            "keelung",
            _pick_first(row, "RoadName", "roadname"),
            _pick_first(row, "PositionLat", "positionlat"),
            _pick_first(row, "PositionLon", "positionlon"),
        )

    lat = _parse_float(_pick_first(row, "PositionLat", "positionlat"))
    lng = _parse_float(_pick_first(row, "PositionLon", "positionlon"))
    if lat is None or lng is None:
        return None

    stream_url = _pick_first(row, "VideoStreamURL", "videostreamurl")
    road_name = _pick_first(row, "RoadName", "roadname")
    description = _pick_first(row, "SurveillanceDescription", "surveillancedescription")

    return {
        **_provider_base("keelung"),
        "id": f"keelung:{source_id}",
        "source_id": source_id,
        "title": road_name or description or f"Keelung CCTV {source_id}",
        "lat": lat,
        "lng": lng,
        "country": "Taiwan",
        "region": "Keelung",
        "status": _normalize_status(None, has_stream=bool(stream_url)),
        "detail_url": stream_url or None,
        "preview_url": stream_url or None,
        "stream_url": stream_url or None,
    }


def _normalize_thb_camera(item: ET.Element, authority_code: str) -> Optional[dict[str, Any]]:
    source_id = (item.findtext("CCTVID") or "").strip()
    if not source_id:
        return None

    lat = _parse_float(item.findtext("PositionLat"))
    lng = _parse_float(item.findtext("PositionLon"))
    if lat is None or lng is None:
        return None

    stream_url = (item.findtext("VideoStreamURL") or "").strip()
    road_name = (item.findtext("RoadName") or "").strip()
    description = (item.findtext("SurveillanceDescription") or "").strip()

    return {
        **_provider_base("thb"),
        "id": f"thb:{authority_code}:{source_id}",
        "source_id": source_id,
        "title": road_name or description or (f"{authority_code} CCTV {source_id}" if authority_code else f"THB CCTV {source_id}"),
        "lat": lat,
        "lng": lng,
        "country": "Taiwan",
        "region": authority_code or "Taiwan Provincial Highway",
        "status": _normalize_status(None, has_stream=bool(stream_url)),
        "detail_url": stream_url,
        "preview_url": stream_url or None,
        "stream_url": stream_url or None,
    }


def _normalize_freeway_camera(
    static_attrs: dict[str, str],
    value_attrs: Optional[dict[str, str]],
) -> Optional[dict[str, Any]]:
    source_id = str(static_attrs.get("cctvid") or "").strip()
    if not source_id:
        return None

    lat = _parse_float(static_attrs.get("py"))
    lng = _parse_float(static_attrs.get("px"))
    if lat is None or lng is None:
        return None

    stream_url = str((value_attrs or {}).get("url") or "").strip()
    raw_status = (value_attrs or {}).get("status")
    roadsection = str(static_attrs.get("roadsection") or "").strip()

    return {
        **_provider_base("freeway"),
        "id": f"freeway:{source_id}",
        "source_id": source_id,
        "title": roadsection or f"Freeway CCTV {source_id}",
        "lat": lat,
        "lng": lng,
        "country": "Taiwan",
        "region": "National Freeway",
        "status": _normalize_status(raw_status, has_stream=bool(stream_url)),
        "detail_url": stream_url or None,
        "preview_url": stream_url or None,
        "stream_url": stream_url or None,
    }


def _normalize_freeway_tdx_camera(item: dict[str, Any]) -> Optional[dict[str, Any]]:
    source_id = _pick_first(item, "CCTVID")
    if not source_id:
        return None

    lat = _parse_float(item.get("PositionLat"))
    lng = _parse_float(item.get("PositionLon"))
    if lat is None or lng is None:
        return None

    road_name = _pick_first(item, "RoadName")
    location_mile = _pick_first(item, "LocationMile")
    road_direction = _pick_first(item, "RoadDirection")
    description = _pick_first(item, "SurveillanceDescription")
    preview_url = _pick_first(item, "VideoImageURL")
    stream_url = _pick_first(item, "VideoStreamURL")

    title_parts = [part for part in (road_name, location_mile) if part]
    title = " | ".join(title_parts) or description or f"Freeway CCTV {source_id}"

    return {
        **_provider_base("freeway"),
        "id": f"freeway:{source_id}",
        "source_id": source_id,
        "title": title,
        "lat": lat,
        "lng": lng,
        "country": "Taiwan",
        "region": "National Freeway",
        "status": _normalize_status(None, has_stream=bool(stream_url or preview_url)),
        "detail_url": stream_url or preview_url or None,
        "preview_url": preview_url or stream_url or None,
        "stream_url": stream_url or None,
        "road_name": road_name or None,
        "road_direction": road_direction or None,
        "location_mile": location_mile or None,
        "surveillance_description": description or None,
    }


def _normalize_twipcam_freeway_camera(item: dict[str, Any]) -> Optional[dict[str, Any]]:
    source_id = _pick_first(item, "id")
    title = _pick_first(item, "name", "title")
    if not source_id or not _is_twipcam_freeway_title(title):
        return None

    lat = _parse_float(_pick_first(item, "lat", "latitude"))
    lng = _parse_float(_pick_first(item, "lon", "lng", "longitude"))
    if lat is None or lng is None:
        return None

    cam_url = _pick_first(item, "cam_url", "camUrl", "stream_url", "streamUrl")
    detail_url = urljoin(TWIPCAM_CAM_PAGE_BASE_URL, source_id)
    stream_url = cam_url if _looks_like_stream_url(cam_url) else ""
    name_match = _TWIPCAM_FREEWAY_NAME_RE.match(title)
    road_name = str(name_match.group("road") or "").strip() if name_match else ""
    location_mile = str(name_match.group("mile") or "").strip() if name_match else ""
    road_direction = str(name_match.group("direction") or "").strip() if name_match else ""
    section = str(name_match.group("section") or "").strip() if name_match else ""

    return {
        **_provider_base("freeway"),
        "id": f"freeway:{source_id}",
        "source_id": source_id,
        "title": title or f"Freeway CCTV {source_id}",
        "provider_name": "Taiwan National Freeway",
        "provider_label": "Freeway",
        "lat": lat,
        "lng": lng,
        "country": "Taiwan",
        "region": "National Freeway",
        "status": _normalize_status(None, has_stream=bool(cam_url)),
        "detail_url": detail_url,
        "preview_url": cam_url or None,
        "stream_url": stream_url or None,
        "road_name": road_name or None,
        "road_direction": road_direction or None,
        "location_mile": location_mile or None,
        "surveillance_description": section or None,
        "license_name": "CC BY 3.0 TW",
        "source_page": TWIPCAM_API_DOCS_URL,
        "source_attribution": "Indexed by twipcam public camera API",
    }


async def _load_taichung_cameras() -> list[dict[str, Any]]:
    data = await _fetch_json(TAICHUNG_CCTV_DATA_URL)
    cameras = []
    for item in _unwrap_json_list(data):
        if not isinstance(item, dict):
            continue
        normalized = _normalize_taichung_camera(item)
        if normalized:
            cameras.append(normalized)
    return cameras


async def _load_tainan_cameras() -> list[dict[str, Any]]:
    data = await _fetch_json(TAINAN_CCTV_DATA_URL)
    cameras = []
    for item in _unwrap_json_list(data):
        if not isinstance(item, dict):
            continue
        normalized = _normalize_tainan_camera(item)
        if normalized:
            cameras.append(normalized)
    return cameras


async def _load_keelung_cameras() -> list[dict[str, Any]]:
    csv_text = (await _fetch_text(KEELUNG_CCTV_DATA_URL)).lstrip("\ufeff")
    reader = csv.DictReader(StringIO(csv_text))

    cameras = []
    for row in reader:
        normalized = _normalize_keelung_camera(row)
        if normalized:
            cameras.append(normalized)
    return cameras


async def _load_thb_cameras() -> list[dict[str, Any]]:
    xml_text = await _fetch_text(THB_CCTV_DATA_URL)
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise HTTPException(status_code=502, detail="Unable to parse Highway Bureau CCTV XML") from exc

    authority_code = (root.findtext("AuthorityCode") or "").strip()
    cameras = []
    for item in root.findall(".//CCTV"):
        normalized = _normalize_thb_camera(item, authority_code)
        if normalized:
            cameras.append(normalized)
    return cameras


async def _load_freeway_cameras() -> list[dict[str, Any]]:
    errors: list[str] = []
    tdx_url = TDX_FREEWAY_CCTV_URL or f"{TDX_API_BASE_URL.rstrip('/')}/v2/Road/Traffic/CCTV/Freeway"

    if _tdx_credentials_configured():
        try:
            payload = await _fetch_tdx_json(
                tdx_url,
                params={
                    "$format": "JSON",
                    "$top": 2000,
                    "$orderby": "CCTVID",
                },
            )
            cameras = []
            for item in payload.get("CCTVs") or []:
                if not isinstance(item, dict):
                    continue
                normalized = _normalize_freeway_tdx_camera(item)
                if normalized:
                    cameras.append(normalized)
            if cameras:
                return cameras
            errors.append("TDX freeway CCTV API returned no cameras")
        except HTTPException as exc:
            error_text = str(getattr(exc, "detail", "")) or str(exc)
            errors.append(error_text)

    try:
        return await _load_freeway_cameras_from_legacy()
    except HTTPException as exc:
        error_text = str(getattr(exc, "detail", "")) or str(exc)
        errors.append(error_text)

    try:
        return await _load_freeway_cameras_from_twipcam()
    except HTTPException as exc:
        error_text = str(getattr(exc, "detail", "")) or str(exc)
        errors.append(error_text)
        raise HTTPException(status_code=502, detail=" | ".join(errors)) from exc


async def _load_freeway_cameras_from_legacy() -> list[dict[str, Any]]:
    info_bytes, value_bytes = await asyncio.gather(
        _fetch_bytes(FREEWAY_CCTV_INFO_URL),
        _fetch_bytes(FREEWAY_CCTV_VALUE_URL),
    )

    try:
        info_root = ET.fromstring(_decode_xml_payload(info_bytes))
        value_root = ET.fromstring(_decode_xml_payload(value_bytes))
    except ET.ParseError as exc:
        raise HTTPException(status_code=502, detail="Unable to parse Freeway CCTV XML") from exc

    value_map = {
        str(item.attrib.get("cctvid") or "").strip(): {key.lower(): value for key, value in item.attrib.items()}
        for item in value_root.findall(".//Info")
        if str(item.attrib.get("cctvid") or "").strip()
    }

    cameras = []
    for item in info_root.findall(".//Info"):
        attrs = {key.lower(): value for key, value in item.attrib.items()}
        normalized = _normalize_freeway_camera(attrs, value_map.get(str(attrs.get("cctvid") or "").strip()))
        if normalized:
            cameras.append(normalized)
    return cameras


async def _load_freeway_cameras_from_twipcam() -> list[dict[str, Any]]:
    data = await _fetch_json(TWIPCAM_CAM_LIST_URL)
    cameras = []
    for item in _unwrap_json_list(data):
        if not isinstance(item, dict):
            continue
        normalized = _normalize_twipcam_freeway_camera(item)
        if normalized:
            cameras.append(normalized)

    if not cameras:
        raise HTTPException(status_code=502, detail="twipcam public cam-list API returned no freeway cameras")
    return cameras


async def _load_all_cameras() -> list[dict[str, Any]]:
    loaders = {
        "freeway": _load_freeway_cameras,
        "thb": _load_thb_cameras,
        "taichung": _load_taichung_cameras,
        "tainan": _load_tainan_cameras,
        "keelung": _load_keelung_cameras,
    }
    results = await asyncio.gather(
        *(loader() for loader in loaders.values()),
        return_exceptions=True,
    )
    cameras: list[dict[str, Any]] = []

    for provider, result in zip(loaders, results):
        if isinstance(result, Exception):
            error_text = str(getattr(result, "detail", "")) or str(result)
            logger.warning("%s camera source unavailable: %s", provider, error_text)
            _set_provider_runtime_status(
                provider,
                available=False,
                count=0,
                error=error_text,
            )
            continue
        _set_provider_runtime_status(
            provider,
            available=True,
            count=len(result),
            error=None,
        )
        cameras.extend(result)

    return cameras


async def _get_cached_cameras(force_refresh: bool = False) -> list[dict[str, Any]]:
    now = time.time()
    if not force_refresh and _camera_cache["expires_at"] > now and _camera_cache["items"]:
        return list(_camera_cache["items"])

    async with _cache_lock:
        now = time.time()
        if not force_refresh and _camera_cache["expires_at"] > now and _camera_cache["items"]:
            return list(_camera_cache["items"])

        items = await _load_all_cameras()
        _camera_cache["items"] = items
        _camera_cache["expires_at"] = now + max(30, CAMERA_MAP_CACHE_TTL)
        return list(items)


async def _resolve_taichung_stream(camera: dict[str, Any]) -> dict[str, Any]:
    detail_url = str(camera.get("detail_url") or "").strip()
    if not detail_url:
        return camera

    cache_key = camera["id"]
    cached = _detail_cache.get(cache_key)
    if cached and cached.get("expires_at", 0) > time.time():
        return {**camera, **cached["payload"]}

    try:
        html = await _fetch_text(detail_url)
    except HTTPException as exc:
        logger.warning("Taichung camera detail fetch failed for %s: %s", detail_url, getattr(exc, "detail", exc))
        return camera

    match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', html, flags=re.IGNORECASE)
    resolved_url = urljoin(detail_url, match.group(1)) if match else ""

    payload = {
        "preview_url": resolved_url or None,
        "stream_url": resolved_url or None,
    }
    _detail_cache[cache_key] = {
        "expires_at": time.time() + max(60, CAMERA_MAP_CACHE_TTL),
        "payload": payload,
    }
    return {**camera, **payload}


async def _resolve_camera_detail(camera: dict[str, Any]) -> dict[str, Any]:
    provider = camera.get("provider")
    if provider == "taichung":
        return await _resolve_taichung_stream(camera)
    return camera


def _filter_cameras(
    cameras: list[dict[str, Any]],
    provider: str,
    bounds: Optional[dict[str, float]],
) -> list[dict[str, Any]]:
    filtered = []
    for camera in cameras:
        if provider != "all" and camera.get("provider") != provider:
            continue
        if not _is_within_bounds(camera, bounds):
            continue
        filtered.append(camera)
    return filtered


def _summarize_providers(cameras: list[dict[str, Any]]) -> dict[str, Any]:
    summary = {}
    for provider, meta in _PROVIDER_CATALOG.items():
        runtime = _provider_runtime_status.get(provider, {})
        summary[provider] = {
            "name": meta["name"],
            "short_name": meta["short_name"],
            "scope": meta["scope"],
            "source_page": meta["source_page"],
            "license_name": meta["license_name"],
            "count": 0,
            "available": runtime.get("available", True),
            "last_error": runtime.get("last_error"),
            "updated_at": runtime.get("updated_at"),
        }

    for camera in cameras:
        provider = camera.get("provider")
        if provider in summary:
            summary[provider]["count"] += 1
    return summary


@router.get("/status")
async def camera_map_status():
    """Report the currently configured Taiwan public camera sources."""
    cameras = await _get_cached_cameras()
    notes = [
        "Only public or licensed camera sources are aggregated.",
        "Phylax does not scan the internet for arbitrary IP cameras.",
        "Coverage focuses on free Taiwan public cameras and expands provider by provider.",
        "National freeway coverage uses official free endpoints first and falls back to twipcam's public camera API when needed.",
    ]
    return {
        "mode": "public_camera_registry",
        "country": "Taiwan",
        "total_count": len(cameras),
        "providers": _summarize_providers(cameras),
        "notes": notes,
    }


@router.get("/cameras")
async def list_public_cameras(
    provider: str = Query("all"),
    north_lat: Optional[float] = Query(None, alias="northLat", ge=-90, le=90),
    east_lon: Optional[float] = Query(None, alias="eastLon", ge=-180, le=180),
    south_lat: Optional[float] = Query(None, alias="southLat", ge=-90, le=90),
    west_lon: Optional[float] = Query(None, alias="westLon", ge=-180, le=180),
    force_refresh: bool = Query(False, alias="forceRefresh"),
):
    bounds = None
    if None not in {north_lat, east_lon, south_lat, west_lon}:
        if south_lat > north_lat:
            raise HTTPException(status_code=400, detail="southLat must be <= northLat")
        bounds = {
            "north_lat": float(north_lat),
            "east_lon": float(east_lon),
            "south_lat": float(south_lat),
            "west_lon": float(west_lon),
        }

    cameras = await _get_cached_cameras(force_refresh=force_refresh)
    filtered = _filter_cameras(cameras, provider, bounds)
    return {
        "mode": "public_camera_registry",
        "provider": provider,
        "count": len(filtered),
        "cameras": filtered,
    }


@router.get("/cameras/{provider}/{source_id}")
async def get_public_camera_detail(provider: str, source_id: str):
    cameras = await _get_cached_cameras()
    camera = next(
        (
            item for item in cameras
            if item.get("provider") == provider and str(item.get("source_id")) == source_id
        ),
        None,
    )
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")

    resolved = await _resolve_camera_detail(camera)
    return {
        "mode": "public_camera_registry",
        "camera": resolved,
    }
