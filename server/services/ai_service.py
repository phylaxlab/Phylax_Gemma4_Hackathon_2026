"""
AI Service - Interface to Gemma4 models via Ollama.
Handles frame analysis and search relevance ranking.
"""

import json
import logging
import re
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

import cv2
import httpx
from ollama import Client

from config import (
    OLLAMA_HOST,
    MODEL_NAME,
    MODEL_TIMEOUT,
    VIDEO_ANALYSIS_MODEL_NAME,
    LIVE_ANALYSIS_MODEL_NAME,
    CAMERA_ANALYSIS_MODEL_NAME,
    SEARCH_MODEL_NAME,
    LIVE_MODEL_TIMEOUT,
    CAMERA_MODEL_TIMEOUT,
    CAMERA_AI_NUM_CTX,
    CAMERA_AI_NUM_PREDICT,
    CAMERA_AI_TEMPERATURE,
    CAMERA_AI_USE_OPTIONS,
)

logger = logging.getLogger(__name__)

_LANGUAGE_NAMES = {
    "en": "English",
    "zh": "Traditional Chinese",
    "es": "Spanish",
    "fr": "French",
    "ja": "Japanese",
    "ko": "Korean",
}

_TRANSLATION_CACHE_MAX = 600
_TRANSLATION_CACHE: "OrderedDict[Tuple[str, bool, str, str], Dict[str, str]]" = OrderedDict()
_TRANSLATION_CACHE_LOCK = threading.RLock()


def ask_gemma(
    prompt: str,
    model: str = None,
    images: list = None,
    stream: bool = False,
    timeout: float = None,
    options: dict = None,
) -> Optional[str]:
    """
    Send a prompt (optionally with images) to the configured Gemma model.
    """
    model = model or MODEL_NAME
    timeout = timeout or MODEL_TIMEOUT
    client = Client(host=OLLAMA_HOST, timeout=timeout)

    message = {"role": "user", "content": prompt}
    if images:
        message["images"] = images

    kwargs = {"model": model, "messages": [message], "stream": stream}
    if options:
        kwargs["options"] = options

    try:
        response = client.chat(**kwargs)
        if stream:
            return response
        return response["message"]["content"]
    except httpx.ReadTimeout:
        logger.error("Ollama call timed out (timeout=%ss, model=%s)", timeout, model)
        return None
    except Exception as exc:
        logger.error("Ollama call failed for model %s: %s", model, exc)
        return None


def translate_event_texts(items: List[Dict[str, Any]], target_language: str, force: bool = False) -> List[Dict[str, str]]:
    """Translate event summaries/descriptions for display without mutating DB rows."""
    normalized_language = (target_language or "en").split("-", 1)[0].lower()
    if normalized_language == "en" and not force:
        return [
            {
                "id": str(item.get("id", "")),
                "summary": str(item.get("summary") or ""),
                "description": str(item.get("description") or ""),
            }
            for item in items
        ]

    language_name = _LANGUAGE_NAMES.get(normalized_language, "English" if normalized_language == "en" else normalized_language)
    output_by_id: Dict[str, Dict[str, str]] = {}
    uncached_items = []
    for item in items[:80]:
        compact = {
            "id": str(item.get("id", "")),
            "summary": str(item.get("summary") or "")[:500],
            "description": str(item.get("description") or "")[:800],
        }
        cache_key = _translation_cache_key(compact, normalized_language, force)
        cached = _get_cached_translation(cache_key)
        if cached and not _translation_result_needs_cleanup(cached, normalized_language):
            output_by_id[compact["id"]] = {"id": compact["id"], **cached}
        else:
            uncached_items.append((compact, cache_key))

    for start in range(0, len(uncached_items), 16):
        compact_items = [item for item, _ in uncached_items[start:start + 16]]
        translated_items = _translate_event_text_batch(compact_items, language_name)
        translated_by_id = {str(item.get("id", "")): item for item in translated_items}
        for compact, cache_key in uncached_items[start:start + 16]:
            translated = translated_by_id.get(compact["id"]) or compact
            cleaned = {
                "summary": _strip_code_fences(str(translated.get("summary") or compact.get("summary") or "")),
                "description": _strip_code_fences(str(translated.get("description") or compact.get("description") or "")),
            }
            if not _translation_result_needs_cleanup(cleaned, normalized_language):
                _set_cached_translation(cache_key, cleaned)
            output_by_id[compact["id"]] = {"id": compact["id"], **cleaned}

    output = []
    for item in items:
        item_id = str(item.get("id", ""))
        output.append(
            output_by_id.get(
                item_id,
                {
                    "id": item_id,
                    "summary": str(item.get("summary") or ""),
                    "description": str(item.get("description") or ""),
                },
            )
        )
    return output


