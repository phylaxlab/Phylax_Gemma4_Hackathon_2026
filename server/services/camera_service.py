"""
Camera Service - Manages persistent IP camera streams.
Handles auto-reconnects, MJPEG frame buffers, and adaptive AI analysis.
"""

from __future__ import annotations

import os as _os
# Suppress noisy OpenCV FFmpeg/TLS stderr warnings (stream timeouts, TLS close
# failures, etc.) that can crash the process in some shell environments.
_os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")
_os.environ.setdefault("OPENCV_FFMPEG_LOGLEVEL", "-8")  # AV_LOG_QUIET

import cv2
import time
import asyncio
import threading
import logging
import json
import numpy as np
from typing import Dict, Any, Optional
from pathlib import Path

from database import get_db
from config import (
    CAMERA_FRAME_ANALYSIS_INTERVAL,
    CAMERA_ANALYSIS_MIN_INTERVAL,
    CAMERA_ANALYSIS_MAX_INTERVAL,
    CAMERA_BACKFILL_MAX_FRAMES,
    CAMERA_AI_MAX_CONCURRENCY,
    CAMERA_AI_DEFAULT_ENABLED,
    CAMERA_REVIEW_BUFFER_SIZE,
    CAMERA_REVIEW_HISTORY_LIMIT,
    CAMERA_ROUTINE_EVENT_MIN_INTERVAL,
    CAMERA_DVR_SECONDS,
    CAMERA_DVR_FPS,
    FRAME_DIR,
    CAMERA_ANALYSIS_WIDTH,
    CAMERA_ANALYSIS_HEIGHT,
)
from services.ai_service import analyze_frames, build_timeline_story_entry
from services.video_service import estimate_motion_score

logger = logging.getLogger(__name__)

from collections import deque

# In-memory dictionary to hold running camera tasks and their latest JPEG frames.
# Each camera owns one capture thread and one async analyzer loop.
_active_cameras: Dict[int, Dict[str, Any]] = {}
_camera_ai_semaphore: Optional[asyncio.Semaphore] = None
_camera_ai_semaphore_limit = 0


def _get_camera_ai_semaphore() -> asyncio.Semaphore:
    """Return a shared limiter for all camera AI inference tasks."""
    global _camera_ai_semaphore, _camera_ai_semaphore_limit

    limit = max(1, CAMERA_AI_MAX_CONCURRENCY)
    if _camera_ai_semaphore is None or _camera_ai_semaphore_limit != limit:
        _camera_ai_semaphore = asyncio.Semaphore(limit)
        _camera_ai_semaphore_limit = limit
    return _camera_ai_semaphore


def _append_replay_frame(state: dict, cam_dir: Path, timestamp: float, frame) -> dict:
    """Persist a low-fps replay frame and keep only the latest rolling window."""
    replay_frames = state["replay_frames"]
    max_frames = int(CAMERA_DVR_SECONDS * CAMERA_DVR_FPS)

    if len(replay_frames) >= max_frames:
        oldest = replay_frames.popleft()
        old_path = Path(oldest["abs_path"])
        if old_path.exists():
            old_path.unlink(missing_ok=True)

    frame_name = f"replay_{int(timestamp * 1000)}.jpg"
    frame_path = cam_dir / frame_name
    cv2.imwrite(str(frame_path), frame, [int(cv2.IMWRITE_JPEG_QUALITY), 82])

    frame_meta = {
        "timestamp_sec": timestamp,
        "abs_path": str(frame_path),
        "url": f"/frames/cam_{state['camera_id']}/{frame_name}",
    }
    replay_frames.append(frame_meta)
    return frame_meta


