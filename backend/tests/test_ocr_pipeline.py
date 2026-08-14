import asyncio
import io
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image
from pypdf import PdfWriter
from sqlmodel import col, select

from backend.app.database import get_sessionmaker, init_db
from backend.app.models import (
    Document,
    DocumentPage,
    ExtractionMethod,
    ProcessingStatus,
)
from backend.app.ocr import ExtractedPage, LocalPageTextExtractor, OcrError
from backend.app.processing import process_document


class StubExtractor:
    def __init__(self, pages: list[ExtractedPage]) -> None:
        self.pages = pages

    async def extract(self, path: Path) -> list[ExtractedPage]:
        return self.pages


class FailingExtractor:
    async def extract(self, path: Path) -> list[ExtractedPage]:
        raise OcrError("test_extraction_failure")


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


async def _load_document_and_pages(
    document_id: str,
) -> tuple[Document, list[DocumentPage]]:
    session = get_sessionmaker()()
    try:
        document_result = await session.execute(
            select(Document).where(Document.id == document_id)
        )
        document = document_result.scalar_one()
        page_result = await session.execute(
            select(DocumentPage)
            .where(DocumentPage.document_id == document_id)
            .order_by(col(DocumentPage.page_number))
        )
        return document, list(page_result.scalars().all())
    finally:
        await session.close()


def test_image_ocr_returns_page_text(tmp_path, monkeypatch):
    image_path = tmp_path / "scan.png"
    Image.new("RGB", (20, 20), "white").save(image_path)
    monkeypatch.setattr(
        "backend.app.ocr.pytesseract.image_to_string",
        lambda image: "  scanned page text  ",
    )

    pages = asyncio.run(LocalPageTextExtractor().extract(image_path))

    assert pages == [ExtractedPage(1, "scanned page text", ExtractionMethod.ocr)]


def test_pdf_without_native_text_uses_ocr(tmp_path, monkeypatch):
    pdf_path = tmp_path / "scan.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    with pdf_path.open("wb") as output:
        writer.write(output)
    monkeypatch.setattr(
        "backend.app.ocr.pytesseract.image_to_string",
        lambda image: "scanned pdf text",
    )

    pages = asyncio.run(LocalPageTextExtractor().extract(pdf_path))

    assert pages == [ExtractedPage(1, "scanned pdf text", ExtractionMethod.ocr)]


def test_image_upload_processes_and_returns_pages(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path / "uploads"))
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setattr(
        "backend.app.ocr.pytesseract.image_to_string",
        lambda image: "uploaded scan text",
    )
    asyncio.run(init_db())

    image_bytes = io.BytesIO()
    Image.new("RGB", (20, 20), "white").save(image_bytes, format="PNG")
    image_bytes.seek(0)

    from backend.app.main import app

    client = TestClient(app)
    upload_response = client.post(
        "/api/v1/documents/upload",
        files={"file": ("scan.png", image_bytes, "image/png")},
    )

    assert upload_response.status_code == 200
    document_id = upload_response.json()["id"]
    pages_response = client.get(f"/api/v1/documents/{document_id}/pages")
    assert pages_response.status_code == 200
    assert pages_response.json()[0]["text"] == "uploaded scan text"
    assert pages_response.json()[0]["extraction_method"] == "ocr"


def test_processing_stores_and_replaces_pages(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    asyncio.run(init_db())
    source_path = tmp_path / "document.pdf"
    source_path.write_bytes(b"test document")
    document_id = asyncio.run(_create_document(source_path))

    initial_pages = [
        ExtractedPage(1, "first page", ExtractionMethod.native),
        ExtractedPage(2, "second page", ExtractionMethod.ocr),
    ]
    asyncio.run(process_document(document_id, StubExtractor(initial_pages)))

    document, pages = asyncio.run(_load_document_and_pages(document_id))
    assert document.status == ProcessingStatus.processed
    assert [(page.page_number, page.text) for page in pages] == [
        (1, "first page"),
        (2, "second page"),
    ]

    replacement_pages = [
        ExtractedPage(1, "replacement text", ExtractionMethod.native)
    ]
    asyncio.run(process_document(document_id, StubExtractor(replacement_pages)))

    _, replaced_pages = asyncio.run(_load_document_and_pages(document_id))
    assert [(page.page_number, page.text) for page in replaced_pages] == [
        (1, "replacement text")
    ]

    from backend.app.main import app

    response = TestClient(app).get(f"/api/v1/documents/{document_id}/pages")
    assert response.status_code == 200
    assert response.json()[0]["text"] == "replacement text"


def test_processing_failure_marks_document_failed(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    asyncio.run(init_db())
    source_path = tmp_path / "document.pdf"
    source_path.write_bytes(b"test document")
    document_id = asyncio.run(_create_document(source_path))

    asyncio.run(process_document(document_id, FailingExtractor()))

    document, pages = asyncio.run(_load_document_and_pages(document_id))
    assert document.status == ProcessingStatus.failed
    assert pages == []