def _translate_event_text_batch(compact_items: List[Dict[str, str]], language_name: str) -> List[Dict[str, str]]:
    prompt = f"""Translate surveillance event text into {language_name}.
Preserve the meaning, severity, traffic terms, and camera-observation style.
Do not add new facts. Keep each summary concise.
The final translated text must be entirely in {language_name}.
Do not leave any English words, phrases, or clauses in the output unless the source contains an unavoidable proper noun.
If a line starts with a field marker like [[scene_description]], [[frame_observation]], [[temporal_assessment]], [[anomaly_rationale]], [[keyframe_reason]], [[keyword]], [[subject]], or [[change]],
keep the marker exactly as-is and translate only the text after the marker.
If the input mixes English with another language, normalize the whole result into {language_name}.

Respond ONLY with valid JSON in this exact shape:
{{"items":[{{"id":"same id","summary":"translated summary","description":"translated description"}}]}}

Input JSON:
{json.dumps({"items": compact_items}, ensure_ascii=False)}
"""
    raw_response = ask_gemma(
        prompt,
        model=SEARCH_MODEL_NAME,
        timeout=min(MODEL_TIMEOUT, 120),
        options={"temperature": 0},
    )
    parsed = _parse_translation_response(raw_response)
    if not parsed:
        return compact_items

    originals_by_id = {str(item["id"]): item for item in compact_items}
    output = []
    for translated in parsed:
        item_id = str(translated.get("id", ""))
        original = originals_by_id.get(item_id)
        if not original:
            continue
        output.append(
            {
                "id": item_id,
                "summary": _strip_code_fences(str(translated.get("summary") or original.get("summary") or "")),
                "description": _strip_code_fences(str(translated.get("description") or original.get("description") or "")),
            }
        )

    return output or compact_items


def _translation_cache_key(item: Dict[str, str], language: str, force: bool) -> Tuple[str, bool, str, str]:
    return (
        language,
        bool(force),
        str(item.get("summary") or ""),
        str(item.get("description") or ""),
    )


def _get_cached_translation(cache_key: Tuple[str, bool, str, str]) -> Optional[Dict[str, str]]:
    with _TRANSLATION_CACHE_LOCK:
        cached = _TRANSLATION_CACHE.get(cache_key)
        if not cached:
            return None
        _TRANSLATION_CACHE.move_to_end(cache_key)
        return dict(cached)


def _set_cached_translation(cache_key: Tuple[str, bool, str, str], value: Dict[str, str]) -> None:
    with _TRANSLATION_CACHE_LOCK:
        _TRANSLATION_CACHE[cache_key] = dict(value)
        _TRANSLATION_CACHE.move_to_end(cache_key)
        while len(_TRANSLATION_CACHE) > _TRANSLATION_CACHE_MAX:
            _TRANSLATION_CACHE.popitem(last=False)


def _translation_result_needs_cleanup(value: Dict[str, str], language: str) -> bool:
    if not language or language == "en":
        return False
    combined = " ".join(
        part for part in [
            str(value.get("summary") or ""),
            str(value.get("description") or ""),
        ] if part
    )
    return _needs_target_language_cleanup(combined, language)


def _strip_code_fences(text: str) -> str:
    value = str(text or "").strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?", "", value, flags=re.IGNORECASE).strip()
        value = re.sub(r"```$", "", value).strip()
    return value


def _parse_translation_response(raw_response: Optional[str]) -> List[Dict[str, Any]]:
    if not raw_response:
        return []
    text = raw_response.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"```$", "", text).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            return []
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            return []
    items = parsed.get("items") if isinstance(parsed, dict) else parsed
    return items if isinstance(items, list) else []


FRAME_ANALYSIS_PROMPT = """You are a fast surveillance anomaly reviewer.
Analyze the provided security camera frame(s) and focus only on important abnormal changes.

{comparison_instruction}

Respond ONLY with valid JSON. Do not add markdown or extra text.
Use this exact structure:
{{
  "scene_description": "Short scene description",
  "changes_detected": ["brief important changes"],
  "event_type": "person|vehicle|motion|anomaly|normal",
  "severity": "Normal|Warning|Emergency",
  "anomaly_score": 0,
  "requires_attention": false,
  "summary": "Very short alert summary",
  "keywords": ["tag1", "tag2", "tag3"]
}}

Rules:
- Keep output compact.
- Prefer "normal" only when the scene is routine and nothing unusual is happening.
- Use "anomaly" for suspicious, hazardous, unexpected, or unclear abnormal situations.
- Use "person" or "vehicle" when those are the main notable subjects.
- anomaly_score must be an integer 0-100.
- requires_attention should be true when a human operator should review it.
- keywords should be highly searchable surveillance terms.
- Ignore minor camera shake or harmless lighting changes.
"""

FAST_FRAME_ANALYSIS_PROMPT = """You are a fast surveillance anomaly triage AI.
Analyze the provided security camera frame(s) and prioritize unusual events over routine motion.

{comparison_instruction}

Respond ONLY with valid JSON. Do not add markdown or extra text.
Use this exact structure:
{{
  "scene_description": "Short scene description",
  "changes_detected": ["brief important changes"],
  "event_type": "person|vehicle|motion|anomaly|normal",
  "severity": "Normal|Warning|Emergency",
  "anomaly_score": 0,
  "requires_attention": false,
  "summary": "Short alert summary",
  "keywords": ["tag1", "tag2", "tag3"]
}}

Rules:
- Be concise.
- Prioritize intrusion, loitering, falls, collisions, smoke, fire, crowding, running, blocking, and sudden scene changes.
- Ignore tiny lighting changes or harmless background flicker.
- anomaly_score must be an integer 0-100.
"""

