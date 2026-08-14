import asyncio
import logging
import tempfile
from enum import Enum
from pathlib import Path

from sqlalchemy import delete
from sqlmodel import col, select

from .classification import (
    ClassificationResult,
    DocumentClassifier,
    LocalKeywordClassifier,
)
from .database import get_session
from .embeddings import (
    EmbeddingProvider,
    EmbeddingSourcePage,
    TextChunker,
    index_document_pages,
)
from .models import (
    ClassificationSource,
    Document,
    DocumentClassification,
    DocumentPage,
    DocumentStructuredExtraction,
    DocumentStructuredField,
    DocumentType,
    ProcessingStatus,
    StructuredExtractionStatus,
    utc_now,
)
from .ocr import ExtractedPage, LocalPageTextExtractor, PageTextExtractor
from .structured_extraction import (
    LocalStructuredExtractor,
    StructuredExtractionResult,
    StructuredExtractor,
    StructuredTextPage,
)
from .storage import StorageProvider, get_storage_provider

logger = logging.getLogger(__name__)


class ProcessingOutcome(str, Enum):
    succeeded = "succeeded"
    failed = "failed"
    document_not_found = "document_not_found"


async def process_document(
    document_id: str,
    extractor: PageTextExtractor | None = None,
    classifier: DocumentClassifier | None = None,
    structured_extractor: StructuredExtractor | None = None,
    embedding_provider: EmbeddingProvider | None = None,
    chunker: TextChunker | None = None,
    storage_provider: StorageProvider | None = None,
) -> ProcessingOutcome:
    """Extract page text, classify, extract fields, and index chunks."""
    document_source = await _mark_processing(document_id)
    if document_source is None:
        return ProcessingOutcome.document_not_found

    active_extractor = extractor or LocalPageTextExtractor()
    try:
        active_storage = storage_provider or get_storage_provider()
        filename, storage_reference = document_source
        content = await active_storage.read(storage_reference)
        pages = await _extract_pages(active_extractor, filename, content)
        if not pages:
            raise ValueError("document_has_no_pages")
        await _store_pages(document_id, pages)
        active_classifier = classifier or LocalKeywordClassifier()
        classification = await active_classifier.classify(
            [page.text for page in pages]
        )
        effective_type = await _store_classification(document_id, classification)
        active_structured_extractor = structured_extractor or LocalStructuredExtractor()
        await _run_structured_extraction(
            document_id,
            effective_type,
            [StructuredTextPage(page.page_number, page.text) for page in pages],
            active_structured_extractor,
        )
        await index_document_pages(
            document_id,
            [EmbeddingSourcePage(page.page_number, page.text) for page in pages],
            embedding_provider,
            chunker,
        )
        return ProcessingOutcome.succeeded
    except Exception:
        logger.exception("Document processing failed for id=%s", document_id)
        await _mark_failed(document_id)
        return ProcessingOutcome.failed


async def _mark_processing(document_id: str) -> tuple[str, str] | None:
    async for session in get_session():
        result = await session.execute(select(Document).where(Document.id == document_id))
        document = result.scalar_one_or_none()
        if document is None:
            return None
        document.status = ProcessingStatus.processing
        document.updated_at = utc_now()
        await session.commit()
        return document.filename, document.storage_path
    return None


async def _extract_pages(
    extractor: PageTextExtractor, filename: str, content: bytes
) -> list[ExtractedPage]:
    """Materialize provider bytes only for path-based local OCR libraries."""

    suffix = Path(filename).suffix.lower()

    def create_temporary_file() -> Path:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temporary:
            temporary.write(content)
            return Path(temporary.name)

    temporary_path = await asyncio.to_thread(create_temporary_file)
    try:
        return await extractor.extract(temporary_path)
    finally:
        await asyncio.to_thread(temporary_path.unlink, missing_ok=True)


async def _store_pages(document_id: str, pages: list[ExtractedPage]) -> None:
    async for session in get_session():
        result = await session.execute(select(Document).where(Document.id == document_id))
        document = result.scalar_one_or_none()
        if document is None:
            return

        await session.execute(
            delete(DocumentPage).where(col(DocumentPage.document_id) == document_id)
        )
        session.add_all(
            [
                DocumentPage(
                    document_id=document_id,
                    page_number=page.page_number,
                    text=page.text,
                    extraction_method=page.extraction_method,
                )
                for page in pages
            ]
        )
        document.status = ProcessingStatus.processed
        document.updated_at = utc_now()
        await session.commit()
        return


async def _mark_failed(document_id: str) -> None:
    async for session in get_session():
        result = await session.execute(select(Document).where(Document.id == document_id))
        document = result.scalar_one_or_none()
        if document is None:
            return
        document.status = ProcessingStatus.failed
        document.updated_at = utc_now()
        await session.commit()
        return


