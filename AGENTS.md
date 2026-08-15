Agents
======

This repository uses background workers for document processing. The current local worker
persists observable jobs and runs them through FastAPI background tasks. Its dispatcher
and worker protocols support local delivery or Redis/RQ delivery to a standalone process.

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
- Workers must claim queued jobs before processing and use bounded retries.
- Workers must retrieve source bytes through the configured storage provider rather than
  assuming an API-local filesystem path.
- Sensitive document text must never be logged.

Notes for Milestone 1
- Local worker implementation was deferred until Milestone 2.
- The project now uses Alembic for schema migrations; agents must assume the database schema is managed via migrations rather than SQLModel.create_all in production.
- Agents must obtain DB sessions via the FastAPI dependency get_session to ensure transactional safety and consistent async session lifecycle.

Completed Milestone 2 implementation
- Document processing is dispatched through a replaceable abstraction.
- The initial implementation uses FastAPI background tasks and a local, idempotent processor.
- OCR/text extraction, per-page persistence, local classification, and deterministic
  structured extraction are active.
- Human classification corrections must remain authoritative during automatic reprocessing.
- Structured field corrections remain authoritative while their automatic field exists;
  missing fields retain explicitly orphaned audit history.
- Successful processing indexes non-empty page text with the replaceable local embedding
  provider and atomically replaces stale chunks.
- Grounded Q&A uses retrieved chunks only and binds citations from stored provenance.
- External AI providers and later deployment infrastructure remain deferred.

Current Milestone 3 worker slice
- Each processing request creates a durable job with queued, running, succeeded, or failed state.
- Only one queued or running job may exist for a document; terminal jobs remain as history.
- The local worker atomically claims jobs and makes at most two processing attempts.
- Persisted errors use stable codes rather than exception text or document content.
- RQ can deliver stable job IDs through Redis to a standalone worker process; PostgreSQL
  claiming and bounded attempts remain authoritative.
- Workers are trusted internal processes and do not accept end-user tokens. Tenant ownership
  remains attached to the document loaded from each durable job ID.
- Kubernetes worker pods use the RQ transport and external PostgreSQL, Redis, and S3-compatible
  services. Pod-local storage is temporary only; queue messages continue to contain job IDs.