CAMERA_TRIAGE_PROMPT = """You are a realtime CCTV triage model.
Analyze one low-resolution camera frame and decide whether it contains a save-worthy surveillance event.
Use the recent timeline context as memory: decide whether the current frame is routine, a continuation,
an escalation, a resolution, or a new abnormal change compared with earlier Gemma observations.
Your output is used later to reconstruct an incident story, so preserve enough temporal clues for a detective-style timeline.

{comparison_instruction}

Respond ONLY with compact valid JSON:
{{
  "scene_description": "short scene",
  "frame_observation": "what Gemma sees in the current frame",
  "temporal_assessment": "how this frame compares with recent prior results",
  "continuity_label": "new|continuing|escalating|resolving|routine|unclear",
  "story_phase": "before|start|development|peak|after|routine",
  "tracked_subjects": ["main visible people, vehicles, or objects"],
  "keyframe_reason": "why this frame matters in the story, or why it is routine",
  "changes_detected": [],
  "event_type": "person|vehicle|motion|anomaly|normal",
  "severity": "Normal|Warning|Emergency",
  "anomaly_score": 0,
  "requires_attention": false,
  "anomaly_rationale": "why this score was assigned",
  "summary": "short alert",
  "keywords": ["tag1", "tag2", "tag3"]
}}

Rules:
- Write every free-text field in plain English only.
- Never mix English with Chinese, Japanese, Korean, or any other language in the same output.
- If recent context contains another language, normalize your answer back into English.
- Use "person" when any person is clearly visible.
- Use "vehicle" when road traffic, moving vehicles, parked vehicles, or vehicle queues are clearly visible.
- Use "normal" when the visible scene matches recent routine observations and has no safety issue.
- Use "anomaly" for suspicious, hazardous, blocked, collision, fall, fire, smoke, intrusion, crowding, or unsafe conditions.
- anomaly_score is 0-100: 0-20 routine, 21-45 notable but ordinary, 46-70 needs review, 71-100 urgent.
- Warning/Emergency only when an operator should review it.
- story_phase should describe the frame's role in the visible sequence, not a generic label.
- tracked_subjects should be short stable nouns such as "white sedan", "worker", "truck queue", or "road cones".
- keyframe_reason should say what this frame proves or why it helps understand before/after changes.
- Keep every string brief.
"""

TEXT_FALLBACK_PROMPT = """You are a surveillance monitoring assistant.
Describe the current frame in one short sentence.
Focus on people, vehicles, hazards, obstructions, smoke, fire, falls, suspicious activity, or whether the scene appears routine.
"""

SINGLE_FRAME_INSTRUCTION = (
    "Describe this single security camera frame briefly. "
    "Focus only on important subjects, hazards, and unusual conditions."
)

COMPARISON_INSTRUCTION = """Compare these two consecutive security camera frames.
Frame 1 (previous, timestamp: {prev_ts}s) is the first image.
Frame 2 (current, timestamp: {curr_ts}s) is the second image.

Identify only the important semantic difference between them. Focus on:
- people, vehicles, and motion entering or leaving
- suspicious, unsafe, abnormal, or high-risk behavior
- scene obstructions, crowding, falls, smoke, fire, or sudden disruption
- changes that a human operator should review quickly
"""

SINGLE_FRAME_WITH_MOTION_HINT = """Analyze this single security camera frame.
The previous frame is not attached because the current model may not reliably compare multiple images.

Use this additional context from automated vision comparison:
- estimated_change_level: {change_level}
- changed_area_ratio: {change_ratio}%

Focus on whether the current frame appears routine or abnormal, and whether the visible scene suggests an event worth operator attention.
"""

SUPPORTING_IMAGE_INSTRUCTION = """If extra images are attached after the main overview frame(s), use them only as supporting detail.
Ground your final judgment in the full-scene frame(s)."""

TIMELINE_CONTINUITY_INSTRUCTION = """Recent timeline context may also be provided from just before the current frame.
Use it to keep the narrative coherent across time. Let the scene_description, summary, continuity_label, story_phase, tracked_subjects, and keyframe_reason reflect whether the situation is new, continuing, escalating, dispersing, or returning to normal, but do not invent events that are not supported by the current frame(s)."""

RELEVANCE_PROMPT = """You are a search relevance engine. Given a user's search query and a list of surveillance event descriptions, rate each event's relevance to the query on a scale of 0 to 10.

User Query: "{query}"

Events (numbered):
{events_text}

Respond ONLY with valid JSON (no markdown, no code fences). Use this exact structure:
{{
  "rankings": [
    {{"index": 0, "score": 8, "reason": "..."}},
    {{"index": 1, "score": 2, "reason": "..."}}
  ]
}}
"""

EVENT_TYPE_VALUES = {"person", "vehicle", "motion", "anomaly", "normal"}
SEVERITY_VALUES = {"normal": "Normal", "warning": "Warning", "emergency": "Emergency"}
ANOMALY_HINTS = {
    "fire", "smoke", "fall", "fallen", "weapon", "intruder", "intrusion", "fight",
    "collision", "crash", "blood", "panic", "running", "loitering", "blocked",
    "hazard", "hazardous", "suspicious", "anomaly", "emergency", "trespass",
}
PERSON_HINTS = {"person", "people", "human", "pedestrian", "worker", "visitor"}
VEHICLE_HINTS = {"vehicle", "car", "truck", "motorcycle", "van", "bus"}
MOTION_HINTS = {"motion", "movement", "moving", "entered", "left", "changed"}


