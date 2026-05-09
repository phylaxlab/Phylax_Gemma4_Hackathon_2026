"""
Analysis Router — Triggers and monitors AI-powered video analysis.
Runs frame extraction + Gemma4 analysis as background tasks.
"""

from __future__ import annotations

import json
import logging
import re
import hashlib
import asyncio
from collections import deque
from io import BytesIO
from typing import List, Optional

from fastapi import APIRouter, HTTPException, BackgroundTasks, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from database import get_db
from config import FRAME_ANALYSIS_INTERVAL
from services.video_service import extract_frames, estimate_motion_score
from services.ai_service import analyze_frames, build_timeline_story_entry, translate_event_texts
from services.video_qa_service import answer_video_question
from services.report_service import build_investigation_report_pdf
from models.schemas import (
    AnalysisEventOut,
    AnalysisStartOptions,
    AnalysisStatusOut,
    InvestigationReportRequest,
    VideoQuestionRequest,
    VideoQuestionResponseOut,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/analysis", tags=["analysis"])

# Track running analysis tasks to prevent duplicates
_running_analyses = set()


class EventTranslationItem(BaseModel):
    id: str
    summary: str = ""
    description: str = ""


class EventTranslationRequest(BaseModel):
    target_language: str = Field(..., min_length=2, max_length=12)
    items: List[EventTranslationItem] = Field(default_factory=list, max_length=40)


@router.post("/translate-events")
async def translate_events(body: EventTranslationRequest):
    if not body.items:
        return {"target_language": body.target_language, "items": []}

    translated = await asyncio.to_thread(
        translate_event_texts,
        [item.dict() for item in body.items],
        body.target_language,
    )
    return {"target_language": body.target_language, "items": translated}


@router.post("/start/{video_id}")
async def start_analysis(
    video_id: int,
    background_tasks: BackgroundTasks,
    options: Optional[AnalysisStartOptions] = None,
):
    """
    Trigger AI analysis for a video. Runs as a background task.
    Extracts frames at configured intervals and sends consecutive
    pairs to Gemma4 for comparison.
    """
    if video_id in _running_analyses:
        raise HTTPException(409, "Analysis already in progress for this video")

    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM videos WHERE id=?", [video_id])
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(404, "Video not found")

        if row["status"] == "done":
            raise HTTPException(400, "Analysis already completed. Delete events to re-run.")

        # Mark as analyzing
        await db.execute(
            "UPDATE videos SET status='analyzing', analysis_progress=0 WHERE id=?",
            [video_id],
        )
        await db.commit()
    finally:
        await db.close()

    options = options or AnalysisStartOptions()

    _running_analyses.add(video_id)
    background_tasks.add_task(
        _run_analysis,
        video_id,
        row["filepath"],
        options.detail_mode,
        options.motion_filter_enabled,
        options.motion_threshold,
        options.analysis_interval_seconds,
    )

    return {
        "detail": "Analysis started",
        "video_id": video_id,
        "detail_mode": options.detail_mode,
        "motion_filter_enabled": options.motion_filter_enabled,
        "motion_threshold": options.motion_threshold,
        "analysis_interval_seconds": options.analysis_interval_seconds,
    }


@router.get("/status/{video_id}", response_model=AnalysisStatusOut)
async def get_analysis_status(video_id: int):
    """Check the progress of an ongoing or completed analysis."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT status, analysis_progress FROM videos WHERE id=?", [video_id]
        )
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(404, "Video not found")

        event_cursor = await db.execute(
            "SELECT COUNT(*) as cnt FROM analysis_events WHERE video_id=?", [video_id]
        )
        event_count = (await event_cursor.fetchone())["cnt"]

        return AnalysisStatusOut(
            video_id=video_id,
            status=row["status"],
            progress=row["analysis_progress"] or 0,
            total_events=event_count,
        )
    finally:
        await db.close()


@router.get("/events/{video_id}", response_model=List[AnalysisEventOut])
async def get_analysis_events(video_id: int, language: Optional[str] = Query(None, min_length=2, max_length=12)):
    """Get all analysis events for a specific video, ordered by timestamp."""
    db = await get_db()
    try:
        cursor = await db.execute(
            """SELECT * FROM analysis_events
               WHERE video_id=?
               ORDER BY timestamp_sec ASC""",
            [video_id],
        )
        rows = await cursor.fetchall()
        events = [_row_to_event(r) for r in rows]
        return await _localize_event_outputs(events, language)
    finally:
        await db.close()


@router.post("/ask/{video_id}", response_model=VideoQuestionResponseOut)
async def ask_video_question_route(video_id: int, body: VideoQuestionRequest):
    """Answer a natural-language question about one analyzed video."""
    db = await get_db()
    try:
        video_cursor = await db.execute(
            "SELECT id, title, duration, status FROM videos WHERE id=?",
            [video_id],
        )
        video_row = await video_cursor.fetchone()
        if not video_row:
            raise HTTPException(404, "Video not found")

        event_cursor = await db.execute(
            """SELECT id, timestamp_sec, frame_path, description, event_type,
                      severity, diff_description, summary, keywords, raw_json
               FROM analysis_events
               WHERE video_id=?
               ORDER BY timestamp_sec ASC, id ASC""",
            [video_id],
        )
        event_rows = await event_cursor.fetchall()
    finally:
        await db.close()

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
        answer_video_question,
        dict(video_row),
        [dict(row) for row in event_rows],
        question=body.question,
        language=body.language,
        current_timestamp_sec=body.current_timestamp_sec,
        history=history,
    )
    return VideoQuestionResponseOut(**response)


@router.post("/report/{video_id}")
async def export_video_investigation_report(video_id: int, body: InvestigationReportRequest):
    """Render a PDF investigation report from the current watch-page QA session."""
    db = await get_db()
    try:
        video_cursor = await db.execute(
            "SELECT id, title, duration, status, video_type FROM videos WHERE id=?",
            [video_id],
        )
        video_row = await video_cursor.fetchone()
        if not video_row:
            raise HTTPException(404, "Video not found")

        event_cursor = await db.execute(
            """SELECT id, timestamp_sec, frame_path, description, event_type,
                      severity, summary
               FROM analysis_events
               WHERE video_id=?
               ORDER BY timestamp_sec ASC, id ASC""",
            [video_id],
        )
        event_rows = await event_cursor.fetchall()
    finally:
        await db.close()

    report_bytes = await asyncio.to_thread(
        build_investigation_report_pdf,
        language=body.language or "en",
        resource_kind="video",
        resource_title=str(video_row["title"] or f"Video {video_id}"),
        scope_summary=f"Video #{video_id} | {video_row['video_type']} | duration {round(float(video_row['duration'] or 0.0), 1)}s",
        current_timestamp_sec=body.current_timestamp_sec,
        messages=[message.model_dump() for message in body.messages],
        timeline_rows=[dict(row) for row in event_rows],
    )

    filename = f"phylax-investigation-video-{video_id}.pdf"
    return StreamingResponse(
        BytesIO(report_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("/events/{video_id}")
async def delete_analysis_events(video_id: int):
    """
    Delete all analysis events for a video and reset its status to 'pending'.
    This allows the video to be re-analyzed.
    """
    if video_id in _running_analyses:
        raise HTTPException(409, "Analysis is currently in progress for this video")

    db = await get_db()
    try:
        cursor = await db.execute("SELECT id FROM videos WHERE id=?", [video_id])
        if not await cursor.fetchone():
            raise HTTPException(404, "Video not found")

        await db.execute("DELETE FROM analysis_events WHERE video_id=?", [video_id])
        await db.execute(
            "UPDATE videos SET status='pending', analysis_progress=0 WHERE id=?",
            [video_id],
        )
        await db.commit()

        logger.info("Cleared analysis events for video %d", video_id)
        return {"detail": "Analysis events cleared", "video_id": video_id}
    finally:
        await db.close()


async def _run_analysis(
    video_id: int,
    video_path: str,
    detail_mode: str = "careful",
    motion_filter_enabled: bool = False,
    motion_threshold: int = 0,
    analysis_interval_seconds: float = FRAME_ANALYSIS_INTERVAL,
):
    """
    Background task: extract frames and analyze them pairwise.
    Updates progress in the database as it goes.
    """
    try:
        logger.info("Starting analysis for video %d", video_id)

        frame_width = 512 if detail_mode == "careful" else 448
        frame_height = 288 if detail_mode == "careful" else 252
        jpeg_quality = 84 if detail_mode == "careful" else 78

        # Step 1: Extract frames (in thread to avoid blocking API)
        frames = await asyncio.to_thread(
            extract_frames,
            video_path,
            video_id,
            max(1.0, min(60.0, float(analysis_interval_seconds or FRAME_ANALYSIS_INTERVAL))),
            frame_width,
            frame_height,
            jpeg_quality,
        )

        if not frames:
            logger.error("No frames extracted for video %d", video_id)
            await _update_video_status(video_id, "error", 0)
            return

        total = len(frames)
        logger.info("Extracted %d frames for video %d", total, video_id)

        successful_results = 0
        attempted_analyses = 0
        skipped_by_motion = 0
        story_context = deque(maxlen=4)

        # Step 2: Analyze each frame pair
        for i, (frame_path, timestamp) in enumerate(frames):
            prev_frame_path = frames[i - 1][0] if i > 0 else None
            prev_timestamp = frames[i - 1][1] if i > 0 else 0

            if motion_filter_enabled and prev_frame_path:
                motion_score, changed_ratio = await asyncio.to_thread(
                    estimate_motion_score,
                    prev_frame_path,
                    frame_path,
                )
                if motion_score < motion_threshold:
                    skipped_by_motion += 1
                    logger.info(
                        "Skipping frame %.1fs for video %d due to motion filter: score=%d threshold=%d changed_ratio=%.2f%%",
                        timestamp,
                        video_id,
                        motion_score,
                        motion_threshold,
                        changed_ratio,
                    )
                    progress = (i + 1) / total
                    await _update_video_status(video_id, "analyzing", progress)
                    continue

            # Call AI analysis (in thread to avoid blocking FastAPI)
            attempted_analyses += 1
            result = await asyncio.to_thread(
                analyze_frames,
                current_frame_path=frame_path,
                previous_frame_path=prev_frame_path,
                current_timestamp=timestamp,
                previous_timestamp=prev_timestamp,
                profile="video",
                detail_mode=detail_mode,
                timeline_context=list(story_context),
            )

            if result:
                story_entry = build_timeline_story_entry(result, timestamp=timestamp, source="video")
                if story_entry:
                    story_context.append(story_entry)
                await _save_analysis_event(video_id, timestamp, frame_path, result)
                successful_results += 1

            # Update progress
            progress = (i + 1) / total
            await _update_video_status(video_id, "analyzing", progress)

            # Small delay to avoid overwhelming Ollama
            await asyncio.sleep(0.1)

        if successful_results == 0 and attempted_analyses > 0:
            logger.error("Analysis produced no usable AI results for video %d", video_id)
            await _update_video_status(video_id, "error", 0)
            return

        # Mark as complete
        await _update_video_status(video_id, "done", 1.0)
        logger.info(
            "Analysis complete for video %d (%d frames, attempted=%d, skipped_by_motion=%d)",
            video_id,
            total,
            attempted_analyses,
            skipped_by_motion,
        )

    except Exception as e:
        logger.error("Analysis failed for video %d: %s", video_id, str(e))
        await _update_video_status(video_id, "error", 0)
    finally:
        _running_analyses.discard(video_id)


async def _save_analysis_event(
    video_id: int, timestamp: float, frame_path: str, result: dict
):
    """Persist a single analysis event to the database."""
    db = await get_db()
    try:
        keywords = result.get("keywords", [])
        keywords_str = ", ".join(keywords) if isinstance(keywords, list) else str(keywords)

        await db.execute(
            """INSERT INTO analysis_events
               (video_id, timestamp_sec, frame_path, description, event_type,
                severity, diff_description, summary, keywords, raw_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                video_id,
                timestamp,
                frame_path,
                result.get("scene_description", ""),
                result.get("event_type", "normal"),
                result.get("severity", "Normal"),
                json.dumps(result.get("changes_detected", []), ensure_ascii=False),
                result.get("summary", ""),
                keywords_str,
                json.dumps(result, ensure_ascii=False),
            ],
        )
        await db.commit()
    finally:
        await db.close()


