import logging
from typing import Protocol

from fastapi import BackgroundTasks, Depends
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from .database import get_session, get_sessionmaker
from .job_transport import (
    DocumentJobTransport,
    JobTransportSettings,
    LocalBackgroundTaskTransport,
    create_rq_transport,
)
from .models import DocumentProcessingJob, ProcessingJobStatus, utc_now
from .processing import ProcessingOutcome, process_document

logger = logging.getLogger(__name__)


class DocumentJobDispatcher(Protocol):
    """Persist and dispatch processing behind a queue-neutral boundary."""

    async def enqueue(self, document_id: str) -> DocumentProcessingJob: ...


class DocumentJobWorker(Protocol):
    """Execute a previously persisted processing job."""

    async def run(self, job_id: str) -> None: ...


class DocumentProcessor(Protocol):
    """Adapt document orchestration to the worker's outcome contract."""

    async def __call__(self, document_id: str) -> ProcessingOutcome: ...


class LocalDocumentJobWorker:
    """Run persisted jobs locally with bounded, immediate retries."""

    def __init__(self, processor: DocumentProcessor = process_document) -> None:
        self._processor = processor

    async def run(self, job_id: str) -> None:
        while claim := await _claim_queued_job(job_id):
            document_id, attempt_count, max_attempts = claim
            error_code: str | None = None
            try:
                outcome = await self._processor(document_id)
                succeeded = outcome == ProcessingOutcome.succeeded
                if not succeeded:
                    error_code = outcome.value
            except Exception:
                # Persist only a stable code; exception text could contain document data.
                logger.error("Processing job processor raised for id=%s", job_id)
                succeeded = False
                error_code = "processor_exception"

            should_retry = await _finish_attempt(
                job_id,
                succeeded=succeeded,
                error_code=error_code,
                attempt_count=attempt_count,
                max_attempts=max_attempts,
            )
            if not should_retry:
                return


class DurableDocumentJobDispatcher:
    """Persist authoritative job state before dispatching its identifier."""

    def __init__(
        self,
        session: AsyncSession,
        transport: DocumentJobTransport,
        max_attempts: int = 2,
    ) -> None:
        self._session = session
        self._transport = transport
        self._max_attempts = max_attempts

    async def enqueue(self, document_id: str) -> DocumentProcessingJob:
        active_job = await _get_active_job(self._session, document_id)
        if active_job is not None:
            if active_job.status == ProcessingJobStatus.queued:
                await self._transport.dispatch(active_job.id)
            return active_job

        job = DocumentProcessingJob(
            document_id=document_id,
            max_attempts=self._max_attempts,
        )
        self._session.add(job)
        try:
            await self._session.commit()
            await self._session.refresh(job)
        except IntegrityError:
            # The partial unique index resolves concurrent enqueue races.
            await self._session.rollback()
            active_job = await _get_active_job(self._session, document_id)
            if active_job is None:
                raise
            job = active_job

        if job.status == ProcessingJobStatus.queued:
            await self._transport.dispatch(job.id)
        return job


class LocalDocumentJobDispatcher(DurableDocumentJobDispatcher):
    """Preserve FastAPI background-task delivery as the default transport."""

    def __init__(
        self,
        background_tasks: BackgroundTasks,
        session: AsyncSession,
        worker: DocumentJobWorker | None = None,
        max_attempts: int = 2,
    ) -> None:
        active_worker = worker or LocalDocumentJobWorker()
        super().__init__(
            session,
            LocalBackgroundTaskTransport(background_tasks, active_worker),
            max_attempts,
        )


async def _get_active_job(
    session: AsyncSession, document_id: str
) -> DocumentProcessingJob | None:
    result = await session.execute(
        select(DocumentProcessingJob)
        .where(
            DocumentProcessingJob.document_id == document_id,
            col(DocumentProcessingJob.status).in_(
                [ProcessingJobStatus.queued, ProcessingJobStatus.running]
            ),
        )
        .order_by(col(DocumentProcessingJob.queued_at).desc())
    )
    return result.scalars().first()


async def _claim_queued_job(job_id: str) -> tuple[str, int, int] | None:
    """Atomically claim a queued job so duplicate callbacks become no-ops."""

    session = get_sessionmaker()()
    try:
        now = utc_now()
        result = await session.execute(
            update(DocumentProcessingJob)
            .where(
                col(DocumentProcessingJob.id) == job_id,
                col(DocumentProcessingJob.status) == ProcessingJobStatus.queued,
            )
            .values(
                status=ProcessingJobStatus.running,
                attempt_count=col(DocumentProcessingJob.attempt_count) + 1,
                started_at=now,
                finished_at=None,
                updated_at=now,
            )
            .returning(
                col(DocumentProcessingJob.document_id),
                col(DocumentProcessingJob.attempt_count),
                col(DocumentProcessingJob.max_attempts),
            )
        )
        claim = result.one_or_none()
        await session.commit()
        if claim is None:
            return None
        return str(claim[0]), int(claim[1]), int(claim[2])
    finally:
        await session.close()


async def _finish_attempt(
    job_id: str,
    *,
    succeeded: bool,
    error_code: str | None,
    attempt_count: int,
    max_attempts: int,
) -> bool:
    session = get_sessionmaker()()
    try:
        result = await session.execute(
            select(DocumentProcessingJob).where(DocumentProcessingJob.id == job_id)
        )
        job = result.scalar_one_or_none()
        if job is None or job.status != ProcessingJobStatus.running:
            return False

        now = utc_now()
        if succeeded:
            job.status = ProcessingJobStatus.succeeded
            job.last_error_code = None
            job.finished_at = now
            should_retry = False
        elif attempt_count < max_attempts:
            job.status = ProcessingJobStatus.queued
            job.last_error_code = error_code
            should_retry = True
        else:
            job.status = ProcessingJobStatus.failed
            job.last_error_code = error_code
            job.finished_at = now
            should_retry = False
        job.updated_at = now
        await session.commit()
        return should_retry
    finally:
        await session.close()


def get_document_job_dispatcher(
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
) -> DocumentJobDispatcher:
    settings = JobTransportSettings.from_environment()
    if settings.transport == "local":
        return LocalDocumentJobDispatcher(background_tasks, session)
    return DurableDocumentJobDispatcher(session, create_rq_transport(settings))
