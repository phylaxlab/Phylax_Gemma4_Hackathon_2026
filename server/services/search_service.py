"""
Search Service — Provides text-based and AI-powered search
across analysis events stored in the database.
"""

import logging
from pathlib import Path
from typing import List, Dict, Any, Optional

from config import FRAME_DIR
from database import get_db
from services.ai_service import rank_event_relevance

logger = logging.getLogger(__name__)


def _frame_path_to_url(frame_path: Optional[str]) -> Optional[str]:
    if not frame_path:
        return None

    raw = str(frame_path).strip()
    if raw.startswith("/frames/"):
        return raw

    try:
        path = Path(raw).resolve()
        frame_root = FRAME_DIR.resolve()
        if path == frame_root or frame_root in path.parents:
            return f"/frames/{path.relative_to(frame_root).as_posix()}"
    except (OSError, ValueError):
        return None

    return None


def _row_to_search_result(row) -> Dict[str, Any]:
    resource_type = "camera" if row["camera_id"] is not None else "video"
    resource_title = row["camera_name"] if resource_type == "camera" else row["video_title"]

    return {
        "event_id": row["event_id"],
        "video_id": row["video_id"],
        "camera_id": row["camera_id"],
        "resource_type": resource_type,
        "video_title": resource_title or "Untitled source",
        "camera_name": row["camera_name"],
        "thumbnail": row["thumbnail"],
        "preview_url": _frame_path_to_url(row["frame_path"]),
        "timestamp_sec": row["timestamp_sec"],
        "description": row["description"],
        "event_type": row["event_type"],
        "severity": row["severity"],
        "summary": row["summary"],
        "keywords": row["keywords"],
        "relevance_score": 0.0,
    }


async def text_search(query: str, limit: int = 50) -> List[Dict[str, Any]]:
    """
    Perform a keyword-based search on event descriptions.
    Splits the query into tokens and matches any token via SQL LIKE.

    Returns:
        List of matching events joined with video metadata.
    """
    db = await get_db()
    try:
        tokens = [t.strip() for t in query.split() if t.strip()]
        if not tokens:
            return []

        # Build WHERE clause: match any token in description, summary, diff, or keywords
        conditions = []
        params = []
        for token in tokens:
            conditions.append(
                "(e.description LIKE ? OR e.summary LIKE ? OR e.diff_description LIKE ? OR e.keywords LIKE ?)"
            )
            wildcard = f"%{token}%"
            params.extend([wildcard, wildcard, wildcard, wildcard])

        where_clause = " OR ".join(conditions)

        sql = f"""
            SELECT
                e.id as event_id,
                e.video_id,
                e.camera_id,
                v.title as video_title,
                c.name as camera_name,
                v.thumbnail,
                e.frame_path,
                e.timestamp_sec,
                e.description,
                e.event_type,
                e.severity,
                e.summary,
                e.keywords
            FROM analysis_events e
            LEFT JOIN videos v ON e.video_id = v.id
            LEFT JOIN cameras c ON e.camera_id = c.id
            WHERE {where_clause}
            ORDER BY e.timestamp_sec ASC
            LIMIT ?
        """
        params.append(limit)

        cursor = await db.execute(sql, params)
        rows = await cursor.fetchall()

        return [_row_to_search_result(row) for row in rows]
    finally:
        await db.close()