def _get_camera_story_context(camera_id: int, limit: int = 4) -> list[dict]:
    state = _active_cameras.get(camera_id)
    if not state:
        return []

    story_context = state.get("recent_story_context")
    if story_context:
        return [dict(item) for item in list(story_context)[-max(1, limit):] if isinstance(item, dict)]

    reviews = list(state.get("recent_ai_reviews") or [])
    timeline = []
    for review in reversed(reviews[: max(1, limit)]):
        entry = build_timeline_story_entry(
            review,
            timestamp=float(review.get("timestamp_sec") or 0),
            source="camera_review",
        )
        if entry:
            timeline.append(entry)
    return timeline


def _append_camera_story_context(camera_id: int, entry: Optional[dict]) -> None:
    if not entry:
        return

    state = _active_cameras.get(camera_id)
    if not state:
        return

    story_context = state.get("recent_story_context")
    if story_context is None:
        story_context = deque(maxlen=6)
        state["recent_story_context"] = story_context
    story_context.append(dict(entry))


def _prepare_analysis_frame(state: dict, source_path: str, timestamp: float) -> Optional[str]:
    """Create a compact AI input frame from a replay frame on demand."""
    source = cv2.imread(source_path)
    if source is None:
        return None

    cam_dir = Path(source_path).parent
    analysis_frames = state.setdefault("analysis_frames", deque())
    max_analysis_frames = 120

    if len(analysis_frames) >= max_analysis_frames:
        oldest_path = Path(analysis_frames.popleft())
        if oldest_path.exists():
            oldest_path.unlink(missing_ok=True)

    resized = cv2.resize(source, (CAMERA_ANALYSIS_WIDTH, CAMERA_ANALYSIS_HEIGHT))
    frame_name = f"analysis_{int(timestamp * 1000)}.jpg"
    frame_path = cam_dir / frame_name
    cv2.imwrite(str(frame_path), resized, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
    analysis_frames.append(str(frame_path))
    return str(frame_path)


def _fit_frame_with_padding(frame, target_width: int, target_height: int):
    source_h, source_w = frame.shape[:2]
    if source_w <= 0 or source_h <= 0:
        return cv2.resize(frame, (target_width, target_height))

    scale = min(target_width / float(source_w), target_height / float(source_h))
    resized_w = max(1, int(round(source_w * scale)))
    resized_h = max(1, int(round(source_h * scale)))
    resized = cv2.resize(frame, (resized_w, resized_h))

    canvas = np.zeros((target_height, target_width, 3), dtype=frame.dtype)
    offset_x = (target_width - resized_w) // 2
    offset_y = (target_height - resized_h) // 2
    canvas[offset_y:offset_y + resized_h, offset_x:offset_x + resized_w] = resized
    return canvas


def _camera_capture_worker(camera_id: int, url: str, state: dict):
    """
    Dedicated native thread for grabbing frames at max speed.
    Ensures MJPEG streams are fluid and unblocked by the asyncio event loop.
    """
    cam_dir = FRAME_DIR / f"cam_{camera_id}"
    cam_dir.mkdir(parents=True, exist_ok=True)
    
    while not state["stop_flag"]:
        cap = None
        try:
            logger.info(f"Connecting to camera {camera_id}: {url}")
            cap = cv2.VideoCapture(url)
            
            if not cap.isOpened():
                import random
                jitter = random.uniform(5, 10)
                logger.warning(f"Camera {camera_id} failed to open. Retrying in {jitter:.1f}s...")
                cap.release()
                cap = None
                time.sleep(jitter)
                continue
                
            fps = cap.get(cv2.CAP_PROP_FPS)
            if fps <= 0 or fps > 60:
                fps = 25.0
                
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            if width == 0 or height == 0:
                width, height = 640, 360  # Safe fallback
                
            last_dvr_time = 0
            while not state["stop_flag"]:
                ret, frame = cap.read()
                
                if not ret:
                    import random
                    jitter = random.uniform(2, 6)
                    logger.warning(f"Camera {camera_id} lost stream. Reconnecting in {jitter:.1f}s...")
                    time.sleep(jitter)
                    break
                    
                now = time.time()
                preview_frame = _fit_frame_with_padding(frame, 640, 360)
                state["latest_preview_frame"] = preview_frame
                state["latest_frame_ts"] = now
                state["latest_frame_seq"] = int(state.get("latest_frame_seq") or 0) + 1
                
                # --- Memory Rolling DVR Buffer Track ---
                if now - last_dvr_time >= (1 / CAMERA_DVR_FPS):
                    last_dvr_time = now
                    # Resize specifically for DVR to save memory (total ~160MB max per camera)
                    state["dvr_buffer"].append(preview_frame)
                    state["latest_analysis_frame"] = _append_replay_frame(
                        state,
                        cam_dir,
                        now,
                        preview_frame,
                    )

                # --- Live Streaming Track ---
                # Encode the same normalized preview frame used for AI/replay so overlays align.
                ret_enc, jpeg_bytes = cv2.imencode('.jpg', preview_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 60])
                if ret_enc:
                    state["frame_bytes"] = jpeg_bytes.tobytes()

                # A tiny sleep avoids consuming 100% of a CPU core when max fps is uncapped
                time.sleep(0.01) 

        except Exception as exc:
            logger.error(f"Camera {camera_id} capture error: {exc}")
            time.sleep(3)
        finally:
            if cap is not None:
                try:
                    cap.release()
                except Exception:
                    pass
        time.sleep(1)

    logger.info(f"Camera {camera_id} loop cleanly stopped.")


