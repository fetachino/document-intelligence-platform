import asyncio
from collections.abc import Sequence
from pathlib import Path

from fastapi import BackgroundTasks
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from backend.app.database import get_sessionmaker, init_db
from backend.app.jobs import LocalDocumentJobDispatcher, LocalDocumentJobWorker
from backend.app.models import (
    Document,
    DocumentProcessingJob,
    ProcessingJobStatus,
)
from backend.app.processing import ProcessingOutcome


class SequenceProcessor:
    def __init__(self, outcomes: Sequence[ProcessingOutcome | Exception]) -> None:
        self._outcomes = list(outcomes)
        self.calls: list[str] = []
        self.observed_statuses: list[ProcessingJobStatus] = []

    async def __call__(self, document_id: str) -> ProcessingOutcome:
        self.calls.append(document_id)
        session = get_sessionmaker()()
        try:
            result = await session.execute(
                select(DocumentProcessingJob).where(
                    DocumentProcessingJob.document_id == document_id,
                    DocumentProcessingJob.status == ProcessingJobStatus.running,
                )
            )
            self.observed_statuses.append(result.scalars().one().status)
        finally:
            await session.close()

        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


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


async def _load_jobs(document_id: str) -> list[DocumentProcessingJob]:
    session = get_sessionmaker()()
    try:
        result = await session.execute(
            select(DocumentProcessingJob)
            .where(DocumentProcessingJob.document_id == document_id)
            .order_by(col(DocumentProcessingJob.queued_at))
        )
        return list(result.scalars().all())
    finally:
        await session.close()


async def _enqueue(
    document_id: str,
    processor: SequenceProcessor,
    *,
    max_attempts: int = 2,
) -> tuple[DocumentProcessingJob, BackgroundTasks]:
    session: AsyncSession = get_sessionmaker()()
    background_tasks = BackgroundTasks()
    try:
        dispatcher = LocalDocumentJobDispatcher(
            background_tasks,
            session,
            LocalDocumentJobWorker(processor),
            max_attempts=max_attempts,
        )
        job = await dispatcher.enqueue(document_id)
        return job, background_tasks
    finally:
        await session.close()


def _set_up_database(tmp_path: Path, monkeypatch) -> str:
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    asyncio.run(init_db())
    source_path = tmp_path / "document.pdf"
    source_path.write_bytes(b"test document")
    return asyncio.run(_create_document(source_path))


def test_dispatch_is_observable_and_active_job_is_idempotent(tmp_path, monkeypatch):
    document_id = _set_up_database(tmp_path, monkeypatch)
    processor = SequenceProcessor([ProcessingOutcome.succeeded])

    async def exercise() -> tuple[str, str]:
        session = get_sessionmaker()()
        background_tasks = BackgroundTasks()
        try:
            dispatcher = LocalDocumentJobDispatcher(
                background_tasks, session, LocalDocumentJobWorker(processor)
            )
            first = await dispatcher.enqueue(document_id)
            duplicate = await dispatcher.enqueue(document_id)
            assert first.status == ProcessingJobStatus.queued
            await background_tasks()
            return first.id, duplicate.id
        finally:
            await session.close()

    first_id, duplicate_id = asyncio.run(exercise())
    jobs = asyncio.run(_load_jobs(document_id))

    assert first_id == duplicate_id
    assert len(jobs) == 1
    assert jobs[0].status == ProcessingJobStatus.succeeded
    assert jobs[0].attempt_count == 1
    assert jobs[0].started_at is not None
    assert jobs[0].finished_at is not None
    assert processor.calls == [document_id]
    assert processor.observed_statuses == [ProcessingJobStatus.running]


def test_worker_retries_then_succeeds_and_terminal_run_is_idempotent(
    tmp_path, monkeypatch
):
    document_id = _set_up_database(tmp_path, monkeypatch)
    processor = SequenceProcessor(
        [ProcessingOutcome.failed, ProcessingOutcome.succeeded]
    )
    job, background_tasks = asyncio.run(_enqueue(document_id, processor))

    asyncio.run(background_tasks())
    asyncio.run(LocalDocumentJobWorker(processor).run(job.id))
    stored_job = asyncio.run(_load_jobs(document_id))[0]

    assert stored_job.status == ProcessingJobStatus.succeeded
    assert stored_job.attempt_count == 2
    assert stored_job.last_error_code is None
    assert processor.calls == [document_id, document_id]


def test_worker_exhausts_retries_without_persisting_exception_text(
    tmp_path, monkeypatch
):
    document_id = _set_up_database(tmp_path, monkeypatch)
    processor = SequenceProcessor([RuntimeError("sensitive detail"), RuntimeError()])
    job, background_tasks = asyncio.run(_enqueue(document_id, processor))

    asyncio.run(background_tasks())
    stored_job = asyncio.run(_load_jobs(document_id))[0]

    assert stored_job.status == ProcessingJobStatus.failed
    assert stored_job.attempt_count == 2
    assert stored_job.last_error_code == "processor_exception"
    assert stored_job.finished_at is not None
    assert len(processor.calls) == 2


def test_reprocessing_creates_new_job_after_terminal_job(tmp_path, monkeypatch):
    document_id = _set_up_database(tmp_path, monkeypatch)
    processor = SequenceProcessor(
        [ProcessingOutcome.succeeded, ProcessingOutcome.succeeded]
    )

    first, first_tasks = asyncio.run(_enqueue(document_id, processor))
    asyncio.run(first_tasks())
    second, second_tasks = asyncio.run(_enqueue(document_id, processor))
    asyncio.run(second_tasks())
    jobs = asyncio.run(_load_jobs(document_id))

    assert first.id != second.id
    assert [job.status for job in jobs] == [
        ProcessingJobStatus.succeeded,
        ProcessingJobStatus.succeeded,
    ]
    assert processor.calls == [document_id, document_id]


def test_job_history_api_returns_persisted_lifecycle(tmp_path, monkeypatch):
    document_id = _set_up_database(tmp_path, monkeypatch)
    processor = SequenceProcessor([ProcessingOutcome.failed])
    _, background_tasks = asyncio.run(
        _enqueue(document_id, processor, max_attempts=1)
    )
    asyncio.run(background_tasks())

    from backend.app.main import app

    response = TestClient(app).get(f"/api/v1/documents/{document_id}/jobs")

    assert response.status_code == 200
    assert response.json()[0]["status"] == "failed"
    assert response.json()[0]["attempt_count"] == 1
    assert response.json()[0]["last_error_code"] == "failed"
    missing = TestClient(app).post("/api/v1/documents/missing/process")
    assert missing.status_code == 404
    assert missing.json()["detail"] == "document_not_found"
