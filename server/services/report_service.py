"""
Investigation report PDF generation.

Builds a lightweight multi-page PDF using Pillow so the frontend can export
human-readable investigation packets without adding extra system dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Optional

from PIL import Image, ImageDraw, ImageFont, ImageOps


PAGE_WIDTH = 1240
PAGE_HEIGHT = 1754
PAGE_MARGIN = 76
CARD_RADIUS = 24
CARD_GAP = 18
CLUE_IMAGE_WIDTH = 360
CLUE_IMAGE_HEIGHT = 220
MAX_QA_PAIRS = 4
MAX_CLUES = 6

COLOR_BG = (245, 247, 250)
COLOR_PANEL = (255, 255, 255)
COLOR_PANEL_ALT = (251, 252, 253)
COLOR_BORDER = (223, 228, 234)
COLOR_TEXT = (22, 28, 36)
COLOR_MUTED = (95, 104, 114)
COLOR_ACCENT = (255, 107, 69)
COLOR_ACCENT_SOFT = (255, 239, 232)
COLOR_SUCCESS = (28, 160, 98)
COLOR_WARNING = (214, 119, 35)
COLOR_DANGER = (207, 70, 70)

RESAMPLING_LANCZOS = getattr(getattr(Image, "Resampling", Image), "LANCZOS")

REPORT_LABELS = {
    "en": {
        "title": "Investigation Report",
        "videoScope": "Analyzed video investigation",
        "cameraScope": "Live camera investigation",
        "generated": "Generated",
        "anchor": "Anchor",
        "eventCount": "Clues",
        "qaSummary": "QA Summary",
        "noQa": "No user QA exchange was captured yet. This report falls back to the current clue timeline.",
        "story": "Incident Story",
        "storyMissing": "No story reconstruction is available yet.",
        "timeline": "Timeline Beats",
        "actors": "Key Actors",
        "reviewFocus": "Review Next",
        "openQuestions": "Still Unclear",
        "recordings": "Recommended Recording Ranges",
        "clues": "Key Clues",
        "agentTrace": "Agent Trace",
        "user": "User",
        "assistant": "Assistant",
        "confidence": "Confidence",
        "high": "High",
        "medium": "Medium",
        "low": "Low",
        "before": "Before",
        "key": "Key",
        "after": "After",
        "none": "None",
        "page": "Page",
        "of": "of",
        "summaryFallback": "Notable clue",
        "window": "Range",
    },
    "zh": {
        "title": "調查報告",
        "videoScope": "影片調查報告",
        "cameraScope": "攝影機調查報告",
        "generated": "輸出時間",
        "anchor": "調閱錨點",
        "eventCount": "線索數",
        "qaSummary": "QA 整理",
        "noQa": "目前尚未留下使用者 QA 對話，以下先整理目前可用的事件線索。",
        "story": "事發還原",
        "storyMissing": "目前尚未生成完整的事發還原。",
        "timeline": "時間軸節點",
        "actors": "關鍵對象",
        "reviewFocus": "建議複查",
        "openQuestions": "待確認",
        "recordings": "建議回看片段",
        "clues": "關鍵線索",
        "agentTrace": "代理調查步驟",
        "user": "使用者",
        "assistant": "系統",
        "confidence": "信心",
        "high": "高",
        "medium": "中",
        "low": "低",
        "before": "事前",
        "key": "關鍵",
        "after": "事後",
        "none": "無",
        "page": "第",
        "of": "頁 / 共",
        "summaryFallback": "關鍵線索",
        "window": "片段",
    },
    "es": {
        "title": "Informe de investigacion",
        "videoScope": "Investigacion de video analizado",
        "cameraScope": "Investigacion de camara en vivo",
        "generated": "Generado",
        "anchor": "Ancla",
        "eventCount": "Pistas",
        "qaSummary": "Resumen QA",
        "noQa": "Todavia no se capturo un intercambio QA. Este informe usa la linea de pistas actual.",
        "story": "Historia del incidente",
        "storyMissing": "Todavia no hay una reconstruccion completa.",
        "timeline": "Momentos",
        "actors": "Actores clave",
        "reviewFocus": "Revisar despues",
        "openQuestions": "Aun incierto",
        "recordings": "Ventanas recomendadas",
        "clues": "Pistas clave",
        "agentTrace": "Pasos del agente",
        "user": "Usuario",
        "assistant": "Sistema",
        "confidence": "Confianza",
        "high": "Alta",
        "medium": "Media",
        "low": "Baja",
        "before": "Antes",
        "key": "Clave",
        "after": "Despues",
        "none": "Ninguno",
        "page": "Pagina",
        "of": "de",
        "summaryFallback": "Pista notable",
        "window": "Ventana",
    },
    "fr": {
        "title": "Rapport d'investigation",
        "videoScope": "Investigation video analysee",
        "cameraScope": "Investigation camera en direct",
        "generated": "Genere",
        "anchor": "Ancre",
        "eventCount": "Indices",
        "qaSummary": "Resume QA",
        "noQa": "Aucun echange QA utile n'a encore ete capture. Ce rapport s'appuie sur les indices actuels.",
        "story": "Recit de l'incident",
        "storyMissing": "Aucune reconstruction complete n'est encore disponible.",
        "timeline": "Moments",
        "actors": "Acteurs cles",
        "reviewFocus": "A revoir",
        "openQuestions": "Encore incertain",
        "recordings": "Fenetres recommandees",
        "clues": "Indices cles",
        "agentTrace": "Etapes agent",
        "user": "Utilisateur",
        "assistant": "Systeme",
        "confidence": "Confiance",
        "high": "Haute",
        "medium": "Moyenne",
        "low": "Faible",
        "before": "Avant",
        "key": "Cle",
        "after": "Apres",
        "none": "Aucun",
        "page": "Page",
        "of": "sur",
        "summaryFallback": "Indice notable",
        "window": "Fenetre",
    },
    "ja": {
        "title": "調査レポート",
        "videoScope": "解析済み動画の調査",
        "cameraScope": "ライブカメラの調査",
        "generated": "出力時刻",
        "anchor": "アンカー",
        "eventCount": "手掛かり数",
        "qaSummary": "QA まとめ",
        "noQa": "まだ QA のやり取りは記録されていません。現在の手掛かりを元に整理しています。",
        "story": "事案再構成",
        "storyMissing": "まだ十分な再構成はありません。",
        "timeline": "時系列ポイント",
        "actors": "主要対象",
        "reviewFocus": "確認ポイント",
        "openQuestions": "未確定",
        "recordings": "確認推奨区間",
        "clues": "主要手掛かり",
        "agentTrace": "調査ステップ",
        "user": "ユーザー",
        "assistant": "システム",
        "confidence": "確信度",
        "high": "高",
        "medium": "中",
        "low": "低",
        "before": "前",
        "key": "要点",
        "after": "後",
        "none": "なし",
        "page": "ページ",
        "of": "/",
        "summaryFallback": "注目ポイント",
        "window": "区間",
    },
    "ko": {
        "title": "조사 보고서",
        "videoScope": "분석된 영상 조사",
        "cameraScope": "실시간 카메라 조사",
        "generated": "생성 시각",
        "anchor": "앵커",
        "eventCount": "단서 수",
        "qaSummary": "QA 정리",
        "noQa": "아직 사용자 QA 기록이 없습니다. 현재 단서 타임라인으로 먼저 정리합니다.",
        "story": "사건 재구성",
        "storyMissing": "아직 충분한 사건 재구성이 없습니다.",
        "timeline": "타임라인 포인트",
        "actors": "핵심 대상",
        "reviewFocus": "다음 확인",
        "openQuestions": "불확실한 점",
        "recordings": "권장 검토 구간",
        "clues": "핵심 단서",
        "agentTrace": "조사 단계",
        "user": "사용자",
        "assistant": "시스템",
        "confidence": "신뢰도",
        "high": "높음",
        "medium": "중간",
        "low": "낮음",
        "before": "이전",
        "key": "핵심",
        "after": "이후",
        "none": "없음",
        "page": "페이지",
        "of": "/",
        "summaryFallback": "주요 단서",
        "window": "구간",
    },
}


@dataclass
class _QaPair:
    question: str
    answer: str
    confidence: Optional[str]


class _PdfReportCanvas:
    def __init__(self, labels: dict[str, str]):
        self.labels = labels
        self.pages: list[Image.Image] = []
        self.page: Optional[Image.Image] = None
        self.draw: Optional[ImageDraw.ImageDraw] = None
        self.y = PAGE_MARGIN
        self.font_title = _load_font(42, bold=True)
        self.font_h2 = _load_font(24, bold=True)
        self.font_h3 = _load_font(18, bold=True)
        self.font_body = _load_font(16, bold=False)
        self.font_small = _load_font(14, bold=False)
        self.font_small_bold = _load_font(14, bold=True)
        self.new_page()

    def new_page(self) -> None:
        page = Image.new("RGB", (PAGE_WIDTH, PAGE_HEIGHT), COLOR_BG)
        draw = ImageDraw.Draw(page)
        self.pages.append(page)
        self.page = page
        self.draw = draw
        self.y = PAGE_MARGIN

    def ensure_space(self, height: int) -> None:
        if self.y + height > PAGE_HEIGHT - PAGE_MARGIN:
            self.new_page()

    def section_title(self, text: str) -> None:
        self.ensure_space(44)
        self.draw.text((PAGE_MARGIN, self.y), text, fill=COLOR_TEXT, font=self.font_h2)
        self.y += 34
        self.draw.line((PAGE_MARGIN, self.y, PAGE_WIDTH - PAGE_MARGIN, self.y), fill=COLOR_BORDER, width=2)
        self.y += 18

    def paragraph(self, text: str, *, fill: tuple[int, int, int] = COLOR_MUTED, top_pad: int = 0) -> None:
        if top_pad:
            self.y += top_pad
        self.y = _draw_wrapped_text(
            self.draw,
            PAGE_MARGIN,
            self.y,
            text,
            font=self.font_body,
            max_width=PAGE_WIDTH - (PAGE_MARGIN * 2),
            fill=fill,
            line_gap=8,
        )
        self.y += 10

    def bullet_list(self, items: list[str], *, max_items: int = 6, muted: bool = False) -> None:
        if not items:
            self.paragraph(self.labels["none"])
            return
        for item in items[:max_items]:
            self.ensure_space(46)
            bullet_x = PAGE_MARGIN + 4
            bullet_y = self.y + 9
            self.draw.ellipse(
                (bullet_x, bullet_y, bullet_x + 8, bullet_y + 8),
                fill=COLOR_ACCENT if not muted else COLOR_MUTED,
            )
            self.y = _draw_wrapped_text(
                self.draw,
                PAGE_MARGIN + 22,
                self.y,
                item,
                font=self.font_body,
                max_width=PAGE_WIDTH - (PAGE_MARGIN * 2) - 22,
                fill=COLOR_MUTED if muted else COLOR_TEXT,
                line_gap=8,
            )
            self.y += 8

    def qa_pair(self, pair: _QaPair) -> None:
        estimated_height = 150
        self.ensure_space(estimated_height)
        x0 = PAGE_MARGIN
        x1 = PAGE_WIDTH - PAGE_MARGIN
        y0 = self.y
        card_height = 126
        self.draw.rounded_rectangle((x0, y0, x1, y0 + card_height), radius=20, fill=COLOR_PANEL, outline=COLOR_BORDER, width=2)
        self.draw.text((x0 + 18, y0 + 14), self.labels["user"], fill=COLOR_ACCENT, font=self.font_small_bold)
        _draw_wrapped_text(
            self.draw,
            x0 + 96,
            y0 + 12,
            pair.question,
            font=self.font_body,
            max_width=(x1 - x0) - 122,
            fill=COLOR_TEXT,
            line_gap=6,
            max_lines=2,
        )
        self.draw.text((x0 + 18, y0 + 62), self.labels["assistant"], fill=COLOR_SUCCESS, font=self.font_small_bold)
        _draw_wrapped_text(
            self.draw,
            x0 + 96,
            y0 + 60,
            pair.answer,
            font=self.font_body,
            max_width=(x1 - x0) - 190,
            fill=COLOR_TEXT,
            line_gap=6,
            max_lines=3,
        )
        if pair.confidence:
            badge_text = f"{self.labels['confidence']}: {self.labels.get(pair.confidence, pair.confidence.title())}"
            _draw_badge(self.draw, x1 - 188, y0 + 14, badge_text, font=self.font_small, fg=COLOR_TEXT, bg=COLOR_ACCENT_SOFT)
        self.y = y0 + card_height + 14

    def key_value_grid(self, values: list[tuple[str, str]]) -> None:
        col_gap = 18
        col_width = ((PAGE_WIDTH - (PAGE_MARGIN * 2)) - col_gap) // 2
        row_height = 74
        rows = [values[index:index + 2] for index in range(0, len(values), 2)]
        for row in rows:
            self.ensure_space(row_height + 10)
            for index, (label, value) in enumerate(row):
                x0 = PAGE_MARGIN + (index * (col_width + col_gap))
                x1 = x0 + col_width
                y0 = self.y
                self.draw.rounded_rectangle((x0, y0, x1, y0 + row_height), radius=18, fill=COLOR_PANEL, outline=COLOR_BORDER, width=2)
                self.draw.text((x0 + 16, y0 + 12), label, fill=COLOR_MUTED, font=self.font_small_bold)
                _draw_wrapped_text(
                    self.draw,
                    x0 + 16,
                    y0 + 34,
                    value,
                    font=self.font_body,
                    max_width=col_width - 32,
                    fill=COLOR_TEXT,
                    line_gap=6,
                    max_lines=2,
                )
            self.y += row_height + 12

    def event_card(self, event: dict[str, Any], absolute_time: bool) -> None:
        card_height = 294
        self.ensure_space(card_height + 14)
        x0 = PAGE_MARGIN
        x1 = PAGE_WIDTH - PAGE_MARGIN
        y0 = self.y
        self.draw.rounded_rectangle((x0, y0, x1, y0 + card_height), radius=CARD_RADIUS, fill=COLOR_PANEL, outline=COLOR_BORDER, width=2)

        image_box = (x0 + 18, y0 + 18, x0 + 18 + CLUE_IMAGE_WIDTH, y0 + 18 + CLUE_IMAGE_HEIGHT)
        image = _load_frame_preview(event.get("frame_path"))
        if image is not None:
            image = ImageOps.fit(image, (CLUE_IMAGE_WIDTH, CLUE_IMAGE_HEIGHT), method=RESAMPLING_LANCZOS)
            self.page.paste(image, (image_box[0], image_box[1]))
        else:
            self.draw.rounded_rectangle(image_box, radius=16, fill=COLOR_PANEL_ALT, outline=COLOR_BORDER, width=2)
            placeholder = self.labels["summaryFallback"]
            bbox = self.draw.textbbox((0, 0), placeholder, font=self.font_small_bold)
            width = bbox[2] - bbox[0]
            height = bbox[3] - bbox[1]
            px = image_box[0] + ((CLUE_IMAGE_WIDTH - width) / 2)
            py = image_box[1] + ((CLUE_IMAGE_HEIGHT - height) / 2)
            self.draw.text((px, py), placeholder, fill=COLOR_MUTED, font=self.font_small_bold)

        right_x = image_box[2] + 22
        time_text = _format_report_timestamp(event.get("timestamp_sec"), absolute_time)
        meta_text = f"{time_text}  |  {event.get('event_type') or 'none'}  |  {event.get('severity') or 'Normal'}"
        self.draw.text((right_x, y0 + 22), meta_text, fill=COLOR_MUTED, font=self.font_small_bold)

        title_text = _clean_text(event.get("summary")) or _clean_text(event.get("description")) or self.labels["summaryFallback"]
        detail_text = _clean_text(event.get("description")) or title_text
        next_y = _draw_wrapped_text(
            self.draw,
            right_x,
            y0 + 52,
            title_text,
            font=self.font_h3,
            max_width=x1 - right_x - 18,
            fill=COLOR_TEXT,
            line_gap=7,
            max_lines=3,
        )
        next_y = _draw_wrapped_text(
            self.draw,
            right_x,
            next_y + 10,
            detail_text,
            font=self.font_body,
            max_width=x1 - right_x - 18,
            fill=COLOR_MUTED,
            line_gap=7,
            max_lines=6,
        )
        event_id = event.get("id")
        if event_id is not None:
            _draw_badge(
                self.draw,
                right_x,
                y0 + card_height - 46,
                f"event #{event_id}",
                font=self.font_small,
                fg=COLOR_TEXT,
                bg=COLOR_ACCENT_SOFT,
            )
        self.y = y0 + card_height + 14

    def finalize(self) -> bytes:
        total_pages = len(self.pages)
        for index, page in enumerate(self.pages, start=1):
            draw = ImageDraw.Draw(page)
            footer = f"Phylax  |  {self.labels['page']} {index} {self.labels['of']} {total_pages}"
            draw.line((PAGE_MARGIN, PAGE_HEIGHT - 52, PAGE_WIDTH - PAGE_MARGIN, PAGE_HEIGHT - 52), fill=COLOR_BORDER, width=2)
            draw.text((PAGE_MARGIN, PAGE_HEIGHT - 40), footer, fill=COLOR_MUTED, font=self.font_small)

        buffer = BytesIO()
        first, *rest = self.pages
        first.save(buffer, format="PDF", save_all=True, append_images=rest)
        buffer.seek(0)
        return buffer.getvalue()


def build_investigation_report_pdf(
    *,
    language: str = "en",
    resource_kind: str,
    resource_title: str,
    scope_summary: str = "",
    current_timestamp_sec: Optional[float] = None,
    messages: list[dict[str, Any]],
    timeline_rows: list[dict[str, Any]],
) -> bytes:
    labels = _report_labels(language)
    absolute_time = _timeline_uses_absolute_time(timeline_rows, current_timestamp_sec)
    qa_pairs = _build_qa_pairs(messages)
    latest_reconstruction = _latest_reconstruction(messages)
    latest_trace = _latest_agent_trace(messages)
    clue_rows = _select_report_clues(messages, timeline_rows)[:MAX_CLUES]
    review_ranges = _build_review_ranges(clue_rows, absolute_time=absolute_time)

    canvas = _PdfReportCanvas(labels)
    scope_label = labels["cameraScope"] if resource_kind == "camera" else labels["videoScope"]
    header_rows = [
        (scope_label, _clean_text(resource_title) or scope_label),
        (labels["generated"], datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        (labels["anchor"], _format_report_timestamp(current_timestamp_sec, absolute_time) if current_timestamp_sec is not None else labels["none"]),
        (labels["eventCount"], str(len(timeline_rows))),
    ]

    canvas.draw.text((PAGE_MARGIN, canvas.y), labels["title"], fill=COLOR_TEXT, font=canvas.font_title)
    canvas.y += 56
    if scope_summary:
        canvas.paragraph(scope_summary, fill=COLOR_MUTED)
    canvas.key_value_grid(header_rows)

    canvas.section_title(labels["qaSummary"])
    if qa_pairs:
        for pair in qa_pairs[-MAX_QA_PAIRS:]:
            canvas.qa_pair(pair)
    else:
        canvas.paragraph(labels["noQa"])

    canvas.section_title(labels["story"])
    if latest_reconstruction:
        headline = _clean_text(latest_reconstruction.get("headline"))
        summary = _clean_text(latest_reconstruction.get("summary"))
        if headline:
            canvas.paragraph(headline, fill=COLOR_TEXT)
        canvas.paragraph(summary or labels["storyMissing"], fill=COLOR_MUTED)

        story_beats = latest_reconstruction.get("story_beats") or []
        if story_beats:
            canvas.draw.text((PAGE_MARGIN, canvas.y), labels["timeline"], fill=COLOR_TEXT, font=canvas.font_h3)
            canvas.y += 26
            for beat in story_beats[:6]:
                phase = labels.get(str(beat.get("phase") or "key").lower(), labels["key"])
                beat_line = f"{phase}  |  {_format_report_timestamp(beat.get('timestamp_sec'), absolute_time)}  |  {_clean_text(beat.get('title')) or _clean_text(beat.get('detail'))}"
                canvas.bullet_list([beat_line], max_items=1)

        actors = _normalize_text_list(latest_reconstruction.get("actors"), limit=8)
        if actors:
            canvas.draw.text((PAGE_MARGIN, canvas.y), labels["actors"], fill=COLOR_TEXT, font=canvas.font_h3)
            canvas.y += 26
            canvas.bullet_list(actors, max_items=8)

        review_focus = _normalize_text_list(latest_reconstruction.get("review_focus"), limit=6)
        if review_focus:
            canvas.draw.text((PAGE_MARGIN, canvas.y), labels["reviewFocus"], fill=COLOR_TEXT, font=canvas.font_h3)
            canvas.y += 26
            canvas.bullet_list(review_focus, max_items=6)

        open_questions = _normalize_text_list(latest_reconstruction.get("open_questions"), limit=5)
        if open_questions:
            canvas.draw.text((PAGE_MARGIN, canvas.y), labels["openQuestions"], fill=COLOR_TEXT, font=canvas.font_h3)
            canvas.y += 26
            canvas.bullet_list(open_questions, max_items=5, muted=True)
    else:
        canvas.paragraph(labels["storyMissing"])

    if review_ranges:
        canvas.section_title(labels["recordings"])
        range_lines = []
        for index, review_range in enumerate(review_ranges, start=1):
            range_lines.append(
                f"{labels['window']} {index}: "
                f"{_format_report_range(review_range['start_sec'], review_range['end_sec'], absolute_time)}"
                f"  |  {review_range['reason']}"
            )
        canvas.bullet_list(range_lines, max_items=6)

    if latest_trace:
        canvas.section_title(labels["agentTrace"])
        trace_lines = [
            f"{_clean_text(step.get('title'))}: {_clean_text(step.get('detail'))}"
            for step in latest_trace[:4]
            if _clean_text(step.get("title")) or _clean_text(step.get("detail"))
        ]
        canvas.bullet_list(trace_lines or [labels["none"]], max_items=6, muted=True)

    if clue_rows:
        canvas.section_title(labels["clues"])
        for clue in clue_rows[:4]:
            canvas.event_card(clue, absolute_time=absolute_time)

    return canvas.finalize()


def _report_labels(language: str) -> dict[str, str]:
    normalized = (language or "en").strip().lower()
    short = normalized.split("-")[0]
    return REPORT_LABELS.get(normalized) or REPORT_LABELS.get(short) or REPORT_LABELS["en"]


def _timeline_uses_absolute_time(timeline_rows: list[dict[str, Any]], current_timestamp_sec: Optional[float]) -> bool:
    timestamps = [float(row.get("timestamp_sec") or 0.0) for row in timeline_rows[:8] if row.get("timestamp_sec") is not None]
    if current_timestamp_sec is not None:
        timestamps.append(float(current_timestamp_sec))
    return any(timestamp > 1_000_000_000 for timestamp in timestamps)


def _build_qa_pairs(messages: list[dict[str, Any]]) -> list[_QaPair]:
    pairs: list[_QaPair] = []
    pending_question: Optional[str] = None
    for message in messages:
        role = _clean_text(message.get("role")).lower()
        content = _clean_text(message.get("content"))
        if not content:
            continue
        if role == "user":
            pending_question = content
            continue
        if role != "assistant":
            continue
        if pending_question:
            pairs.append(
                _QaPair(
                    question=pending_question,
                    answer=content,
                    confidence=_clean_text(message.get("confidence")).lower() or None,
                )
            )
            pending_question = None
    return pairs


def _latest_reconstruction(messages: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    for message in reversed(messages):
        reconstruction = message.get("reconstruction")
        if isinstance(reconstruction, dict):
            return reconstruction
    return None


def _latest_agent_trace(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for message in reversed(messages):
        trace = message.get("agent_trace")
        if isinstance(trace, list) and trace:
            return [step for step in trace if isinstance(step, dict)]
    return []


def _select_report_clues(messages: list[dict[str, Any]], timeline_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized_rows = [_normalize_timeline_row(row) for row in timeline_rows]
    rows_by_id = {
        int(row["id"]): row
        for row in normalized_rows
        if row.get("id") is not None
    }
    selected: list[dict[str, Any]] = []
    seen_keys: set[tuple[int, int]] = set()

    def add_row(row: Optional[dict[str, Any]]) -> None:
        if not row:
            return
        key = (int(row.get("id") or 0), int(round(float(row.get("timestamp_sec") or 0.0))))
        if key in seen_keys:
            return
        seen_keys.add(key)
        selected.append(row)

    for message in reversed(messages):
        reconstruction = message.get("reconstruction")
        if isinstance(reconstruction, dict):
            for beat in reconstruction.get("story_beats") or []:
                resolved = _resolve_clue_reference(beat, rows_by_id, normalized_rows)
                add_row(resolved)
        for event in message.get("relevant_events") or []:
            if isinstance(event, dict):
                resolved = _resolve_clue_reference(event, rows_by_id, normalized_rows)
                add_row(resolved)

    if len(selected) < 4:
        fallback_rows = sorted(normalized_rows, key=_fallback_clue_sort_key)
        for row in fallback_rows:
            add_row(row)
            if len(selected) >= MAX_CLUES:
                break

    return selected[:MAX_CLUES]


def _resolve_clue_reference(
    reference: dict[str, Any],
    rows_by_id: dict[int, dict[str, Any]],
    timeline_rows: list[dict[str, Any]],
) -> Optional[dict[str, Any]]:
    try:
        event_id = int(reference.get("event_id"))
    except (TypeError, ValueError):
        event_id = None

    if event_id is not None and event_id in rows_by_id:
        return rows_by_id[event_id]

    try:
        timestamp_sec = float(reference.get("timestamp_sec"))
    except (TypeError, ValueError):
        timestamp_sec = None

    if timestamp_sec is None or not timeline_rows:
        return _normalize_timeline_row(reference)

    best = min(
        timeline_rows,
        key=lambda row: (
            abs(float(row.get("timestamp_sec") or 0.0) - timestamp_sec),
            0 if row.get("frame_path") else 1,
        ),
    )
    return best


def _fallback_clue_sort_key(row: dict[str, Any]) -> tuple[float, float]:
    score = 0.0
    event_type = _clean_text(row.get("event_type")).lower()
    severity = _clean_text(row.get("severity")).lower()
    if event_type == "anomaly":
        score += 6.0
    elif event_type in {"vehicle", "person"}:
        score += 2.5
    if severity in {"warning", "emergency", "abnormal"}:
        score += 4.0
    if row.get("frame_path"):
        score += 1.0
    if _clean_text(row.get("summary")):
        score += 0.5
    return (-score, -float(row.get("timestamp_sec") or 0.0))


def _build_review_ranges(clue_rows: list[dict[str, Any]], *, absolute_time: bool) -> list[dict[str, Any]]:
    ranges: list[dict[str, Any]] = []
    for row in clue_rows[:5]:
        timestamp_sec = float(row.get("timestamp_sec") or 0.0)
        if absolute_time:
            start_sec = timestamp_sec - 12
            end_sec = timestamp_sec + 12
        else:
            start_sec = max(0.0, timestamp_sec - 8)
            end_sec = timestamp_sec + 10
        ranges.append(
            {
                "start_sec": start_sec,
                "end_sec": end_sec,
                "reason": _clean_text(row.get("summary")) or _clean_text(row.get("description")) or "notable clue",
            }
        )

    merged: list[dict[str, Any]] = []
    for review_range in sorted(ranges, key=lambda item: float(item["start_sec"])):
        if not merged:
            merged.append(review_range)
            continue
        last = merged[-1]
        if review_range["start_sec"] <= last["end_sec"] + 2:
            last["end_sec"] = max(last["end_sec"], review_range["end_sec"])
            if len(_clean_text(review_range["reason"])) > len(_clean_text(last["reason"])):
                last["reason"] = review_range["reason"]
            continue
        merged.append(review_range)
    return merged[:4]


def _normalize_timeline_row(row: dict[str, Any]) -> dict[str, Any]:
    try:
        row_id = int(row.get("id"))
    except (TypeError, ValueError):
        try:
            row_id = int(row.get("event_id"))
        except (TypeError, ValueError):
            row_id = 0
    try:
        timestamp_sec = float(row.get("timestamp_sec") or 0.0)
    except (TypeError, ValueError):
        timestamp_sec = 0.0
    return {
        "id": row_id,
        "event_id": row_id,
        "timestamp_sec": timestamp_sec,
        "frame_path": row.get("frame_path"),
        "summary": _clean_text(row.get("summary")),
        "description": _clean_text(row.get("description")) or _clean_text(row.get("detail")),
        "event_type": _clean_text(row.get("event_type")) or "none",
        "severity": _clean_text(row.get("severity")) or "Normal",
    }


def _normalize_text_list(value: Any, *, limit: int = 6) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for item in value:
        cleaned = _clean_text(item)
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(cleaned)
        if len(normalized) >= limit:
            break
    return normalized


def _draw_badge(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    text: str,
    *,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    fg: tuple[int, int, int],
    bg: tuple[int, int, int],
) -> None:
    bbox = draw.textbbox((0, 0), text, font=font)
    width = (bbox[2] - bbox[0]) + 18
    height = (bbox[3] - bbox[1]) + 12
    draw.rounded_rectangle((x, y, x + width, y + height), radius=999, fill=bg)
    draw.text((x + 9, y + 6), text, fill=fg, font=font)


def _draw_wrapped_text(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    text: str,
    *,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    max_width: int,
    fill: tuple[int, int, int],
    line_gap: int,
    max_lines: Optional[int] = None,
) -> int:
    lines = _wrap_text(draw, text, font, max_width)
    if max_lines is not None and len(lines) > max_lines:
        lines = lines[:max_lines]
        if lines:
            lines[-1] = lines[-1].rstrip(". ") + "..."
    current_y = y
    bbox = draw.textbbox((0, 0), "Ag", font=font)
    line_height = max(18, bbox[3] - bbox[1] + line_gap)
    for line in lines or [""]:
        draw.text((x, current_y), line, fill=fill, font=font)
        current_y += line_height
    return current_y


def _wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    max_width: int,
) -> list[str]:
    paragraphs = str(text or "").replace("\r", "").split("\n")
    lines: list[str] = []
    for paragraph in paragraphs:
        if not paragraph:
            lines.append("")
            continue
        current = ""
        for char in paragraph:
            candidate = current + char
            bbox = draw.textbbox((0, 0), candidate, font=font)
            width = bbox[2] - bbox[0]
            if current and width > max_width:
                lines.append(current.rstrip())
                current = char.lstrip()
            else:
                current = candidate
        if current:
            lines.append(current.rstrip())
    return [line for line in lines if line is not None]


def _load_frame_preview(frame_path: Any) -> Optional[Image.Image]:
    path = Path(str(frame_path or "").strip())
    if not path.exists():
        return None
    try:
        image = Image.open(path)
        return image.convert("RGB")
    except Exception:
        return None


def _load_font(size: int, *, bold: bool) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    font = _try_load_font(size=size, bold=bold)
    if font is not None:
        return font
    return ImageFont.load_default()


def _try_load_font(size: int, *, bold: bool) -> Optional[ImageFont.FreeTypeFont]:
    candidates = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc" if bold else "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc" if bold else "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate)
        if not path.exists():
            continue
        try:
            return ImageFont.truetype(str(path), size=size)
        except Exception:
            continue
    return None


def _format_report_timestamp(value: Any, absolute_time: bool) -> str:
    try:
        timestamp_sec = float(value)
    except (TypeError, ValueError):
        return "-"
    if absolute_time:
        return datetime.fromtimestamp(timestamp_sec).strftime("%Y-%m-%d %H:%M:%S")
    total = max(0, int(round(timestamp_sec)))
    hours = total // 3600
    minutes = (total % 3600) // 60
    seconds = total % 60
    if hours > 0:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def _format_report_range(start_sec: float, end_sec: float, absolute_time: bool) -> str:
    return f"{_format_report_timestamp(start_sec, absolute_time)} - {_format_report_timestamp(end_sec, absolute_time)}"


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).strip().split())