async def _run_camera_analysis(
    camera_id: int,
    current_path: str,
    prev_path: Optional[str],
    timestamp: float,
    *,
    motion_context: Optional[str] = None,
) -> Optional[dict]:
    """Fires AI analysis without blocking the capture loop, saves to DB."""
    state = None
    result = None
    try:
        timeline_context = _get_camera_story_context(camera_id)
        async with _get_camera_ai_semaphore():
            state = _active_cameras.get(camera_id)
            if state:
                state["current_analyzing_ts"] = timestamp

            result = await asyncio.to_thread(
                analyze_frames,
                current_frame_path=current_path,
                previous_frame_path=None,
                current_timestamp=0, # relative timestamps not strict for continuous streams
                previous_timestamp=0,
                profile="camera",
                context_text=motion_context,
                timeline_context=timeline_context,
                output_language="en",
            )
            should_store = False

            if result:
                should_store = _should_store_camera_result(camera_id, timestamp, result)
                _record_camera_review(
                    camera_id,
                    timestamp,
                    result,
                    is_waived=not should_store,
                )

            if result and should_store:
                await _save_camera_event(camera_id, timestamp, current_path, result)
            elif result:
                await _save_camera_review(
                    camera_id,
                    timestamp,
                    current_path,
                    result,
                    is_waived=True,
                )
                _record_waived_camera_result(camera_id, timestamp, result)
                logger.info(
                    "Camera %d AI triage skipped DB write: severity=%s event_type=%s",
                    camera_id,
                    result.get("severity"),
                    result.get("event_type"),
                )
            else:
                fallback_review = {
                    "scene_description": "AI review unavailable",
                    "changes_detected": [],
                    "event_type": "normal",
                    "severity": "Normal",
                    "anomaly_score": 0,
                    "requires_attention": False,
                    "summary": "AI review unavailable",
                    "keywords": ["ai_unavailable"],
                }
                _record_camera_review(
                    camera_id,
                    timestamp,
                    fallback_review,
                    is_waived=True,
                    is_error=True,
                )
                await _save_camera_review(
                    camera_id,
                    timestamp,
                    current_path,
                    fallback_review,
                    is_waived=True,
                    is_error=True,
                )
                result = fallback_review

        story_entry = build_timeline_story_entry(result, timestamp=timestamp, source="camera")
        _append_camera_story_context(camera_id, story_entry)
        return result
    except Exception as e:
        logger.error(f"AI Analysis failed for camera {camera_id}: {e}")
        return None
    finally:
        if state:
            state["analysis_inflight"] = False
        if state and state.get("current_analyzing_ts") == timestamp:
            state["current_analyzing_ts"] = None


