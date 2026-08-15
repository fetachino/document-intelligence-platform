import asyncio
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest
from fastapi import BackgroundTasks
from sqlmodel import select

from backend.app.database import get_sessionmaker, init_db
from backend.app.job_transport import (
    RQ_DOCUMENT_TASK,
    JobTransportError,
    JobTransportSettings,
    RqDocumentJobTransport,
)
from backend.app.jobs import (
    DurableDocumentJobDispatcher,
    LocalDocumentJobDispatcher,
    LocalDocumentJobWorker,
    get_document_job_dispatcher,
)
from backend.app.models import (
    Document,
    DocumentProcessingJob,
    ProcessingJobStatus,
)
from backend.app.processing import ProcessingOutcome
from backend.app.worker import execute_document_job


class FakeRqQueue:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[tuple[str, tuple[str, ...], dict[str, Any]]] = []

    def enqueue(
        self, f: str | Callable[..., Any], *args: Any, **kwargs: Any
    ) -> None:
        if self.error:
            raise self.error
        assert isinstance(f, str)
        self.calls.append((f, args, kwargs))


class SequenceProcessor:
    def __init__(self, outcomes: Sequence[ProcessingOutcome | Exception]) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[str] = []

    async def __call__(self, document_id: str) -> ProcessingOutcome:
        self.calls.append(document_id)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class RecordingWorker:
    def __init__(self) -> None:
        self.job_ids: list[str] = []

    async def run(self, job_id: str) -> None:
        self.job_ids.append(job_id)


async def _create_document_and_job(
    path: Path, *, max_attempts: int = 2
) -> tuple[str, str]:
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
        assert document.id is not None
        job = DocumentProcessingJob(
            document_id=document.id,
            max_attempts=max_attempts,
        )
        session.add(job)
        await session.commit()
        return document.id, job.id
    finally:
        await session.close()


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
        assert document.id is not None
        return document.id
    finally:
        await session.close()


async def _load_job(job_id: str) -> DocumentProcessingJob:
    session = get_sessionmaker()()
    try:
        result = await session.execute(
            select(DocumentProcessingJob).where(DocumentProcessingJob.id == job_id)
        )
        return result.scalar_one()
    finally:
        await session.close()


async def _load_document_jobs(document_id: str) -> list[DocumentProcessingJob]:
    session = get_sessionmaker()()
    try:
        result = await session.execute(
            select(DocumentProcessingJob).where(
                DocumentProcessingJob.document_id == document_id
            )
        )
        return list(result.scalars().all())
    finally:
        await session.close()


