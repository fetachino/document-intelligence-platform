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
- Object keys are generated from internal document IDs and sanitized filenames; callers cannot
  submit arbitrary keys. New database rows do not contain machine-specific paths.

Object storage
- S3-compatible credentials are read only from environment/provider configuration and are not
  written to database rows or logs.
- The application performs private object operations only and does not set public bucket or object
  ACLs. Bucket policy and transport security remain deployment-operator trust boundaries.
- Provider failures are surfaced through stable storage error codes without provider exception
  details. Network calls use bounded SDK timeouts and retries.
- Signed URLs are not currently required or exposed.

Logging
- Include request IDs in logs.
- Avoid logging full document contents or PII. Log only document IDs, sizes, and high-level statuses.

Background jobs
- Job failures persist stable error codes, not exception text or document content.
- Active jobs are claimed by ID and do not grant workers arbitrary SQL, filesystem, shell,
  or tool access beyond the existing document processor dependencies.
- The RQ producer submits only job IDs to one fixed module entrypoint. User input cannot select
  task names or functions, and raw documents and storage credentials are never queue payloads.
- Broker URLs and credentials come from environment configuration. Transport failures collapse
  to a stable error without logging raw broker exceptions.

Grounded answering
- Answer providers receive retrieved text only; they are not given database sessions,
  filesystem access, shell access, SQL execution, or arbitrary tools.
- Citation provenance is assembled from stored retrieval results rather than provider output.

Network and Timeouts
- All external network calls must have sensible timeouts and retries.
- Fail gracefully and surface clear errors to users without leaking sensitive data.

Access Control
- Local passwords are stored as Argon2 hashes; plaintext passwords and access tokens must never
  be logged. Signing keys and optional bootstrap credentials are environment-only.
- Access tokens have a bounded lifetime and identify a user; current tenant, active state, and
  role are loaded from the database on each request. Login failures use one generic response.
- Tenant ownership is enforced by backend queries for documents, derived resources, search, and
  Q&A. Frontend role controls are usability hints, not a security boundary.
- Browser token storage is trusted against script injection in this local implementation. A
  hardened deployment should apply a strict content-security policy and may replace the local
  token adapter with an external identity provider and protected cookie flow.
- Background workers are trusted internal processes. They receive durable job IDs without user
  tokens and preserve tenant ownership by processing the referenced document in place.

Kubernetes scaffolding
- Checked-in manifests reference Kubernetes Secrets and do not contain deployable credentials.
  `secret.example.yaml` is a template; the populated `secret.yaml` path is ignored by Git.
- Workloads disable privilege escalation, drop Linux capabilities, use non-root identities, and
  define bounded resource requests and limits. API and worker temporary files use ephemeral
  volumes and durable document storage remains external.
- Only ClusterIP Services are defined. Network policy, ingress, TLS, image registry controls,
  external secret management, and cluster-level policy remain deployment-operator boundaries.

Testing
- Mock external providers in tests.
- Include failure-case tests to ensure safe behavior on provider errors.
- Unit tests run against SQLite+aiosqlite and the full integration flow uses Postgres+asyncpg via Docker Compose; Alembic is used for schema migrations in integration tests.
