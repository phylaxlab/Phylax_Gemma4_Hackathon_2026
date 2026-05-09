"""
Camera QA service.

Adapts recent camera events and AI reviews into the same timeline-question
flow used by uploaded videos. Evidence is limited to event text and original
frame snapshots.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from config import CAMERA_DVR_SECONDS
from services.video_qa_service import _normalize_language, _qa_text, answer_video_question


def answer_camera_question(
    camera: dict[str, Any],
    event_rows: list[dict[str, Any]],
    review_rows: list[dict[str, Any]],
    *,
    question: str,
    language: Optional[str] = None,
    current_timestamp_sec: Optional[float] = None,
    history: Optional[list[dict[str, Any]]] = None,
    live_frame_path: Optional[str] = None,
    anchor_frames: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    language = _normalize_language(language, question)
    combined_rows = _build_camera_timeline_rows(
        event_rows,
        review_rows,
        language=language,
        live_frame_path=live_frame_path,
        anchor_frames=anchor_frames,
    )

    if not combined_rows:
        return {
            "answer": _qa_text(language, "empty_answer"),
            "confidence": "low",
            "relevant_events": [],
            "current_timestamp_sec": current_timestamp_sec,
            "follow_up_suggestion": _qa_text(language, "empty_follow_up"),
            "agent_trace": [],
            "reconstruction": None,
        }

    latest_ts = max(float(row.get("timestamp_sec") or 0.0) for row in combined_rows)
    earliest_ts = min(float(row.get("timestamp_sec") or latest_ts) for row in combined_rows)
    anchor_abs = float(current_timestamp_sec) if current_timestamp_sec is not None else latest_ts
    window_start_ts = max(earliest_ts, latest_ts - float(CAMERA_DVR_SECONDS))
    duration = max(1.0, latest_ts - window_start_ts)

    relative_rows = [
        {
            **row,
            "timestamp_sec": max(0.0, float(row.get("timestamp_sec") or 0.0) - window_start_ts),
        }
        for row in combined_rows
    ]

    pseudo_video = {
        "title": camera.get("name") or f"Camera {camera.get('id') or 'unknown'}",
        "duration": duration,
        "status": "live camera recent window (0:00 oldest buffered frame, end of timeline newest frame)",
        "source": "camera",
        "qa_mode": "camera_direct",
    }

    response = answer_video_question(
        pseudo_video,
        relative_rows,
        question=question,
        language=language,
        current_timestamp_sec=max(0.0, anchor_abs - window_start_ts),
        history=history or [],
    )

    for event in response.get("relevant_events", []):
        event["timestamp_sec"] = float(event.get("timestamp_sec") or 0.0) + window_start_ts
    reconstruction = response.get("reconstruction") or {}
    if isinstance(reconstruction, dict):
        for beat in reconstruction.get("story_beats") or []:
            if isinstance(beat, dict):
                beat["timestamp_sec"] = float(beat.get("timestamp_sec") or 0.0) + window_start_ts
    if response.get("current_timestamp_sec") is not None:
        response["current_timestamp_sec"] = float(response["current_timestamp_sec"]) + window_start_ts
    return response


def _build_camera_timeline_rows(
    event_rows: list[dict[str, Any]],
    review_rows: list[dict[str, Any]],
    *,
    language: str = "en",
    live_frame_path: Optional[str] = None,
    anchor_frames: Optional[list[dict[str, Any]]] = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    for row in event_rows:
        rows.append(_coerce_timeline_row(row, event_id=int(row.get("id") or 0)))

    for row in review_rows:
        review_id = -abs(int(row.get("id") or 0))
        rows.append(_coerce_timeline_row(row, event_id=review_id))

    evidence_rows = list(rows)
    for index, frame in enumerate(anchor_frames or []):
        anchor_row = _build_anchor_frame_row(
            frame,
            index=index,
            language=language,
            related_row=_find_nearest_evidence_row(evidence_rows, frame),
            live_frame_path=live_frame_path,
        )
        if anchor_row:
            rows.append(anchor_row)

    rows.sort(key=lambda item: (float(item.get("timestamp_sec") or 0.0), int(item.get("id") or 0)))
    return rows


def _coerce_timeline_row(row: dict[str, Any], *, event_id: int) -> dict[str, Any]:
    return {
        "id": event_id,
        "timestamp_sec": float(row.get("timestamp_sec") or 0.0),
        "frame_path": row.get("frame_path"),
        "description": row.get("description") or row.get("summary") or "",
        "event_type": row.get("event_type") or "none",
        "severity": row.get("severity") or "Normal",
        "summary": row.get("summary") or "",
        "keywords": row.get("keywords") or "",
        "raw_json": row.get("raw_json") or "{}",
    }


def _build_anchor_frame_row(
    frame: dict[str, Any],
    *,
    index: int,
    language: str = "en",
    related_row: Optional[dict[str, Any]] = None,
    live_frame_path: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    if not isinstance(frame, dict):
        return None
    timestamp_sec = float(frame.get("timestamp_sec") or 0.0)
    frame_path = frame.get("abs_path") or frame.get("frame_path") or live_frame_path
    if timestamp_sec <= 0 or not frame_path:
        return None

    reference_text = _camera_qa_static_text(language, "reference_frame")
    selected_text = _camera_qa_static_text(language, "reference_frame_selected")
    nearby_prefix = _camera_qa_static_text(language, "nearby_analyzed_clue")
    related_summary = _clean_text((related_row or {}).get("summary")) or _clean_text((related_row or {}).get("description"))
    changes = [selected_text]
    if related_summary:
        changes.append(f"{nearby_prefix}{related_summary}")

    payload = {
        "changes_detected": changes,
        "keywords": ["anchor", "replay", "current", "visual", "position"],
        "anchor_frame": True,
    }
    return {
        "id": -900000000 - index,
        "timestamp_sec": timestamp_sec,
        "frame_path": frame_path,
        "description": reference_text,
        "event_type": (related_row or {}).get("event_type") or "motion",
        "severity": (related_row or {}).get("severity") or "Normal",
        "summary": _camera_qa_static_text(language, "reference_frame_summary"),
        "keywords": ",".join(payload["keywords"]),
        "raw_json": json.dumps(payload, ensure_ascii=False),
    }


def _camera_qa_static_text(language: str, key: str) -> str:
    lang = str(language or "en").split("-", 1)[0].lower()
    messages = {
        "en": {
            "reference_frame": "Reference frame near the current playback point.",
            "reference_frame_summary": "Reference frame near current playback point",
            "reference_frame_selected": "Reference frame selected near the current playback point.",
            "nearby_analyzed_clue": "Nearby analyzed clue: ",
        },
        "zh": {
            "reference_frame": "目前播放位置附近的參考畫面。",
            "reference_frame_summary": "目前播放位置附近的參考畫面",
            "reference_frame_selected": "已選取目前播放位置附近的參考畫面。",
            "nearby_analyzed_clue": "附近已分析線索：",
        },
        "es": {
            "reference_frame": "Fotograma de referencia cerca del punto de reproducción actual.",
            "reference_frame_summary": "Fotograma de referencia cerca del punto actual",
            "reference_frame_selected": "Fotograma de referencia seleccionado cerca del punto de reproducción actual.",
            "nearby_analyzed_clue": "Pista analizada cercana: ",
        },
        "fr": {
            "reference_frame": "Image de référence près du point de lecture actuel.",
            "reference_frame_summary": "Image de référence près du point actuel",
            "reference_frame_selected": "Image de référence sélectionnée près du point de lecture actuel.",
            "nearby_analyzed_clue": "Indice analysé à proximité : ",
        },
        "ja": {
            "reference_frame": "現在の再生位置付近の参照フレーム。",
            "reference_frame_summary": "現在の再生位置付近の参照フレーム",
            "reference_frame_selected": "現在の再生位置付近の参照フレームを選択しました。",
            "nearby_analyzed_clue": "近くの解析済み手がかり：",
        },
        "ko": {
            "reference_frame": "현재 재생 위치 근처의 참조 프레임입니다.",
            "reference_frame_summary": "현재 재생 위치 근처의 참조 프레임",
            "reference_frame_selected": "현재 재생 위치 근처의 참조 프레임이 선택되었습니다.",
            "nearby_analyzed_clue": "근처 분석 단서: ",
        },
    }
    return messages.get(lang, messages["en"]).get(key, messages["en"][key])


def _find_nearest_evidence_row(
    rows: list[dict[str, Any]],
    frame: dict[str, Any],
    *,
    threshold_sec: float = 12.0,
) -> Optional[dict[str, Any]]:
    timestamp = float(frame.get("timestamp_sec") or 0.0)
    if timestamp <= 0 or not rows:
        return None
    nearest = min(rows, key=lambda row: abs(float(row.get("timestamp_sec") or 0.0) - timestamp))
    if abs(float(nearest.get("timestamp_sec") or 0.0) - timestamp) > threshold_sec:
        return None
    return nearest


def _clean_text(value: Any) -> str:
    return str(value or "").strip()
