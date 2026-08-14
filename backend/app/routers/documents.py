import io
import logging
import os
from collections.abc import Sequence
from typing import List

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from ..database import get_session
from ..jobs import DocumentJobDispatcher, get_document_job_dispatcher
from ..models import (
    ClassificationReviewRequest,
    ClassificationSource,
    Document,
    DocumentClassification,
    DocumentClassificationReview,
    DocumentPage,
    DocumentStructuredExtraction,
    DocumentStructuredField,
    DocumentStructuredFieldCorrection,
    ProcessingStatus,
    StructuredExtractionResponse,
    StructuredFieldCorrectionRequest,
    StructuredFieldCorrectionResponse,
    StructuredFieldResponse,
    StructuredFieldReviewHistoryResponse,
    StructuredFieldReviewStatus,
    utc_now,
)
from ..processing import reextract_document_fields
from ..storage import is_allowed_extension, save_upload, validate_file_size
from ..structured_review import LocalStructuredFieldReviewer, StructuredFieldReviewError

router = APIRouter()


@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
    dispatcher: DocumentJobDispatcher = Depends(get_document_job_dispatcher),
) -> dict:
    if not file.filename or not isinstance(file.filename, str) or not file.filename.strip():
        raise HTTPException(status_code=400, detail="missing_filename")
    filename = file.filename

    if not is_allowed_extension(filename):
        raise HTTPException(status_code=400, detail="unsupported_file_type")
    content_bytes = await file.read()
    content = io.BytesIO(content_bytes)
    try:
        size = validate_file_size(content)
    except ValueError:
        raise HTTPException(status_code=400, detail="file_too_large")

    try:
        storage_path = await save_upload(content, filename)
    except Exception:
        logging.exception("Failed to save upload")
        raise HTTPException(status_code=500, detail="storage_error")

    document = Document(
        filename=filename,
        content_type=file.content_type or "application/octet-stream",
        size=size,
        storage_path=storage_path,
        status=ProcessingStatus.uploaded,
    )
    try:
        session.add(document)
        await session.commit()
        await session.refresh(document)
    except SQLAlchemyError:
        logging.exception("Database error when storing document metadata")
        try:
            if os.path.exists(storage_path):
                os.remove(storage_path)
        except Exception:
            pass
        await session.rollback()
        raise HTTPException(status_code=500, detail="db_error")

    document_id = str(document.id)
    logging.info("Stored document id=%s", document_id)
    dispatcher.enqueue(document_id)
    return {
        "id": document_id,
        "filename": document.filename,
        "status": document.status,
    }


@router.get("/")
async def list_documents(
    session: AsyncSession = Depends(get_session),
) -> List[Document]:
    result = await session.execute(select(Document))
    return list(result.scalars().all())


@router.get("/{document_id}/pages")
async def list_document_pages(
    document_id: str, session: AsyncSession = Depends(get_session)
) -> List[DocumentPage]:
    document_result = await session.execute(
        select(Document).where(Document.id == document_id)
    )
    if document_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="document_not_found")

    page_result = await session.execute(
        select(DocumentPage)
        .where(DocumentPage.document_id == document_id)
        .order_by(col(DocumentPage.page_number))
    )
    return list(page_result.scalars().all())


@router.get("/{document_id}/classification")
async def get_document_classification(
    document_id: str, session: AsyncSession = Depends(get_session)
) -> DocumentClassification:
    return await _get_classification(session, document_id)


@router.patch("/{document_id}/classification")
async def review_document_classification(
    document_id: str,
    review: ClassificationReviewRequest,
    session: AsyncSession = Depends(get_session),
) -> DocumentClassification:
    classification = await _get_classification(session, document_id)
    if classification.effective_type == review.document_type:
        await reextract_document_fields(document_id)
        return classification

    now = utc_now()
    session.add(
        DocumentClassificationReview(
            document_id=document_id,
            previous_type=classification.effective_type,
            corrected_type=review.document_type,
            created_at=now,
        )
    )
    classification.effective_type = review.document_type
    classification.source = ClassificationSource.human
    classification.reviewed_at = now
    classification.updated_at = now
    await session.commit()
    await session.refresh(classification)
    await reextract_document_fields(document_id)
    return classification


async def _get_classification(
    session: AsyncSession, document_id: str
) -> DocumentClassification:
    result = await session.execute(
        select(DocumentClassification).where(
            DocumentClassification.document_id == document_id
        )
    )
    classification = result.scalar_one_or_none()
    if classification is None:
        raise HTTPException(status_code=404, detail="classification_not_found")
    return classification


@router.get("/{document_id}/extraction")
async def get_document_structured_extraction(
    document_id: str, session: AsyncSession = Depends(get_session)
) -> StructuredExtractionResponse:
    state = await _get_structured_extraction_state(session, document_id)

    fields_result = await session.execute(
        select(DocumentStructuredField)
        .where(DocumentStructuredField.document_id == document_id)
        .order_by(
            col(DocumentStructuredField.field_name),
            col(DocumentStructuredField.value_index),
        )
    )
    correction_result = await session.execute(
        select(DocumentStructuredFieldCorrection)
        .where(DocumentStructuredFieldCorrection.document_id == document_id)
        .order_by(
            col(DocumentStructuredFieldCorrection.created_at),
            col(DocumentStructuredFieldCorrection.id),
        )
    )
    latest_corrections = _latest_corrections(correction_result.scalars().all())
    fields = [
        _structured_field_response(
            field,
            latest_corrections.get((field.field_name, field.value_index)),
        )
        for field in fields_result.scalars().all()
    ]
    return StructuredExtractionResponse(
        document_id=state.document_id,
        document_type=state.document_type,
        status=state.status,
        extractor_version=state.extractor_version,
        started_at=state.started_at,
        completed_at=state.completed_at,
        fields=fields,
    )


