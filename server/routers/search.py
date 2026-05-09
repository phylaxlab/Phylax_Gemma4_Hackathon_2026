"""
Search Router — Text-based and AI-powered event search endpoints.
"""

import logging
from fastapi import APIRouter, Query, HTTPException

from services.search_service import text_search, ai_search, get_search_suggestions
from models.schemas import SearchQuery, SearchResultOut, SearchResponseOut

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/search", tags=["search"])


@router.get("/suggestions")
async def search_suggestions(q: str = Query(..., min_length=1, max_length=100)):
    """
    Get autocomplete suggestions for a given substring.
    Powered by AI with a database fallback for low latency.
    """
    try:
        suggestions = await get_search_suggestions(q)
        return {"suggestions": suggestions}
    except Exception as e:
        logger.error(f"Error fetching suggestions: {e}")
        return {"suggestions": []}


@router.get("", response_model=SearchResponseOut)
async def search_events(q: str = Query(..., min_length=1, max_length=500)):
    """
    Keyword-based search across all analysis event descriptions.
    Fast but less intelligent than AI search.
    """
    results = await text_search(q)

    return SearchResponseOut(
        query=q,
        results=[SearchResultOut(**r) for r in results],
        total=len(results),
    )


@router.post("/ask", response_model=SearchResponseOut)
async def ai_search_events(body: SearchQuery):
    """
    AI-powered natural language search.
    Uses Gemma4 to re-rank results by semantic relevance.
    Slower but understands context and intent better.
    """
    results = await ai_search(body.query)

    return SearchResponseOut(
        query=body.query,
        results=[SearchResultOut(**r) for r in results],
        total=len(results),
    )
