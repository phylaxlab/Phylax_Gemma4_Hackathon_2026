"""
Stream Service — Manages live webcam stream sessions.
Handles saving incoming frames, triggering AI analysis,
and assembling recordings.
"""

from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path
from typing import Any, Dict, Optional
from datetime import datetime

import cv2
import numpy as np

from config import VIDEO_DIR, FRAME_DIR
from database import get_db

from collections import deque

# Active sessions stored in memory
_active_sessions: Dict[int, dict] = {}


async def create_session(title: str) -> int:
    """
    Create a new live stream session in the database.
    Returns the session ID.
    """
    db = await get_db()
    try:
        cursor = await db.execute(
            "INSERT INTO live_sessions (title) VALUES (?)",
            [title],
        )
        await db.commit()
        session_id = cursor.lastrowid

        # Prepare in-memory state
        session_dir = FRAME_DIR / f"live_{session_id}"
        session_dir.mkdir(parents=True, exist_ok=True)

        _active_sessions[session_id] = {
            "title": title,
            "frame_count": 0,
            "start_time": time.time(),
            "last_analysis_time": 0,
            "analysis_inflight": False,
            "session_dir": str(session_dir),
            "frames": [], # Deprecated: disk paths
            "dvr_buffer": deque(maxlen=240), # 2 Minutes @ 2 FPS
            "latest_frame_image": None,
            "latest_frame_ts": 0.0,
            "latest_frame_seq": 0,
            "latest_frame_path": None,
            "recent_analysis_context": deque(maxlen=4),
        }

        logger.info("Created live session %d: %s", session_id, title)
        return session_id
    finally:
        await db.close()


async def save_frame(session_id: int, frame_data: bytes) -> Optional[str]:
    """
    Save an incoming webcam frame from WebSocket.

    Args:
        session_id: The active session ID.
        frame_data: Raw image bytes (JPEG).

    Returns:
        Path to the saved frame file, or None on failure.
    """
    session = _active_sessions.get(session_id)
    if not session:
        logger.warning("No active session %d", session_id)
        return None

    session["frame_count"] += 1
    frame_filename = f"frame_{session['frame_count']:06d}.jpg"
    frame_path = Path(session["session_dir"]) / frame_filename

    # Still save to disk optionally for the 'Realtime AI' to pick up individual frames if enabled
    # but primarily feed the memory buffer for instant Export
    with open(frame_path, "wb") as f:
        f.write(frame_data)

    # Decode for memory buffer (2 FPS throttling happens in routers/stream.py usually, 
    # but we'll append here. Throttling is better handled at the source).
    nparr = np.frombuffer(frame_data, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is not None:
        resized = cv2.resize(img, (640, 360))
        session["dvr_buffer"].append(resized)
        session["latest_frame_image"] = img
        session["latest_frame_ts"] = time.time()
        session["latest_frame_seq"] = session["frame_count"]
        session["latest_frame_path"] = str(frame_path)

    session["frames"].append(str(frame_path))
    return str(frame_path)


def should_analyze(session_id: int, interval_sec: float = 5.0) -> bool:
    """
    Check if enough time has passed since the last analysis
    for this session.
    """
    session = _active_sessions.get(session_id)
    if not session:
        return False

    now = time.time()
    if now - session["last_analysis_time"] >= interval_sec:
        session["last_analysis_time"] = now
        return True
    return False


def is_analysis_inflight(session_id: int) -> bool:
    session = _active_sessions.get(session_id)
    if not session:
        return False
    return bool(session.get("analysis_inflight"))


def set_analysis_inflight(session_id: int, inflight: bool) -> None:
    session = _active_sessions.get(session_id)
    if session is not None:
        session["analysis_inflight"] = inflight


def get_latest_frames(session_id: int) -> tuple:
    """
    Get the current and previous frame paths for analysis.
    Returns (current_frame_path, previous_frame_path) or (None, None).
    """
    session = _active_sessions.get(session_id)
    if not session or not session["frames"]:
        return None, None

    current = session["frames"][-1]
    previous = session["frames"][-2] if len(session["frames"]) > 1 else None
    return current, previous


def get_latest_frame_candidate(session_id: int) -> Optional[dict]:
    session = _active_sessions.get(session_id)
    if not session:
        return None

    image = session.get("latest_frame_image")
    if image is None:
        return None

    return {
        "image": image.copy(),
        "seq": int(session.get("latest_frame_seq") or 0),
        "timestamp": float(session.get("latest_frame_ts") or 0),
        "path": session.get("latest_frame_path"),
    }


def get_recent_analysis_context(session_id: int) -> list[dict[str, Any]]:
    session = _active_sessions.get(session_id)
    if not session:
        return []
    history = session.get("recent_analysis_context") or []
    return [dict(item) for item in history if isinstance(item, dict)]


def append_recent_analysis_context(session_id: int, entry: Optional[dict[str, Any]]) -> None:
    if not entry:
        return
    session = _active_sessions.get(session_id)
    if not session:
        return
    history = session.get("recent_analysis_context")
    if history is None:
        history = deque(maxlen=4)
        session["recent_analysis_context"] = history
    history.append(dict(entry))


async def stop_session(session_id: int) -> Optional[int]:
    """
    Stop a live session: assemble frames into a video file and
    create a video record in the database.

    Returns:
        The video_id of the assembled recording, or None on failure.
    """
    session = _active_sessions.pop(session_id, None)
    if not session:
        logger.warning("Session %d not found or already stopped", session_id)
        return None

    db = await get_db()
    try:
        await db.execute(
            "UPDATE live_sessions SET end_time=datetime('now'), status='stopped' WHERE id=?",
            [session_id],
        )
        await db.commit()
    finally:
        await db.close()

    # Assemble frames into MP4 if we have enough
    video_id = None
    if len(session["frames"]) >= 2:
        video_filename = f"live_recording_{session_id}.mp4"
        video_path = VIDEO_DIR / video_filename

        # Read first frame to get dimensions
        first_frame = cv2.imread(session["frames"][0])
        if first_frame is not None:
            h, w = first_frame.shape[:2]
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            writer = cv2.VideoWriter(str(video_path), fourcc, 10, (w, h))

            for fp in session["frames"]:
                frame = cv2.imread(fp)
                if frame is not None:
                    writer.write(frame)

            writer.release()

            # Create video record in DB
            db = await get_db()
            try:
                cursor = await db.execute(
                    """INSERT INTO videos (title, filename, filepath, video_type, status)
                       VALUES (?, ?, ?, 'live', 'done')""",
                    [session["title"], video_filename, str(video_path)],
                )
                await db.commit()
                video_id = cursor.lastrowid

                # Link session to video
                await db.execute(
                    "UPDATE live_sessions SET video_id=? WHERE id=?",
                    [video_id, session_id],
                )
                await db.commit()
            finally:
                await db.close()

            logger.info("Assembled live recording: %s (video_id=%s)", video_path, video_id)

    session_dir = Path(session.get("session_dir") or "")
    if session_dir.exists():
        shutil.rmtree(session_dir, ignore_errors=True)

    return video_id


def is_session_active(session_id: int) -> bool:
    """Check if a session is currently active."""
    return session_id in _active_sessions
