import asyncio
import os
from collections.abc import Sequence
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import delete
from sqlmodel import col

from backend.app.answering import (
    INSUFFICIENT_EVIDENCE_ANSWER,
    LocalExtractiveAnswerGenerator,
    answer_question,
)
from backend.app.database import get_engine, get_sessionmaker
from backend.app.models import (
    LEGACY_TENANT_ID,
    Document,
    ExtractionMethod,
    QaAnswerStatus,
    QaResponse,
    Tenant,
)
from backend.app.ocr import ExtractedPage
from backend.app.processing import process_document
from backend.app.qa_evaluation import (
    evaluate_qa_dataset,
    load_qa_evaluation_dataset,
)


class StaticPageExtractor:
    def __init__(self, pages: list[ExtractedPage]) -> None:
        self.pages = pages

    async def extract(self, path: Path) -> list[ExtractedPage]:
        return self.pages


def test_local_generator_is_grounded_and_repeatable():
    generator = LocalExtractiveAnswerGenerator()
    contexts = [
        "Project Atlas deadline is September 30, 2026. Project Atlas owner is Dana Lee."
    ]

    first = asyncio.run(generator.generate("What is the Project Atlas deadline?", contexts))
    second = asyncio.run(
        generator.generate("What is the Project Atlas deadline?", contexts)
    )

    assert first == second
    assert first.status == QaAnswerStatus.answered
    assert first.answer == "Project Atlas deadline is September 30, 2026."
    assert first.evidence_indices == (0,)


def test_local_generator_uses_multiple_contexts_when_needed():
    result = asyncio.run(
        LocalExtractiveAnswerGenerator().generate(
            "What are the Alpha and Beta delivery dates?",
            [
                "Alpha delivery date is September 10, 2026.",
                "Beta delivery date is September 20, 2026.",
            ],
        )
    )

    assert result.status == QaAnswerStatus.answered
    assert result.evidence_indices == (0, 1)
    assert "September 10, 2026" in result.answer
    assert "September 20, 2026" in result.answer


def test_local_generator_refuses_incomplete_evidence():
    result = asyncio.run(
        LocalExtractiveAnswerGenerator().generate(
            "What is the Project Atlas budget?",
            ["Project Atlas deadline is September 30, 2026."],
        )
    )

    assert result.status == QaAnswerStatus.insufficient_evidence
    assert result.answer == INSUFFICIENT_EVIDENCE_ANSWER
    assert result.evidence_indices == ()


def _postgres_url() -> str:
    url = os.getenv("DATABASE_URL", "")
    if not url.startswith("postgresql+asyncpg://"):
        pytest.skip("PostgreSQL integration database is not configured")
    return url


async def _create_document(tmp_path: Path, name: str, pages: list[str]) -> str:
    path = tmp_path / name
    path.write_bytes(b"test document")
    session = get_sessionmaker()()
    try:
        document = Document(
            filename=name,
            content_type="application/pdf",
            size=path.stat().st_size,
            storage_path=str(path),
        )
        session.add(document)
        await session.commit()
        await session.refresh(document)
        assert document.id is not None
        document_id = document.id
    finally:
        await session.close()

    await process_document(
        document_id,
        StaticPageExtractor(
            [
                ExtractedPage(index, text, ExtractionMethod.native)
                for index, text in enumerate(pages, start=1)
            ]
        ),
    )
    return document_id


async def _delete_documents(document_ids: list[str]) -> None:
    session = get_sessionmaker()()
    try:
        await session.execute(delete(Document).where(col(Document.id).in_(document_ids)))
        await session.commit()
    finally:
        await session.close()