def _set_up_database(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    asyncio.run(init_db())
    source = tmp_path / "document.pdf"
    source.write_bytes(b"document bytes")
    return source


def test_local_dispatcher_remains_default(tmp_path, monkeypatch) -> None:
    _set_up_database(tmp_path, monkeypatch)
    monkeypatch.delenv("JOB_TRANSPORT", raising=False)
    session = get_sessionmaker()()
    try:
        dispatcher = get_document_job_dispatcher(BackgroundTasks(), session)
        assert type(dispatcher) is LocalDocumentJobDispatcher
    finally:
        asyncio.run(session.close())


def test_dispatcher_selects_rq_transport_from_configuration(
    tmp_path, monkeypatch
) -> None:
    _set_up_database(tmp_path, monkeypatch)
    monkeypatch.setenv("JOB_TRANSPORT", "rq")
    monkeypatch.setenv("REDIS_URL", "redis://queue:6379/0")
    session = get_sessionmaker()()
    try:
        dispatcher = get_document_job_dispatcher(BackgroundTasks(), session)
        assert type(dispatcher) is DurableDocumentJobDispatcher
    finally:
        asyncio.run(session.close())


def test_rq_transport_enqueues_only_expected_job_id() -> None:
    queue = FakeRqQueue()
    transport = RqDocumentJobTransport(queue, job_timeout_seconds=300)
    job_id = str(uuid.uuid4())

    asyncio.run(transport.dispatch(job_id))

    assert queue.calls == [
        (
            RQ_DOCUMENT_TASK,
            (job_id,),
            {
                "job_timeout": 300,
                "result_ttl": 0,
                "failure_ttl": 86400,
                "retry": None,
            },
        )
    ]


def test_distributed_dispatcher_persists_then_enqueues_job_id(
    tmp_path, monkeypatch
) -> None:
    source = _set_up_database(tmp_path, monkeypatch)
    document_id = asyncio.run(_create_document(source))
    queue = FakeRqQueue()

    async def exercise() -> DocumentProcessingJob:
        session = get_sessionmaker()()
        try:
            dispatcher = DurableDocumentJobDispatcher(
                session, RqDocumentJobTransport(queue)
            )
            return await dispatcher.enqueue(document_id)
        finally:
            await session.close()

    job = asyncio.run(exercise())

    assert job.status == ProcessingJobStatus.queued
    assert queue.calls[0][0] == RQ_DOCUMENT_TASK
    assert queue.calls[0][1] == (job.id,)
    assert asyncio.run(_load_job(job.id)).status == ProcessingJobStatus.queued


def test_standalone_worker_duplicate_delivery_is_safe(tmp_path, monkeypatch) -> None:
    source = _set_up_database(tmp_path, monkeypatch)
    document_id, job_id = asyncio.run(_create_document_and_job(source))
    processor = SequenceProcessor([ProcessingOutcome.succeeded])
    worker = LocalDocumentJobWorker(processor)

    assert execute_document_job(job_id, worker)
    assert execute_document_job(job_id, worker)

    job = asyncio.run(_load_job(job_id))
    assert job.status == ProcessingJobStatus.succeeded
    assert job.attempt_count == 1
    assert processor.calls == [document_id]


def test_standalone_worker_preserves_bounded_database_retries(
    tmp_path, monkeypatch
) -> None:
    source = _set_up_database(tmp_path, monkeypatch)
    _, job_id = asyncio.run(_create_document_and_job(source, max_attempts=2))
    processor = SequenceProcessor(
        [RuntimeError("document text must not persist"), ProcessingOutcome.failed]
    )

    assert execute_document_job(job_id, LocalDocumentJobWorker(processor))

    job = asyncio.run(_load_job(job_id))
    assert job.status == ProcessingJobStatus.failed
    assert job.attempt_count == 2
    assert job.last_error_code == ProcessingOutcome.failed.value
    assert "document text" not in (job.last_error_code or "")


def test_standalone_worker_rejects_invalid_and_ignores_missing_job_ids(
    tmp_path, monkeypatch
) -> None:
    _set_up_database(tmp_path, monkeypatch)
    worker = RecordingWorker()

    assert not execute_document_job("../../arbitrary-task", worker)
    missing_job_id = str(uuid.uuid4())
    assert execute_document_job(missing_job_id, LocalDocumentJobWorker())
    assert worker.job_ids == []


def test_rq_transport_failure_hides_broker_details() -> None:
    queue = FakeRqQueue(RuntimeError("redis://user:secret@broker/0"))
    transport = RqDocumentJobTransport(queue)

    with pytest.raises(
        JobTransportError, match="^job_transport_unavailable$"
    ) as error:
        asyncio.run(transport.dispatch(str(uuid.uuid4())))

    assert error.value.__cause__ is None
    assert "secret" not in str(error.value)


def test_transport_failure_leaves_authoritative_job_queued(
    tmp_path, monkeypatch
) -> None:
    source = _set_up_database(tmp_path, monkeypatch)
    document_id = asyncio.run(_create_document(source))
    queue = FakeRqQueue(RuntimeError("redis://user:secret@broker/0"))

    async def exercise() -> None:
        session = get_sessionmaker()()
        try:
            dispatcher = DurableDocumentJobDispatcher(
                session, RqDocumentJobTransport(queue)
            )
            with pytest.raises(
                JobTransportError, match="^job_transport_unavailable$"
            ):
                await dispatcher.enqueue(document_id)
        finally:
            await session.close()

    asyncio.run(exercise())
    jobs = asyncio.run(_load_document_jobs(document_id))
    assert len(jobs) == 1
    assert jobs[0].status == ProcessingJobStatus.queued
    assert jobs[0].attempt_count == 0


def test_transport_configuration_selection_and_validation(monkeypatch) -> None:
    monkeypatch.delenv("JOB_TRANSPORT", raising=False)
    assert JobTransportSettings.from_environment().transport == "local"

    monkeypatch.setenv("JOB_TRANSPORT", "rq")
    monkeypatch.setenv("REDIS_URL", "redis://queue:6379/2")
    monkeypatch.setenv("RQ_QUEUE_NAME", "documents")
    monkeypatch.setenv("RQ_JOB_TIMEOUT_SECONDS", "600")
    settings = JobTransportSettings.from_environment()
    assert settings == JobTransportSettings(
        transport="rq",
        redis_url="redis://queue:6379/2",
        queue_name="documents",
        job_timeout_seconds=600,
    )

    monkeypatch.setenv("JOB_TRANSPORT", "arbitrary")
    with pytest.raises(JobTransportError, match="^unsupported_job_transport$"):
        JobTransportSettings.from_environment()
