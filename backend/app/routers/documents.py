from typing import List
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from sqlmodel import select
from sqlalchemy.exc import SQLAlchemyError
from ..database import get_session
from ..models import Document, ProcessingStatus
from ..storage import save_upload, validate_file_size, is_allowed_extension
import io
import logging

from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


@router.post('/upload')
async def upload_document(file: UploadFile = File(...), session: AsyncSession = Depends(get_session)) -> dict:
    # validate that filename is present
    if not file.filename or not isinstance(file.filename, str) or not file.filename.strip():
        raise HTTPException(status_code=400, detail='missing_filename')
    filename = file.filename

    # validate extension
    if not is_allowed_extension(filename):
        raise HTTPException(status_code=400, detail='unsupported_file_type')
    # read bytes from UploadFile for size check and streaming save
    content_bytes = await file.read()
    content = io.BytesIO(content_bytes)
    try:
        size = validate_file_size(content)
    except ValueError:
        raise HTTPException(status_code=400, detail='file_too_large')

    # save to storage off the event loop
    try:
        storage_path = await save_upload(content, filename)
    except Exception:
        logging.exception("Failed to save upload")
        raise HTTPException(status_code=500, detail='storage_error')

    # store metadata
    doc = Document(
        filename=filename,
        content_type=file.content_type or 'application/octet-stream',
        size=size,
        storage_path=storage_path,
        status=ProcessingStatus.uploaded,
    )
    try:
        logging.info("Adding document metadata for %s", filename)
        session.add(doc)
        await session.commit()
        await session.refresh(doc)
        logging.info("Stored document id=%s", doc.id)
    except SQLAlchemyError:
        logging.exception("Database error when storing document metadata")
        # attempt to remove partially written file
        try:
            import os
            if os.path.exists(storage_path):
                os.remove(storage_path)
        except Exception:
            pass
        await session.rollback()
        raise HTTPException(status_code=500, detail='db_error')

    return {"id": doc.id, "filename": doc.filename, "status": doc.status}


@router.get('/')
async def list_documents(session: AsyncSession = Depends(get_session)) -> List[Document]:
    result = await session.execute(select(Document))
    docs = list(result.scalars().all())
    return docs
