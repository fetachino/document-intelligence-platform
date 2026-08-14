import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.database import get_sessionmaker, init_db
from backend.app.models import Document, DocumentType, ExtractionMethod
from backend.app.ocr import ExtractedPage
from backend.app.processing import process_document
from backend.app.structured_extraction import (
    LocalStructuredExtractor,
    StructuredTextPage,
)


class StaticPageExtractor:
    def __init__(self, pages: list[ExtractedPage]) -> None:
        self.pages = pages

    async def extract(self, path: Path) -> list[ExtractedPage]:
        return self.pages


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


def _field_values(result) -> dict[tuple[str, int], tuple[str, int]]:
    return {
        (field.field_name, field.value_index): (field.value, field.page_number)
        for field in result.fields
    }


def test_invoice_extraction_with_page_provenance():
    pages = [
        StructuredTextPage(
            1,
            "Invoice Number: INV-42\nInvoice Date: 2026-08-14\nVendor: Acme Corp",
        ),
        StructuredTextPage(2, "Amount Due: $1,234.56"),
    ]

    result = asyncio.run(LocalStructuredExtractor().extract(DocumentType.invoice, pages))

    assert _field_values(result) == {
        ("invoice_number", 0): ("INV-42", 1),
        ("invoice_date", 0): ("2026-08-14", 1),
        ("vendor", 0): ("Acme Corp", 1),
        ("total_amount", 0): ("$1,234.56", 2),
    }
    assert result.extractor_version == "local_regex_v1"
    assert result.extraction_method == "deterministic_regex"


def test_resume_extraction():
    pages = [
        StructuredTextPage(1, "Jane Doe\njane@example.com"),
        StructuredTextPage(2, "Phone: (317) 555-0100"),
    ]

    result = asyncio.run(LocalStructuredExtractor().extract(DocumentType.resume, pages))

    assert _field_values(result) == {
        ("name", 0): ("Jane Doe", 1),
        ("email", 0): ("jane@example.com", 1),
        ("phone", 0): ("(317) 555-0100", 2),
    }


def test_contract_extraction():
    pages = [
        StructuredTextPage(1, "Party A: Acme Corp\nParty B: Beta LLC"),
        StructuredTextPage(
            2,
            "Effective Date: August 14, 2026\nTermination Date: 2027-08-14",
        ),
    ]

    result = asyncio.run(LocalStructuredExtractor().extract(DocumentType.contract, pages))

    assert _field_values(result) == {
        ("party", 0): ("Acme Corp", 1),
        ("party", 1): ("Beta LLC", 1),
        ("effective_date", 0): ("August 14, 2026", 2),
        ("termination_date", 0): ("2027-08-14", 2),
    }


@pytest.mark.parametrize("document_type", [DocumentType.other, DocumentType.unknown])
def test_other_and_unknown_have_no_fields(document_type):
    result = asyncio.run(
        LocalStructuredExtractor().extract(
            document_type, [StructuredTextPage(1, "Invoice Number: should-not-extract")]
        )
    )

    assert result.fields == []


def test_malformed_or_missing_invoice_fields_are_omitted():
    result = asyncio.run(
        LocalStructuredExtractor().extract(
            DocumentType.invoice,
            [
                StructuredTextPage(
                    1,
                    "Invoice Number:\nInvoice Date: someday\nVendor: Valid Vendor\nTotal: TBD",
                )
            ],
        )
    )

    assert _field_values(result) == {("vendor", 0): ("Valid Vendor", 1)}


def test_persistence_retrieval_and_idempotent_reprocessing(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    asyncio.run(init_db())
    source_path = tmp_path / "invoice.pdf"
    source_path.write_bytes(b"test document")
    document_id = asyncio.run(_create_document(source_path))
    first_pages = [
        ExtractedPage(
            1,
            "Invoice Number: OLD-1\nInvoice Date: 2026-01-01\nVendor: Old Co",
            ExtractionMethod.native,
        ),
        ExtractedPage(2, "Amount Due: $10.00", ExtractionMethod.native),
    ]
    asyncio.run(process_document(document_id, StaticPageExtractor(first_pages)))

    from backend.app.main import app

    client = TestClient(app)
    extraction_url = f"/api/v1/documents/{document_id}/extraction"
    first_response = client.get(extraction_url)
    assert first_response.status_code == 200
    assert first_response.json()["status"] == "completed"
    assert first_response.json()["document_type"] == "invoice"
    total = next(
        field
        for field in first_response.json()["fields"]
        if field["field_name"] == "total_amount"
    )
    assert total["page_number"] == 2
    assert total["extraction_method"] == "deterministic_regex"
    assert total["extractor_version"] == "local_regex_v1"

    replacement_pages = [
        ExtractedPage(
            1,
            "Invoice\nVendor: New Co\nAmount Due: $20.00",
            ExtractionMethod.native,
        )
    ]
    asyncio.run(process_document(document_id, StaticPageExtractor(replacement_pages)))
    second_response = client.get(extraction_url)
    values = {
        field["field_name"]: field["value"]
        for field in second_response.json()["fields"]
    }
    assert values == {"total_amount": "$20.00", "vendor": "New Co"}


def test_manual_classification_correction_replaces_schema(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    asyncio.run(init_db())
    source_path = tmp_path / "mixed.pdf"
    source_path.write_bytes(b"test document")
    document_id = asyncio.run(_create_document(source_path))
    text = (
        "Jane Doe\njane@example.com\nProfessional Experience\nEducation\nSkills\n"
        "Party A: Acme Corp\nParty B: Beta LLC\nEffective Date: 2026-08-14"
    )
    asyncio.run(
        process_document(
            document_id,
            StaticPageExtractor([ExtractedPage(1, text, ExtractionMethod.native)]),
        )
    )

    from backend.app.main import app

    client = TestClient(app)
    extraction_url = f"/api/v1/documents/{document_id}/extraction"
    initial = client.get(extraction_url).json()
    assert initial["document_type"] == "resume"
    assert {field["field_name"] for field in initial["fields"]} >= {"name", "email"}

    correction = client.patch(
        f"/api/v1/documents/{document_id}/classification",
        json={"document_type": "contract"},
    )
    assert correction.status_code == 200
    corrected = client.get(extraction_url).json()
    assert corrected["document_type"] == "contract"
    assert {field["field_name"] for field in corrected["fields"]} == {
        "party",
        "effective_date",
    }
