"""
Cameras Router — API for configuring IP cameras and streaming output.
"""

from __future__ import annotations

import json
import asyncio
import re
import hashlib
import shutil
from io import BytesIO
from typing import Optional, List, Any
from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse, Response
from pathlib import Path

from config import (
    CAMERA_AI_DEFAULT_ENABLED,
    CAMERA_DVR_SECONDS,
    CAMERA_DVR_FPS,
    CAMERA_REVIEW_BUFFER_SIZE,
    FRAME_DIR,
)
from database import get_db
from services.camera_service import (
    start_camera,
    stop_camera,
    generate_mjpeg_stream,
    set_camera_ai_state,
    set_camera_analysis_language,
    request_camera_backfill,
)
from services.camera_qa_service import answer_camera_question, _build_camera_timeline_rows
from services.report_service import build_investigation_report_pdf
from models.schemas import AnalysisEventOut, InvestigationReportRequest, VideoQuestionRequest, VideoQuestionResponseOut
from services.ai_service import translate_event_texts

router = APIRouter(prefix="/api/cameras", tags=["cameras"])

class CameraCreate(BaseModel):
    name: str
    stream_url: str
    ai_enabled: bool = CAMERA_AI_DEFAULT_ENABLED

class CameraReviewOut(BaseModel):
    id: int
    camera_id: int
    timestamp_sec: float
    description: str
    event_type: str = "none"
    severity: str = "Normal"
    summary: str = ""
    changes_detected: List[str] = Field(default_factory=list)
    anomaly_score: int = 0
    requires_attention: bool = False
    frame_observation: Optional[str] = None
    temporal_assessment: Optional[str] = None
    anomaly_rationale: Optional[str] = None
    keywords: List[str] = Field(default_factory=list)
    created_at: str
    is_waived: bool = True
    is_error: bool = False

class CameraOut(BaseModel):
    id: int
    name: str
    stream_url: str
    is_active: bool
    ai_enabled: bool
    created_at: str
    current_analyzing_ts: Optional[float] = None
    analysis_inflight: bool = False
    adaptive_interval: Optional[float] = None
    last_analysis_duration: Optional[float] = None
    last_motion_score: Optional[int] = None
    waived_count: int = 0
    last_waived_ts: Optional[float] = None
    last_waived_summary: Optional[str] = None
    last_waived_event_type: Optional[str] = None
    last_waived_severity: Optional[str] = None
    recent_ai_reviews: List[CameraReviewOut] = Field(default_factory=list)
    last_ai_review_ts: Optional[float] = None
    last_ai_review_summary: Optional[str] = None
    last_ai_review_event_type: Optional[str] = None
    last_ai_review_severity: Optional[str] = None
    last_ai_review_is_waived: bool = False
    last_ai_review_is_error: bool = False
    last_ai_error: Optional[str] = None
    last_ai_error_ts: Optional[float] = None

class CameraAIToggle(BaseModel):
    enabled: bool

class CameraLanguagePreference(BaseModel):
    language: str = Field(..., min_length=2, max_length=12)

class CameraUpdate(BaseModel):
    name: Optional[str] = None
    stream_url: Optional[str] = None


def _review_row_to_out(row) -> dict:
    payload = _parse_raw_payload(row["raw_json"])
    changes_detected = payload.get("changes_detected")
    if not isinstance(changes_detected, list):
        changes_detected = []
    keywords = payload.get("keywords")
    if not isinstance(keywords, list):
        keywords = [item.strip() for item in str(row["keywords"] or "").split(",") if item.strip()]
    return {
        "id": row["id"],
        "camera_id": row["camera_id"],
        "timestamp_sec": row["timestamp_sec"],
        "description": row["description"],
        "event_type": row["event_type"] or "none",
        "severity": row["severity"] or "Normal",
        "summary": row["summary"] or "",
        "changes_detected": [str(item) for item in changes_detected[:6] if str(item).strip()],
        "anomaly_score": _coerce_int(payload.get("anomaly_score"), 0, 100),
        "requires_attention": bool(payload.get("requires_attention", False)),
        "frame_observation": str(payload.get("frame_observation") or payload.get("scene_description") or "").strip() or None,
        "temporal_assessment": str(payload.get("temporal_assessment") or "").strip() or None,
        "anomaly_rationale": str(payload.get("anomaly_rationale") or "").strip() or None,
        "keywords": [str(item) for item in keywords[:8] if str(item).strip()],
        "created_at": row["created_at"],
        "is_waived": bool(row["is_waived"]),
        "is_error": bool(row["is_error"]),
    }


def _parse_raw_payload(raw_json: Optional[str]) -> dict:
    if not raw_json:
        return {}
    try:
        parsed = json.loads(raw_json)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def _parse_json_list(raw_value: Optional[str]) -> list:
    if not raw_value:
        return []
    try:
        parsed = json.loads(raw_value)
        if isinstance(parsed, list):
            return [str(item) for item in parsed if str(item).strip()]
    except (TypeError, json.JSONDecodeError):
        pass
    return [item.strip() for item in str(raw_value).split(",") if item.strip()]


