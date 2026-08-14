import asyncio
import io
import logging
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from backend.app.database import get_sessionmaker, init_db
from backend.app.main import app
from backend.app.models import Document, ExtractionMethod
from backend.app.ocr import ExtractedPage
from backend.app.processing import ProcessingOutcome, process_document
from backend.app.storage import (
    LocalStorageProvider,
    S3StorageProvider,
    StorageConfigurationError,
    StorageError,
    StorageSettings,
    build_document_object_key,
    get_storage_provider,
)


class FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}
        self.calls: list[tuple[str, str, str]] = []

    def put_object(self, *, Bucket: str, Key: str, Body: bytes) -> None:
        self.calls.append(("put", Bucket, Key))
        self.objects[(Bucket, Key)] = Body

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, io.BytesIO]:
        self.calls.append(("get", Bucket, Key))
        return {"Body": io.BytesIO(self.objects[(Bucket, Key)])}

    def delete_object(self, *, Bucket: str, Key: str) -> None:
        self.calls.append(("delete", Bucket, Key))
        self.objects.pop((Bucket, Key), None)


class FailingS3Client:
    def put_object(self, **kwargs: Any) -> None:
        raise RuntimeError("secret-access-key-must-not-escape")


class InMemoryStorageProvider:
    def __init__(self, content: bytes = b"") -> None:
        self.content = content
        self.read_keys: list[str] = []

    async def save(self, object_key: str, content: bytes) -> None:
        self.content = content

    async def read(self, object_key: str) -> bytes:
        self.read_keys.append(object_key)
        return self.content

    async def delete(self, object_key: str) -> None:
        self.content = b""


class ReadingExtractor:
    def __init__(self) -> None:
        self.observed_content: bytes | None = None
        self.observed_suffix: str | None = None

    async def extract(self, path: Path) -> list[ExtractedPage]:
        self.observed_content = path.read_bytes()
        self.observed_suffix = path.suffix
        return [ExtractedPage(1, "stored text", ExtractionMethod.native)]


class FailingStorageProvider:
    async def save(self, object_key: str, content: bytes) -> None:
        raise StorageError("credential=do-not-log")

    async def read(self, object_key: str) -> bytes:
        raise StorageError("credential=do-not-log")

    async def delete(self, object_key: str) -> None:
        raise StorageError("credential=do-not-log")


def test_document_object_key_is_deterministic_and_sanitized() -> None:
    first = build_document_object_key("document-123", "../../Quarter 1 invoice.pdf")
    second = build_document_object_key("document-123", "Quarter 1 invoice.pdf")

    assert first == second == "documents/document-123/Quarter_1_invoice.pdf"
    assert not Path(first).is_absolute()
    with pytest.raises(StorageError, match="^invalid_document_id$"):
        build_document_object_key("../outside", "invoice.pdf")


def test_local_storage_upload_retrieval_delete_and_legacy_read(tmp_path: Path) -> None:
    provider = LocalStorageProvider(tmp_path / "objects")
    key = "documents/document-123/invoice.pdf"

    asyncio.run(provider.save(key, b"invoice bytes"))

    assert asyncio.run(provider.read(key)) == b"invoice bytes"
    stored_path = (
        tmp_path / "objects" / "documents" / "document-123" / "invoice.pdf"
    )
    assert stored_path.is_file()
    asyncio.run(provider.delete(key))
    assert not stored_path.exists()

    legacy = tmp_path / "legacy.pdf"
    legacy.write_bytes(b"legacy bytes")
    assert asyncio.run(provider.read(str(legacy))) == b"legacy bytes"


def test_s3_compatible_storage_upload_retrieval_and_delete() -> None:
    client = FakeS3Client()
    provider = S3StorageProvider("private-documents", client)
    key = "documents/document-123/invoice.pdf"

    asyncio.run(provider.save(key, b"invoice bytes"))
    assert asyncio.run(provider.read(key)) == b"invoice bytes"
    asyncio.run(provider.delete(key))

    assert client.calls == [
        ("put", "private-documents", key),
        ("get", "private-documents", key),
        ("delete", "private-documents", key),
    ]
    assert client.objects == {}


