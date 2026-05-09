"""
Video Service — Handles video file management and frame extraction.
Uses OpenCV for frame extraction and thumbnail generation.
"""

from __future__ import annotations

import uuid
import logging
from pathlib import Path
from typing import Optional, List, Tuple

import cv2
from PIL import Image

from config import (
    VIDEO_DIR,
    FRAME_DIR,
    THUMBNAIL_DIR,
    ALLOWED_VIDEO_EXTENSIONS,
    VIDEO_ANALYSIS_WIDTH,
    VIDEO_ANALYSIS_HEIGHT,
)

logger = logging.getLogger(__name__)


def generate_unique_filename(original_filename: str) -> str:
    """
    Generate a unique filename preserving the original extension.
    Uses UUID4 to avoid collisions.
    """
    ext = Path(original_filename).suffix.lower()
    return f"{uuid.uuid4().hex}{ext}"


async def save_uploaded_video(file_content: bytes, original_filename: str) -> Tuple[str, str]:
    """
    Save uploaded video bytes to the videos directory.

    Returns:
        Tuple of (unique_filename, full_filepath)
    """
    filename = generate_unique_filename(original_filename)
    filepath = VIDEO_DIR / filename

    with open(filepath, "wb") as f:
        f.write(file_content)

    logger.info("Saved uploaded video: %s -> %s", original_filename, filepath)
    return filename, str(filepath)


def validate_video_extension(filename: str) -> bool:
    """Check if the file extension is in the allowed set."""
    ext = Path(filename).suffix.lower()
    return ext in ALLOWED_VIDEO_EXTENSIONS


def get_video_duration(video_path: str) -> float:
    """
    Get the duration of a video file in seconds using OpenCV.
    Returns 0.0 if the video cannot be opened.
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        logger.warning("Cannot open video for duration: %s", video_path)
        return 0.0

    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    cap.release()

    if fps <= 0:
        return 0.0

    return frame_count / fps


def generate_thumbnail(video_path: str, video_id: int) -> Optional[str]:
    """
    Extract the first meaningful frame from a video and save as a JPEG thumbnail.

    Returns:
        Relative path to the thumbnail file, or None on failure.
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        logger.warning("Cannot open video for thumbnail: %s", video_path)
        return None

    # Skip ahead a bit for a more representative frame (1 second in)
    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps > 0:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(fps))

    ret, frame = cap.read()
    cap.release()

    if not ret:
        logger.warning("Cannot read frame for thumbnail: %s", video_path)
        return None

    thumb_filename = f"thumb_{video_id}.jpg"
    thumb_path = THUMBNAIL_DIR / thumb_filename

    # Resize to a consistent thumbnail size (320x180, 16:9)
    thumb_frame = cv2.resize(frame, (320, 180))
    cv2.imwrite(str(thumb_path), thumb_frame, [cv2.IMWRITE_JPEG_QUALITY, 85])

    logger.info("Generated thumbnail: %s", thumb_path)
    return thumb_filename


def extract_frames(
    video_path: str,
    video_id: int,
    interval_sec: float = 5.0,
    target_width: int = VIDEO_ANALYSIS_WIDTH,
    target_height: int = VIDEO_ANALYSIS_HEIGHT,
    jpeg_quality: int = 78,
) -> List[Tuple[str, float]]:
    """
    Extract frames from a video at regular intervals.

    Args:
        video_path: Path to the video file.
        video_id: Database ID for naming frames.
        interval_sec: Seconds between extracted frames.

    Returns:
        List of (frame_file_path, timestamp_sec) tuples.
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        logger.error("Cannot open video for frame extraction: %s", video_path)
        return []

    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    if fps <= 0:
        logger.error("Invalid FPS for video: %s", video_path)
        cap.release()
        return []

    frame_interval = max(1, int(fps * max(0.1, float(interval_sec or 5.0))))
    frames_dir = FRAME_DIR / str(video_id)
    frames_dir.mkdir(parents=True, exist_ok=True)

    extracted: List[Tuple[str, float]] = []
    frame_idx = 0

    while True:
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = cap.read()

        if not ret:
            break

        timestamp = frame_idx / fps
        frame_filename = f"frame_{frame_idx:06d}.jpg"
        frame_path = frames_dir / frame_filename

        # Resize and compress based on the selected per-run analysis mode.
        resized_frame = cv2.resize(frame, (target_width, target_height))
        cv2.imwrite(str(frame_path), resized_frame, [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality])
        extracted.append((str(frame_path), timestamp))

        frame_idx += frame_interval
        if frame_idx >= total_frames:
            break

    cap.release()
    logger.info(
        "Extracted %d frames from video %d (interval=%.1fs)",
        len(extracted),
        video_id,
        interval_sec,
    )
    return extracted


def estimate_motion_score(previous_frame_path: str, current_frame_path: str) -> tuple[int, float]:
    """
    Estimate coarse frame-to-frame motion on a 0-10 scale.
    Returns (motion_score, changed_area_ratio_percent).
    """
    prev = cv2.imread(str(previous_frame_path), cv2.IMREAD_GRAYSCALE)
    curr = cv2.imread(str(current_frame_path), cv2.IMREAD_GRAYSCALE)
    if prev is None or curr is None:
        return 10, 100.0

    if prev.shape != curr.shape:
        curr = cv2.resize(curr, (prev.shape[1], prev.shape[0]))

    diff = cv2.absdiff(prev, curr)
    _, thresh = cv2.threshold(diff, 22, 255, cv2.THRESH_BINARY)
    changed_ratio = (cv2.countNonZero(thresh) / thresh.size) * 100.0

    motion_score = min(10, max(0, int(round(changed_ratio / 2.4))))
    return motion_score, changed_ratio