def _should_store_camera_result(camera_id: int, timestamp: float, result: dict) -> bool:
    """Persist only actionable camera triage results."""
    state = _active_cameras.get(camera_id)
    severity = str(result.get("severity", "")).lower()
    event_type = str(result.get("event_type", "")).lower()

    if severity in {"warning", "emergency"} or event_type == "anomaly":
        return True

    if event_type in {"person", "vehicle"}:
        if not state:
            return True

        last_by_type = state.setdefault("last_persisted_routine_event_ts", {})
        last_ts = float(last_by_type.get(event_type) or 0)
        if timestamp - last_ts >= CAMERA_ROUTINE_EVENT_MIN_INTERVAL:
            last_by_type[event_type] = timestamp
            return True

    return False


def _record_camera_review(
    camera_id: int,
    timestamp: float,
    result: dict,
    is_waived: bool,
    is_error: bool = False,
) -> None:
    """Keep a short in-memory stream of AI reviews for dashboard feedback."""
    state = _active_cameras.get(camera_id)
    if not state:
        return

    state["ai_review_count"] = int(state.get("ai_review_count") or 0) + 1
    review_id = -state["ai_review_count"]
    summary = result.get("summary") or result.get("frame_observation") or result.get("scene_description") or "AI review"
    description = (
        result.get("temporal_assessment")
        or result.get("frame_observation")
        or result.get("scene_description")
        or summary
    )

    reviews = state.get("recent_ai_reviews")
    if reviews is None:
        reviews = deque(maxlen=max(1, CAMERA_REVIEW_BUFFER_SIZE))
        state["recent_ai_reviews"] = reviews

    reviews.appendleft({
        "id": review_id,
        "camera_id": camera_id,
        "timestamp_sec": timestamp,
        "description": description,
        "event_type": result.get("event_type", "none"),
        "severity": result.get("severity", "Normal"),
        "summary": summary,
        "changes_detected": result.get("changes_detected", []),
        "anomaly_score": result.get("anomaly_score", 0),
        "requires_attention": bool(result.get("requires_attention", False)),
        "keywords": result.get("keywords", []),
        "frame_observation": result.get("frame_observation") or result.get("scene_description") or "",
        "temporal_assessment": result.get("temporal_assessment") or "",
        "anomaly_rationale": result.get("anomaly_rationale") or "",
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
        "is_waived": is_waived,
        "is_error": is_error,
    })

    if is_error:
        state["last_ai_error"] = summary
        state["last_ai_error_ts"] = timestamp


