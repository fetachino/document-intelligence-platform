import asyncio
import os
from pathlib import Path

import pytest
from httpx import AsyncClient
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlmodel import col, select

from backend.app.database import get_engine, get_sessionmaker
from backend.app.embeddings import (
    EmbeddingSourcePage,
    LocalHashEmbeddingProvider,
    PageTextChunker,
)
from backend.app.models import Document, DocumentChunk, ExtractionMethod
from backend.app.ocr import ExtractedPage
from backend.app.processing import process_document


class StaticPageExtractor:
    def __init__(self, pages: list[ExtractedPage]) -> None:
        self.pages = pages

    async def extract(self, path: Path) -> list[ExtractedPage]:
        return self.pages


def test_chunk_generation_and_multiple_page_provenance():
    chunks = PageTextChunker(max_words=4, overlap_words=1).chunk(
        [
            EmbeddingSourcePage(1, "one two three four five six"),
            EmbeddingSourcePage(2, "seven eight"),
        ]
    )

    assert [(chunk.page_number, chunk.chunk_index, chunk.text) for chunk in chunks] == [
        (1, 0, "one two three four"),
        (1, 1, "four five six"),
        (2, 0, "seven eight"),
    ]


def test_empty_text_is_not_chunked_or_embedded():
    chunks = PageTextChunker().chunk(
        [EmbeddingSourcePage(1, "  \n\t "), EmbeddingSourcePage(2, "useful text")]
    )
    vectors = asyncio.run(
        LocalHashEmbeddingProvider().embed([chunk.text for chunk in chunks])
    )

    assert [(chunk.page_number, chunk.text) for chunk in chunks] == [
        (2, "useful text")
    ]
    assert len(vectors) == 1
    assert len(vectors[0]) == 128


def _postgres_url() -> str:
    url = os.getenv("DATABASE_URL", "")
    if not url.startswith("postgresql+asyncpg://"):
        pytest.skip("PostgreSQL integration database is not configured")
    return url


async def _create_document(path: Path) -> str:
    session = get_sessionmaker()()
    try:
        document = Document(
            filename=path.name,
            content_type="application/pdf",
            size=path.stat().st_size,
            storage_path=str(path),
        )
        session.add(document)
        await session.commit()
        await session.refresh(document)
        assert document.id is not None
        return document.id
    finally:
        await session.close()


async def _load_chunks(document_id: str) -> list[DocumentChunk]:
    session = get_sessionmaker()()
    try:
        result = await session.execute(
            select(DocumentChunk)
            .where(DocumentChunk.document_id == document_id)
            .order_by(
                col(DocumentChunk.page_number), col(DocumentChunk.chunk_index)
            )
        )
        return list(result.scalars().all())
    finally:
        await session.close()


async def _delete_documents(document_ids: list[str]) -> None:
    session = get_sessionmaker()()
    try:
        await session.execute(delete(Document).where(col(Document.id).in_(document_ids)))
        await session.commit()
    finally:
        await session.close()


async def _new_document(tmp_path: Path, name: str) -> str:
    path = tmp_path / name
    path.write_bytes(b"test document")
    return await _create_document(path)


def test_postgres_embedding_persistence_idempotency_and_stale_replacement(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("DATABASE_URL", _postgres_url())

    async def scenario() -> None:
        document_id = await _new_document(tmp_path, "indexed.pdf")
        first_pages = [
            ExtractedPage(
                1, "alpha beta gamma delta epsilon", ExtractionMethod.native
            ),
            ExtractedPage(2, "second page provenance", ExtractionMethod.native),
        ]
        chunker = PageTextChunker(max_words=4, overlap_words=1)
        try:
            await process_document(
                document_id, StaticPageExtractor(first_pages), chunker=chunker
            )
            first = await _load_chunks(document_id)
            assert [(chunk.page_number, chunk.chunk_index) for chunk in first] == [
                (1, 0),
                (1, 1),
                (2, 0),
            ]
            assert all(chunk.embedding_model == "local_hash_v1" for chunk in first)
            assert all(len(chunk.embedding) == 128 for chunk in first)

            await process_document(
                document_id, StaticPageExtractor(first_pages), chunker=chunker
            )
            assert len(await _load_chunks(document_id)) == 3

            replacement = [
                ExtractedPage(1, "replacement content only", ExtractionMethod.native)
            ]
            await process_document(
                document_id, StaticPageExtractor(replacement), chunker=chunker
            )
            replaced = await _load_chunks(document_id)
            assert [
                (chunk.page_number, chunk.chunk_index, chunk.text)
                for chunk in replaced
            ] == [(1, 0, "replacement content only")]

            await process_document(
                document_id,
                StaticPageExtractor(
                    [ExtractedPage(1, "  \n\t ", ExtractionMethod.native)]
                ),
                chunker=chunker,
            )
            assert await _load_chunks(document_id) == []
        finally:
            await _delete_documents([document_id])
            await get_engine().dispose()

    asyncio.run(scenario())


def test_postgres_search_api_relevance_and_document_isolation(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", _postgres_url())
    async def scenario() -> None:
        apple_id = await _new_document(tmp_path, "orchard.pdf")
        ocean_id = await _new_document(tmp_path, "ocean.pdf")
        try:
            await process_document(
                apple_id,
                StaticPageExtractor(
                    [
                        ExtractedPage(
                            1,
                            "quasarfruitalpha apple orchard harvest",
                            ExtractionMethod.native,
                        )
                    ]
                ),
            )
            await process_document(
                ocean_id,
                StaticPageExtractor(
                    [
                        ExtractedPage(
                            1,
                            "pelagictopicbeta ocean current navigation",
                            ExtractionMethod.native,
                        )
                    ]
                ),
            )

            from backend.app.main import app

            async with AsyncClient(app=app, base_url="http://test") as client:
                response = await client.get(
                    "/api/v1/search",
                    params={"q": "quasarfruitalpha", "limit": 2},
                )
            assert response.status_code == 200
            results = response.json()["results"]
            assert results[0]["document_id"] == apple_id
            assert results[0]["page_number"] == 1
            assert results[0]["chunk_index"] == 0
            assert results[0]["embedding_model"] == "local_hash_v1"
            assert results[0]["distance"] <= results[1]["distance"]
            assert {result["document_id"] for result in results} == {
                apple_id,
                ocean_id,
            }

            async with AsyncClient(app=app, base_url="http://test") as client:
                scoped_response = await client.get(
                    "/api/v1/search",
                    params={
                        "q": "quasarfruitalpha",
                        "limit": 2,
                        "document_id": ocean_id,
                    },
                )
            assert scoped_response.status_code == 200
            scoped_results = scoped_response.json()["results"]
            assert [result["document_id"] for result in scoped_results] == [ocean_id]
        finally:
            await _delete_documents([apple_id, ocean_id])
            await get_engine().dispose()

    asyncio.run(scenario())


def test_search_query_validation(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", _postgres_url())

    from backend.app.main import app

    client = TestClient(app)
    assert client.get("/api/v1/search", params={"q": "   "}).status_code == 422
    assert (
        client.get("/api/v1/search", params={"q": "valid", "limit": 0}).status_code
        == 422
    )
    assert client.get("/api/v1/search").status_code == 422
