"""
Lightweight runtime maintenance tasks.

Keeps temporary frame artifacts from growing without bound so long-running
demo sessions stay smooth and the workspace remains manageable.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import time
from pathlib import Path

from config import (
    CAMERA_FRAME_RETENTION_SEC,
    CACHE_FILE_RETENTION_SEC,
    FRAME_DIR,
    LIVE_FRAME_DIR_RETENTION_SEC,
    LOG_MAX_BYTES,
    LOG_RETENTION_SEC,
    QA_CROP_RETENTION_SEC,
    RUNTIME_CLEANUP_INTERVAL_SEC,
    TEMP_FILE_RETENTION_SEC,
    TEMP_DIR,
)

logger = logging.getLogger(__name__)

PROJECT_DIR = Path(__file__).resolve().parents[2]
_LOG_SUFFIXES = (".log", ".out", ".err")


def cleanup_runtime_artifacts() -> dict[str, int]:
    removed = {
        "temp_files": 0,
        "live_frame_dirs": 0,
        "camera_frame_files": 0,
        "qa_crop_files": 0,
        "empty_frame_dirs": 0,
        "pycache_dirs": 0,
        "old_log_files": 0,
        "trimmed_log_files": 0,
        "trimmed_log_bytes": 0,
        "vite_temp_dirs": 0,
    }
    now = time.time()

    removed["temp_files"] = _cleanup_old_files(TEMP_DIR, now, TEMP_FILE_RETENTION_SEC)
    removed["live_frame_dirs"] = _cleanup_live_frame_dirs(FRAME_DIR, now, LIVE_FRAME_DIR_RETENTION_SEC)
    removed["camera_frame_files"] = _cleanup_old_files_in_named_dirs(
        FRAME_DIR,
        now,
        CAMERA_FRAME_RETENTION_SEC,
        dir_prefixes=("cam_",),
        suffixes=(".jpg", ".jpeg"),
    )
    removed["qa_crop_files"] = _cleanup_old_files(
        FRAME_DIR / "qa_crops",
        now,
        QA_CROP_RETENTION_SEC,
        suffixes=(".jpg", ".jpeg"),
    )
    removed["empty_frame_dirs"] = _cleanup_empty_frame_dirs(FRAME_DIR)
    removed["pycache_dirs"] = _cleanup_pycache_dirs(Path(__file__).resolve().parents[1])
    removed["vite_temp_dirs"] = _cleanup_vite_temp_dirs(PROJECT_DIR, now, CACHE_FILE_RETENTION_SEC)

    log_files = list(_iter_log_files(PROJECT_DIR))
    removed["old_log_files"] = _cleanup_old_paths(log_files, now, LOG_RETENTION_SEC)
    trimmed = _trim_large_logs(_iter_log_files(PROJECT_DIR), LOG_MAX_BYTES)
    removed["trimmed_log_files"] = trimmed["files"]
    removed["trimmed_log_bytes"] = trimmed["bytes"]

    logger.info(
        "Runtime cleanup complete: temp_files=%d live_frame_dirs=%d camera_frame_files=%d "
        "qa_crop_files=%d empty_frame_dirs=%d pycache_dirs=%d old_log_files=%d "
        "trimmed_log_files=%d trimmed_log_bytes=%d vite_temp_dirs=%d",
        removed["temp_files"],
        removed["live_frame_dirs"],
        removed["camera_frame_files"],
        removed["qa_crop_files"],
        removed["empty_frame_dirs"],
        removed["pycache_dirs"],
        removed["old_log_files"],
        removed["trimmed_log_files"],
        removed["trimmed_log_bytes"],
        removed["vite_temp_dirs"],
    )
    return removed


async def run_periodic_cleanup() -> None:
    while True:
        await asyncio.sleep(max(60, RUNTIME_CLEANUP_INTERVAL_SEC))
        try:
            await asyncio.to_thread(cleanup_runtime_artifacts)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Periodic runtime cleanup failed")


def _cleanup_old_files(
    directory: Path,
    now: float,
    max_age_sec: int,
    suffixes: tuple[str, ...] | None = None,
) -> int:
    if not directory.exists():
        return 0

    removed = 0
    for path in directory.iterdir():
        try:
            if not path.is_file():
                continue
            if suffixes and path.suffix.lower() not in suffixes:
                continue
            if now - path.stat().st_mtime < max_age_sec:
                continue
            path.unlink(missing_ok=True)
            removed += 1
        except OSError:
            logger.debug("Failed to remove temp artifact: %s", path)
    return removed


def _cleanup_live_frame_dirs(directory: Path, now: float, max_age_sec: int) -> int:
    if not directory.exists():
        return 0

    removed = 0
    for path in directory.iterdir():
        try:
            if not path.is_dir() or not path.name.startswith("live_"):
                continue
            if now - path.stat().st_mtime < max_age_sec:
                continue
            shutil.rmtree(path, ignore_errors=True)
            removed += 1
        except OSError:
            logger.debug("Failed to remove stale live frame dir: %s", path)
    return removed


def _cleanup_old_files_in_named_dirs(
    directory: Path,
    now: float,
    max_age_sec: int,
    dir_prefixes: tuple[str, ...],
    suffixes: tuple[str, ...],
) -> int:
    if not directory.exists():
        return 0

    removed = 0
    for path in directory.iterdir():
        if not path.is_dir() or not path.name.startswith(dir_prefixes):
            continue
        removed += _cleanup_old_files(path, now, max_age_sec, suffixes=suffixes)
    return removed


def _cleanup_empty_frame_dirs(directory: Path) -> int:
    if not directory.exists():
        return 0

    removed = 0
    for path in directory.iterdir():
        try:
            if not path.is_dir() or path.name.isdigit():
                continue
            path.rmdir()
            removed += 1
        except OSError:
            continue
    return removed


def _cleanup_pycache_dirs(root: Path) -> int:
    removed = 0
    for path in root.rglob("__pycache__"):
        try:
            shutil.rmtree(path, ignore_errors=True)
            removed += 1
        except OSError:
            logger.debug("Failed to remove __pycache__: %s", path)
    return removed


def _iter_log_files(project_dir: Path):
    seen: set[Path] = set()
    candidates = [
        project_dir / ".cache" / "logs",
        project_dir / "server" / "runtime_logs",
        project_dir / "frontend" / "runtime_logs",
    ]
    for directory in candidates:
        if not directory.exists():
            continue
        for path in directory.rglob("*"):
            if path.is_file() and path.suffix.lower() in _LOG_SUFFIXES:
                resolved = path.resolve()
                if resolved not in seen:
                    seen.add(resolved)
                    yield path

    for pattern in ("*.log", "server/crash*.log"):
        for path in project_dir.glob(pattern):
            if path.is_file():
                resolved = path.resolve()
                if resolved not in seen:
                    seen.add(resolved)
                    yield path


def _cleanup_old_paths(paths, now: float, max_age_sec: int) -> int:
    if max_age_sec <= 0:
        return 0

    removed = 0
    for path in paths:
        try:
            if not path.exists() or not path.is_file():
                continue
            if now - path.stat().st_mtime < max_age_sec:
                continue
            path.unlink(missing_ok=True)
            removed += 1
        except OSError:
            logger.debug("Failed to remove old log file: %s", path)
    return removed


def _trim_large_logs(paths, max_bytes: int) -> dict[str, int]:
    if max_bytes <= 0:
        return {"files": 0, "bytes": 0}

    keep_bytes = max(64 * 1024, max_bytes // 2)
    trimmed_files = 0
    trimmed_bytes = 0

    for path in paths:
        try:
            if not path.exists() or not path.is_file():
                continue
            original_size = path.stat().st_size
            if original_size <= max_bytes:
                continue

            with path.open("rb") as handle:
                handle.seek(max(0, original_size - keep_bytes))
                tail = handle.read()

            marker = (
                f"\n--- Phylax log trimmed at {time.strftime('%Y-%m-%d %H:%M:%S')} "
                f"kept_last_bytes={len(tail)} original_bytes={original_size} ---\n"
            ).encode("utf-8")
            path.write_bytes(marker + tail)
            trimmed_files += 1
            trimmed_bytes += max(0, original_size - path.stat().st_size)
        except OSError:
            logger.debug("Failed to trim log file: %s", path)

    return {"files": trimmed_files, "bytes": trimmed_bytes}


def _cleanup_vite_temp_dirs(project_dir: Path, now: float, max_age_sec: int) -> int:
    if max_age_sec <= 0:
        return 0

    removed = 0
    for path in (
        project_dir / "frontend" / "node_modules" / ".vite-temp",
    ):
        try:
            if not path.exists() or not path.is_dir():
                continue
            if now - path.stat().st_mtime < max_age_sec:
                continue
            shutil.rmtree(path, ignore_errors=True)
            removed += 1
        except OSError:
            logger.debug("Failed to remove frontend temp cache: %s", path)
    return removed