async def _update_video_status(video_id: int, status: str, progress: float):
    """Update the analysis status and progress of a video."""
    db = await get_db()
    try:
        await db.execute(
            "UPDATE videos SET status=?, analysis_progress=? WHERE id=?",
            [status, progress, video_id],
        )
        await db.commit()
    finally:
        await db.close()


def _row_to_event(row) -> AnalysisEventOut:
    """Convert a database row to an AnalysisEventOut schema."""
    payload = _parse_event_payload(row["raw_json"])
    changes_detected = payload.get("changes_detected")
    if not isinstance(changes_detected, list):
        changes_detected = _parse_json_list(row["diff_description"])
    keywords = payload.get("keywords")
    if not isinstance(keywords, list):
        keywords = _split_keywords(row["keywords"] if "keywords" in row.keys() else "")
    return AnalysisEventOut(
        id=row["id"],
        video_id=row["video_id"],
        camera_id=row["camera_id"],
        timestamp_sec=row["timestamp_sec"],
        frame_path=row["frame_path"],
        description=row["description"],
        event_type=row["event_type"] or "none",
        severity=row["severity"] or "low",
        diff_description=row["diff_description"],
        summary=row["summary"],
        changes_detected=[str(item) for item in changes_detected[:6] if str(item).strip()],
        anomaly_score=_coerce_int(payload.get("anomaly_score"), 0, 100),
        requires_attention=bool(payload.get("requires_attention", False)),
        frame_observation=str(payload.get("frame_observation") or payload.get("scene_description") or "").strip() or None,
        temporal_assessment=str(payload.get("temporal_assessment") or "").strip() or None,
        anomaly_rationale=str(payload.get("anomaly_rationale") or "").strip() or None,
        keywords=[str(item) for item in keywords[:8] if str(item).strip()],
        created_at=row["created_at"],
    )