async def _save_camera_review(
    camera_id: int,
    timestamp: float,
    frame_path: Optional[str],
    result: dict,
    *,
    is_waived: bool,
    is_error: bool = False,
) -> None:
    """Persist waived/error camera AI reviews so history survives page changes and restarts."""
    db = await get_db()
    try:
        keywords = result.get("keywords", [])
        keywords_str = ", ".join(keywords) if isinstance(keywords, list) else str(keywords)
        await db.execute(
            """INSERT INTO camera_ai_reviews
               (camera_id, timestamp_sec, frame_path, description, event_type,
                severity, summary, keywords, raw_json, is_waived, is_error)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                camera_id,
                timestamp,
                frame_path,
                result.get("temporal_assessment")
                or result.get("frame_observation")
                or result.get("scene_description")
                or result.get("summary")
                or "AI review",
                result.get("event_type", "none"),
                result.get("severity", "Normal"),
                result.get("summary")
                or result.get("frame_observation")
                or result.get("scene_description")
                or "AI review",
                keywords_str,
                json.dumps(result, ensure_ascii=False),
                1 if is_waived else 0,
                1 if is_error else 0,
            ],
        )

        history_limit = max(20, CAMERA_REVIEW_HISTORY_LIMIT)
        await db.execute(
            """DELETE FROM camera_ai_reviews
               WHERE camera_id=?
                 AND id NOT IN (
                   SELECT id FROM camera_ai_reviews
                   WHERE camera_id=?
                   ORDER BY timestamp_sec DESC, id DESC
                   LIMIT ?
                 )""",
            [camera_id, camera_id, history_limit],
        )
        await db.commit()
    finally:
        await db.close()


def _record_waived_camera_result(camera_id: int, timestamp: float, result: dict) -> None:
    """Keep lightweight feedback for triage results that are not persisted."""
    state = _active_cameras.get(camera_id)
    if not state:
        return

    summary = result.get("summary") or result.get("scene_description") or "Routine scene"
    state["waived_count"] = int(state.get("waived_count") or 0) + 1
    state["last_waived_ts"] = timestamp
    state["last_waived_summary"] = summary
    state["last_waived_event_type"] = result.get("event_type", "normal")
    state["last_waived_severity"] = result.get("severity", "Normal")


async def _save_camera_event(
    camera_id: int,
    timestamp: float,
    frame_path: str,
    result: dict,
) -> None:
    """Persist a camera analysis event after triage filtering."""
    db = await get_db()
    try:
        keywords = result.get("keywords", [])
        keywords_str = ", ".join(keywords) if isinstance(keywords, list) else str(keywords)
        await db.execute(
            """INSERT INTO analysis_events
               (camera_id, timestamp_sec, frame_path, description, event_type,
                severity, diff_description, summary, keywords, raw_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                camera_id,
                timestamp,
                frame_path,
                result.get("temporal_assessment")
                or result.get("frame_observation")
                or result.get("scene_description", ""),
                result.get("event_type", "normal"),
                result.get("severity", "Normal"),
                json.dumps(result.get("changes_detected", []), ensure_ascii=False),
                result.get("summary") or result.get("frame_observation", ""),
                keywords_str,
                json.dumps(result, ensure_ascii=False),
            ],
        )
        await db.commit()
    finally:
        await db.close()


def _result_requires_attention(result: Optional[dict]) -> bool:
    """Return True when the model result should keep the analyzer hot."""
    if not result:
        return False

    severity = str(result.get("severity", "")).lower()
    event_type = str(result.get("event_type", "")).lower()
    try:
        anomaly_score = int(result.get("anomaly_score") or 0)
    except (TypeError, ValueError):
        anomaly_score = 0

    return (
        bool(result.get("requires_attention"))
        or severity in {"warning", "emergency"}
        or event_type == "anomaly"
        or anomaly_score >= 55
    )


def _next_camera_interval(
    previous_interval: float,
    result: Optional[dict],
    motion_score: Optional[int],
) -> float:
    """
    Adapt the next sleep interval.
    Attention-worthy or high-motion scenes stay hot; quiet scenes back off.
    """
    min_interval = max(0.5, CAMERA_ANALYSIS_MIN_INTERVAL)
    max_interval = max(min_interval, CAMERA_ANALYSIS_MAX_INTERVAL)
    base_interval = max(min_interval, CAMERA_FRAME_ANALYSIS_INTERVAL)

    if _result_requires_attention(result):
        return min_interval

    if motion_score is None:
        return min(max_interval, base_interval)

    if motion_score >= 7:
        return min_interval

    if motion_score >= 3:
        return min(max_interval, base_interval)

    return min(max_interval, max(base_interval, previous_interval * 1.4))


