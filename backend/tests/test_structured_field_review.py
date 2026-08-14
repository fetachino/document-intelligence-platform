import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.database import get_sessionmaker, init_db
from backend.app.models import Document, ExtractionMethod
from backend.app.ocr import ExtractedPage
from backend.app.processing import process_document


class StaticPageExtractor:
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


def _processed_document(tmp_path: Path, monkeypatch, text: str) -> tuple[TestClient, str]:
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    asyncio.run(init_db())
    source_path = tmp_path / "document.pdf"
    source_path.write_bytes(b"test document")
    document_id = asyncio.run(_create_document(source_path))
    asyncio.run(process_document(document_id, StaticPageExtractor(text)))

    from backend.app.main import app

    return TestClient(app), document_id


def _field(response: dict, field_name: str, value_index: int = 0) -> dict:
    return next(
        field
        for field in response["fields"]
        if field["field_name"] == field_name and field["value_index"] == value_index
    )


@pytest.mark.parametrize(
    ("text", "field_name", "automatic_value", "corrected_value"),
    [
        (
            "Invoice Number: INV-1\nInvoice Date: 2026-08-14\n"
            "Vendor: Acme Corp\nAmount Due: $10.00",
            "total_amount",
            "$10.00",
            "$12.00",
        ),
        (
            "Jane Doe\njane@example.com\nPhone: (317) 555-0100\n"
            "Professional Experience\nEducation\nSkills",
            "email",
            "jane@example.com",
            "jane.doe@example.com",
        ),
        (
            "This agreement has an effective date and governing law.\n"
            "Party A: Acme Corp\nParty B: Beta LLC\nEffective Date: 2026-08-14",
            "party",
            "Acme Corp",
            "Acme Corporation",
        ),
    ],
)
def test_corrects_supported_document_fields(
    tmp_path, monkeypatch, text, field_name, automatic_value, corrected_value
):
    client, document_id = _processed_document(tmp_path, monkeypatch, text)
    response = client.patch(
        f"/api/v1/documents/{document_id}/extraction/fields/{field_name}/0",
        json={"value": corrected_value, "reviewer_id": "local-reviewer"},
    )

    assert response.status_code == 200
    assert response.json()["value"] == automatic_value
    assert response.json()["effective_value"] == corrected_value
    assert response.json()["reviewed"] is True
    assert response.json()["reviewer_id"] == "local-reviewer"

    extraction = client.get(f"/api/v1/documents/{document_id}/extraction").json()
    reviewed_field = _field(extraction, field_name)
    assert reviewed_field["value"] == automatic_value
    assert reviewed_field["effective_value"] == corrected_value


def test_history_is_append_only_ordered_and_duplicate_corrections_are_idempotent(
    tmp_path, monkeypatch
):
    client, document_id = _processed_document(
        tmp_path,
        monkeypatch,
        "Invoice Number: INV-1\nVendor: Acme Corp\nAmount Due: $10.00",
    )
    url = f"/api/v1/documents/{document_id}/extraction/fields/total_amount/0"
    first = client.patch(
        url, json={"value": "$12.00", "reviewer_id": "reviewer-a"}
    )
    duplicate = client.patch(
        url, json={"value": "$12.00", "reviewer_id": "reviewer-a"}
    )
    second = client.patch(
        url, json={"value": "$14.00", "reviewer_id": "reviewer-b"}
    )

    assert first.status_code == duplicate.status_code == second.status_code == 200
    history = client.get(
        f"/api/v1/documents/{document_id}/extraction/reviews"
    ).json()["corrections"]
    assert len(history) == 2
    assert [item["corrected_value"] for item in history] == ["$12.00", "$14.00"]
    assert history[0]["automatic_value"] == "$10.00"
    assert history[0]["previous_effective_value"] == "$10.00"
    assert history[0]["status"] == "superseded"
    assert history[1]["previous_effective_value"] == "$12.00"
    assert history[1]["status"] == "active"
    assert history[1]["effective_value"] == "$14.00"


def test_invalid_and_missing_field_corrections_are_rejected(tmp_path, monkeypatch):
    client, document_id = _processed_document(
        tmp_path,
        monkeypatch,
        "Invoice Number: INV-1\nVendor: Acme Corp\nAmount Due: $10.00",
    )
    base = f"/api/v1/documents/{document_id}/extraction/fields"

    unsupported = client.patch(
        f"{base}/email/0",
        json={"value": "valid@example.com", "reviewer_id": "reviewer"},
    )
    missing = client.patch(
        f"{base}/invoice_date/0",
        json={"value": "2026-08-14", "reviewer_id": "reviewer"},
    )
    invalid = client.patch(
        f"{base}/total_amount/0",
        json={"value": "approximately ten", "reviewer_id": "reviewer"},
    )
    missing_document = client.patch(
        "/api/v1/documents/missing/extraction/fields/total_amount/0",
        json={"value": "$10.00", "reviewer_id": "reviewer"},
    )

    assert unsupported.status_code == 422
    assert unsupported.json()["detail"] == "unsupported_field_name"
    assert missing.status_code == 404
    assert missing.json()["detail"] == "structured_field_not_found"
    assert invalid.status_code == 422
    assert invalid.json()["detail"] == "invalid_field_value"
    assert missing_document.status_code == 404
    assert missing_document.json()["detail"] == "document_not_found"


def test_reprocessing_updates_automatic_value_and_preserves_correction(
    tmp_path, monkeypatch
):
    client, document_id = _processed_document(
        tmp_path,
        monkeypatch,
        "Invoice Number: INV-1\nVendor: Acme Corp\nAmount Due: $10.00",
    )
    client.patch(
        f"/api/v1/documents/{document_id}/extraction/fields/total_amount/0",
        json={"value": "$12.00", "reviewer_id": "reviewer"},
    )

    asyncio.run(
        process_document(
            document_id,
            StaticPageExtractor(
                "Invoice Number: INV-1\nVendor: Acme Corp\nAmount Due: $20.00"
            ),
        )
    )
    extraction = client.get(f"/api/v1/documents/{document_id}/extraction").json()
    total = _field(extraction, "total_amount")
    assert total["value"] == "$20.00"
    assert total["effective_value"] == "$12.00"

    history = client.get(
        f"/api/v1/documents/{document_id}/extraction/reviews"
    ).json()["corrections"]
    assert history[0]["automatic_value"] == "$10.00"
    assert history[0]["status"] == "active"


def test_missing_automatic_field_makes_latest_correction_orphaned(
    tmp_path, monkeypatch
):
    client, document_id = _processed_document(
        tmp_path,
        monkeypatch,
        "Invoice Number: INV-1\nVendor: Acme Corp\nAmount Due: $10.00",
    )
    client.patch(
        f"/api/v1/documents/{document_id}/extraction/fields/invoice_number/0",
        json={"value": "INV-CORRECTED", "reviewer_id": "reviewer"},
    )

    asyncio.run(
        process_document(
            document_id,
            StaticPageExtractor("Invoice\nVendor: Acme Corp\nAmount Due: $20.00"),
        )
    )
    extraction = client.get(f"/api/v1/documents/{document_id}/extraction").json()
    assert "invoice_number" not in {
        field["field_name"] for field in extraction["fields"]
    }

    history = client.get(
        f"/api/v1/documents/{document_id}/extraction/reviews"
    ).json()["corrections"]
    assert history[0]["status"] == "orphaned"
    assert history[0]["effective_value"] is None
