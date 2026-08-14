from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from ..answering import answer_question
from ..auth import require_roles
from ..database import get_session
from ..models import Document, QaRequest, QaResponse, User, UserRole

router = APIRouter()


@router.post("/qa")
async def ask_document_question(
    request: QaRequest,
    user: Annotated[
        User, Depends(require_roles(UserRole.admin, UserRole.reviewer, UserRole.viewer))
    ],
    session: AsyncSession = Depends(get_session),
) -> QaResponse:
    question = request.question.strip()
    if not question:
        raise HTTPException(status_code=422, detail="empty_question")

    document_ids = _normalized_document_ids(request.document_ids)
    if document_ids is not None:
        result = await session.execute(
            select(Document.id).where(
                col(Document.id).in_(document_ids),
                col(Document.tenant_id) == user.tenant_id,
            )
        )
        existing_ids = set(result.scalars().all())
        if existing_ids != set(document_ids):
            raise HTTPException(status_code=404, detail="document_not_found")

    return await answer_question(
        session,
        question,
        tenant_id=user.tenant_id,
        document_ids=document_ids,
        retrieval_limit=request.retrieval_limit,
    )


def _normalized_document_ids(document_ids: list[str] | None) -> list[str] | None:
    if document_ids is None:
        return None
    normalized = list(dict.fromkeys(document_id.strip() for document_id in document_ids))
    if not normalized or any(not document_id for document_id in normalized):
        raise HTTPException(status_code=422, detail="invalid_document_scope")
    return normalized