def _coerce_int(value, min_value: int, max_value: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = min_value
    return max(min_value, min(max_value, number))


def _collect_camera_artifact_paths(rows: list, camera_id: int) -> set[Path]:
    paths: set[Path] = set()
    for row in rows:
        frame_path = row["frame_path"] if "frame_path" in row.keys() else None
        paths.update(_resolve_camera_artifact_path(frame_path, camera_id))
        payload = _parse_raw_payload(row["raw_json"] if "raw_json" in row.keys() else None)
        paths.update(_extract_artifact_paths_from_payload(payload, camera_id))
    return paths


def _extract_artifact_paths_from_payload(value: Any, camera_id: int) -> set[Path]:
    paths: set[Path] = set()
    if isinstance(value, dict):
        for item in value.values():
            paths.update(_extract_artifact_paths_from_payload(item, camera_id))
    elif isinstance(value, list):
        for item in value:
            paths.update(_extract_artifact_paths_from_payload(item, camera_id))
    elif isinstance(value, str):
        paths.update(_resolve_camera_artifact_path(value, camera_id))
    return paths


def _resolve_camera_artifact_path(value: Optional[str], camera_id: int) -> set[Path]:
    if not value:
        return set()

    raw = str(value).strip()
    if not _looks_like_camera_artifact_path(raw, camera_id):
        return set()

    candidates = []
    camera_prefix = f"/frames/cam_{camera_id}/"
    if raw.startswith(camera_prefix):
        candidates.append(FRAME_DIR / f"cam_{camera_id}" / raw[len(camera_prefix):])
    elif raw.startswith("/frames/qa_crops/"):
        qa_prefix = "/frames/qa_crops/"
        candidates.append(FRAME_DIR / "qa_crops" / raw[len(qa_prefix):])
    else:
        candidates.append(Path(raw))

    frame_root = FRAME_DIR.resolve()
    resolved = set()
    for candidate in candidates:
        try:
            path = candidate.resolve()
        except OSError:
            continue
        if path.exists() and path.is_file() and (path == frame_root or frame_root in path.parents):
            resolved.add(path)
    return resolved


def _looks_like_camera_artifact_path(value: str, camera_id: int) -> bool:
    if not value or len(value) > 512:
        return False
    if "\n" in value or "\r" in value:
        return False
    if value.lstrip().startswith(("{", "[")):
        return False
    if value.startswith((f"/frames/cam_{camera_id}/", "/frames/qa_crops/")):
        return True
    if value.startswith(("http://", "https://")):
        return False
    if "/" not in value and "\\" not in value:
        return False
    lowered = value.split("?", 1)[0].lower()
    return lowered.endswith((".jpg", ".jpeg", ".png", ".webp"))


def _remove_camera_artifacts(paths: set[Path], camera_id: int) -> dict[str, int]:
    removed_files = 0
    errors = 0
    for path in paths:
        try:
            path.unlink(missing_ok=True)
            removed_files += 1
        except OSError:
            errors += 1
            continue

    removed_dirs = 0
    camera_dir = FRAME_DIR / f"cam_{camera_id}"
    if camera_dir.exists():
        try:
            shutil.rmtree(camera_dir)
            removed_dirs += 1
        except OSError:
            errors += 1

    return {"files": removed_files, "directories": removed_dirs, "errors": errors}


async def _load_camera_review_bundle(db, camera_id: int, *, include_reviews: bool = True) -> dict:
    review_limit = max(20, CAMERA_REVIEW_BUFFER_SIZE * 3)

    reviews = []
    if include_reviews:
        review_cursor = await db.execute(
            """SELECT *
               FROM camera_ai_reviews
               WHERE camera_id=?
               ORDER BY timestamp_sec DESC, id DESC
               LIMIT ?""",
            [camera_id, review_limit],
        )
        review_rows = await review_cursor.fetchall()
        reviews = [_review_row_to_out(row) for row in review_rows]

    waived_cursor = await db.execute(
        """SELECT COUNT(*) AS count
           FROM camera_ai_reviews
           WHERE camera_id=?
             AND is_waived=1
             AND is_error=0""",
        [camera_id],
    )
    waived_count = int((await waived_cursor.fetchone())["count"] or 0)

    last_waived_cursor = await db.execute(
        """SELECT timestamp_sec, summary, event_type, severity
           FROM camera_ai_reviews
           WHERE camera_id=?
             AND is_waived=1
             AND is_error=0
           ORDER BY timestamp_sec DESC, id DESC
           LIMIT 1""",
        [camera_id],
    )
    last_waived_row = await last_waived_cursor.fetchone()

    last_error_cursor = await db.execute(
        """SELECT timestamp_sec, summary
           FROM camera_ai_reviews
           WHERE camera_id=?
             AND is_error=1
           ORDER BY timestamp_sec DESC, id DESC
           LIMIT 1""",
        [camera_id],
    )
    last_error_row = await last_error_cursor.fetchone()

    latest_review = reviews[0] if reviews else None
    if latest_review is None:
        latest_review_cursor = await db.execute(
            """SELECT *
               FROM camera_ai_reviews
               WHERE camera_id=?
               ORDER BY timestamp_sec DESC, id DESC
               LIMIT 1""",
            [camera_id],
        )
        latest_review_row = await latest_review_cursor.fetchone()
        if latest_review_row:
            latest_review = _review_row_to_out(latest_review_row)

    latest_event_cursor = await db.execute(
        """SELECT timestamp_sec, description, event_type, severity, summary, raw_json
           FROM analysis_events
           WHERE camera_id=?
           ORDER BY timestamp_sec DESC, id DESC
           LIMIT 1""",
        [camera_id],
    )
    latest_event_row = await latest_event_cursor.fetchone()

    latest_activity = latest_review
    if latest_event_row and (
        latest_activity is None
        or float(latest_event_row["timestamp_sec"] or 0) > float(latest_activity["timestamp_sec"] or 0)
    ):
        latest_activity = {
            "timestamp_sec": latest_event_row["timestamp_sec"],
            "summary": latest_event_row["summary"] or latest_event_row["description"] or "",
            "event_type": latest_event_row["event_type"] or "none",
            "severity": latest_event_row["severity"] or "Normal",
            "is_waived": False,
            "is_error": False,
        }

    return {
        "reviews": reviews,
        "waived_count": waived_count,
        "last_waived_ts": last_waived_row["timestamp_sec"] if last_waived_row else None,
        "last_waived_summary": last_waived_row["summary"] if last_waived_row else None,
        "last_waived_event_type": last_waived_row["event_type"] if last_waived_row else None,
        "last_waived_severity": last_waived_row["severity"] if last_waived_row else None,
        "last_ai_error": last_error_row["summary"] if last_error_row else None,
        "last_ai_error_ts": last_error_row["timestamp_sec"] if last_error_row else None,
        "last_ai_review_ts": latest_activity["timestamp_sec"] if latest_activity else None,
        "last_ai_review_summary": latest_activity["summary"] if latest_activity else None,
        "last_ai_review_event_type": latest_activity["event_type"] if latest_activity else None,
        "last_ai_review_severity": latest_activity["severity"] if latest_activity else None,
        "last_ai_review_is_waived": bool(latest_activity["is_waived"]) if latest_activity else False,
        "last_ai_review_is_error": bool(latest_activity["is_error"]) if latest_activity else False,
    }


def _merge_runtime_camera_state(row_dict: dict, runtime_state: dict, persisted: dict) -> dict:
    runtime_reviews = list(runtime_state.get("recent_ai_reviews", []))
    latest_runtime_review = runtime_reviews[0] if runtime_reviews else None

    row_dict["current_analyzing_ts"] = runtime_state.get("current_analyzing_ts")
    row_dict["analysis_inflight"] = bool(runtime_state.get("analysis_inflight", False))
    row_dict["adaptive_interval"] = runtime_state.get("adaptive_interval")
    row_dict["last_analysis_duration"] = runtime_state.get("last_analysis_duration")
    row_dict["last_motion_score"] = runtime_state.get("last_motion_score")

    row_dict["waived_count"] = max(
        int(runtime_state.get("waived_count") or 0),
        int(persisted.get("waived_count") or 0),
    )
    row_dict["last_waived_ts"] = runtime_state.get("last_waived_ts") or persisted.get("last_waived_ts")
    row_dict["last_waived_summary"] = runtime_state.get("last_waived_summary") or persisted.get("last_waived_summary")
    row_dict["last_waived_event_type"] = runtime_state.get("last_waived_event_type") or persisted.get("last_waived_event_type")
    row_dict["last_waived_severity"] = runtime_state.get("last_waived_severity") or persisted.get("last_waived_severity")
    row_dict["recent_ai_reviews"] = persisted.get("reviews") or runtime_reviews
    row_dict["last_ai_error"] = runtime_state.get("last_ai_error") or persisted.get("last_ai_error")
    row_dict["last_ai_error_ts"] = runtime_state.get("last_ai_error_ts") or persisted.get("last_ai_error_ts")
    row_dict["last_ai_review_ts"] = persisted.get("last_ai_review_ts") or (latest_runtime_review or {}).get("timestamp_sec")
    row_dict["last_ai_review_summary"] = persisted.get("last_ai_review_summary") or (latest_runtime_review or {}).get("summary")
    row_dict["last_ai_review_event_type"] = persisted.get("last_ai_review_event_type") or (latest_runtime_review or {}).get("event_type")
    row_dict["last_ai_review_severity"] = persisted.get("last_ai_review_severity") or (latest_runtime_review or {}).get("severity")
    row_dict["last_ai_review_is_waived"] = bool(
        persisted.get("last_ai_review_is_waived")
        or (latest_runtime_review or {}).get("is_waived")
    )
    row_dict["last_ai_review_is_error"] = bool(
        persisted.get("last_ai_review_is_error")
        or (latest_runtime_review or {}).get("is_error")
    )
    return row_dict


def _empty_camera_review_bundle() -> dict:
    return {
        "reviews": [],
        "waived_count": 0,
        "last_waived_ts": None,
        "last_waived_summary": None,
        "last_waived_event_type": None,
        "last_waived_severity": None,
        "last_ai_error": None,
        "last_ai_error_ts": None,
        "last_ai_review_ts": None,
        "last_ai_review_summary": None,
        "last_ai_review_event_type": None,
        "last_ai_review_severity": None,
        "last_ai_review_is_waived": False,
        "last_ai_review_is_error": False,
    }


def _select_replay_anchor_frames(
    state: dict,
    current_timestamp_sec: Optional[float],
    *,
    radius: int = 2,
) -> list[dict[str, Any]]:
    frames = list((state or {}).get("replay_frames") or [])
    if not frames:
        return []

    target_ts = float(current_timestamp_sec) if current_timestamp_sec is not None else float(frames[-1].get("timestamp_sec") or 0.0)
    if target_ts <= 0:
        return []

    anchor_index = min(
        range(len(frames)),
        key=lambda index: abs(float(frames[index].get("timestamp_sec") or 0.0) - target_ts),
    )
    start = max(0, anchor_index - radius)
    end = min(len(frames), anchor_index + radius + 1)
    selected = []
    seen_paths = set()
    for frame in frames[start:end]:
        path = str(frame.get("abs_path") or "").strip()
        if not path or path in seen_paths:
            continue
        seen_paths.add(path)
        selected.append(
            {
                "timestamp_sec": float(frame.get("timestamp_sec") or 0.0),
                "abs_path": path,
            }
        )
    return selected

@router.post("", response_model=CameraOut)
async def add_camera(payload: CameraCreate):
    db = await get_db()
    try:
        cursor = await db.execute(
            "INSERT INTO cameras (name, stream_url, ai_enabled) VALUES (?, ?, ?)",
            [payload.name, payload.stream_url, 1 if payload.ai_enabled else 0]
        )
        await db.commit()
        camera_id = cursor.lastrowid
        
        cursor = await db.execute("SELECT * FROM cameras WHERE id=?", [camera_id])
        row = await cursor.fetchone()
        
        # Auto-start standard behavior
        start_camera(camera_id, payload.stream_url, payload.ai_enabled)
        
        return _merge_runtime_camera_state(dict(row), {}, _empty_camera_review_bundle())
    finally:
        await db.close()

@router.get("", response_model=List[CameraOut])
async def list_cameras(language: Optional[str] = Query(None, min_length=2, max_length=12)):
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM cameras ORDER BY id DESC")
        rows = await cursor.fetchall()
        from services.camera_service import _active_cameras

        cameras = []
        normalized_language = str(language or "").strip().lower().split("-", 1)[0]
        for row in rows:
            row_dict = dict(row)
            camera_id = row_dict["id"]
            persisted = await _load_camera_review_bundle(db, camera_id, include_reviews=False)
            runtime_state = _active_cameras.get(camera_id, {})
            merged = _merge_runtime_camera_state(row_dict, runtime_state, persisted)
            if normalized_language:
                set_camera_analysis_language(camera_id, normalized_language)
                await _localize_camera_summary_fields(merged, normalized_language)
            cameras.append(merged)
        return cameras
    finally:
        await db.close()




@router.post("/{camera_id}/export")
async def export_camera_dvr(camera_id: int):
    """Dynamically stitch up to the last 2 minutes of chunks and save to DB."""
    raise HTTPException(404, "Camera DVR export is disabled.")


@router.get("/{camera_id}", response_model=CameraOut)
async def get_camera(camera_id: int, language: Optional[str] = Query(None, min_length=2, max_length=12)):
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM cameras WHERE id=?", [camera_id])
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(404, "Camera not found")
            
        row_dict = dict(row)
        from services.camera_service import _active_cameras
        state = _active_cameras.get(camera_id, {})
        persisted = await _load_camera_review_bundle(db, camera_id)
        merged = _merge_runtime_camera_state(row_dict, state, persisted)
        normalized_language = str(language or "").strip().lower().split("-", 1)[0]
        if normalized_language:
            set_camera_analysis_language(camera_id, normalized_language)
            await _localize_camera_summary_fields(merged, normalized_language)
        if normalized_language and _reviews_need_localization(merged.get("recent_ai_reviews") or [], normalized_language):
            merged["recent_ai_reviews"] = await _localize_camera_reviews(merged.get("recent_ai_reviews") or [], language)
            if merged.get("last_waived_summary") and _text_needs_localization(merged.get("last_waived_summary") or "", normalized_language):
                translated = await asyncio.to_thread(
                    translate_event_texts,
                    [{"id": "last-waived", "summary": merged["last_waived_summary"], "description": ""}],
                    language,
                    normalized_language == "en",
                )
                if translated:
                    merged["last_waived_summary"] = str(translated[0].get("summary") or merged["last_waived_summary"])
        return merged
    finally:
        await db.close()

@router.put("/{camera_id}/ai", response_model=CameraOut)
async def toggle_camera_ai(camera_id: int, payload: CameraAIToggle):
    db = await get_db()
    try:
        cursor = await db.execute("SELECT id FROM cameras WHERE id=?", [camera_id])
        if not await cursor.fetchone():
            raise HTTPException(404, "Camera not found")
            
        await db.execute(
            "UPDATE cameras SET ai_enabled=? WHERE id=?", 
            [1 if payload.enabled else 0, camera_id]
        )
        await db.commit()
        
        # Dynamically push to the running background thread state
        set_camera_ai_state(camera_id, payload.enabled)
        
        # Return updated state
        cursor = await db.execute("SELECT * FROM cameras WHERE id=?", [camera_id])
        row = await cursor.fetchone()
        from services.camera_service import _active_cameras
        persisted = await _load_camera_review_bundle(db, camera_id)
        return _merge_runtime_camera_state(dict(row), _active_cameras.get(camera_id, {}), persisted)
    finally:
        await db.close()


@router.put("/{camera_id}/language")
async def update_camera_analysis_language(camera_id: int, payload: CameraLanguagePreference):
    db = await get_db()
    try:
        cursor = await db.execute("SELECT id FROM cameras WHERE id=?", [camera_id])
        if not await cursor.fetchone():
            raise HTTPException(404, "Camera not found")
        language = set_camera_analysis_language(camera_id, payload.language)
        return {"camera_id": camera_id, "language": language}
    finally:
        await db.close()


@router.post("/{camera_id}/analyze_recent")
async def analyze_recent_camera_window(camera_id: int):
    db = await get_db()
    try:
        cursor = await db.execute("SELECT id FROM cameras WHERE id=?", [camera_id])
        if not await cursor.fetchone():
            raise HTTPException(404, "Camera not found")
    finally:
        await db.close()

    if not request_camera_backfill(camera_id):
        raise HTTPException(409, "Camera AI must be active and stream ready before backfill can run")

    return {"detail": "Recent camera backfill queued", "camera_id": camera_id}


@router.post("/{camera_id}/ask", response_model=VideoQuestionResponseOut)
async def ask_camera_question_route(camera_id: int, body: VideoQuestionRequest):
    db = await get_db()
    try:
        camera_cursor = await db.execute("SELECT * FROM cameras WHERE id=?", [camera_id])
        camera_row = await camera_cursor.fetchone()
        if not camera_row:
            raise HTTPException(404, "Camera not found")

        event_cursor = await db.execute(
            """SELECT id, timestamp_sec, frame_path, description, event_type,
                      severity, diff_description, summary, keywords, raw_json
               FROM analysis_events
               WHERE camera_id=?
                 AND timestamp_sec >= (strftime('%s','now') - ?)
               ORDER BY timestamp_sec ASC, id ASC
               LIMIT 240""",
            [camera_id, CAMERA_DVR_SECONDS * 2],
        )
        event_rows = await event_cursor.fetchall()

        review_cursor = await db.execute(
            """SELECT id, camera_id, timestamp_sec, frame_path, description, event_type,
                      severity, summary, keywords, raw_json, is_waived, is_error, created_at
               FROM camera_ai_reviews
               WHERE camera_id=?
                 AND timestamp_sec >= (strftime('%s','now') - ?)
               ORDER BY timestamp_sec ASC, id ASC
               LIMIT 240""",
            [camera_id, CAMERA_DVR_SECONDS * 2],
        )
        review_rows = await review_cursor.fetchall()
    finally:
        await db.close()

    from services.camera_service import _active_cameras

    state = _active_cameras.get(camera_id, {})
    anchor_frames = _select_replay_anchor_frames(state, body.current_timestamp_sec)
    history = [
        {
            "role": turn.role,
            "content": turn.content,
            "confidence": turn.confidence,
            "relevant_events": turn.relevant_events,
            "reconstruction": turn.reconstruction,
        }
        for turn in body.history
    ]

    response = await asyncio.to_thread(
        answer_camera_question,
        dict(camera_row),
        [dict(row) for row in event_rows],
        [dict(row) for row in review_rows],
        question=body.question,
        language=body.language,
        current_timestamp_sec=body.current_timestamp_sec,
        history=history,
        live_frame_path=(state.get("latest_analysis_frame") or {}).get("abs_path"),
        anchor_frames=anchor_frames,
    )
    return VideoQuestionResponseOut(**response)


@router.post("/{camera_id}/report")
async def export_camera_investigation_report(camera_id: int, body: InvestigationReportRequest):
    """Render a PDF investigation report from the current camera QA session."""
    db = await get_db()
    try:
        camera_cursor = await db.execute("SELECT * FROM cameras WHERE id=?", [camera_id])
        camera_row = await camera_cursor.fetchone()
        if not camera_row:
            raise HTTPException(404, "Camera not found")

        event_cursor = await db.execute(
            """SELECT id, timestamp_sec, frame_path, description, event_type,
                      severity, summary, keywords, raw_json
               FROM analysis_events
               WHERE camera_id=?
                 AND timestamp_sec >= (strftime('%s','now') - ?)
               ORDER BY timestamp_sec ASC, id ASC
               LIMIT 240""",
            [camera_id, CAMERA_DVR_SECONDS * 2],
        )
        event_rows = await event_cursor.fetchall()

        review_cursor = await db.execute(
            """SELECT id, camera_id, timestamp_sec, frame_path, description, event_type,
                      severity, summary, keywords, raw_json, is_waived, is_error, created_at
               FROM camera_ai_reviews
               WHERE camera_id=?
                 AND timestamp_sec >= (strftime('%s','now') - ?)
               ORDER BY timestamp_sec ASC, id ASC
               LIMIT 240""",
            [camera_id, CAMERA_DVR_SECONDS * 2],
        )
        review_rows = await review_cursor.fetchall()
    finally:
        await db.close()

    from services.camera_service import _active_cameras

    state = _active_cameras.get(camera_id, {})
    combined_rows = _build_camera_timeline_rows(
        [dict(row) for row in event_rows],
        [dict(row) for row in review_rows],
        live_frame_path=(state.get("latest_analysis_frame") or {}).get("abs_path"),
    )

    report_bytes = await asyncio.to_thread(
        build_investigation_report_pdf,
        language=body.language or "en",
        resource_kind="camera",
        resource_title=str(camera_row["name"] or f"Camera {camera_id}"),
        scope_summary=f"Camera #{camera_id} | recent {CAMERA_DVR_SECONDS // 60} minute review window",
        current_timestamp_sec=body.current_timestamp_sec,
        messages=[message.model_dump() for message in body.messages],
        timeline_rows=combined_rows,
    )

    filename = f"phylax-investigation-camera-{camera_id}.pdf"
    return StreamingResponse(
        BytesIO(report_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

@router.put("/{camera_id}", response_model=CameraOut)
async def update_camera(camera_id: int, payload: CameraUpdate):
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM cameras WHERE id=?", [camera_id])
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(404, "Camera not found")

        current = dict(row)
        new_name = payload.name.strip() if payload.name is not None else current["name"]
        new_stream_url = payload.stream_url.strip() if payload.stream_url is not None else current["stream_url"]

        if not new_name:
            raise HTTPException(400, "Camera name cannot be empty")
        if not new_stream_url:
            raise HTTPException(400, "Camera stream URL cannot be empty")

        await db.execute(
            "UPDATE cameras SET name=?, stream_url=? WHERE id=?",
            [new_name, new_stream_url, camera_id]
        )
        await db.commit()

        # Restart the capture worker if the stream URL changed.
        if new_stream_url != current["stream_url"]:
            stop_camera(camera_id)
            start_camera(camera_id, new_stream_url, bool(current["ai_enabled"]))

        cursor = await db.execute("SELECT * FROM cameras WHERE id=?", [camera_id])
        updated_row = await cursor.fetchone()
        from services.camera_service import _active_cameras
        persisted = await _load_camera_review_bundle(db, camera_id)
        return _merge_runtime_camera_state(dict(updated_row), _active_cameras.get(camera_id, {}), persisted)
    finally:
        await db.close()

@router.delete("/{camera_id}")
async def delete_camera(camera_id: int):
    stop_camera(camera_id)
    await asyncio.sleep(0.2)
    
    db = await get_db()
    removed = {"files": 0, "directories": 0, "errors": 0}
    try:
        cursor = await db.execute("SELECT id FROM cameras WHERE id=?", [camera_id])
        if not await cursor.fetchone():
            raise HTTPException(404, "Camera not found")

        artifact_paths: set[Path] = set()
        event_cursor = await db.execute(
            "SELECT frame_path, raw_json FROM analysis_events WHERE camera_id=?",
            [camera_id],
        )
        event_rows = await event_cursor.fetchall()
        review_cursor = await db.execute(
            "SELECT frame_path, raw_json FROM camera_ai_reviews WHERE camera_id=?",
            [camera_id],
        )
        review_rows = await review_cursor.fetchall()
        artifact_paths = _collect_camera_artifact_paths([*event_rows, *review_rows], camera_id)

        await db.execute("DELETE FROM analysis_events WHERE camera_id=?", [camera_id])
        await db.execute("DELETE FROM camera_ai_reviews WHERE camera_id=?", [camera_id])
        await db.execute("DELETE FROM cameras WHERE id=?", [camera_id])
        await db.commit()

        removed = await asyncio.to_thread(_remove_camera_artifacts, artifact_paths, camera_id)
        return {
            "detail": "Camera removed",
            "camera_id": camera_id,
            "removed_files": removed["files"],
            "removed_directories": removed["directories"],
            "cleanup_errors": removed["errors"],
        }
    except HTTPException:
        raise
    except Exception as exc:
        await db.rollback()
        raise HTTPException(500, f"Failed to remove camera: {exc}") from exc
    finally:
        await db.close()

@router.get("/{camera_id}/stream")
async def stream_camera(
    camera_id: int,
    fps: int = Query(30, ge=1, le=30),
):
    """Streams MJPEG frames directly from the active background cv2 parser."""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT id FROM cameras WHERE id=?", [camera_id])
        if not await cursor.fetchone():
            raise HTTPException(404, "Camera not found")
    finally:
        await db.close()
        
    return StreamingResponse(
        generate_mjpeg_stream(camera_id, fps=fps),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )

@router.get("/{camera_id}/snapshot")
async def camera_snapshot(camera_id: int):
    """Return the latest single JPEG frame for lightweight dashboard previews."""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT id FROM cameras WHERE id=?", [camera_id])
        if not await cursor.fetchone():
            raise HTTPException(404, "Camera not found")
    finally:
        await db.close()

    from services.camera_service import _active_cameras
    state = _active_cameras.get(camera_id)
    if not state or not state.get("frame_bytes"):
        raise HTTPException(404, "Camera preview not ready")

    return Response(content=state["frame_bytes"], media_type="image/jpeg")


@router.get("/{camera_id}/buffer")
async def camera_replay_buffer(camera_id: int):
    """Return rolling replay metadata for the recent camera buffer."""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT id FROM cameras WHERE id=?", [camera_id])
        if not await cursor.fetchone():
            raise HTTPException(404, "Camera not found")
    finally:
        await db.close()

    from services.camera_service import _active_cameras
    state = _active_cameras.get(camera_id)
    if not state:
        raise HTTPException(404, "Camera stream not active")

    frames = [
        {
            "timestamp_sec": item["timestamp_sec"],
            "url": item["url"],
        }
        for item in state.get("replay_frames", [])
    ]

    return {
        "camera_id": camera_id,
        "window_seconds": CAMERA_DVR_SECONDS,
        "fps": CAMERA_DVR_FPS,
        "frames": frames,
        "latest_timestamp_sec": frames[-1]["timestamp_sec"] if frames else None,
    }

@router.get("/{camera_id}/events", response_model=List[AnalysisEventOut])
async def get_camera_events(
    camera_id: int,
    limit: int = 50,
    window_seconds: Optional[int] = Query(None, ge=1, le=3600),
    language: Optional[str] = Query(None, min_length=2, max_length=12),
):
    """Get recent events for a specific camera."""
    db = await get_db()
    try:
        filters = ["camera_id=?"]
        params = [camera_id]

        if window_seconds is not None:
            filters.append("timestamp_sec >= (strftime('%s','now') - ?)")
            params.append(window_seconds)

        cursor = await db.execute(
            f"""SELECT * FROM analysis_events
               WHERE {' AND '.join(filters)}
               ORDER BY timestamp_sec DESC, id DESC LIMIT ?""",
            params + [limit],
        )
        rows = await cursor.fetchall()
        from routers.analysis import _localize_event_outputs, _row_to_event
        events = [_row_to_event(r) for r in rows]
        return await _localize_event_outputs(events, language)
    finally:
        await db.close()


async def _localize_camera_reviews(reviews: List[dict], language: Optional[str]) -> List[dict]:
    normalized_language = str(language or "").strip().lower().split("-", 1)[0]
    if normalized_language == "" or not reviews:
        return reviews

    translatable_reviews = [
        (index, review) for index, review in enumerate(reviews)
        if _review_needs_localization(review, normalized_language)
    ]
    if not translatable_reviews:
        return reviews

    cached_by_id = await _load_localized_review_cache(translatable_reviews, normalized_language)
    items = [
        {
            "id": str(review.get("id") or index),
            "summary": str(review.get("summary") or ""),
            "description": "\n".join(
                part for part in [
                    str(review.get("description") or ""),
                    f"[[frame_observation]] {review.get('frame_observation')}" if review.get("frame_observation") else "",
                    f"[[temporal_assessment]] {review.get('temporal_assessment')}" if review.get("temporal_assessment") else "",
                    f"[[anomaly_rationale]] {review.get('anomaly_rationale')}" if review.get("anomaly_rationale") else "",
                    "\n".join(
                        f"[[change]] {item}" for item in (review.get("changes_detected") or []) if str(item).strip()
                    ),
                ] if part
            ),
        }
        for index, review in translatable_reviews
        if str(review.get("id") or index) not in cached_by_id
    ]

    translated_by_id = dict(cached_by_id)
    if items:
        translated = await asyncio.to_thread(
            translate_event_texts,
            items,
            normalized_language,
            normalized_language == "en",
        )
        translated_by_id.update({str(item.get("id")): item for item in translated})

    from routers.analysis import _parse_translated_event_text

    localized = []
    cache_payloads = {}
    reviews_by_id = {str(review.get("id") or index): review for index, review in enumerate(reviews)}
    for index, review in enumerate(reviews):
        translated_item = translated_by_id.get(str(review.get("id") or index))
        if not translated_item:
            localized.append(review)
            continue
        parsed = _parse_translated_event_text(str(translated_item.get("description") or review.get("description") or ""))
        payload = {
            "summary": str(translated_item.get("summary") or review.get("summary") or ""),
            "description": parsed["description"] or review.get("description") or "",
            "frame_observation": parsed["frame_observation"] or review.get("frame_observation"),
            "temporal_assessment": parsed["temporal_assessment"] or review.get("temporal_assessment"),
            "anomaly_rationale": parsed["anomaly_rationale"] or review.get("anomaly_rationale"),
            "changes_detected": parsed["changes_detected"] or review.get("changes_detected") or [],
        }
        if not _review_payload_needs_cleanup(payload, normalized_language):
            cache_payloads[str(review.get("id") or index)] = payload
        localized.append({**review, **payload})
    if cache_payloads:
        await _store_localized_review_cache(reviews_by_id, cache_payloads, normalized_language)
    return localized


async def _load_localized_review_cache(review_pairs: List[tuple[int, dict]], language: str) -> dict[str, dict]:
    db = await get_db()
    try:
        output = {}
        for index, review in review_pairs:
            review_id = str(review.get("id") or index)
            cursor = await db.execute(
                """SELECT source_hash, summary, description, frame_observation,
                          temporal_assessment, anomaly_rationale, changes_json
                   FROM localized_event_texts
                   WHERE source_kind='camera_review' AND source_id=? AND language=?""",
                [int(review.get("id") or index), language],
            )
            row = await cursor.fetchone()
            if not row or row["source_hash"] != _review_source_hash(review):
                continue
            payload = {
                "summary": row["summary"] or "",
                "description": row["description"] or "",
                "frame_observation": row["frame_observation"] or "",
                "temporal_assessment": row["temporal_assessment"] or "",
                "anomaly_rationale": row["anomaly_rationale"] or "",
                "changes_detected": _parse_json_list(row["changes_json"]),
            }
            if _review_payload_needs_cleanup(payload, language):
                continue
            output[review_id] = {
                "id": review_id,
                "summary": payload["summary"],
                "description": _compose_cached_review_text(payload),
            }
        return output
    finally:
        await db.close()


async def _store_localized_review_cache(reviews_by_id: dict[str, dict], payloads: dict[str, dict], language: str) -> None:
    db = await get_db()
    try:
        for review_id, payload in payloads.items():
            review = reviews_by_id.get(review_id)
            if not review:
                continue
            await db.execute(
                """INSERT OR REPLACE INTO localized_event_texts
                   (source_kind, source_id, language, source_hash, summary, description,
                    frame_observation, temporal_assessment, anomaly_rationale, changes_json, updated_at)
                   VALUES ('camera_review', ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
                [
                    int(review.get("id") or 0),
                    language,
                    _review_source_hash(review),
                    payload.get("summary") or "",
                    payload.get("description") or "",
                    payload.get("frame_observation") or "",
                    payload.get("temporal_assessment") or "",
                    payload.get("anomaly_rationale") or "",
                    json.dumps(payload.get("changes_detected") or [], ensure_ascii=False),
                ],
            )
        await db.commit()
    finally:
        await db.close()


def _review_source_hash(review: dict) -> str:
    payload = {
        "summary": str(review.get("summary") or ""),
        "description": str(review.get("description") or ""),
        "frame_observation": str(review.get("frame_observation") or ""),
        "temporal_assessment": str(review.get("temporal_assessment") or ""),
        "anomaly_rationale": str(review.get("anomaly_rationale") or ""),
        "changes_detected": review.get("changes_detected") or [],
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _review_payload_needs_cleanup(payload: dict, language: str) -> bool:
    text = " ".join(
        part for part in [
            str(payload.get("summary") or ""),
            str(payload.get("description") or ""),
            str(payload.get("frame_observation") or ""),
            str(payload.get("temporal_assessment") or ""),
            str(payload.get("anomaly_rationale") or ""),
            " ".join(str(item) for item in payload.get("changes_detected") or []),
        ] if part
    )
    return _text_needs_localization(text, language)


def _compose_cached_review_text(payload: dict) -> str:
    parts = [str(payload.get("description") or "")]
    if payload.get("frame_observation"):
        parts.append(f"[[frame_observation]] {payload['frame_observation']}")
    if payload.get("temporal_assessment"):
        parts.append(f"[[temporal_assessment]] {payload['temporal_assessment']}")
    if payload.get("anomaly_rationale"):
        parts.append(f"[[anomaly_rationale]] {payload['anomaly_rationale']}")
    for change in payload.get("changes_detected") or []:
        if change:
            parts.append(f"[[change]] {change}")
    return "\n".join(part for part in parts if part)


async def _localize_camera_summary_fields(camera: dict, language: str) -> None:
    fields = [
        "last_ai_review_summary",
        "last_waived_summary",
    ]
    items = []
    field_by_id = {}
    for field in fields:
        value = str(camera.get(field) or "").strip()
        if not value or not _text_needs_localization(value, language):
            continue
        item_id = field
        field_by_id[item_id] = field
        items.append({"id": item_id, "summary": value, "description": ""})

    if not items:
        return

    translated = await asyncio.to_thread(
        translate_event_texts,
        items,
        language,
        language == "en",
    )
    for item in translated:
        field = field_by_id.get(str(item.get("id") or ""))
        if field:
            camera[field] = str(item.get("summary") or camera.get(field) or "")


def _reviews_need_localization(reviews: List[dict], language: str) -> bool:
    return any(_review_needs_localization(review, language) for review in reviews)


def _review_needs_localization(review: dict, language: str) -> bool:
    text = " ".join(
        part for part in [
            str(review.get("summary") or ""),
            str(review.get("description") or ""),
            str(review.get("frame_observation") or ""),
            str(review.get("temporal_assessment") or ""),
            str(review.get("anomaly_rationale") or ""),
            " ".join(str(item) for item in review.get("changes_detected") or []),
            " ".join(str(item) for item in review.get("keywords") or []),
        ] if part
    )
    return _text_needs_localization(text, language)


def _text_needs_localization(text: str, language: str) -> bool:
    value = str(text or "")
    if not value.strip():
        return False
    if language == "en":
        return _contains_cjk_text(value)
    if language in {"zh", "ja", "ko"}:
        return _text_needs_cjk_language_cleanup(value, language)
    if language in {"es", "fr"}:
        return _text_needs_latin_language_cleanup(value, language)
    return _contains_cjk_text(value)


def _contains_cjk_text(text: str) -> bool:
    return bool(re.search(r"[\u3400-\u4dbf\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]", str(text or "")))


def _contains_han_text(text: str) -> bool:
    return bool(re.search(r"[\u3400-\u4dbf\u4e00-\u9fff]", str(text or "")))


def _contains_kana_text(text: str) -> bool:
    return bool(re.search(r"[\u3040-\u30ff]", str(text or "")))


def _contains_hangul_text(text: str) -> bool:
    return bool(re.search(r"[\uac00-\ud7af]", str(text or "")))


def _text_needs_cjk_language_cleanup(text: str, language: str) -> bool:
    value = str(text or "")
    has_english = bool(re.search(r"[A-Za-z]{2,}", value))
    if language == "zh":
        return has_english or _contains_kana_text(value) or _contains_hangul_text(value) or not _contains_han_text(value)
    if language == "ja":
        return has_english or _contains_hangul_text(value) or not (_contains_han_text(value) or _contains_kana_text(value))
    if language == "ko":
        return has_english or _contains_kana_text(value) or not _contains_hangul_text(value)
    return has_english


def _text_needs_latin_language_cleanup(text: str, language: str) -> bool:
    value = str(text or "")
    if _contains_cjk_text(value):
        return True
    ascii_words = re.findall(r"\b[A-Za-z]{3,}\b", value)
    if not ascii_words:
        return False

    common_english = {
        "the", "this", "that", "with", "without", "traffic", "vehicle", "vehicles",
        "routine", "normal", "highway", "road", "flow", "continues", "stable",
        "observed", "scene", "frame", "previous", "results", "score", "rationale",
        "moderate", "heavy", "entrance", "intersection", "interchange",
    }
    if language == "es":
        target_markers = {
            "el", "la", "los", "las", "un", "una", "con", "sin", "tráfico",
            "vehículo", "vehículos", "carretera", "flujo", "normal", "estable",
            "observado", "continúa", "entrada", "intersección",
        }
    elif language == "fr":
        target_markers = {
            "le", "la", "les", "un", "une", "des", "avec", "sans", "trafic",
            "véhicule", "véhicules", "route", "flux", "normal", "stable",
            "observé", "continue", "entrée", "intersection",
        }
    else:
        target_markers = set()

    lowered = {word.lower() for word in ascii_words}
    english_hits = lowered & common_english
    target_hits = lowered & target_markers
    return bool(english_hits and not target_hits)