def test_postgres_qa_api_grounding_scope_and_validation(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", _postgres_url())

    async def scenario() -> None:
        atlas_id = await _create_document(
            tmp_path,
            "atlas.pdf",
            [
                "Project Atlas deadline is September 30, 2026. "
                "Alpha delivery date is September 10, 2026.",
                "Beta delivery date is September 20, 2026. "
                "Project Atlas owner is Dana Lee.",
            ],
        )
        ocean_id = await _create_document(
            tmp_path,
            "ocean.pdf",
            ["Project Ocean deadline is December 15, 2026. Project Ocean owner is Morgan Reed."],
        )
        try:
            from backend.app.main import app

            async with AsyncClient(app=app, base_url="http://test") as client:
                payload = {
                    "question": "What is the Project Atlas deadline?",
                    "document_ids": [atlas_id],
                }
                first = await client.post("/api/v1/qa", json=payload)
                repeated = await client.post("/api/v1/qa", json=payload)
                multiple = await client.post(
                    "/api/v1/qa",
                    json={
                        "question": "What are the Alpha and Beta delivery dates?",
                        "document_ids": [atlas_id],
                    },
                )
                insufficient = await client.post(
                    "/api/v1/qa",
                    json={
                        "question": "What is the Project Atlas budget?",
                        "document_ids": [atlas_id],
                    },
                )
                isolated = await client.post(
                    "/api/v1/qa",
                    json={
                        "question": "What is the Project Atlas deadline?",
                        "document_ids": [ocean_id],
                    },
                )
                whitespace = await client.post(
                    "/api/v1/qa", json={"question": "   "}
                )
                empty = await client.post("/api/v1/qa", json={"question": ""})
                empty_scope = await client.post(
                    "/api/v1/qa",
                    json={"question": "Valid question", "document_ids": []},
                )
                missing_scope = await client.post(
                    "/api/v1/qa",
                    json={"question": "Valid question", "document_ids": ["missing"]},
                )

            assert first.status_code == repeated.status_code == 200
            assert first.json() == repeated.json()
            response = first.json()
            assert response["status"] == "answered"
            assert response["answer_provider"] == "local_extractive_v1"
            assert response["retrieval"]["embedding_model"] == "local_hash_v1"
            assert len(response["citations"]) == 1
            citation = response["citations"][0]
            assert (citation["document_id"], citation["page_number"], citation["chunk_index"]) == (
                atlas_id,
                1,
                0,
            )
            retrieved = response["retrieval"]["results"][0]
            assert citation["source_snippet"] == retrieved["text"]
            assert citation["distance"] == retrieved["distance"]

            assert multiple.status_code == 200
            assert {
                (item["document_id"], item["page_number"], item["chunk_index"])
                for item in multiple.json()["citations"]
            } == {(atlas_id, 1, 0), (atlas_id, 2, 0)}
            assert insufficient.json()["status"] == "insufficient_evidence"
            assert insufficient.json()["citations"] == []
            assert isolated.json()["status"] == "insufficient_evidence"
            assert isolated.json()["citations"] == []
            assert whitespace.status_code == 422
            assert empty.status_code == 422
            assert empty_scope.status_code == 422
            assert missing_scope.status_code == 404
        finally:
            await _delete_documents([atlas_id, ocean_id])
            await get_engine().dispose()

    asyncio.run(scenario())


def test_postgres_search_and_qa_exclude_foreign_tenant_content(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", _postgres_url())

    async def scenario() -> None:
        local_id = await _create_document(
            tmp_path,
            "tenant-local.pdf",
            ["Tenant Alpha launch date is October 2, 2026."],
        )
        foreign_path = tmp_path / "tenant-foreign.pdf"
        foreign_path.write_bytes(b"test document")
        foreign_tenant = Tenant(name="Foreign tenant", slug=f"foreign-{local_id}")
        async with get_sessionmaker()() as session:
            session.add(foreign_tenant)
            await session.flush()
            foreign_document = Document(
                tenant_id=foreign_tenant.id,
                filename=foreign_path.name,
                content_type="application/pdf",
                size=foreign_path.stat().st_size,
                storage_path=str(foreign_path),
            )
            session.add(foreign_document)
            await session.commit()
            assert foreign_document.id is not None
            foreign_id = foreign_document.id
        await process_document(
            foreign_id,
            StaticPageExtractor(
                [ExtractedPage(1, "Tenant Beta secret code is ORANGE-77.", ExtractionMethod.native)]
            ),
        )

        try:
            from backend.app.main import app

            async with AsyncClient(app=app, base_url="http://test") as client:
                search = await client.get("/api/v1/search", params={"q": "tenant launch secret"})
                qa = await client.post(
                    "/api/v1/qa", json={"question": "What is the Tenant Alpha launch date?"}
                )
            assert search.status_code == 200
            assert {item["document_id"] for item in search.json()["results"]} == {local_id}
            assert qa.status_code == 200
            assert qa.json()["status"] == "answered"
            assert {item["document_id"] for item in qa.json()["citations"]} == {local_id}
            assert all(
                item["document_id"] == local_id
                for item in qa.json()["retrieval"]["results"]
            )
        finally:
            await _delete_documents([local_id, foreign_id])
            async with get_sessionmaker()() as session:
                await session.delete(foreign_tenant)
                await session.commit()
            await get_engine().dispose()

    asyncio.run(scenario())


def test_postgres_qa_evaluation_dataset_execution(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", _postgres_url())

    async def scenario() -> None:
        dataset = load_qa_evaluation_dataset()
        document_ids = {}
        try:
            for document in dataset.documents:
                document_ids[document.key] = await _create_document(
                    tmp_path,
                    f"evaluation-{document.key}.pdf",
                    list(document.pages),
                )

            session = get_sessionmaker()()
            try:
                async def run_case(
                    question: str,
                    document_ids: Sequence[str] | None,
                    retrieval_limit: int,
                ) -> QaResponse:
                    return await answer_question(
                        session,
                        question,
                        LEGACY_TENANT_ID,
                        document_ids=document_ids,
                        retrieval_limit=retrieval_limit,
                    )

                metrics = await evaluate_qa_dataset(dataset, document_ids, run_case)
            finally:
                await session.close()

            assert metrics.case_count == 5
            assert metrics.status_accuracy == 1.0
            assert metrics.answer_content_accuracy == 1.0
            assert metrics.citation_accuracy == 1.0
            assert metrics.citation_grounding_accuracy == 1.0
            assert metrics.retrieval_relevance_accuracy == 1.0
        finally:
            await _delete_documents(list(document_ids.values()))
            await get_engine().dispose()

    asyncio.run(scenario())
