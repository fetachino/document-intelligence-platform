Agents
======

This repository uses background workers for document processing. For Milestone 1 a local worker is included; in later milestones this can be replaced with Celery, RQ, or a cloud task runner.

Local worker responsibilities:
- Process newly uploaded documents
- Run OCR and text extraction
- Perform document classification and structured extraction
- Chunk text and generate embeddings
- Mark processing status and produce audit logs

Agent guidelines
- Agents should be idempotent and re-entrant.
- All network calls must have timeouts and retries.
- Agents must update document processing status in the database.
- Sensitive document text must never be logged.

Notes for Milestone 1
- Local worker implementation was deferred until Milestone 2.
- The project now uses Alembic for schema migrations; agents must assume the database schema is managed via migrations rather than SQLModel.create_all in production.
- Agents must obtain DB sessions via the FastAPI dependency get_session to ensure transactional safety and consistent async session lifecycle.

Milestone 2 implementation
- Document processing is dispatched through a replaceable abstraction.
- The initial implementation uses FastAPI background tasks and a local, idempotent processor.
- OCR/text extraction, per-page persistence, local classification, and deterministic
  structured extraction are active.
- Human classification corrections must remain authoritative during automatic reprocessing.
- Structured field corrections remain authoritative while their automatic field exists;
  missing fields retain explicitly orphaned audit history.
- Successful processing indexes non-empty page text with the replaceable local embedding
  provider and atomically replaces stale chunks.
- Later pipeline stages remain deferred.
