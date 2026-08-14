import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from backend.app.classification import LocalKeywordClassifier
from backend.app.database import get_sessionmaker, init_db
from backend.app.models import (
    ClassificationSource,
    Document,
    DocumentClassificationReview,
    DocumentType,
    ExtractionMethod,
)
from backend.app.ocr import ExtractedPage
from backend.app.processing import process_document


class StaticExtractor:
    def __init__(self, text: str) -> None:
        self.text = text

    async def extract(self, path: Path) -> list[ExtractedPage]:
        return [ExtractedPage(1, self.text, ExtractionMethod.native)]


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


async def _load_reviews(document_id: str) -> list[DocumentClassificationReview]:
    session = get_sessionmaker()()
    try:
        result = await session.execute(
            select(DocumentClassificationReview).where(
                DocumentClassificationReview.document_id == document_id
            )
        )
        return list(result.scalars().all())
    finally:
        await session.close()


@pytest.mark.parametrize(
    ("text", "expected_type"),
    [
        ("Invoice number 42\nBill to Example Co\nAmount due $10", DocumentType.invoice),
        ("Professional experience\nEducation\nSkills", DocumentType.resume),
        ("This agreement has an effective date and governing law", DocumentType.contract),
        ("Meeting notes and project update", DocumentType.other),
        ("   ", DocumentType.unknown),
    ],
)
def test_local_classifier_types(text, expected_type):
    result = asyncio.run(LocalKeywordClassifier().classify([text]))

    assert result.document_type == expected_type
    assert result.classifier_version == "local_keyword_v1"


def test_classification_review_and_reprocessing(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    asyncio.run(init_db())
    source_path = tmp_path / "document.pdf"
    source_path.write_bytes(b"test document")
    document_id = asyncio.run(_create_document(source_path))

    asyncio.run(
        process_document(
            document_id,
            StaticExtractor("Invoice number 42\nBill to Example Co\nAmount due $10"),
        )
    )

    from backend.app.main import app

    client = TestClient(app)
    classification_url = f"/api/v1/documents/{document_id}/classification"
    response = client.get(classification_url)
    assert response.status_code == 200
    assert response.json()["predicted_type"] == "invoice"
    assert response.json()["effective_type"] == "invoice"
    assert response.json()["source"] == "classifier"

    correction = client.patch(
        classification_url, json={"document_type": "contract"}
    )
    assert correction.status_code == 200
    assert correction.json()["predicted_type"] == "invoice"
    assert correction.json()["effective_type"] == "contract"
    assert correction.json()["source"] == "human"

    duplicate_correction = client.patch(
        classification_url, json={"document_type": "contract"}
    )
    assert duplicate_correction.status_code == 200

    invalid_correction = client.patch(
        classification_url, json={"document_type": "memo"}
    )
    assert invalid_correction.status_code == 422

    asyncio.run(
        process_document(
            document_id,
            StaticExtractor("Professional experience\nEducation\nSkills"),
        )
    )
    reprocessed = client.get(classification_url)
    assert reprocessed.status_code == 200
    assert reprocessed.json()["predicted_type"] == "resume"
    assert reprocessed.json()["effective_type"] == "contract"
    assert reprocessed.json()["source"] == "human"

    reviews = asyncio.run(_load_reviews(document_id))
    assert len(reviews) == 1
    assert reviews[0].previous_type == DocumentType.invoice
    assert reviews[0].corrected_type == DocumentType.contract
    assert reviews[0].document_id == document_id
    assert ClassificationSource(reprocessed.json()["source"]) == ClassificationSource.human
