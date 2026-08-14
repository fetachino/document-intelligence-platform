from typing import Protocol

from fastapi import BackgroundTasks

from .processing import process_document


class DocumentJobDispatcher(Protocol):
    """Dispatch document processing without coupling routes to a worker backend."""

    def enqueue(self, document_id: str) -> None: ...


class LocalDocumentJobDispatcher:
    """Run document processing through FastAPI's local background task queue."""

    def __init__(self, background_tasks: BackgroundTasks) -> None:
        self._background_tasks = background_tasks

    def enqueue(self, document_id: str) -> None:
        self._background_tasks.add_task(process_document, document_id)


def get_document_job_dispatcher(
    background_tasks: BackgroundTasks,
) -> DocumentJobDispatcher:
    return LocalDocumentJobDispatcher(background_tasks)
