"""
Timeline QA service.

Answers questions from analyzed event rows using the Gemma/Ollama text+image
model. Evidence comes from event text, timestamps, and original frame previews.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

from services.ai_service import ask_gemma, translate_event_texts


SUPPORTED_QA_LANGUAGES = {"en", "zh", "es", "fr", "ja", "ko"}

LANGUAGE_NAMES = {
    "en": "English",
    "zh": "Traditional Chinese",
    "es": "Spanish",
    "fr": "French",
    "ja": "Japanese",
    "ko": "Korean",
}

QA_TEXT = {
    "en": {
        "timeline_evidence_summary": "Timeline evidence summary",
        "timeline_clue": "Timeline clue",
        "fallback_answer_prefix": "The most relevant clues are ",
        "empty_answer": "There are not enough timeline clues yet. Run analysis first or let the camera collect more events.",
        "empty_follow_up": "Ask again once the timeline contains events.",
        "follow_up": "You can ask about a specific timestamp or ask what changed before and after it.",
        "review_focus_1": "Review the referenced original frames",
        "review_focus_2": "Check moments immediately before and after the highlighted timestamps",
        "open_question_1": "Off-frame or low-resolution details may remain uncertain",
        "reconstruction_summary": "I used the most relevant timeline events and frame evidence to answer. If details are not visible in the available frames, a human review of the referenced timestamps is still needed.",
        "trace_scan_title": "Timeline scan",
        "trace_scan_detail": "Reviewed {total_events} analyzed timeline events.",
        "trace_interpret_title": "Evidence shortlist",
        "trace_interpret_detail": "Selected {selected_events} relevant clues and {image_count} frame preview(s).",
    },
    "zh": {
        "timeline_evidence_summary": "時間軸線索摘要",
        "timeline_clue": "時間軸線索",
        "fallback_answer_prefix": "目前最相關的線索是：",
        "empty_answer": "目前還沒有足夠的時間軸線索。請先完成分析或讓攝影機再收集一些事件。",
        "empty_follow_up": "等時間軸產生後，再詢問特定人物、車輛或事件。",
        "follow_up": "可以指定一個時間點，或問我「前後發生了什麼變化？」",
        "review_focus_1": "回看相關時間點的原始畫面",
        "review_focus_2": "確認事件前後是否有進一步變化",
        "open_question_1": "畫面外或解析度不足的細節可能無法完全確認",
        "reconstruction_summary": "我依照最相關的時間軸事件與畫面線索整理回答。若畫面資訊不足，仍需要人工回看相關時間點確認細節。",
        "trace_scan_title": "掃描時間軸",
        "trace_scan_detail": "已檢視 {total_events} 個分析事件。",
        "trace_interpret_title": "整理關鍵線索",
        "trace_interpret_detail": "已挑出 {selected_events} 個相關線索與 {image_count} 張預覽畫面。",
    },
    "es": {
        "timeline_evidence_summary": "Resumen de evidencias de la linea temporal",
        "timeline_clue": "Pista temporal",
        "fallback_answer_prefix": "Las pistas mas relevantes son: ",
        "empty_answer": "Todavia no hay suficientes pistas en la linea temporal. Ejecuta el analisis primero o deja que la camara recoja mas eventos.",
        "empty_follow_up": "Vuelve a preguntar cuando la linea temporal tenga mas eventos.",
        "follow_up": "Puedes preguntar por una marca de tiempo concreta o por lo que cambio antes y despues.",
        "review_focus_1": "Revisa los fotogramas originales indicados",
        "review_focus_2": "Comprueba los momentos justo antes y despues de las marcas destacadas",
        "open_question_1": "Los detalles fuera de cuadro o con baja resolucion pueden seguir siendo inciertos",
        "reconstruction_summary": "Use los eventos mas relevantes de la linea temporal y la evidencia visual para responder. Si algun detalle no se ve bien, aun hace falta una revision humana de los tiempos indicados.",
        "trace_scan_title": "Revision de la linea temporal",
        "trace_scan_detail": "Se revisaron {total_events} eventos analizados de la linea temporal.",
        "trace_interpret_title": "Seleccion de evidencias",
        "trace_interpret_detail": "Se seleccionaron {selected_events} pistas relevantes y {image_count} vista(s) previa(s) de fotogramas.",
    },
    "fr": {
        "timeline_evidence_summary": "Resume des indices de la chronologie",
        "timeline_clue": "Indice chronologique",
        "fallback_answer_prefix": "Les indices les plus pertinents sont : ",
        "empty_answer": "Il n'y a pas encore assez d'indices dans la chronologie. Lancez d'abord l'analyse ou laissez la camera collecter plus d'evenements.",
        "empty_follow_up": "Reposez la question lorsque la chronologie contient plus d'evenements.",
        "follow_up": "Vous pouvez demander un horodatage precis ou ce qui a change avant et apres.",
        "review_focus_1": "Verifier les images originales referencees",
        "review_focus_2": "Controler les instants juste avant et juste apres les horodatages mis en avant",
        "open_question_1": "Les details hors champ ou en basse resolution peuvent rester incertains",
        "reconstruction_summary": "J'ai utilise les evenements les plus pertinents de la chronologie et les images associees pour repondre. Si certains details ne sont pas visibles, une verification humaine des horodatages cites reste necessaire.",
        "trace_scan_title": "Analyse de la chronologie",
        "trace_scan_detail": "{total_events} evenements analyses ont ete examines.",
        "trace_interpret_title": "Selection des indices",
        "trace_interpret_detail": "{selected_events} indices pertinents et {image_count} apercu(s) d'image ont ete retenus.",
    },
    "ja": {
        "timeline_evidence_summary": "時系列証拠の要約",
        "timeline_clue": "時系列の手掛かり",
        "fallback_answer_prefix": "最も関連性の高い手掛かりは、",
        "empty_answer": "まだ十分な時系列の手掛かりがありません。先に解析を実行するか、カメラでもう少しイベントを集めてください。",
        "empty_follow_up": "時系列にイベントが増えたら、もう一度質問してください。",
        "follow_up": "特定の時刻を指定するか、その前後で何が変わったかを聞けます。",
        "review_focus_1": "参照された元フレームを確認する",
        "review_focus_2": "強調された時刻の直前と直後を確認する",
        "open_question_1": "画面外や低解像度の情報は不確かなままの場合があります",
        "reconstruction_summary": "最も関連の高い時系列イベントとフレーム証拠を使って回答しました。見えにくい詳細は、引用した時刻を人が見直す必要があります。",
        "trace_scan_title": "時系列を確認",
        "trace_scan_detail": "{total_events} 件の解析済みイベントを確認しました。",
        "trace_interpret_title": "証拠を選別",
        "trace_interpret_detail": "{selected_events} 件の関連手掛かりと {image_count} 枚のプレビューを選びました。",
    },
    "ko": {
        "timeline_evidence_summary": "타임라인 증거 요약",
        "timeline_clue": "타임라인 단서",
        "fallback_answer_prefix": "가장 관련 있는 단서는 ",
        "empty_answer": "아직 타임라인 단서가 충분하지 않습니다. 먼저 분석을 실행하거나 카메라가 이벤트를 더 수집하도록 기다려 주세요.",
        "empty_follow_up": "타임라인에 이벤트가 더 쌓인 뒤 다시 질문해 주세요.",
        "follow_up": "특정 시점을 지정하거나 그 전후에 무엇이 바뀌었는지 물어볼 수 있습니다.",
        "review_focus_1": "참조된 원본 프레임을 확인하기",
        "review_focus_2": "강조된 시점의 직전과 직후를 확인하기",
        "open_question_1": "화면 밖 정보나 저해상도 세부 내용은 여전히 불확실할 수 있습니다",
        "reconstruction_summary": "가장 관련 있는 타임라인 이벤트와 프레임 증거를 바탕으로 답했습니다. 보이지 않는 세부 내용은 인용한 시점을 사람이 다시 확인해야 합니다.",
        "trace_scan_title": "타임라인 검토",
        "trace_scan_detail": "분석된 타임라인 이벤트 {total_events}개를 검토했습니다.",
        "trace_interpret_title": "핵심 단서 선별",
        "trace_interpret_detail": "관련 단서 {selected_events}개와 프레임 미리보기 {image_count}장을 골랐습니다.",
    },
}


def _qa_text(language: str, key: str, **vars: Any) -> str:
    template = QA_TEXT.get(language, QA_TEXT["en"]).get(key) or QA_TEXT["en"][key]
    for name, value in vars.items():
        template = template.replace(f"{{{name}}}", str(value))
    return template


def _normalize_language(language: Optional[str], fallback_text: str = "") -> str:
    candidate = str(language or "").strip().lower().split("-", 1)[0]
    if candidate in SUPPORTED_QA_LANGUAGES:
        return candidate
    return _detect_question_language(fallback_text)


def answer_video_question(
    video: dict[str, Any],
    event_rows: list[dict[str, Any]],
    *,
    question: str,
    language: Optional[str] = None,
    current_timestamp_sec: Optional[float] = None,
    history: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    cleaned_question = _clean_text(question)
    language = _normalize_language(language, cleaned_question)
    events = [_normalize_event_row(row) for row in event_rows]
    events = [event for event in events if event.get("event_id")]
    events.sort(key=lambda item: float(item.get("timestamp_sec") or 0.0))

    if not events:
        return _empty_answer(language, current_timestamp_sec)

    question_for_search = _augment_question_with_history(cleaned_question, history or [])
    selected_events = _select_relevant_events(
        events,
        question_for_search,
        current_timestamp_sec=current_timestamp_sec,
        limit=8,
    )
    if not selected_events:
        selected_events = events[-min(8, len(events)):]

    images = _select_image_paths(selected_events, limit=4)
    prompt = _build_answer_prompt(
        video,
        selected_events,
        question=cleaned_question,
        current_timestamp_sec=current_timestamp_sec,
        language=language,
        history=history or [],
    )
    raw_answer = ask_gemma(prompt=prompt, images=images or None, timeout=120, options={"temperature": 0})
    parsed = _parse_answer_json(raw_answer)

    translated_events = _localized_events(selected_events, language=language)

    fallback_reconstruction = _build_reconstruction(
        translated_events,
        language=language,
    )
    answer_text = _clean_text(parsed.get("answer")) if parsed else ""
    if not answer_text:
        answer_text = _fallback_answer(translated_events, language=language)

    confidence = str((parsed or {}).get("confidence") or "medium").lower()
    if confidence not in {"high", "medium", "low"}:
        confidence = "medium"

    reconstruction = _coerce_reconstruction(
        (parsed or {}).get("reconstruction"),
        fallback=fallback_reconstruction,
    )

    return {
        "answer": answer_text,
        "confidence": confidence,
        "relevant_events": [_response_event(event) for event in translated_events[:6]],
        "current_timestamp_sec": current_timestamp_sec,
        "follow_up_suggestion": _follow_up(language),
        "agent_trace": _agent_trace(len(events), len(selected_events), len(images), language=language),
        "reconstruction": reconstruction,
    }


def _normalize_event_row(row: dict[str, Any]) -> dict[str, Any]:
    payload = _parse_payload(row.get("raw_json"))
    changes = payload.get("changes_detected")
    if not isinstance(changes, list):
        changes = _parse_json_list(row.get("diff_description"))

    keywords = payload.get("keywords")
    if not isinstance(keywords, list):
        keywords = _split_keywords(row.get("keywords"))

    summary = _clean_text(row.get("summary")) or _clean_text(payload.get("summary"))
    description = _clean_text(row.get("description")) or _clean_text(payload.get("scene_description"))

    return {
        "event_id": int(row.get("id") or row.get("event_id") or 0),
        "timestamp_sec": float(row.get("timestamp_sec") or 0.0),
        "frame_path": row.get("frame_path"),
        "description": description,
        "summary": summary,
        "event_type": _clean_text(row.get("event_type")) or _clean_text(payload.get("event_type")) or "none",
        "severity": _clean_text(row.get("severity")) or _clean_text(payload.get("severity")) or "Normal",
        "changes_detected": [_clean_text(item) for item in changes if _clean_text(item)][:6],
        "keywords": [_clean_text(item) for item in keywords if _clean_text(item)][:10],
        "created_at": row.get("created_at"),
    }


def _select_relevant_events(
    events: list[dict[str, Any]],
    question: str,
    *,
    current_timestamp_sec: Optional[float],
    limit: int,
) -> list[dict[str, Any]]:
    tokens = _tokenize(question)
    if _is_recent_or_keyframe_question(question):
        candidates = sorted(
            events,
            key=lambda event: (
                _priority_score(event),
                float(event.get("timestamp_sec") or 0.0),
            ),
            reverse=True,
        )[:limit]
        return sorted(candidates, key=lambda item: float(item.get("timestamp_sec") or 0.0))

    scored = []
    for event in events:
        score = _event_score(event, tokens)
        if current_timestamp_sec is not None:
            distance = abs(float(event.get("timestamp_sec") or 0.0) - float(current_timestamp_sec))
            score += max(0.0, 3.0 - distance / 20.0)
        scored.append((score, event))

    scored.sort(key=lambda item: (-item[0], float(item[1].get("timestamp_sec") or 0.0)))
    selected = [event for score, event in scored if score > 0][:limit]

    if selected:
        selected.sort(key=lambda item: float(item.get("timestamp_sec") or 0.0))
        return selected

    if current_timestamp_sec is not None:
        nearest = sorted(
            events,
            key=lambda event: abs(float(event.get("timestamp_sec") or 0.0) - float(current_timestamp_sec)),
        )
        return sorted(nearest[:limit], key=lambda item: float(item.get("timestamp_sec") or 0.0))

    return events[-limit:]


def _event_score(event: dict[str, Any], tokens: set[str]) -> float:
    if not tokens:
        return 1.0
    haystack = " ".join(
        [
            event.get("summary") or "",
            event.get("description") or "",
            event.get("event_type") or "",
            event.get("severity") or "",
            " ".join(event.get("keywords") or []),
            " ".join(event.get("changes_detected") or []),
        ]
    ).lower()
    score = 0.0
    for token in tokens:
        if token in haystack:
            score += 2.0 if len(token) > 2 else 1.0
    if str(event.get("severity") or "").lower() in {"warning", "emergency"}:
        score += 1.5
    if str(event.get("event_type") or "").lower() in {"person", "vehicle", "anomaly"}:
        score += 0.8
    return score


def _is_recent_or_keyframe_question(question: str) -> bool:
    lowered = (question or "").lower()
    intent_terms = {
        "recent", "latest", "key", "keyframe", "important", "happened",
        "timestamp", "time", "when", "moment", "change", "before", "after",
    }
    if any(term in lowered for term in intent_terms):
        return True
    return bool(re.search(r"最近|關鍵|影像|畫面|時間|幾點|發生|變化|前後|重要", question or ""))


def _priority_score(event: dict[str, Any]) -> float:
    score = 0.0
    severity = str(event.get("severity") or "").lower()
    event_type = str(event.get("event_type") or "").lower()
    if severity == "emergency":
        score += 5
    elif severity == "warning":
        score += 3
    if event_type == "anomaly":
        score += 4
    elif event_type in {"person", "vehicle"}:
        score += 2
    if event.get("frame_path"):
        score += 1
    return score


def _build_answer_prompt(
    video: dict[str, Any],
    events: list[dict[str, Any]],
    *,
    question: str,
    current_timestamp_sec: Optional[float],
    language: str,
    history: list[dict[str, Any]],
) -> str:
    timeline = "\n".join(_event_line(event) for event in events)
    history_text = "\n".join(
        f"- {turn.get('role')}: {_clean_text(turn.get('content'))[:400]}"
        for turn in history[-6:]
        if _clean_text(turn.get("content"))
    )
    language_name = LANGUAGE_NAMES.get(language, LANGUAGE_NAMES["en"])
    current = "unknown" if current_timestamp_sec is None else _format_seconds(current_timestamp_sec)

    return f"""You are a careful surveillance investigation assistant.
