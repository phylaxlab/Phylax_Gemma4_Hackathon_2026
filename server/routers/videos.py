"""
Videos Router — CRUD endpoints for video management.
Handles upload, listing, retrieval, update, deletion, and streaming.

Upload is optimized for responsiveness: the file is saved and a DB
record is created immediately, then thumbnail generation and duration
extraction run as a background task so the user gets instant feedback.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, UploadFile, File, HTTPException, Query, BackgroundTasks
from fastapi.responses import FileResponse

from database import get_db
from config import MAX_UPLOAD_SIZE, FRAME_DIR
from services.video_service import (
    save_uploaded_video,
    validate_video_extension,
    get_video_duration,
    generate_thumbnail,
)
from models.schemas import VideoOut, VideoListOut, VideoUpdate

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/videos", tags=["videos"])


@router.post("/upload", response_model=VideoOut)
async def upload_video(
    file: UploadFile = File(...),
    title: Optional[str] = None,
    background_tasks: BackgroundTasks = None,
):
    """
    Upload a video file.

    The file is saved to disk and a database record is created immediately,
    giving the user an instant response.  Thumbnail generation and duration
    extraction are offloaded to a background task so the user does not have
    to wait.

    Analysis is NOT automatically triggered — call
    ``POST /api/analysis/start/{id}`` after upload.
    """
    # Validate extension
    if not validate_video_extension(file.filename):
        raise HTTPException(400, "Unsupported video format")

    # Read and validate size
    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(
            400, f"File too large. Max: {MAX_UPLOAD_SIZE // (1024*1024)}MB"
        )

    # Save file to disk
    filename, filepath = await save_uploaded_video(content, file.filename)

    video_title = title or Path(file.filename).stem

    # Insert a minimal DB record so we can respond immediately
    db = await get_db()
    try:
        cursor = await db.execute(
            """INSERT INTO videos (title, filename, filepath, duration, video_type, status)
               VALUES (?, ?, ?, 0, 'uploaded', 'pending')""",
            [video_title, filename, filepath],
        )
        await db.commit()
        video_id = cursor.lastrowid

        # Fetch the (incomplete) record to return right away
        cursor = await db.execute("SELECT * FROM videos WHERE id=?", [video_id])
        row = await cursor.fetchone()

        logger.info(
            "Uploaded video: id=%d title=%s (metadata extraction queued)",
            video_id,
            video_title,
        )

        # Schedule thumbnail + duration extraction in the background
        if background_tasks:
            background_tasks.add_task(
                _extract_metadata, video_id, filepath
            )

        return _row_to_video(row)
    finally:
        await db.close()


async def _extract_metadata(video_id: int, filepath: str):
    """
    Background task: extract video duration and generate a thumbnail.
    Updates the database record once finished.
    """
    try:
        duration = get_video_duration(filepath)
        thumb = generate_thumbnail(filepath, video_id)

        db = await get_db()
        try:
            if thumb:
                await db.execute(
                    "UPDATE videos SET duration=?, thumbnail=? WHERE id=?",
                    [duration, thumb, video_id],
                )
            else:
                await db.execute(
                    "UPDATE videos SET duration=? WHERE id=?",
                    [duration, video_id],
                )
            await db.commit()
            logger.info(
                "Metadata extracted for video %d: duration=%.1fs thumb=%s",
                video_id,
                duration,
                thumb,
            )
        finally:
            await db.close()
    except Exception as e:
        logger.error("Background metadata extraction failed for video %d: %s", video_id, e)


@router.get("", response_model=VideoListOut)
async def list_videos(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    video_type: Optional[str] = None,
):
    """List all videos with pagination and optional type filter."""
    db = await get_db()
    try:
        offset = (page - 1) * page_size

        # Build filter
        where = ""
        params = []
        if video_type:
            where = "WHERE video_type = ?"
            params.append(video_type)

        # Count total
        count_cursor = await db.execute(
            f"SELECT COUNT(*) as cnt FROM videos {where}", params
        )
        total = (await count_cursor.fetchone())["cnt"]

        # Fetch page
        cursor = await db.execute(
            f"""SELECT * FROM videos {where}
                ORDER BY upload_time DESC
                LIMIT ? OFFSET ?""",
            params + [page_size, offset],
        )
        rows = await cursor.fetchall()

        return VideoListOut(
            videos=[_row_to_video(r) for r in rows],
            total=total,
            page=page,
            page_size=page_size,
        )
    finally:
        await db.close()


@router.get("/{video_id}", response_model=VideoOut)
async def get_video(video_id: int):
    """Get a single video by ID."""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM videos WHERE id=?", [video_id])
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(404, "Video not found")
        return _row_to_video(row)
    finally:
        await db.close()


@router.put("/{video_id}", response_model=VideoOut)
async def update_video(video_id: int, payload: VideoUpdate):
    """Update a video's details (e.g., title)."""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM videos WHERE id=?", [video_id])
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(404, "Video not found")

        if payload.title is not None:
            await db.execute(
                "UPDATE videos SET title=? WHERE id=?", [payload.title, video_id]
            )
            await db.commit()

        cursor = await db.execute("SELECT * FROM videos WHERE id=?", [video_id])
        row = await cursor.fetchone()
        
        logger.info("Updated video: id=%d", video_id)
        return _row_to_video(row)
    finally:
        await db.close()


@router.delete("/{video_id}")
async def delete_video(video_id: int):
    """Delete a video and all associated data (files, thumbnails, frames)."""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM videos WHERE id=?", [video_id])
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(404, "Video not found")

        # Delete video file from disk
        filepath = Path(row["filepath"])
        if filepath.exists():
            filepath.unlink()

        # Delete thumbnail
        if row["thumbnail"]:
            from config import THUMBNAIL_DIR
            thumb_path = THUMBNAIL_DIR / row["thumbnail"]
            if thumb_path.exists():
                thumb_path.unlink()

        # Delete extracted frames directory
        frames_dir = FRAME_DIR / str(video_id)
        if frames_dir.exists():
            shutil.rmtree(frames_dir, ignore_errors=True)

        # Delete from DB (cascades to analysis_events)
        await db.execute("DELETE FROM videos WHERE id=?", [video_id])
        await db.commit()

        logger.info("Deleted video: id=%d", video_id)
        return {"detail": "Video deleted", "id": video_id}
    finally:
        await db.close()


@router.get("/{video_id}/stream")
async def stream_video(video_id: int):
    """
    Stream a video file with support for range requests.
    Returns the video file for HTML5 video player consumption.
    """
    db = await get_db()
    try:
        cursor = await db.execute("SELECT filepath FROM videos WHERE id=?", [video_id])
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(404, "Video not found")

        filepath = Path(row["filepath"])
        if not filepath.exists():
            raise HTTPException(404, "Video file missing from disk")

        return FileResponse(
            str(filepath),
            media_type="video/mp4",
            filename=filepath.name,
        )
    finally:
        await db.close()


def _row_to_video(row) -> VideoOut:
    """Convert a database row to a VideoOut schema."""
    return VideoOut(
        id=row["id"],
        title=row["title"],
        filename=row["filename"],
        thumbnail=row["thumbnail"],
        duration=row["duration"] or 0,
        upload_time=row["upload_time"],
        video_type=row["video_type"],
        status=row["status"],
        analysis_progress=row["analysis_progress"] or 0,
    )