def test_s3_provider_failure_uses_stable_error_without_client_details() -> None:
    provider = S3StorageProvider("private-documents", FailingS3Client())

    with pytest.raises(StorageError, match="^storage_put_object_failed$") as error:
        asyncio.run(
            provider.save("documents/document-123/invoice.pdf", b"invoice bytes")
        )

    assert error.value.__cause__ is None
    assert "secret-access-key" not in str(error.value)


def test_storage_provider_configuration(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path))
    assert isinstance(get_storage_provider(), LocalStorageProvider)

    captured: dict[str, Any] = {}

    def fake_client(service: str, **kwargs: Any) -> FakeS3Client:
        captured.update(service=service, **kwargs)
        return FakeS3Client()

    monkeypatch.setenv("STORAGE_BACKEND", "s3")
    monkeypatch.setenv("S3_BUCKET_NAME", "private-documents")
    monkeypatch.setenv("S3_REGION", "us-test-1")
    monkeypatch.setenv("S3_ENDPOINT_URL", "http://object-store:9000")
    monkeypatch.setenv("S3_ACCESS_KEY_ID", "environment-access-key")
    monkeypatch.setenv("S3_SECRET_ACCESS_KEY", "environment-secret-key")
    monkeypatch.setenv("S3_FORCE_PATH_STYLE", "true")
    monkeypatch.setattr("backend.app.storage.boto3.client", fake_client)

    assert isinstance(get_storage_provider(), S3StorageProvider)
    assert captured["service"] == "s3"
    assert captured["region_name"] == "us-test-1"
    assert captured["endpoint_url"] == "http://object-store:9000"
    assert captured["aws_access_key_id"] == "environment-access-key"
    assert captured["aws_secret_access_key"] == "environment-secret-key"
    assert captured["config"].s3["addressing_style"] == "path"


def test_storage_configuration_rejects_missing_or_partial_values(monkeypatch) -> None:
    monkeypatch.setenv("STORAGE_BACKEND", "s3")
    monkeypatch.delenv("S3_BUCKET_NAME", raising=False)
    with pytest.raises(StorageConfigurationError, match="^s3_bucket_required$"):
        StorageSettings.from_environment()

    monkeypatch.setenv("S3_BUCKET_NAME", "private-documents")
    monkeypatch.setenv("S3_ACCESS_KEY_ID", "access-only")
    monkeypatch.delenv("S3_SECRET_ACCESS_KEY", raising=False)
    with pytest.raises(
        StorageConfigurationError, match="^incomplete_s3_credentials$"
    ):
        StorageSettings.from_environment()


def test_worker_reads_document_through_storage_provider(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    asyncio.run(init_db())
    storage = InMemoryStorageProvider(b"remote document bytes")
    extractor = ReadingExtractor()

    async def exercise() -> tuple[Document, ProcessingOutcome]:
        session = get_sessionmaker()()
        try:
            document = Document(
                filename="remote.pdf",
                content_type="application/pdf",
                size=len(storage.content),
                storage_path="documents/document-123/remote.pdf",
            )
            session.add(document)
            await session.commit()
            assert document.id is not None
            outcome = await process_document(
                document.id,
                extractor=extractor,
                storage_provider=storage,
            )
            result = await session.execute(
                select(Document).where(Document.id == document.id)
            )
            return result.scalar_one(), outcome
        finally:
            await session.close()

    stored_document, outcome = asyncio.run(exercise())

    assert outcome == ProcessingOutcome.succeeded
    assert storage.read_keys == ["documents/document-123/remote.pdf"]
    assert extractor.observed_content == b"remote document bytes"
    assert extractor.observed_suffix == ".pdf"
    assert stored_document.storage_path == "documents/document-123/remote.pdf"


def test_upload_storage_failure_does_not_log_provider_detail(
    tmp_path: Path, monkeypatch, caplog
) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    asyncio.run(init_db())
    from backend.app.storage import get_storage_provider as storage_dependency

    app.dependency_overrides[storage_dependency] = FailingStorageProvider
    caplog.set_level(logging.ERROR)
    try:
        response = TestClient(app).post(
            "/api/v1/documents/upload",
            files={"file": ("invoice.pdf", io.BytesIO(b"content"), "application/pdf")},
        )
    finally:
        app.dependency_overrides.pop(storage_dependency, None)

    assert response.status_code == 500
    assert response.json() == {"detail": "storage_error"}
    assert "do-not-log" not in caplog.text
    assert "credential" not in caplog.text