async def _camera_analysis_loop(camera_id: int) -> None:
    """
    Continuously analyze the newest available camera frame while AI is enabled.
    The loop never queues old frames; it samples the latest replay frame after
    each model call so slow inference does not create stale work.
    """
    logger.info("Adaptive AI loop started for camera %d", camera_id)

    while True:
        state = _active_cameras.get(camera_id)
        if not state or state.get("stop_flag"):
            break

        if not state.get("ai_enabled"):
            await asyncio.sleep(0.5)
            continue

        if state.get("backfill_inflight") or state.get("analysis_inflight"):
            await asyncio.sleep(0.5)
            continue

        now = time.time()
        next_analysis_after = state.get("next_analysis_after", 0)
        if now < next_analysis_after:
            await asyncio.sleep(min(1.0, next_analysis_after - now))
            continue

        candidate = state.get("latest_analysis_frame")
        if not candidate:
            await asyncio.sleep(0.5)
            continue

        current_ts = float(candidate["timestamp_sec"])
        current_path = candidate["abs_path"]
        if current_ts <= state.get("last_analyzed_ts", 0):
            await asyncio.sleep(0.5)
            continue

        if not Path(current_path).exists():
            await asyncio.sleep(0.5)
            continue

        prepared_path = await asyncio.to_thread(
            _prepare_analysis_frame,
            state,
            current_path,
            current_ts,
        )
        if not prepared_path:
            await asyncio.sleep(0.5)
            continue
        current_path = prepared_path

        try:
            prev_path = state.get("previous_analysis_path")
            motion_score = None
            changed_ratio = None
            motion_context = None
            if prev_path and Path(prev_path).exists():
                motion_score, changed_ratio = await asyncio.to_thread(
                    estimate_motion_score,
                    prev_path,
                    current_path,
                )
                motion_context = (
                    f"Automated motion hint on the current frame: motion_score={motion_score}/10, "
                    f"changed_area_ratio={changed_ratio:.2f}%."
                )

            state["analysis_inflight"] = True
            started_at = time.time()
            result = await _run_camera_analysis(
                camera_id,
                current_path,
                prev_path,
                current_ts,
                motion_context=motion_context,
            )
            duration = time.time() - started_at
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Adaptive AI loop failed for camera %d: %s", camera_id, exc)
            state = _active_cameras.get(camera_id)
            if state:
                state["analysis_inflight"] = False
                state["current_analyzing_ts"] = None
                state["next_analysis_after"] = time.time() + CAMERA_FRAME_ANALYSIS_INTERVAL
            await asyncio.sleep(1)
            continue

        state = _active_cameras.get(camera_id)
        if not state or state.get("stop_flag"):
            break

        previous_interval = float(state.get("adaptive_interval") or CAMERA_FRAME_ANALYSIS_INTERVAL)
        next_interval = _next_camera_interval(previous_interval, result, motion_score)

        state["previous_analysis_path"] = current_path
        state["last_analyzed_ts"] = current_ts
        state["last_analysis"] = time.time()
        state["last_analysis_duration"] = duration
        state["last_motion_score"] = motion_score
        state["last_changed_ratio"] = changed_ratio
        state["adaptive_interval"] = next_interval
        state["next_analysis_after"] = time.time() + next_interval

        logger.info(
            "Camera %d AI analyzed latest frame in %.1fs; motion=%s changed=%s next=%.1fs",
            camera_id,
            duration,
            motion_score,
            f"{changed_ratio:.2f}%" if changed_ratio is not None else "n/a",
            next_interval,
        )

    logger.info("Adaptive AI loop stopped for camera %d", camera_id)


async def _camera_event_exists(camera_id: int, timestamp: float, tolerance_sec: float = 1.5) -> bool:
    db = await get_db()
    try:
        cursor = await db.execute(
            """SELECT 1
               FROM analysis_events
               WHERE camera_id=?
                 AND ABS(timestamp_sec - ?) <= ?
               LIMIT 1""",
            [camera_id, timestamp, tolerance_sec],
        )
        return bool(await cursor.fetchone())
    finally:
        await db.close()