def analyze_frames(
    current_frame_path: str,
    previous_frame_path: Optional[str] = None,
    current_timestamp: float = 0,
    previous_timestamp: float = 0,
    profile: str = "video",
    detail_mode: str = "careful",
    context_text: Optional[str] = None,
    extra_image_paths: Optional[List[str]] = None,
    timeline_context: Optional[List[Dict[str, Any]]] = None,
    output_language: str = "en",
) -> Optional[Dict[str, Any]]:
    """
    Analyze one or two consecutive frames using a profile-specific model.
    Profiles:
      - video: archived video analysis
      - live: faster webcam/live-stream analysis
      - camera: faster persistent IP-camera analysis
    """
    images = []
    used_comparison_mode = False

    extra_image_paths = [path for path in (extra_image_paths or []) if path and Path(path).exists()]

    if previous_frame_path and Path(previous_frame_path).exists():
        images.append(previous_frame_path)
        images.append(current_frame_path)
        instruction = COMPARISON_INSTRUCTION.format(
            prev_ts=previous_timestamp, curr_ts=current_timestamp
        )
        used_comparison_mode = True
    else:
        images.append(current_frame_path)
        instruction = SINGLE_FRAME_INSTRUCTION

    instruction = _append_analysis_context(
        instruction,
        context_text=context_text,
        extra_image_paths=extra_image_paths,
        timeline_context=timeline_context,
    )
    if extra_image_paths:
        images.extend(extra_image_paths)

    prompt, model, timeout, options = _get_analysis_profile(profile, instruction, detail_mode, output_language)
    raw_response = ask_gemma(
        prompt=prompt,
        model=model,
        images=images,
        timeout=timeout,
        options=options,
    )

    if profile == "camera" and (not raw_response or not raw_response.strip()) and options:
        logger.warning(
            "Camera triage returned empty with Ollama options; retrying without options."
        )
        raw_response = ask_gemma(
            prompt=prompt,
            model=model,
            images=images,
            timeout=timeout,
            options=None,
        )

    if (not raw_response or not raw_response.strip()) and used_comparison_mode:
        change_ratio, change_level = _estimate_change(previous_frame_path, current_frame_path)
        fallback_instruction = SINGLE_FRAME_WITH_MOTION_HINT.format(
            change_level=change_level,
            change_ratio=f"{change_ratio:.2f}",
        )
        fallback_instruction = _append_analysis_context(
            fallback_instruction,
            context_text=context_text,
            extra_image_paths=extra_image_paths,
            timeline_context=timeline_context,
        )
        fallback_prompt, model, timeout, options = _get_analysis_profile(profile, fallback_instruction, detail_mode, output_language)
        raw_response = ask_gemma(
            prompt=fallback_prompt,
            model=model,
            images=[current_frame_path] + extra_image_paths,
            timeout=timeout,
            options=options,
        )

    if not raw_response or not raw_response.strip():
        if profile == "camera":
            logger.warning(
                "Empty camera triage response for frame at %.1fs using model=%s",
                current_timestamp,
                model,
            )
            return None

        fallback_prompt = TEXT_FALLBACK_PROMPT
        fallback_prompt = _append_analysis_context(
            fallback_prompt,
            context_text=context_text,
            extra_image_paths=extra_image_paths,
            timeline_context=timeline_context,
        )
        raw_response = ask_gemma(
            prompt=fallback_prompt,
            model=model,
            images=[current_frame_path] + extra_image_paths,
            timeout=timeout,
            options=options,
        )

    if not raw_response or not raw_response.strip():
        logger.warning(
            "Empty response from AI for frame at %.1fs using profile=%s model=%s",
            current_timestamp,
            profile,
            model,
        )
        return None

    parsed = _parse_json_response(raw_response, current_timestamp)
    if not parsed:
        return None

    normalized = _normalize_analysis_result(parsed, output_language=output_language)
    logger.info(
        "AI analysis completed profile=%s model=%s severity=%s event_type=%s anomaly_score=%s",
        profile,
        model,
        normalized["severity"],
        normalized["event_type"],
        normalized["anomaly_score"],
    )
    return normalized


def rank_event_relevance(query: str, event_descriptions: List[str]) -> Optional[List[Dict[str, Any]]]:
    """
    Use Gemma to rank how relevant each event description is to the given search query.
    """
    if not event_descriptions:
        return []

    events_text = "\n".join(f"{i}. {desc}" for i, desc in enumerate(event_descriptions))
    prompt = RELEVANCE_PROMPT.format(query=query, events_text=events_text)

    raw = ask_gemma(prompt=prompt, model=SEARCH_MODEL_NAME)
    if not raw:
        return None

    parsed = _parse_json_response(raw, 0)
    if parsed and "rankings" in parsed:
        return parsed["rankings"]

    return None