@router.patch(
    "/{document_id}/extraction/fields/{field_name}/{value_index}",
)
async def correct_document_structured_field(
    document_id: str,
    field_name: str,
    value_index: int,
    review: StructuredFieldCorrectionRequest,
    session: AsyncSession = Depends(get_session),
) -> StructuredFieldResponse:
    state = await _get_structured_extraction_state(session, document_id)
    reviewer_id = review.reviewer_id.strip()
    if not reviewer_id:
        raise HTTPException(status_code=422, detail="invalid_reviewer_id")

    try:
        corrected_value = LocalStructuredFieldReviewer().validate(
            state.document_type, field_name, review.value
        )
    except StructuredFieldReviewError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    field_result = await session.execute(
        select(DocumentStructuredField).where(
            DocumentStructuredField.document_id == document_id,
            DocumentStructuredField.field_name == field_name,
            DocumentStructuredField.value_index == value_index,
        )
    )
    field = field_result.scalar_one_or_none()
    if field is None:
        raise HTTPException(status_code=404, detail="structured_field_not_found")

    corrections_result = await session.execute(
        select(DocumentStructuredFieldCorrection)
        .where(
            DocumentStructuredFieldCorrection.document_id == document_id,
            DocumentStructuredFieldCorrection.field_name == field_name,
            DocumentStructuredFieldCorrection.value_index == value_index,
        )
        .order_by(
            col(DocumentStructuredFieldCorrection.created_at),
            col(DocumentStructuredFieldCorrection.id),
        )
    )
    corrections = list(corrections_result.scalars().all())
    latest = corrections[-1] if corrections else None
    previous_effective_value = latest.corrected_value if latest else field.value
    if corrected_value == previous_effective_value:
        return _structured_field_response(field, latest)

    correction = DocumentStructuredFieldCorrection(
        document_id=document_id,
        field_name=field_name,
        value_index=value_index,
        automatic_value=field.value,
        previous_effective_value=previous_effective_value,
        corrected_value=corrected_value,
        reviewer_id=reviewer_id,
        created_at=utc_now(),
    )
    session.add(correction)
    await session.commit()
    await session.refresh(correction)
    return _structured_field_response(field, correction)


@router.get("/{document_id}/extraction/reviews")
async def get_document_structured_field_reviews(
    document_id: str, session: AsyncSession = Depends(get_session)
) -> StructuredFieldReviewHistoryResponse:
    state = await _get_structured_extraction_state(session, document_id)
    fields_result = await session.execute(
        select(DocumentStructuredField).where(
            DocumentStructuredField.document_id == document_id
        )
    )
    current_keys = {
        (field.field_name, field.value_index)
        for field in fields_result.scalars().all()
    }
    corrections_result = await session.execute(
        select(DocumentStructuredFieldCorrection)
        .where(DocumentStructuredFieldCorrection.document_id == document_id)
        .order_by(
            col(DocumentStructuredFieldCorrection.created_at),
            col(DocumentStructuredFieldCorrection.id),
        )
    )
    corrections = list(corrections_result.scalars().all())
    latest = _latest_corrections(corrections)
    responses = []
    for correction in corrections:
        key = (correction.field_name, correction.value_index)
        if latest[key].id != correction.id:
            status = StructuredFieldReviewStatus.superseded
            effective_value = None
        elif key not in current_keys:
            status = StructuredFieldReviewStatus.orphaned
            effective_value = None
        else:
            status = StructuredFieldReviewStatus.active
            effective_value = correction.corrected_value
        responses.append(
            StructuredFieldCorrectionResponse(
                id=correction.id,
                document_id=correction.document_id,
                field_name=correction.field_name,
                value_index=correction.value_index,
                automatic_value=correction.automatic_value,
                previous_effective_value=correction.previous_effective_value,
                corrected_value=correction.corrected_value,
                effective_value=effective_value,
                reviewer_id=correction.reviewer_id,
                created_at=correction.created_at,
                status=status,
            )
        )
    return StructuredFieldReviewHistoryResponse(
        document_id=state.document_id, corrections=responses
    )


async def _get_structured_extraction_state(
    session: AsyncSession, document_id: str
) -> DocumentStructuredExtraction:
    document_result = await session.execute(
        select(Document).where(Document.id == document_id)
    )
    if document_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="document_not_found")
    state_result = await session.execute(
        select(DocumentStructuredExtraction).where(
            DocumentStructuredExtraction.document_id == document_id
        )
    )
    state = state_result.scalar_one_or_none()
    if state is None:
        raise HTTPException(status_code=404, detail="structured_extraction_not_found")
    return state


def _latest_corrections(
    corrections: Sequence[DocumentStructuredFieldCorrection],
) -> dict[tuple[str, int], DocumentStructuredFieldCorrection]:
    latest = {}
    for correction in corrections:
        latest[(correction.field_name, correction.value_index)] = correction
    return latest


def _structured_field_response(
    field: DocumentStructuredField,
    correction: DocumentStructuredFieldCorrection | None,
) -> StructuredFieldResponse:
    return StructuredFieldResponse(
        field_name=field.field_name,
        value_index=field.value_index,
        value=field.value,
        effective_value=correction.corrected_value if correction else field.value,
        reviewed=correction is not None,
        reviewer_id=correction.reviewer_id if correction else None,
        reviewed_at=correction.created_at if correction else None,
        page_number=field.page_number,
        extraction_method=field.extraction_method,
        extractor_version=field.extractor_version,
    )
