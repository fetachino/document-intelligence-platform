from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_roles
from ..database import get_session
from ..models import Document, SemanticSearchResponse, User, UserRole
from sqlmodel import col, select
from ..search import semantic_search

router = APIRouter()


@router.get("/search")
async def search_documents(
    user: Annotated[
        User, Depends(require_roles(UserRole.admin, UserRole.reviewer, UserRole.viewer))
    ],
    q: str = Query(min_length=1, max_length=500),
    limit: int = Query(default=10, ge=1, le=50),
    document_id: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> SemanticSearchResponse:
    query = q.strip()
    if not query:
        raise HTTPException(status_code=422, detail="empty_search_query")
    document_ids = [document_id] if document_id is not None else None
    if document_id is not None:
        scoped = await session.execute(
            select(Document.id).where(
                Document.id == document_id,
                col(Document.tenant_id) == user.tenant_id,
            )
        )
        if scoped.scalar_one_or_none() is None:
            raise HTTPException(status_code=404, detail="document_not_found")
    results = await semantic_search(
        session, query, limit, user.tenant_id, document_ids=document_ids
    )
    return SemanticSearchResponse(query=query, results=results)
