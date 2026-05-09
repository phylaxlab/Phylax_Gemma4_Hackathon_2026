"""
Stream Router — WebSocket endpoint for live webcam streaming
and session management endpoints.
"""

from __future__ import annotations

import json
import logging
import asyncio
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException

from database import get_db
from config import LIVE_FRAME_ANALYSIS_INTERVAL
from services.stream_service import (
    append_recent_analysis_context,
    create_session,
    get_recent_analysis_context,
    get_latest_frames,
    get_latest_frame_candidate,
    is_analysis_inflight,
    is_session_active,
    save_frame,
    set_analysis_inflight,
    should_analyze,
    stop_session,
)
from services.ai_service import analyze_frames, build_timeline_story_entry
from services.security_service import websocket_is_authorized
from models.schemas import LiveSessionCreate, LiveSessionOut

logger = logging.getLogger(__name__)
router = APIRouter(tags=["stream"])


async def _send_json(websocket: WebSocket, send_lock: asyncio.Lock, payload: dict):
    async with send_lock:
        await websocket.send_json(payload)


async def _run_live_analysis(
    websocket: WebSocket,
    send_lock: asyncio.Lock,
    session_id: int,
    current_frame: str,
    prev_frame: str,
    *,
    frame_timestamp: float,
):
    """Analyze frames without blocking the main WebSocket receive loop."""
    try:
        timeline_context = get_recent_analysis_context(session_id)
        result = await asyncio.to_thread(
            analyze_frames,
            current_frame_path=current_frame,
            previous_frame_path=prev_frame,
            current_timestamp=0,
            previous_timestamp=0,
            profile="live",
            timeline_context=timeline_context,
        )

        if result:
            story_entry = build_timeline_story_entry(result, timestamp=frame_timestamp, source="live")
            append_recent_analysis_context(session_id, story_entry)
            await _send_json(websocket, send_lock, {
                "type": "analysis",
                "data": result,
            })
    except Exception as exc:
        logger.error("Live analysis failed for session %d: %s", session_id, exc)
    finally:
        set_analysis_inflight(session_id, False)


@router.post("/api/stream/start", response_model=LiveSessionOut)
async def start_stream(body: LiveSessionCreate):
    """Create a new live stream session."""
    session_id = await create_session(body.title)

    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM live_sessions WHERE id=?", [session_id]
        )
        row = await cursor.fetchone()
        return LiveSessionOut(
            id=row["id"],
            title=row["title"],
            start_time=row["start_time"],
            end_time=row["end_time"],
            status=row["status"],
            video_id=row["video_id"],
        )
    finally:
        await db.close()


@router.post("/api/stream/stop/{session_id}")
async def stop_stream(session_id: int):
    """
    Stop a live stream session.
    Assembles the recorded frames into a video and creates a video record.
    """
    if not is_session_active(session_id):
        raise HTTPException(404, "Session not found or already stopped")

    video_id = await stop_session(session_id)

    return {
        "detail": "Stream stopped",
        "session_id": session_id,
        "video_id": video_id,
    }

@router.post("/api/stream/{session_id}/export")
async def export_stream_dvr(session_id: int):
    """Dynamically compile up to the last 2 minutes of webcam frames and save to DB."""
    from services.stream_service import _active_sessions
    from config import VIDEO_DIR
    
    session = _active_sessions.get(session_id)
    if not session or not session.get("dvr_buffer"):
        raise HTTPException(404, "No frames available for this session yet")
        
    # Freezing buffer to list for thread-safe iteration
    frames = list(session["dvr_buffer"])
    
    import cv2, time, asyncio
    
    video_filename = f"dvr_export_stream_{session_id}_{int(time.time())}.mp4"
    out_path = VIDEO_DIR / video_filename
    
    # Use temp paths for intermediate processing
    raw_filename = f"raw_{video_filename}"
    raw_path = VIDEO_DIR / raw_filename
    
    def _compile():
        try:
            h, w = frames[0].shape[:2]
            fourcc = cv2.VideoWriter_fourcc(*'mp4v') # Reliable intermediate codec
            writer = cv2.VideoWriter(str(raw_path), fourcc, 2.0, (w, h))  # 2 FPS
            
            for img in frames:
                if img is not None:
                    writer.write(img)
            writer.release()
            
            # --- Re-encode with FFmpeg for Browser Compatibility (H.264) ---
            import subprocess
            cmd = [
                "ffmpeg", "-i", str(raw_path),
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-pix_fmt", "yuv420p",
                "-y", str(out_path)
            ]
            subprocess.run(cmd, check=True, capture_output=True)
            
            if raw_path.exists():
                raw_path.unlink()
                
            return None
        except Exception as e:
            if raw_path.exists(): raw_path.unlink()
            return str(e)
            
    err = await asyncio.to_thread(_compile)
    if err:
        raise HTTPException(500, f"Compile error: {err}")
    
    if not out_path.exists():
        raise HTTPException(500, "Failed to compile export video")
        
    db = await get_db()
    try:
        # Post-process: Calculate metadata
        from services.video_service import get_video_duration, generate_thumbnail
        duration = get_video_duration(str(out_path))
        
        # Insert initial record to get ID for thumbnail
        cursor = await db.execute(
            "INSERT INTO videos (title, filename, filepath, duration, video_type) VALUES (?, ?, ?, ?, ?)",
            [f"DVR Export: Live Session {session['title']}", video_filename, str(out_path), duration, "uploaded"]
        )
        video_id = cursor.lastrowid
        
        # Generate thumbnail
        thumbnail_path = generate_thumbnail(str(out_path), video_id)
        if thumbnail_path:
             await db.execute("UPDATE videos SET thumbnail=? WHERE id=?", [thumbnail_path, video_id])
             
        await db.commit()
        return {"video_id": video_id}
    finally:
        await db.close()


@router.websocket("/ws/stream/{session_id}")
async def websocket_stream(websocket: WebSocket, session_id: int):
    """
    WebSocket endpoint for receiving live webcam frames.

    Protocol:
    - Client sends binary messages (JPEG frame data).
    - Server responds with JSON analysis results when available.
    """
    if not websocket_is_authorized(websocket):
        await websocket.close(code=4401, reason="Authentication required")
        return

    if not is_session_active(session_id):
        await websocket.close(code=4004, reason="Session not found")
        return

    await websocket.accept()
    logger.info("WebSocket connected for session %d", session_id)
    send_lock = asyncio.Lock()

    try:
        while True:
            # Receive binary frame data from the client
            frame_data = await websocket.receive_bytes()

            # Save the frame
            frame_path = await save_frame(session_id, frame_data)

            if not frame_path:
                continue

            # Check if it's time for AI analysis
            if should_analyze(session_id, LIVE_FRAME_ANALYSIS_INTERVAL) and not is_analysis_inflight(session_id):
                current_frame, prev_frame = get_latest_frames(session_id)
                current_candidate = get_latest_frame_candidate(session_id)

                if current_frame and current_candidate:
                    set_analysis_inflight(session_id, True)
                    asyncio.create_task(
                        _run_live_analysis(
                            websocket,
                            send_lock,
                            session_id,
                            current_frame,
                            prev_frame,
                            frame_timestamp=float(current_candidate["timestamp"]),
                        )
                    )

            # Acknowledge frame receipt immediately so capture stays smooth.
            await _send_json(websocket, send_lock, {"type": "ack"})

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected for session %d", session_id)
    except Exception as e:
        logger.error("WebSocket error for session %d: %s", session_id, str(e))
        await websocket.close(code=1011, reason="Internal error")