Answer in {language_name}. Use only the timeline evidence and attached frame images.
Every field in your JSON must be entirely in {language_name}.
Do not mix languages, even if the evidence snippets contain another language.
Do not leave headings, titles, phases, or short labels in English unless the target language is English.
Your job is to help the operator find the key visual evidence quickly.
Always identify the most useful timestamps/key frames first, using event_id values from the evidence.
If evidence is uncertain, say what is uncertain and point to the closest timestamps.

Video/camera: {_clean_text(video.get("title")) or "Untitled"}
Status: {_clean_text(video.get("status")) or "unknown"}
Current playback time: {current}

Recent conversation:
{history_text or "- none"}

Evidence timeline:
{timeline}

Question: {question}

Respond ONLY with valid JSON:
{{
  "answer": "direct answer with timestamp references and what to inspect",
  "confidence": "high|medium|low",
  "reconstruction": {{
    "headline": "short key-evidence headline",
    "summary": "3-5 sentence incident story when useful",
    "story_beats": [
      {{"event_id": 1, "timestamp_sec": 0.0, "phase": "before|key|after", "title": "short", "detail": "what this clue shows"}}
    ],
    "actors": ["people, vehicles, or scene elements visible in evidence"],
    "review_focus": ["what a human should verify next"],
    "open_questions": ["what remains unclear"]
  }}
}}"""


def _event_line(event: dict[str, Any]) -> str:
    changes = "; ".join(event.get("changes_detected") or [])
    keywords = ", ".join(event.get("keywords") or [])
    summary = event.get("summary") or event.get("description") or "No summary"
    description = event.get("description") or ""
    return (
        f"- event_id={event['event_id']} time={_format_seconds(event['timestamp_sec'])} "
        f"type={event.get('event_type')} severity={event.get('severity')} "
        f"summary={summary} description={description} changes={changes or 'none'} keywords={keywords or 'none'}"
    )


def _select_image_paths(events: list[dict[str, Any]], *, limit: int) -> list[str]:
    paths = []
    seen = set()
    for event in events:
        frame_path = _resolve_image_path(event.get("frame_path"))
        if frame_path and frame_path not in seen:
            paths.append(frame_path)
            seen.add(frame_path)
        if len(paths) >= limit:
            break
    return paths


def _response_event(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "event_id": event["event_id"],
        "timestamp_sec": float(event.get("timestamp_sec") or 0.0),
        "event_type": event.get("event_type") or "none",
        "severity": event.get("severity") or "Normal",
        "summary": event.get("summary") or "",
        "description": event.get("description") or "",
        "preview_url": _frame_preview_url(event.get("frame_path")),
    }


def _localized_events(events: list[dict[str, Any]], *, language: str) -> list[dict[str, Any]]:
    if not events:
        return []
    translated_items = translate_event_texts(events, language)
    translated_by_id = {str(item.get("id")): item for item in translated_items}
    localized = []
    for event in events:
        translated = translated_by_id.get(str(event.get("event_id")))
        localized.append(
            {
                **event,
                "summary": _clean_text((translated or {}).get("summary")) or event.get("summary") or "",
                "description": _clean_text((translated or {}).get("description")) or event.get("description") or "",
            }
        )
    return localized


def _build_reconstruction(events: list[dict[str, Any]], *, language: str) -> dict[str, Any]:
    ordered = sorted(events[:5], key=lambda item: float(item.get("timestamp_sec") or 0.0))
    story_beats = []
    phases = ["before", "key", "after"]
    for index, event in enumerate(ordered):
        story_beats.append(
            {
                "event_id": event["event_id"],
                "timestamp_sec": float(event.get("timestamp_sec") or 0.0),
                "phase": phases[min(index, len(phases) - 1)],
                "title": event.get("summary") or event.get("event_type") or _qa_text(language, "timeline_clue"),
                "detail": event.get("description") or event.get("summary") or "",
                "preview_url": _frame_preview_url(event.get("frame_path")),
            }
        )

    return {
        "headline": _qa_text(language, "timeline_evidence_summary"),
        "summary": _qa_text(language, "reconstruction_summary"),
        "story_beats": story_beats,
        "actors": _actor_labels(events),
        "review_focus": [
            _qa_text(language, "review_focus_1"),
            _qa_text(language, "review_focus_2"),
        ],
        "open_questions": [_qa_text(language, "open_question_1")],
    }


def _coerce_reconstruction(value: Any, *, fallback: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        return fallback
    story_beats = value.get("story_beats")
    if not isinstance(story_beats, list):
        story_beats = fallback.get("story_beats", [])
    return {
        "headline": _clean_text(value.get("headline")) or fallback.get("headline") or QA_TEXT["en"]["timeline_evidence_summary"],
        "summary": _clean_text(value.get("summary")) or fallback.get("summary") or "",
        "story_beats": [
            {
                "event_id": int(beat.get("event_id")) if str(beat.get("event_id", "")).lstrip("-").isdigit() else None,
                "timestamp_sec": _coerce_timestamp_seconds(beat.get("timestamp_sec")),
                "phase": _clean_text(beat.get("phase")) or "key",
                "title": _clean_text(beat.get("title")) or fallback.get("headline") or QA_TEXT["en"]["timeline_clue"],
                "detail": _clean_text(beat.get("detail")) or "",
                "preview_url": beat.get("preview_url"),
            }
            for beat in story_beats
            if isinstance(beat, dict)
        ][:6],
        "actors": _clean_list(value.get("actors")) or fallback.get("actors", []),
        "review_focus": _clean_list(value.get("review_focus")) or fallback.get("review_focus", []),
        "open_questions": _clean_list(value.get("open_questions")) or fallback.get("open_questions", []),
    }


def _agent_trace(total_events: int, selected_events: int, image_count: int, *, language: str) -> list[dict[str, str]]:
    return [
        {
            "step": "scan",
            "title": _qa_text(language, "trace_scan_title"),
            "detail": _qa_text(language, "trace_scan_detail", total_events=total_events),
        },
        {
            "step": "interpret",
            "title": _qa_text(language, "trace_interpret_title"),
            "detail": _qa_text(
                language,
                "trace_interpret_detail",
                selected_events=selected_events,
                image_count=image_count,
            ),
        },
    ]


def _fallback_answer(events: list[dict[str, Any]], *, language: str) -> str:
    if language == "zh":
        parts = [
            f"{_format_seconds(event['timestamp_sec'])}：{event.get('summary') or event.get('description') or event.get('event_type')}"
            for event in events[:4]
        ]
        return _qa_text(language, "fallback_answer_prefix") + "；".join(parts) + "。"
    if language in {"ja", "ko"}:
        parts = [
            f"{_format_seconds(event['timestamp_sec'])}: {event.get('summary') or event.get('description') or event.get('event_type')}"
            for event in events[:4]
        ]
        return _qa_text(language, "fallback_answer_prefix") + "、".join(parts) + "。"
    parts = [
        f"{_format_seconds(event['timestamp_sec'])}: {event.get('summary') or event.get('description') or event.get('event_type')}"
        for event in events[:4]
    ]
    return _qa_text(language, "fallback_answer_prefix") + "; ".join(parts) + "."


def _empty_answer(language: str, current_timestamp_sec: Optional[float]) -> dict[str, Any]:
    return {
        "answer": _qa_text(language, "empty_answer"),
        "confidence": "low",
        "relevant_events": [],
        "current_timestamp_sec": current_timestamp_sec,
        "follow_up_suggestion": _qa_text(language, "empty_follow_up"),
        "agent_trace": [],
        "reconstruction": None,
    }


def _follow_up(language: str) -> str:
    return _qa_text(language, "follow_up")


def _augment_question_with_history(question: str, history: list[dict[str, Any]]) -> str:
    snippets = [
        _clean_text(turn.get("content"))
        for turn in history[-4:]
        if turn.get("role") == "user" and _clean_text(turn.get("content"))
    ]
    if not snippets:
        return question
    return f"{question}\nPrevious user context: {' | '.join(snippets)}"


def _actor_labels(events: list[dict[str, Any]]) -> list[str]:
    labels = []
    for event in events:
        value = str(event.get("event_type") or "").strip().lower()
        if value and value not in {"normal", "none"} and value not in labels:
            labels.append(value)
    return labels[:6]


def _parse_answer_json(raw: Optional[str]) -> dict[str, Any]:
    if not raw:
        return {}
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"```$", "", text).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            return {}
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            return {}
    return parsed if isinstance(parsed, dict) else {}


def _parse_payload(raw_json: Any) -> dict[str, Any]:
    if isinstance(raw_json, dict):
        return raw_json
    if not raw_json:
        return {}
    try:
        parsed = json.loads(str(raw_json))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _parse_json_list(raw_value: Any) -> list[Any]:
    if isinstance(raw_value, list):
        return raw_value
    if not raw_value:
        return []
    try:
        parsed = json.loads(str(raw_value))
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _coerce_timestamp_seconds(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()
    try:
        return float(text)
    except ValueError:
        pass

    time_match = re.fullmatch(r"(?:(\d+):)?([0-5]?\d):([0-5]?\d(?:\.\d+)?)", text)
    if not time_match:
        return 0.0

    hours = float(time_match.group(1) or 0)
    minutes = float(time_match.group(2) or 0)
    seconds = float(time_match.group(3) or 0)
    return (hours * 3600.0) + (minutes * 60.0) + seconds


def _split_keywords(raw_value: Any) -> list[str]:
    if isinstance(raw_value, list):
        return [str(item).strip() for item in raw_value if str(item).strip()]
    if not raw_value:
        return []
    return [item.strip() for item in str(raw_value).replace(";", ",").split(",") if item.strip()]


def _clean_list(value: Any, *, limit: int = 8) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_clean_text(item) for item in value if _clean_text(item)][:limit]


def _tokenize(text: str) -> set[str]:
    lowered = (text or "").lower()
    tokens = set(re.findall(r"[a-z0-9_]{2,}|[一-鿿]", lowered))
    return {token for token in tokens if token not in {"the", "and", "what", "when", "where", "with"}}


def _detect_question_language(text: str) -> str:
    lowered = text or ""
    if re.search(r"[一-鿿]", lowered):
        return "zh"
    if re.search(r"[\u3040-\u30ff]", lowered):
        return "ja"
    if re.search(r"[\uac00-\ud7af]", lowered):
        return "ko"
    return "en"


def _resolve_image_path(image_path: Any) -> Optional[str]:
    raw = _clean_text(image_path)
    if not raw:
        return None
    if raw.startswith("/frames/"):
        path = Path(__file__).resolve().parents[1] / "data" / raw.lstrip("/")
    else:
        path = Path(raw)
    if not path.exists() or not path.is_file():
        return None
    return str(path)


def _frame_preview_url(frame_path: Any) -> Optional[str]:
    raw = _clean_text(frame_path)
    if not raw:
        return None
    if raw.startswith("/frames/"):
        return raw
    parts = Path(raw).parts
    if "frames" not in parts:
        return None
    index = parts.index("frames")
    return "/" + "/".join(parts[index:])


def _format_seconds(value: Any) -> str:
    try:
        seconds = max(0.0, float(value))
    except (TypeError, ValueError):
        seconds = 0.0
    minutes = int(seconds // 60)
    remainder = int(round(seconds % 60))
    return f"{minutes}:{remainder:02d}"


def _clean_text(value: Any) -> str:
    return str(value or "").replace("\x00", "").strip()