def _parse_event_payload(raw_json: Optional[str]) -> dict:
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
        return parsed if isinstance(parsed, list) else []
    except json.JSONDecodeError:
        return []


def _split_keywords(raw_value: Optional[str]) -> list:
    if not raw_value:
        return []
    return [item.strip() for item in str(raw_value).split(",") if item.strip()]


async def _localize_event_outputs(
    events: List[AnalysisEventOut],
    language: Optional[str],
) -> List[AnalysisEventOut]:
    normalized_language = str(language or "").strip().lower().split("-", 1)[0]
    if normalized_language == "" or not events:
        return events

    translatable_events = [
        event for event in events
        if _event_needs_localization(event, normalized_language)
    ]
    if not translatable_events:
        return events

    cached_by_id = await _load_localized_event_cache(translatable_events, normalized_language)
    uncached_events = [
        event for event in translatable_events
        if str(event.id) not in cached_by_id
    ]

    items = []
    events_by_id = {}
    for event in uncached_events:
        event_id = str(event.id)
        events_by_id[event_id] = event
        items.append(
            {
                "id": event_id,
                "summary": event.summary or "",
                "description": _compose_translation_text(event),
            }
        )

    translated_by_id = dict(cached_by_id)
    if items:
        translated = await asyncio.to_thread(
            translate_event_texts,
            items,
            normalized_language,
            normalized_language == "en",
        )
        parsed_for_cache = {}
        for item in translated:
            event_id = str(item.get("id"))
            event = events_by_id.get(event_id)
            if not event:
                continue
            parsed = _parse_translated_event_text(str(item.get("description") or event.description or ""))
            cache_payload = {
                "summary": str(item.get("summary") or event.summary or ""),
                "description": parsed["description"] or event.description,
                "frame_observation": parsed["frame_observation"] or event.frame_observation,
                "temporal_assessment": parsed["temporal_assessment"] or event.temporal_assessment,
                "anomaly_rationale": parsed["anomaly_rationale"] or event.anomaly_rationale,
                "changes_detected": parsed["changes_detected"] or event.changes_detected,
            }
            if _localized_payload_needs_cleanup(cache_payload, normalized_language):
                continue
            translated_by_id[event_id] = {
                "id": event_id,
                "summary": cache_payload["summary"],
                "description": _compose_cached_translation_text(cache_payload),
            }
            parsed_for_cache[event_id] = cache_payload
        if parsed_for_cache:
            await _store_localized_event_cache(events_by_id, parsed_for_cache, normalized_language)

    localized = []
    for event in events:
        translated_item = translated_by_id.get(str(event.id))
        if not translated_item:
            localized.append(event)
            continue

        parsed = _parse_translated_event_text(
            str(translated_item.get("description") or event.description or "")
        )
        payload = event.model_dump()
        payload.update(
            summary=str(translated_item.get("summary") or event.summary or ""),
            description=parsed["description"] or event.description,
            frame_observation=parsed["frame_observation"] or event.frame_observation,
            temporal_assessment=parsed["temporal_assessment"] or event.temporal_assessment,
            anomaly_rationale=parsed["anomaly_rationale"] or event.anomaly_rationale,
            changes_detected=parsed["changes_detected"] or event.changes_detected,
        )
        localized.append(AnalysisEventOut(**payload))
    return localized