def _downsample_frames(frames: list[dict], max_count: int) -> list[dict]:
    """Evenly sample frames so backfill cannot starve live analysis."""
    if max_count <= 0:
        return []
    if len(frames) <= max_count:
        return frames
    if max_count == 1:
        return [frames[-1]]

    step = (len(frames) - 1) / (max_count - 1)
    sampled = []
    seen_timestamps = set()
    for i in range(max_count):
        frame = frames[round(i * step)]
        ts = frame["timestamp_sec"]
        if ts not in seen_timestamps:
            sampled.append(frame)
            seen_timestamps.add(ts)
    return sampled


async def _backfill_camera_window(camera_id: int) -> None:
    """
    Analyze representative frames from the recent replay window so the dashboard
    can surface the last 5 minutes of events even if AI was enabled late.
    """
    state = _active_cameras.get(camera_id)
    if not state or state.get("backfill_inflight"):
        return

    state["backfill_inflight"] = True
    try:
        frames = list(state.get("replay_frames", []))
        if len(frames) < 2:
            return

        selected_frames = []
        last_selected_ts = None
        for frame in frames:
            ts = frame["timestamp_sec"]
            if last_selected_ts is None or ts - last_selected_ts >= CAMERA_FRAME_ANALYSIS_INTERVAL:
                selected_frames.append(frame)
                last_selected_ts = ts

        selected_frames = _downsample_frames(selected_frames, CAMERA_BACKFILL_MAX_FRAMES)

        for index, frame in enumerate(selected_frames):
            live_state = _active_cameras.get(camera_id)
            if not live_state or live_state.get("stop_flag") or not live_state.get("ai_enabled"):
                break

            current_ts = frame["timestamp_sec"]
            if await _camera_event_exists(camera_id, current_ts):
                continue

            while live_state.get("analysis_inflight"):
                await asyncio.sleep(0.2)
                live_state = _active_cameras.get(camera_id)
                if not live_state or live_state.get("stop_flag") or not live_state.get("ai_enabled"):
                    return

            prev_path = selected_frames[index - 1]["abs_path"] if index > 0 else None
            current_path = await asyncio.to_thread(
                _prepare_analysis_frame,
                live_state,
                frame["abs_path"],
                current_ts,
            )
            if not current_path:
                continue

            live_state["analysis_inflight"] = True
            result = await _run_camera_analysis(
                camera_id,
                current_path,
                prev_path,
                current_ts,
            )
            live_state["previous_analysis_path"] = current_path
            live_state["last_analyzed_ts"] = max(
                live_state.get("last_analyzed_ts", 0),
                current_ts,
            )
            live_state["adaptive_interval"] = _next_camera_interval(
                float(live_state.get("adaptive_interval") or CAMERA_FRAME_ANALYSIS_INTERVAL),
                result,
                None,
            )
            live_state["next_analysis_after"] = time.time() + min(
                live_state["adaptive_interval"],
                CAMERA_FRAME_ANALYSIS_INTERVAL,
            )
            await asyncio.sleep(0.05)
    finally:
        state = _active_cameras.get(camera_id)
        if state:
            state["backfill_inflight"] = False


def request_camera_backfill(camera_id: int) -> bool:
    """
    Schedule a recent-window backfill for an active camera.
    Returns True if the request was scheduled.
    """
    state = _active_cameras.get(camera_id)
    if not state or state.get("stop_flag") or not state.get("ai_enabled"):
        return False
    if state.get("backfill_inflight"):
        return True

    loop = asyncio.get_running_loop()
    loop.create_task(_backfill_camera_window(camera_id))
    return True


async def start_camera_manager():
    """Starts all active cameras from the DB on boot."""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT id, stream_url, ai_enabled FROM cameras WHERE is_active = 1")
        cameras = await cursor.fetchall()
        for cam in cameras:
            start_camera(cam["id"], cam["stream_url"], bool(cam["ai_enabled"]))
            # Stagger connections to avoid hitting the same provider with 5+ requests in the same ms
            await asyncio.sleep(1.2)
    finally:
        await db.close()


