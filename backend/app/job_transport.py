import asyncio
import os
import re
from dataclasses import dataclass
from collections.abc import Callable
from typing import Any, Protocol, cast

from fastapi import BackgroundTasks
from redis import Redis
from rq import Queue

RQ_DOCUMENT_TASK = "backend.app.worker.execute_document_job"
_QUEUE_NAME = re.compile(r"^[A-Za-z0-9_-]+$")


class JobTransportError(RuntimeError):
    """Represent a broker failure without retaining provider exception details."""


class DocumentJobTransport(Protocol):
    """Deliver a stable processing job ID to a known worker entrypoint."""

    async def dispatch(self, job_id: str) -> None: ...


class JobRunner(Protocol):
    async def run(self, job_id: str) -> None: ...


class RqQueue(Protocol):
    def enqueue(
        self, f: str | Callable[..., Any], *args: Any, **kwargs: Any
    ) -> Any: ...


@dataclass(frozen=True)
class JobTransportSettings:
    transport: str = "local"
    redis_url: str = "redis://localhost:6379/0"
    queue_name: str = "document-processing"
    job_timeout_seconds: int = 900

    @classmethod
    def from_environment(cls) -> "JobTransportSettings":
        transport = os.getenv("JOB_TRANSPORT", "local").strip().lower()
        if transport not in {"local", "rq"}:
            raise JobTransportError("unsupported_job_transport")

        queue_name = os.getenv("RQ_QUEUE_NAME", "document-processing").strip()
        if not _QUEUE_NAME.fullmatch(queue_name):
            raise JobTransportError("invalid_rq_queue_name")
        try:
            job_timeout_seconds = int(os.getenv("RQ_JOB_TIMEOUT_SECONDS", "900"))
        except ValueError:
            raise JobTransportError("invalid_rq_job_timeout") from None
        if not 1 <= job_timeout_seconds <= 86400:
            raise JobTransportError("invalid_rq_job_timeout")

        return cls(
            transport=transport,
            redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0").strip(),
            queue_name=queue_name,
            job_timeout_seconds=job_timeout_seconds,
        )


class LocalBackgroundTaskTransport:
    """Deliver jobs inside the API process for the default development path."""

    def __init__(
        self, background_tasks: BackgroundTasks, worker: JobRunner
    ) -> None:
        self._background_tasks = background_tasks
        self._worker = worker

    async def dispatch(self, job_id: str) -> None:
        self._background_tasks.add_task(self._worker.run, job_id)


class RqDocumentJobTransport:
    """Enqueue only job IDs to the fixed document worker task through RQ."""

    def __init__(self, queue: RqQueue, job_timeout_seconds: int = 900) -> None:
        self._queue = queue
        self._job_timeout_seconds = job_timeout_seconds

    async def dispatch(self, job_id: str) -> None:
        try:
            await asyncio.to_thread(
                self._queue.enqueue,
                RQ_DOCUMENT_TASK,
                job_id,
                job_timeout=self._job_timeout_seconds,
                result_ttl=0,
                failure_ttl=86400,
                retry=None,
            )
        except Exception:
            raise JobTransportError("job_transport_unavailable") from None


def create_redis_connection(settings: JobTransportSettings) -> Redis:
    return Redis.from_url(
        settings.redis_url,
        socket_connect_timeout=5,
        socket_timeout=5,
        retry_on_timeout=False,
    )


def create_rq_transport(settings: JobTransportSettings) -> RqDocumentJobTransport:
    connection = create_redis_connection(settings)
    queue = cast(RqQueue, Queue(settings.queue_name, connection=connection))
    return RqDocumentJobTransport(queue, settings.job_timeout_seconds)
