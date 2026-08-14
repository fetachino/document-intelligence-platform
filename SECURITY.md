Security Guidelines
===================

Secrets
- Store provider keys and database credentials in environment variables or secret managers.
- Do NOT commit secrets to the repository.

Uploads
- Validate file types and maximum file sizes.
- Sanitize filenames and prevent path traversal (use os.path.basename and additional checks).
- Store uploaded files outside the web root and serve via secure, signed URLs when necessary.
- File writes are performed off the event loop (asyncio.to_thread) to avoid blocking the ASGI event loop.
- Partially written files are deleted if database persistence fails.

Logging
- Include request IDs in logs.
- Avoid logging full document contents or PII. Log only document IDs, sizes, and high-level statuses.

Background jobs
- Job failures persist stable error codes, not exception text or document content.
- Active jobs are claimed by ID and do not grant workers arbitrary SQL, filesystem, shell,
  or tool access beyond the existing document processor dependencies.

Grounded answering
- Answer providers receive retrieved text only; they are not given database sessions,
  filesystem access, shell access, SQL execution, or arbitrary tools.
- Citation provenance is assembled from stored retrieval results rather than provider output.

Network and Timeouts
- All external network calls must have sensible timeouts and retries.
- Fail gracefully and surface clear errors to users without leaking sensitive data.

Access Control
- Authentication and authorization are not implemented and remain planned for a later milestone.

Testing
- Mock external providers in tests.
- Include failure-case tests to ensure safe behavior on provider errors.
- Unit tests run against SQLite+aiosqlite and the full integration flow uses Postgres+asyncpg via Docker Compose; Alembic is used for schema migrations in integration tests.