def build_timeline_story_entry(
    result: Optional[Dict[str, Any]],
    *,
    timestamp: float,
    source: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    if not result:
        return None

    summary = _clean_text(result.get("summary")) or _clean_text(result.get("frame_observation")) or _clean_text(result.get("scene_description"))
    description = (
        _clean_text(result.get("temporal_assessment"))
        or _clean_text(result.get("frame_observation"))
        or _clean_text(result.get("scene_description"))
        or summary
    )
    if not summary and not description:
        return None

    return {
        "timestamp_sec": float(timestamp or 0),
        "source": _clean_text(source),
        "event_type": str(result.get("event_type") or "normal").strip().lower(),
        "severity": _clean_text(result.get("severity")) or "Normal",
        "summary": summary,
        "scene_description": description,
        "continuity_label": _clean_text(result.get("continuity_label")) or "routine",
        "story_phase": _clean_text(result.get("story_phase")) or "routine",
        "tracked_subjects": _normalize_keywords(result.get("tracked_subjects")),
        "keyframe_reason": _clean_text(result.get("keyframe_reason")),
        "anomaly_score": _coerce_int(result.get("anomaly_score"), 0, 100),
        "keywords": _normalize_keywords(result.get("keywords")),
    }


def _get_analysis_profile(
    profile: str,
    instruction: str,
    detail_mode: str = "careful",
    output_language: str = "en",
) -> Tuple[str, str, float, dict]:
    """Return prompt, model, timeout, and options for a specific analysis profile."""
    language_instruction = _analysis_language_instruction(output_language)
    if language_instruction:
        instruction = f"{instruction}\n\n{language_instruction}"

    if profile == "live":
        return (
            FAST_FRAME_ANALYSIS_PROMPT.format(comparison_instruction=instruction),
            LIVE_ANALYSIS_MODEL_NAME,
            LIVE_MODEL_TIMEOUT,
            None,
        )

    if profile == "camera":
        options = None
        if CAMERA_AI_USE_OPTIONS:
            options = {
                "temperature": CAMERA_AI_TEMPERATURE,
                "num_ctx": CAMERA_AI_NUM_CTX,
                "num_predict": CAMERA_AI_NUM_PREDICT,
            }

        return (
            CAMERA_TRIAGE_PROMPT.format(comparison_instruction=instruction),
            CAMERA_ANALYSIS_MODEL_NAME,
            CAMERA_MODEL_TIMEOUT,
            options,
        )

    if detail_mode == "fast":
        return (
            FAST_FRAME_ANALYSIS_PROMPT.format(comparison_instruction=instruction),
            VIDEO_ANALYSIS_MODEL_NAME or MODEL_NAME,
            MODEL_TIMEOUT,
            None,
        )

    return (
        FRAME_ANALYSIS_PROMPT.format(comparison_instruction=instruction),
        VIDEO_ANALYSIS_MODEL_NAME or MODEL_NAME,
        MODEL_TIMEOUT,
        None,
    )


def _append_analysis_context(
    instruction: str,
    *,
    context_text: Optional[str],
    extra_image_paths: Optional[List[str]],
    timeline_context: Optional[List[Dict[str, Any]]],
) -> str:
    sections = [instruction]

    if extra_image_paths:
        sections.append(SUPPORTING_IMAGE_INSTRUCTION)

    if context_text and context_text.strip():
        sections.append(f"Supplemental context:\n{context_text.strip()}")

    timeline_text = _format_timeline_context(timeline_context)
    if timeline_text:
        sections.append(f"{TIMELINE_CONTINUITY_INSTRUCTION}\n\n{timeline_text}")

    return "\n\n".join(section for section in sections if section)


def _format_timeline_context(timeline_context: Optional[List[Dict[str, Any]]]) -> str:
    if not timeline_context:
        return ""

    items = [item for item in timeline_context if isinstance(item, dict)]
    if not items:
        return ""

    lines = ["Recent scene timeline (oldest to newest):"]
    for item in items[-4:]:
        summary = _clean_text(item.get("summary")) or _clean_text(item.get("scene_description")) or "Routine scene"
        event_type = _clean_text(item.get("event_type")) or "normal"
        severity = _clean_text(item.get("severity")) or "Normal"
        phase = _clean_text(item.get("story_phase")) or "routine"
        continuity = _clean_text(item.get("continuity_label")) or "routine"
        subjects = ", ".join(_normalize_keywords(item.get("tracked_subjects"))) or "none"
        keyframe_reason = _clean_text(item.get("keyframe_reason"))
        score = _coerce_int(item.get("anomaly_score"), 0, 100)
        lines.append(
            f"- { _format_timeline_timestamp(item.get('timestamp_sec')) }: event={event_type}, severity={severity}, "
            f"score={score}, phase={phase}, continuity={continuity}, subjects={subjects}, "
            f"summary={summary}, keyframe_reason={keyframe_reason or 'none'}"
        )
    return "\n".join(lines)


def _format_timeline_timestamp(value: Any) -> str:
    try:
        timestamp = float(value)
    except (TypeError, ValueError):
        return "recently"

    if timestamp <= 0:
        return "recently"
    if timestamp > 1_000_000_000:
        age_sec = max(0, int(round(time.time() - timestamp)))
        return f"~{age_sec}s ago"
    return f"t={timestamp:.1f}s"


def _parse_json_response(raw: str, timestamp: float) -> Optional[Dict[str, Any]]:
    """
    Parse JSON from the model response, handling common formatting issues.
    """
    text = raw.strip()

    if text.startswith("```"):
        lines = text.split("\n")
        lines = [line for line in lines if not line.strip().startswith("```")]
        text = "\n".join(lines).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass

        logger.warning(
            "Failed to parse JSON from AI response at %.1fs. Raw: %s",
            timestamp,
            text[:300],
        )
        return {
            "scene_description": text[:400],
            "changes_detected": [],
            "event_type": _infer_event_type(text.lower()),
            "severity": _infer_severity(text.lower()),
            "anomaly_score": _heuristic_anomaly_score(text.lower(), _infer_event_type(text.lower()), _infer_severity(text.lower())),
            "requires_attention": _infer_severity(text.lower()) != "Normal",
            "summary": text[:120],
            "keywords": _keywords_from_text(text.lower()),
        }


def _normalize_analysis_result(result: Dict[str, Any], output_language: str = "en") -> Dict[str, Any]:
    """
    Normalize the model output and strengthen anomaly scoring with lightweight rules.
    """
    scene_description = _clean_text(result.get("scene_description")) or "Scene observed."
    frame_observation = _clean_text(result.get("frame_observation")) or scene_description
    temporal_assessment = _clean_text(result.get("temporal_assessment"))
    anomaly_rationale = _clean_text(result.get("anomaly_rationale"))
    continuity_label = _normalize_choice(
        result.get("continuity_label"),
        {"new", "continuing", "escalating", "resolving", "routine", "unclear"},
        "routine",
    )
    story_phase = _normalize_choice(
        result.get("story_phase"),
        {"before", "start", "development", "peak", "after", "routine"},
        "routine",
    )
    tracked_subjects = _normalize_keywords(result.get("tracked_subjects"))
    keyframe_reason = _clean_text(result.get("keyframe_reason"))
    changes_detected = _normalize_changes(result.get("changes_detected"))
    summary = _clean_text(result.get("summary")) or frame_observation[:120]
    keywords = _normalize_keywords(result.get("keywords"))

    lowered_text = " ".join(
        [
            scene_description.lower(),
            frame_observation.lower(),
            temporal_assessment.lower(),
            anomaly_rationale.lower(),
            continuity_label.lower(),
            story_phase.lower(),
            keyframe_reason.lower(),
            summary.lower(),
            " ".join(changes_detected).lower(),
            " ".join(tracked_subjects).lower(),
            " ".join(keywords).lower(),
        ]
    )

    event_type = str(result.get("event_type", "")).strip().lower()
    if event_type not in EVENT_TYPE_VALUES:
        event_type = _infer_event_type(lowered_text)

    severity = str(result.get("severity", "")).strip().lower()
    severity = SEVERITY_VALUES.get(severity, _infer_severity(lowered_text))

    anomaly_score = _coerce_int(result.get("anomaly_score"), 0, 100)
    anomaly_score = max(anomaly_score, _heuristic_anomaly_score(lowered_text, event_type, severity))

    requires_attention = bool(result.get("requires_attention", False))
    requires_attention = requires_attention or anomaly_score >= 55 or severity != "Normal"

    if event_type == "normal" and anomaly_score >= 55:
        event_type = "anomaly"
    if severity == "Normal" and anomaly_score >= 75:
        severity = "Emergency"
    elif severity == "Normal" and anomaly_score >= 45:
        severity = "Warning"
    elif severity == "Warning" and anomaly_score >= 80:
        severity = "Emergency"

    if event_type == "normal" and not changes_detected:
        summary = summary or "Routine scene with no notable anomaly."
    elif not summary:
        summary = "Potential abnormal activity detected."

    if not temporal_assessment:
        temporal_assessment = (
            "Matches recent routine observations; no abnormal change is visible."
            if severity == "Normal" and anomaly_score < 46
            else "Differs from recent routine observations and should be reviewed."
        )

    if not anomaly_rationale:
        anomaly_rationale = (
            "Low score because the frame appears consistent with the recent scene."
            if anomaly_score < 46
            else "Elevated score because the frame contains a notable or unsafe change."
        )

    if not tracked_subjects:
        tracked_subjects = _infer_tracked_subjects(lowered_text)

    if not keyframe_reason:
        keyframe_reason = (
            "Routine continuity frame; useful as baseline context."
            if anomaly_score < 46 and severity == "Normal"
            else "Key frame because it shows the notable subject or change to review."
        )

    if story_phase == "routine" and anomaly_score >= 55:
        story_phase = "peak" if severity == "Emergency" else "development"
    if continuity_label == "routine" and anomaly_score >= 55:
        continuity_label = "escalating" if severity != "Normal" else "new"

    normalized = {
        "scene_description": scene_description,
        "frame_observation": frame_observation,
        "temporal_assessment": temporal_assessment,
        "continuity_label": continuity_label,
        "story_phase": story_phase,
        "tracked_subjects": tracked_subjects,
        "keyframe_reason": keyframe_reason,
        "changes_detected": changes_detected,
        "event_type": event_type,
        "severity": severity,
        "anomaly_score": anomaly_score,
        "requires_attention": requires_attention,
        "anomaly_rationale": anomaly_rationale,
        "summary": summary,
        "keywords": keywords,
    }
    return _canonicalize_analysis_language(normalized, output_language)


def _canonicalize_analysis_language(result: Dict[str, Any], output_language: str = "en") -> Dict[str, Any]:
    text_fields = {
        "scene_description": _clean_text(result.get("scene_description")),
        "frame_observation": _clean_text(result.get("frame_observation")),
        "temporal_assessment": _clean_text(result.get("temporal_assessment")),
        "anomaly_rationale": _clean_text(result.get("anomaly_rationale")),
        "summary": _clean_text(result.get("summary")),
        "keyframe_reason": _clean_text(result.get("keyframe_reason")),
    }
    list_fields = {
        "changes_detected": _normalize_changes(result.get("changes_detected")),
        "tracked_subjects": _normalize_keywords(result.get("tracked_subjects")),
        "keywords": _normalize_keywords(result.get("keywords")),
    }

    normalized_language = _normalize_output_language(output_language)
    if normalized_language != "en":
        combined_text = _combine_language_fields(text_fields, list_fields)
        if not _needs_target_language_cleanup(combined_text, normalized_language):
            return result
        return _translate_analysis_result(result, normalized_language, text_fields, list_fields)

    combined_text = _combine_language_fields(text_fields, list_fields)
    if not _contains_cjk(combined_text):
        return result

    prompt = f"""Rewrite this CCTV analysis JSON into plain English only.
Keep the exact meaning, safety judgment, and surveillance tone.
Do not add facts. Do not remove facts.
Translate every string value into English.
Keep enum-like fields unchanged: continuity_label, story_phase, event_type, severity.
Return ONLY valid JSON with this exact shape:
{{
  "scene_description": "English text",
  "frame_observation": "English text",
  "temporal_assessment": "English text",
  "anomaly_rationale": "English text",
  "summary": "English text",
  "keyframe_reason": "English text",
  "changes_detected": ["English item"],
  "tracked_subjects": ["English item"],
  "keywords": ["english", "keywords"]
}}

Input JSON:
{json.dumps({**text_fields, **list_fields}, ensure_ascii=False)}
"""

    raw_response = ask_gemma(
        prompt,
        model=SEARCH_MODEL_NAME,
        timeout=min(MODEL_TIMEOUT, 90),
        options={"temperature": 0},
    )
    translated = _parse_json_response(raw_response or "", 0) if raw_response else None
    if not isinstance(translated, dict):
        return result

    result = dict(result)
    for key in text_fields:
        value = _clean_text(translated.get(key))
        if value:
            result[key] = value
    for key in list_fields:
        if key == "changes_detected":
            values = _normalize_changes(translated.get(key))
        else:
            values = _normalize_keywords(translated.get(key))
        if values:
            result[key] = values
    return result


def _analysis_language_instruction(output_language: str) -> str:
    normalized_language = _normalize_output_language(output_language)
    language_name = _LANGUAGE_NAMES.get(normalized_language, "English")
    if normalized_language == "en":
        return (
            "Language rule: write every free-text field in English only. "
            "Do not mix English with Chinese, Japanese, or Korean. "
            "Keep enum fields exactly in the requested schema values."
        )
    return (
        f"Language rule: write every free-text field in {language_name} only. "
        "Do not include English words, phrases, or clauses unless they are unavoidable proper nouns. "
        "Keep enum fields exactly in the requested schema values: event_type, severity, continuity_label, and story_phase."
    )


def _normalize_output_language(language: str) -> str:
    normalized = str(language or "en").strip().lower().split("-", 1)[0]
    return normalized or "en"


def _combine_language_fields(text_fields: Dict[str, str], list_fields: Dict[str, List[str]]) -> str:
    return " ".join(
        [value for value in text_fields.values() if value]
        + [item for values in list_fields.values() for item in values if item]
    )


def _needs_target_language_cleanup(text: str, target_language: str) -> bool:
    value = str(text or "")
    if not value.strip():
        return False

    if target_language in {"zh", "ja", "ko"}:
        return _text_needs_cjk_language_cleanup(value, target_language)

    if target_language in {"es", "fr"}:
        return _text_needs_latin_language_cleanup(value, target_language)

    if target_language != "en" and _contains_cjk(value):
        return True
    return False


def _translate_analysis_result(
    result: Dict[str, Any],
    target_language: str,
    text_fields: Dict[str, str],
    list_fields: Dict[str, List[str]],
) -> Dict[str, Any]:
    description_parts = [
        f"[[scene_description]] {text_fields.get('scene_description') or ''}",
        f"[[frame_observation]] {text_fields.get('frame_observation') or ''}",
        f"[[temporal_assessment]] {text_fields.get('temporal_assessment') or ''}",
        f"[[anomaly_rationale]] {text_fields.get('anomaly_rationale') or ''}",
        f"[[keyframe_reason]] {text_fields.get('keyframe_reason') or ''}",
    ]
    description_parts.extend(
        f"[[change]] {item}" for item in list_fields.get("changes_detected", []) if item
    )
    description_parts.extend(
        f"[[subject]] {item}" for item in list_fields.get("tracked_subjects", []) if item
    )
    description_parts.extend(
        f"[[keyword]] {item}" for item in list_fields.get("keywords", []) if item
    )

    translated = translate_event_texts(
        [
            {
                "id": "analysis",
                "summary": text_fields.get("summary") or "",
                "description": "\n".join(part for part in description_parts if part.strip()),
            }
        ],
        target_language,
        force=True,
    )
    if not translated:
        return result

    translated_item = translated[0]
    parsed = _parse_analysis_translation_markers(str(translated_item.get("description") or ""))
    localized = dict(result)
    summary = _clean_text(translated_item.get("summary"))
    if summary:
        localized["summary"] = summary
    for key in ("scene_description", "frame_observation", "temporal_assessment", "anomaly_rationale", "keyframe_reason"):
        value = _clean_text(parsed.get(key))
        if value:
            localized[key] = value
    if parsed.get("changes_detected"):
        localized["changes_detected"] = parsed["changes_detected"][:6]
    if parsed.get("tracked_subjects"):
        localized["tracked_subjects"] = parsed["tracked_subjects"][:6]
    if parsed.get("keywords"):
        localized["keywords"] = parsed["keywords"][:6]
    return localized


def _parse_analysis_translation_markers(text: str) -> Dict[str, Any]:
    parsed: Dict[str, Any] = {
        "changes_detected": [],
        "tracked_subjects": [],
        "keywords": [],
    }
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = re.match(
            r"^\[\[(scene_description|frame_observation|temporal_assessment|anomaly_rationale|keyframe_reason|change|subject|keyword)\]\]\s*(.*)$",
            line,
        )
        if not match:
            continue
        field, value = match.group(1), match.group(2).strip()
        if not value:
            continue
        if field == "change":
            parsed["changes_detected"].append(value)
        elif field == "subject":
            parsed["tracked_subjects"].append(value)
        elif field == "keyword":
            parsed["keywords"].append(value)
        else:
            parsed[field] = value
    return parsed


def _normalize_choice(value: Any, allowed: set[str], default: str) -> str:
    cleaned = _clean_text(value).lower().replace(" ", "_")
    return cleaned if cleaned in allowed else default


def _infer_tracked_subjects(text: str) -> List[str]:
    subjects = []
    if any(word in text for word in {"car", "vehicle", "truck", "motorcycle", "bus", "van"}):
        subjects.append("vehicle")
    if any(word in text for word in {"person", "people", "worker", "pedestrian"}):
        subjects.append("person")
    if any(word in text for word in {"cone", "barrier", "blocked", "obstruction"}):
        subjects.append("road obstruction")
    return subjects[:4]


def _normalize_changes(changes: Any) -> List[str]:
    if isinstance(changes, list):
        cleaned = [_clean_text(item) for item in changes]
        return [item for item in cleaned if item]
    if isinstance(changes, str):
        cleaned = _clean_text(changes)
        return [cleaned] if cleaned else []
    return []


def _normalize_keywords(keywords: Any) -> List[str]:
    if isinstance(keywords, list):
        cleaned = [_clean_text(item).lower() for item in keywords]
    elif isinstance(keywords, str):
        cleaned = [_clean_text(item).lower() for item in keywords.split(",")]
    else:
        cleaned = []

    deduped = []
    seen = set()
    for item in cleaned:
        if item and item not in seen:
            deduped.append(item)
            seen.add(item)
    return deduped[:6]


def _contains_cjk(text: str) -> bool:
    if not text:
        return False
    return bool(re.search(r"[\u3400-\u4dbf\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]", text))


def _contains_han(text: str) -> bool:
    return bool(re.search(r"[\u3400-\u4dbf\u4e00-\u9fff]", str(text or "")))


def _contains_kana(text: str) -> bool:
    return bool(re.search(r"[\u3040-\u30ff]", str(text or "")))


def _contains_hangul(text: str) -> bool:
    return bool(re.search(r"[\uac00-\ud7af]", str(text or "")))


def _text_needs_cjk_language_cleanup(text: str, language: str) -> bool:
    value = str(text or "")
    has_english = bool(re.search(r"[A-Za-z]{2,}", value))
    if language == "zh":
        return has_english or _contains_kana(value) or _contains_hangul(value) or not _contains_han(value)
    if language == "ja":
        return has_english or _contains_hangul(value) or not (_contains_han(value) or _contains_kana(value))
    if language == "ko":
        return has_english or _contains_kana(value) or not _contains_hangul(value)
    return has_english


def _text_needs_latin_language_cleanup(text: str, language: str) -> bool:
    value = str(text or "")
    if _contains_cjk(value):
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
            "con", "sin", "trafico", "tráfico", "vehiculo", "vehículo", "vehiculos",
            "vehículos", "carretera", "flujo", "normal", "estable", "observado",
            "continua", "continúa", "entrada", "interseccion", "intersección",
        },
        "fr": {
            "avec", "sans", "trafic", "vehicule", "véhicule", "vehicules", "véhicules",
            "route", "flux", "normal", "stable", "observe", "observé", "continue",
            "entree", "entrée", "intersection",
        },
    }.get(language, set())
    lowered = {word.lower() for word in ascii_words}
    return bool((lowered & common_english) and not (lowered & target_markers))