async def _load_localized_event_cache(events: List[AnalysisEventOut], language: str) -> dict[str, dict]:
    if not events:
        return {}
    db = await get_db()
    try:
        output = {}
        for event in events:
            event_id = str(event.id)
            cursor = await db.execute(
                """SELECT source_hash, summary, description, frame_observation,
                          temporal_assessment, anomaly_rationale, changes_json
                   FROM localized_event_texts
                   WHERE source_kind='analysis_event' AND source_id=? AND language=?""",
                [event.id, language],
            )
            row = await cursor.fetchone()
            if not row or row["source_hash"] != _event_source_hash(event):
                continue
            payload = {
                "summary": row["summary"] or "",
                "description": row["description"] or "",
                "frame_observation": row["frame_observation"] or "",
                "temporal_assessment": row["temporal_assessment"] or "",
                "anomaly_rationale": row["anomaly_rationale"] or "",
                "changes_detected": _parse_json_list(row["changes_json"]),
            }
            if _localized_payload_needs_cleanup(payload, language):
                continue
            output[event_id] = {
                "id": event_id,
                "summary": payload["summary"],
                "description": _compose_cached_translation_text(payload),
            }
        return output
    finally:
        await db.close()


async def _store_localized_event_cache(events_by_id: dict[str, AnalysisEventOut], payloads: dict[str, dict], language: str) -> None:
    db = await get_db()
    try:
        for event_id, payload in payloads.items():
            event = events_by_id.get(event_id)
            if not event:
                continue
            await db.execute(
                """INSERT OR REPLACE INTO localized_event_texts
                   (source_kind, source_id, language, source_hash, summary, description,
                    frame_observation, temporal_assessment, anomaly_rationale, changes_json, updated_at)
                   VALUES ('analysis_event', ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
                [
                    event.id,
                    language,
                    _event_source_hash(event),
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


def _event_source_hash(event: AnalysisEventOut) -> str:
    payload = {
        "summary": event.summary or "",
        "description": event.description or "",
        "frame_observation": event.frame_observation or "",
        "temporal_assessment": event.temporal_assessment or "",
        "anomaly_rationale": event.anomaly_rationale or "",
        "changes_detected": event.changes_detected or [],
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _localized_payload_needs_cleanup(payload: dict, language: str) -> bool:
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


def _compose_cached_translation_text(payload: dict) -> str:
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


def _event_needs_localization(event: AnalysisEventOut, language: str) -> bool:
    text = " ".join(
        part for part in [
            event.summary or "",
            event.description or "",
            event.frame_observation or "",
            event.temporal_assessment or "",
            event.anomaly_rationale or "",
            " ".join(event.changes_detected or []),
            " ".join(event.keywords or []),
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
    target_markers = {
        "es": {
            "el", "la", "los", "las", "un", "una", "con", "sin", "tráfico",
            "vehículo", "vehículos", "carretera", "flujo", "normal", "estable",
            "observado", "continúa", "entrada", "intersección",
        },
        "fr": {
            "le", "la", "les", "un", "une", "des", "avec", "sans", "trafic",
            "véhicule", "véhicules", "route", "flux", "normal", "stable",
            "observé", "continue", "entrée", "intersection",
        },
    }.get(language, set())

    lowered = {word.lower() for word in ascii_words}
    return bool((lowered & common_english) and not (lowered & target_markers))


def _compose_translation_text(event: AnalysisEventOut) -> str:
    parts = [event.description or ""]
    if event.frame_observation:
        parts.append(f"[[frame_observation]] {event.frame_observation}")
    if event.temporal_assessment:
        parts.append(f"[[temporal_assessment]] {event.temporal_assessment}")
    if event.anomaly_rationale:
        parts.append(f"[[anomaly_rationale]] {event.anomaly_rationale}")
    for change in event.changes_detected or []:
        if change:
            parts.append(f"[[change]] {change}")
    return "\n".join(part for part in parts if part)


def _parse_translated_event_text(text: str) -> dict:
    parsed = {
        "description": "",
        "frame_observation": "",
        "temporal_assessment": "",
        "anomaly_rationale": "",
        "changes_detected": [],
    }
    plain_lines = []
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = re.match(r"^\[\[(frame_observation|temporal_assessment|anomaly_rationale|change)\]\]\s*(.*)$", line)
        if not match:
            plain_lines.append(line)
            continue
        field, value = match.group(1), match.group(2).strip()
        if not value:
            continue
        if field == "change":
            parsed["changes_detected"].append(value)
        else:
            parsed[field] = value

    parsed["description"] = "\n".join(plain_lines)
    return parsed


def _coerce_int(value, min_value: int, max_value: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = min_value
    return max(min_value, min(max_value, number))