async def ai_search(query: str, limit: int = 20) -> List[Dict[str, Any]]:
    """
    Perform an AI-augmented search:
    1. First do a broad text search to get candidates.
    2. Use Gemma4 to re-rank results by semantic relevance.

    Returns:
        Results sorted by AI-assigned relevance score.
    """
    # Step 1: Get broad text search candidates
    candidates = await text_search(query, limit=limit * 3)

    if not candidates:
        # If no text matches found, try loading recent events and ranking them
        candidates = await _get_recent_events(limit=100)

    if not candidates:
        return []

    # Step 2: Batch descriptions for AI ranking (cap at 30 to stay within context)
    batch = candidates[:30]
    descriptions = [
        f"{c.get('summary', '')} - {c.get('description', '')}" for c in batch
    ]

    rankings = rank_event_relevance(query, descriptions)

    if rankings:
        # Apply AI scores to candidates
        for ranking in rankings:
            idx = ranking.get("index", -1)
            score = ranking.get("score", 0)
            if 0 <= idx < len(batch):
                batch[idx]["relevance_score"] = score

        # Sort by relevance score (descending) and filter out low scores
        batch.sort(key=lambda x: x.get("relevance_score", 0), reverse=True)
        return [r for r in batch if r.get("relevance_score", 0) > 2][:limit]
    else:
        # Fallback: return text search results without AI ranking
        logger.warning("AI ranking failed, returning text search results only")
        return candidates[:limit]


async def _get_recent_events(limit: int = 100) -> List[Dict[str, Any]]:
    """
    Fetch the most recent analysis events for AI ranking fallback.
    Used when text search returns no results.
    """
    db = await get_db()
    try:
        sql = """
            SELECT
                e.id as event_id,
                e.video_id,
                e.camera_id,
                v.title as video_title,
                c.name as camera_name,
                v.thumbnail,
                e.frame_path,
                e.timestamp_sec,
                e.description,
                e.event_type,
                e.severity,
                e.summary,
                e.keywords
            FROM analysis_events e
            LEFT JOIN videos v ON e.video_id = v.id
            LEFT JOIN cameras c ON e.camera_id = c.id
            ORDER BY e.created_at DESC
            LIMIT ?
        """
        cursor = await db.execute(sql, [limit])
        rows = await cursor.fetchall()

        return [_row_to_search_result(row) for row in rows]
    finally:
        await db.close()


async def get_search_suggestions(query: str, limit: int = 5) -> List[str]:
    """
    Generate real-time autocomplete suggestions for a partial search query.
    1. Fast prompt to Gemma4 to predict realistic query completions.
    2. Fallback to SQL prefix match on event summaries if AI fails.
    """
    if not query or len(query.strip()) < 2:
        return []

    from services.ai_service import ask_gemma, _parse_json_response

    prompt = f"""You are a search autocomplete engine for a video surveillance system.
The user has typed this partial query: "{query}"

Predict {limit} realistic and short search queries the user might be trying to type.
Respond ONLY with a valid JSON array of strings, and nothing else.

Example format:
["{query} red car", "{query} person walking", "{query} running fast"]
"""
    raw = ask_gemma(prompt=prompt, timeout=3.0, model=__import__("config").SEARCH_MODEL_NAME)  # low timeout to ensure UI stays responsive

    if raw:
        try:
            # We use an internal helper that strips markdown fences, then try to parse list
            if raw.strip().startswith("```"):
                lines = raw.strip().split("\n")
                lines = [l for l in lines if not l.strip().startswith("```")]
                raw = "\n".join(lines)
            
            import json
            suggestions = json.loads(raw)
            if isinstance(suggestions, list) and all(isinstance(s, str) for s in suggestions):
                # Return top N suggestions
                return [s.strip() for s in suggestions if s.strip()][:limit]
        except Exception as e:
            logger.warning(f"AI autocomplete failed to parse: {e}")

    # --- Fallback: Fast SQL prefix/substring match ---
    db = await get_db()
    try:
        sql = """
            SELECT DISTINCT summary 
            FROM analysis_events 
            WHERE summary LIKE ? 
            ORDER BY created_at DESC 
            LIMIT ?
        """
        cursor = await db.execute(sql, [f"%{query}%", limit])
        rows = await cursor.fetchall()
        return [row["summary"] for row in rows]
    except Exception as e:
        logger.error(f"Fallback suggestion failed: {str(e)}")
        return []
    finally:
        await db.close()