def _keywords_from_text(text: str) -> List[str]:
    found = []
    ordered_terms = [
        "person", "people", "vehicle", "car", "truck", "motorcycle", "road",
        "smoke", "fire", "fall", "intruder", "running", "landslide",
        "debris", "blocked", "hazard", "crowd", "night", "daytime",
    ]
    for term in ordered_terms:
        if term in text and term not in found:
            found.append(term)
    return found[:6]


def _infer_event_type(text: str) -> str:
    if any(word in text for word in ANOMALY_HINTS):
        return "anomaly"
    if any(word in text for word in VEHICLE_HINTS):
        return "vehicle"
    if any(word in text for word in PERSON_HINTS):
        return "person"
    if any(word in text for word in MOTION_HINTS):
        return "motion"
    return "normal"


def _infer_severity(text: str) -> str:
    if any(word in text for word in {"fire", "smoke", "weapon", "blood", "crash", "collision", "emergency"}):
        return "Emergency"
    if any(word in text for word in ANOMALY_HINTS):
        return "Warning"
    return "Normal"


def _heuristic_anomaly_score(text: str, event_type: str, severity: str) -> int:
    score = 0

    if event_type == "person":
        score += 18
    elif event_type == "vehicle":
        score += 22
    elif event_type == "motion":
        score += 12
    elif event_type == "anomaly":
        score += 50

    if severity == "Warning":
        score += 20
    elif severity == "Emergency":
        score += 35

    for word in ANOMALY_HINTS:
        if word in text:
            score += 12

    if "person" in text and any(word in text for word in {"running", "fight", "fall", "intruder", "loitering"}):
        score += 15

    if "vehicle" in text and any(word in text for word in {"crash", "blocked", "collision", "speeding"}):
        score += 15

    return min(score, 100)