async def _store_classification(
    document_id: str, result: ClassificationResult
) -> DocumentType:
    async for session in get_session():
        classification_result = await session.execute(
            select(DocumentClassification).where(
                DocumentClassification.document_id == document_id
            )
        )
        classification = classification_result.scalar_one_or_none()
        now = utc_now()
        if classification is None:
            effective_type = result.document_type
            session.add(
                DocumentClassification(
                    document_id=document_id,
                    predicted_type=result.document_type,
                    effective_type=result.document_type,
                    source=ClassificationSource.classifier,
                    classifier_version=result.classifier_version,
                    classified_at=now,
                    updated_at=now,
                )
            )
        else:
            classification.predicted_type = result.document_type
            classification.classifier_version = result.classifier_version
            classification.classified_at = now
            classification.updated_at = now
            if classification.source != ClassificationSource.human:
                classification.effective_type = result.document_type
                classification.source = ClassificationSource.classifier
                classification.reviewed_at = None
            effective_type = classification.effective_type
        await session.commit()
        return effective_type
    raise RuntimeError("classification_session_unavailable")


async def reextract_document_fields(
    document_id: str, extractor: StructuredExtractor | None = None
) -> None:
    """Rebuild structured fields from stored pages after classification review."""

    async for session in get_session():
        classification_result = await session.execute(
            select(DocumentClassification).where(
                DocumentClassification.document_id == document_id
            )
        )
        classification = classification_result.scalar_one_or_none()
        if classification is None:
            return
        page_result = await session.execute(
            select(DocumentPage)
            .where(DocumentPage.document_id == document_id)
            .order_by(col(DocumentPage.page_number))
        )
        pages = [
            StructuredTextPage(page.page_number, page.text)
            for page in page_result.scalars().all()
        ]
        effective_type = classification.effective_type
        break
    else:
        return

    active_extractor = extractor or LocalStructuredExtractor()
    await _run_structured_extraction(
        document_id, effective_type, pages, active_extractor
    )


async def _run_structured_extraction(
    document_id: str,
    document_type: DocumentType,
    pages: list[StructuredTextPage],
    extractor: StructuredExtractor,
) -> None:
    await _begin_structured_extraction(
        document_id, document_type, extractor.version
    )
    try:
        result = await extractor.extract(document_type, pages)
        if result.document_type != document_type:
            raise ValueError("structured_extraction_type_mismatch")
        await _complete_structured_extraction(document_id, result)
    except Exception:
        await _mark_structured_extraction_failed(document_id)
        raise


async def _begin_structured_extraction(
    document_id: str, document_type: DocumentType, extractor_version: str
) -> None:
    async for session in get_session():
        result = await session.execute(
            select(DocumentStructuredExtraction).where(
                DocumentStructuredExtraction.document_id == document_id
            )
        )
        state = result.scalar_one_or_none()
        now = utc_now()
        if state is None:
            session.add(
                DocumentStructuredExtraction(
                    document_id=document_id,
                    document_type=document_type,
                    status=StructuredExtractionStatus.processing,
                    extractor_version=extractor_version,
                    started_at=now,
                    updated_at=now,
                )
            )
        else:
            state.document_type = document_type
            state.status = StructuredExtractionStatus.processing
            state.extractor_version = extractor_version
            state.started_at = now
            state.completed_at = None
            state.updated_at = now
        await session.execute(
            delete(DocumentStructuredField).where(
                col(DocumentStructuredField.document_id) == document_id
            )
        )
        await session.commit()
        return


async def _complete_structured_extraction(
    document_id: str, result: StructuredExtractionResult
) -> None:
    async for session in get_session():
        state_result = await session.execute(
            select(DocumentStructuredExtraction).where(
                DocumentStructuredExtraction.document_id == document_id
            )
        )
        state = state_result.scalar_one()
        session.add_all(
            [
                DocumentStructuredField(
                    document_id=document_id,
                    field_name=field.field_name,
                    value_index=field.value_index,
                    value=field.value,
                    page_number=field.page_number,
                    extraction_method=result.extraction_method,
                    extractor_version=result.extractor_version,
                )
                for field in result.fields
            ]
        )
        now = utc_now()
        state.document_type = result.document_type
        state.status = StructuredExtractionStatus.completed
        state.extractor_version = result.extractor_version
        state.completed_at = now
        state.updated_at = now
        await session.commit()
        return


async def _mark_structured_extraction_failed(document_id: str) -> None:
    async for session in get_session():
        result = await session.execute(
            select(DocumentStructuredExtraction).where(
                DocumentStructuredExtraction.document_id == document_id
            )
        )
        state = result.scalar_one_or_none()
        if state is None:
            return
        state.status = StructuredExtractionStatus.failed
        state.completed_at = None
        state.updated_at = utc_now()
        await session.commit()
        return
