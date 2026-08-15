import asyncio
import uuid

from rq import Queue, Worker

from .job_transport import JobTransportSettings, create_redis_connection
from .jobs import DocumentJobWorker, LocalDocumentJobWorker


def execute_document_job(
    job_id: str, worker: DocumentJobWorker | None = None
) -> bool:
    """Run the fixed document task; database claiming makes redelivery a no-op."""

    if not _is_job_id(job_id):
        return False
    asyncio.run((worker or LocalDocumentJobWorker()).run(job_id))
    return True


def main() -> None:
    settings = JobTransportSettings.from_environment()
    if settings.transport != "rq":
        raise RuntimeError("standalone_worker_requires_rq_transport")
    connection = create_redis_connection(settings)
    queue = Queue(settings.queue_name, connection=connection)
    Worker([queue], connection=connection).work(with_scheduler=False)


def _is_job_id(job_id: str) -> bool:
    try:
        return str(uuid.UUID(job_id)) == job_id
    except (AttributeError, ValueError):
        return False


if __name__ == "__main__":
    main()