def _coerce_int(value: Any, minimum: int, maximum: int) -> int:
    try:
        return max(minimum, min(maximum, int(value)))
    except (TypeError, ValueError):
        return minimum


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).strip().split())


def _estimate_change(previous_frame_path: Optional[str], current_frame_path: str) -> Tuple[float, str]:
    """
    Estimate coarse visual change between consecutive frames as a fallback signal.
    Returns (changed_area_ratio_percent, change_level).
    """
    if not previous_frame_path:
        return 0.0, "unknown"

    prev = cv2.imread(str(previous_frame_path), cv2.IMREAD_GRAYSCALE)
    curr = cv2.imread(str(current_frame_path), cv2.IMREAD_GRAYSCALE)
    if prev is None or curr is None:
        return 0.0, "unknown"

    if prev.shape != curr.shape:
        curr = cv2.resize(curr, (prev.shape[1], prev.shape[0]))

    diff = cv2.absdiff(prev, curr)
    _, thresh = cv2.threshold(diff, 22, 255, cv2.THRESH_BINARY)
    changed_ratio = (cv2.countNonZero(thresh) / thresh.size) * 100.0

    if changed_ratio >= 18:
        level = "high"
    elif changed_ratio >= 6:
        level = "medium"
    else:
        level = "low"

    return changed_ratio, level
