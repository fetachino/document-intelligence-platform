from collections.abc import Sequence
from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from .embeddings import EmbeddingProvider, LocalHashEmbeddingProvider
from .models import DocumentChunk, SemanticSearchResult


async def semantic_search(
    session: AsyncSession,
    query: str,
    limit: int,
    provider: EmbeddingProvider | None = None,
    document_ids: Sequence[str] | None = None,
) -> list[SemanticSearchResult]:
    """Rank compatible stored chunks by pgvector cosine distance."""

    active_provider = provider or LocalHashEmbeddingProvider()
    vectors = await active_provider.embed([query])
    if len(vectors) != 1 or len(vectors[0]) != active_provider.dimensions:
        raise ValueError("invalid_embedding_dimensions")

    embedding_column = cast(Any, DocumentChunk).embedding
    distance = embedding_column.cosine_distance(vectors[0])
    statement = (
        select(DocumentChunk, distance.label("distance"))
        .where(DocumentChunk.embedding_model == active_provider.model)
        .order_by(distance)
        .limit(limit)
    )
    if document_ids is not None:
        statement = statement.where(col(DocumentChunk.document_id).in_(document_ids))
    result = await session.execute(statement)
    return [
        SemanticSearchResult(
            document_id=chunk.document_id,
            page_number=chunk.page_number,
            chunk_index=chunk.chunk_index,
            text=chunk.text,
            embedding_model=chunk.embedding_model,
            distance=float(distance_value),
        )
        for chunk, distance_value in result.all()
    ]
