from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from ..models import SemanticSearchResponse
from ..search import semantic_search

router = APIRouter()


@router.get("/search")
async def search_documents(
    q: str = Query(min_length=1, max_length=500),
    limit: int = Query(default=10, ge=1, le=50),
    document_id: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> SemanticSearchResponse:
    query = q.strip()
    if not query:
        raise HTTPException(status_code=422, detail="empty_search_query")
    document_ids = [document_id] if document_id is not None else None
    results = await semantic_search(session, query, limit, document_ids=document_ids)
    return SemanticSearchResponse(query=query, results=results)
