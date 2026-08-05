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

Network and Timeouts
- All external network calls must have sensible timeouts and retries.
- Fail gracefully and surface clear errors to users without leaking sensitive data.

Access Control
- APIs must validate authentication and authorization (not implemented in Milestone 1).

Testing
- Mock external providers in tests.
- Include failure-case tests to ensure safe behavior on provider errors.
- Unit tests run against SQLite+aiosqlite and the full integration flow uses Postgres+asyncpg via Docker Compose; Alembic is used for schema migrations in integration tests.