def start_camera(camera_id: int, url: str, ai_enabled: bool = CAMERA_AI_DEFAULT_ENABLED):
    """Spawns the background loop for a camera."""
    if camera_id in _active_cameras:
        return
        
    _active_cameras[camera_id] = {
        "task": None,
        "analysis_task": None,
        "camera_id": camera_id,
        "frame_bytes": None,
        "latest_preview_frame": None,
        "latest_frame_ts": 0.0,
        "latest_frame_seq": 0,
        "last_analysis": 0,
        "ai_enabled": ai_enabled,
        "analysis_language": "en",
        "analysis_inflight": False,
        "backfill_inflight": False,
        "stop_flag": False,
        "current_analyzing_ts": None,
        "latest_analysis_frame": None,
        "previous_analysis_path": None,
        "last_analyzed_ts": 0,
        "last_analysis_duration": None,
        "last_motion_score": None,
        "last_changed_ratio": None,
        "waived_count": 0,
        "last_waived_ts": None,
        "last_waived_summary": None,
        "last_waived_event_type": None,
        "last_waived_severity": None,
        "ai_review_count": 0,
        "recent_ai_reviews": deque(maxlen=max(1, CAMERA_REVIEW_BUFFER_SIZE)),
        "last_ai_error": None,
        "last_ai_error_ts": None,
        "last_persisted_routine_event_ts": {},
        "adaptive_interval": CAMERA_FRAME_ANALYSIS_INTERVAL,
        "next_analysis_after": 0,
        "dvr_buffer": deque(maxlen=int(CAMERA_DVR_SECONDS * CAMERA_DVR_FPS)),
        "replay_frames": deque(),
        "analysis_frames": deque(),
        "recent_story_context": deque(maxlen=6),
    }
    
    loop = asyncio.get_running_loop()
    thread = threading.Thread(
        target=_camera_capture_worker,
        args=(camera_id, url, _active_cameras[camera_id]),
        daemon=True
    )
    thread.start()
    _active_cameras[camera_id]["task"] = thread
    _active_cameras[camera_id]["analysis_task"] = loop.create_task(
        _camera_analysis_loop(camera_id)
    )


def stop_camera(camera_id: int):
    """Signals the background loop to stop."""
    if camera_id in _active_cameras:
        state = _active_cameras[camera_id]
        state["stop_flag"] = True
        analysis_task = state.get("analysis_task")
        if analysis_task and not analysis_task.done():
            analysis_task.cancel()
        # cleanup happens naturally when the loop exits
        del _active_cameras[camera_id]


def set_camera_ai_state(camera_id: int, enabled: bool):
    """Toggles AI state dynamically for an active camera stream."""
    if camera_id in _active_cameras:
        state = _active_cameras[camera_id]
        state["ai_enabled"] = enabled
        if enabled:
            state["next_analysis_after"] = 0
            state["adaptive_interval"] = CAMERA_FRAME_ANALYSIS_INTERVAL
            request_camera_backfill(camera_id)


def set_camera_analysis_language(camera_id: int, language: str) -> str:
    """Sets the preferred free-text language for active camera AI reviews."""
    normalized = str(language or "en").strip().lower().split("-", 1)[0] or "en"
    if camera_id in _active_cameras:
        state = _active_cameras[camera_id]
        if state.get("analysis_language") != normalized:
            state["analysis_language"] = normalized
            state["next_analysis_after"] = 0
    return normalized


async def generate_mjpeg_stream(camera_id: int, fps: int = 30):
    """
    Async generator that yields JPEG bytes indefinitely.
    Used for FastAPI StreamingResponse.
    """
    if camera_id not in _active_cameras:
        return
        
    state = _active_cameras[camera_id]
    frame_interval = 1 / max(1, min(30, fps))
    
    while not state.get("stop_flag", True):
        frame = state.get("frame_bytes")

        if frame:
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
            await asyncio.sleep(frame_interval)
        else:
            await asyncio.sleep(0.1)
