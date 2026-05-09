"""
Pydantic schemas for API request/response validation.
Keeps a clean separation between database rows and API contracts.
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from typing_extensions import Literal


# -- Video Schemas --

class VideoOut(BaseModel):
    """Response schema for a single video."""
    id: int
    title: str
    filename: str
    thumbnail: Optional[str] = None
    duration: float = 0
    upload_time: str
    video_type: str = "uploaded"
    status: str = "pending"
    analysis_progress: float = 0


class VideoUpdate(BaseModel):
    """Schema for updating a video."""
    title: Optional[str] = Field(None, min_length=1, max_length=200)


class VideoListOut(BaseModel):
    """Paginated list of videos."""
    videos: List[VideoOut]
    total: int
    page: int
    page_size: int


# -- Analysis Event Schemas --

class AnalysisEventOut(BaseModel):
    """Single analysis event from AI frame comparison."""
    id: int
    video_id: Optional[int] = None
    camera_id: Optional[int] = None
    timestamp_sec: float
    frame_path: Optional[str] = None
    description: str
    event_type: str = "none"
    severity: str = "low"
    diff_description: Optional[str] = None
    summary: Optional[str] = None
    changes_detected: List[str] = Field(default_factory=list)
    anomaly_score: int = 0
    requires_attention: bool = False
    frame_observation: Optional[str] = None
    temporal_assessment: Optional[str] = None
    anomaly_rationale: Optional[str] = None
    keywords: List[str] = Field(default_factory=list)
    created_at: str


class AnalysisStatusOut(BaseModel):
    """Status of an ongoing or completed analysis."""
    video_id: int
    status: str
    progress: float
    total_events: int


class AnalysisStartOptions(BaseModel):
    """Optional controls for per-run video analysis behavior."""
    motion_filter_enabled: bool = False
    motion_threshold: int = Field(0, ge=0, le=10)
    detail_mode: Literal["fast", "careful"] = "careful"
    analysis_interval_seconds: float = Field(10, ge=1, le=60)


class VideoQuestionTurn(BaseModel):
    """A lightweight prior chat turn for video QA continuity."""
    role: Literal["user", "assistant"]
    content: str = Field(..., min_length=1, max_length=2000)
    confidence: Optional[Literal["high", "medium", "low"]] = None
    relevant_events: List[Dict[str, Any]] = Field(default_factory=list)
    reconstruction: Optional[Dict[str, Any]] = None


class VideoQuestionRequest(BaseModel):
    """Question about one analyzed video, optionally anchored to playback time."""
    question: str = Field(..., min_length=1, max_length=2000)
    language: Optional[str] = Field(None, min_length=2, max_length=8)
    current_timestamp_sec: Optional[float] = Field(None, ge=0)
    history: List[VideoQuestionTurn] = Field(default_factory=list)


class VideoQuestionRelevantEventOut(BaseModel):
    """A clue event surfaced to support a video QA answer."""
    event_id: int
    timestamp_sec: float
    event_type: str = "none"
    severity: str = "Normal"
    summary: str = ""
    description: str = ""
    preview_url: Optional[str] = None


class VideoQuestionAgentStepOut(BaseModel):
    """One internal investigation step from the agentic QA workflow."""
    step: str
    title: str
    detail: str


class VideoQuestionStoryBeatOut(BaseModel):
    """One story beat inside an incident reconstruction."""
    event_id: Optional[int] = None
    timestamp_sec: float = 0
    phase: str = "key"
    title: str
    detail: str
    preview_url: Optional[str] = None


class VideoQuestionReconstructionOut(BaseModel):
    """Human-friendly incident reconstruction assembled from nearby evidence."""
    headline: str
    summary: str
    story_beats: List[VideoQuestionStoryBeatOut] = Field(default_factory=list)
    actors: List[str] = Field(default_factory=list)
    review_focus: List[str] = Field(default_factory=list)
    open_questions: List[str] = Field(default_factory=list)


class VideoQuestionResponseOut(BaseModel):
    """Structured answer for the watch-page QA panel."""
    answer: str
    confidence: Literal["high", "medium", "low"] = "medium"
    relevant_events: List[VideoQuestionRelevantEventOut] = Field(default_factory=list)
    current_timestamp_sec: Optional[float] = None
    follow_up_suggestion: Optional[str] = None
    agent_trace: List[VideoQuestionAgentStepOut] = Field(default_factory=list)
    reconstruction: Optional[VideoQuestionReconstructionOut] = None


class InvestigationReportMessage(BaseModel):
    """One QA message included in an exported investigation report."""
    role: Literal["user", "assistant"]
    content: str = Field(..., min_length=1, max_length=4000)
    confidence: Optional[Literal["high", "medium", "low"]] = None
    relevant_events: List[VideoQuestionRelevantEventOut] = Field(default_factory=list)
    agent_trace: List[VideoQuestionAgentStepOut] = Field(default_factory=list)
    reconstruction: Optional[VideoQuestionReconstructionOut] = None


class InvestigationReportRequest(BaseModel):
    """Payload used to render a PDF investigation report for a video or camera."""
    language: Optional[str] = Field(None, min_length=2, max_length=8)
    current_timestamp_sec: Optional[float] = Field(None, ge=0)
    messages: List[InvestigationReportMessage] = Field(default_factory=list)


# -- Search Schemas --

class SearchQuery(BaseModel):
    """Natural language search query."""
    query: str = Field(..., min_length=1, max_length=500)


class SearchResultOut(BaseModel):
    """A single search result with source reference and timestamp."""
    event_id: int
    video_id: Optional[int] = None
    camera_id: Optional[int] = None
    resource_type: str = "video"
    video_title: str
    camera_name: Optional[str] = None
    thumbnail: Optional[str] = None
    preview_url: Optional[str] = None
    timestamp_sec: float
    description: str
    event_type: str
    severity: str
    summary: Optional[str] = None
    relevance_score: float = 0.0


class SearchResponseOut(BaseModel):
    """Collection of search results."""
    query: str
    results: List[SearchResultOut]
    total: int


# -- Live Stream Schemas --

class LiveSessionCreate(BaseModel):
    """Request to start a new live stream session."""
    title: str = Field(..., min_length=1, max_length=200)


class LiveSessionOut(BaseModel):
    """Response for a live stream session."""
    id: int
    title: str
    start_time: str
    end_time: Optional[str] = None
    status: str
    video_id: Optional[int] = None
