# Security Guidelines

This document describes the security controls, trust boundaries, and security-related limitations of the Document Intelligence Platform. It reflects the current implementation and distinguishes application-level protections from responsibilities that belong to a production deployment environment.

## Secrets

- Store provider keys, database credentials, signing keys, and other sensitive configuration in environment variables or an appropriate secret manager.
- Do not commit secrets, credentials, private keys, populated `.env` files, or access tokens to the repository.
- Example configuration files contain placeholders or development-only values and must not be treated as production credentials.

## Upload Security

- Validate supported file types and maximum upload sizes.
- Sanitize filenames, reject unsafe path components, and generate storage keys internally to prevent path traversal and arbitrary object access.
- Store uploaded files outside the web root.
- If direct object access is introduced later, use an authenticated delivery mechanism such as short-lived signed URLs where appropriate.
- File operations that would otherwise block the ASGI event loop are performed off the event loop using `asyncio.to_thread`.
- Partially written objects are deleted if database persistence fails.
- Object keys are generated from internal document IDs and sanitized filenames. Callers cannot submit arbitrary storage keys.
- New database rows store opaque relative object references rather than machine-specific filesystem paths.

## Object Storage

- S3-compatible credentials are read only from environment or provider configuration and are not written to database rows or application logs.
- The application performs private object operations and does not request public bucket or object ACLs.
- Bucket policy, encryption, network transport, retention policy, and infrastructure-level access controls remain deployment-operator responsibilities.
- Provider failures are converted to stable storage error codes rather than exposing raw provider exception details.
- S3-compatible network operations use bounded SDK timeouts and retries.
- Signed URLs are not currently required or exposed by the application.

## Logging and Sensitive Data

- Include request identifiers where appropriate to support troubleshooting and auditability.
- Avoid logging document contents, passwords, access tokens, credentials, or unnecessary personally identifiable information.
- Prefer document IDs, object identifiers, sizes, lifecycle states, and stable error codes when diagnostic information is required.
- Provider and broker exceptions exposed to callers are reduced to stable application-level errors rather than raw infrastructure details.

## Background Jobs

- Job failures persist stable error codes rather than exception text, credentials, or document contents.
- Durable processing state is maintained in PostgreSQL.
- Jobs transition through explicit lifecycle states and use atomic claiming to protect against duplicate delivery.
- Application-level bounded retry semantics remain authoritative.
- Active jobs are claimed by durable identifiers and do not grant workers arbitrary SQL, filesystem, shell, or tool execution capabilities beyond the existing document-processing pipeline.
- The RQ producer submits only durable job IDs to a fixed worker entrypoint.
- User input cannot select arbitrary task names, Python functions, commands, or worker entrypoints.
- Raw documents and storage credentials are never included in queue payloads.
- Broker URLs and credentials come from environment configuration.
- Transport failures are converted to stable errors without exposing raw broker exception details.

## Grounded Answering

- Answer providers receive the user question and retrieved text rather than database sessions, filesystem access, shell access, SQL execution capabilities, or arbitrary tools.
- Retrieval and answer generation remain separate operations.
- Citation provenance is assembled from stored retrieval results rather than trusted directly from generated provider output.
- Unsupported questions can return an insufficient-evidence state rather than requiring an answer.
- Citation document IDs, pages, chunks, snippets, and retrieval distances originate from stored retrieval results.
- Local evaluation results are synthetic development measurements and must not be interpreted as production security or model-quality guarantees.

## Network Boundaries and Timeouts

- External provider and broker integrations should use bounded timeouts and conservative retry behavior.
- Application-level retry semantics remain authoritative where applicable.
- Infrastructure errors should fail safely and surface stable application errors without exposing credentials, document contents, internal connection details, or unnecessary stack traces.
- Production network segmentation, firewall policy, TLS termination, egress restrictions, and private networking remain deployment responsibilities.

## Authentication, Authorization, and Tenant Isolation

- Local passwords are stored using Argon2 hashes.
- Plaintext passwords and access tokens must never be logged.
- Token-signing keys and optional bootstrap credentials are environment-only.
- Access tokens have bounded lifetimes and identify a user.
- Current tenant membership, account state, and role are loaded from PostgreSQL for authenticated requests rather than trusting client-supplied authorization information.
- Login failures use a generic response to reduce account-enumeration information.
- Backend authorization is authoritative. Frontend role controls are usability features and are not treated as a security boundary.
- Tenant ownership is enforced by backend queries for documents and derived resources.
- Semantic search applies tenant filtering before result limiting.
- Grounded Q&A operates over tenant-scoped retrieval results so citations cannot intentionally reference another tenant's documents.
- Foreign document identifiers are treated as unavailable rather than exposing cross-tenant resource details.
- Structured-field corrections are attributed to the authenticated user rather than a client-supplied reviewer identity.
- The current local browser session implementation trusts browser token storage against script injection. A hardened deployment should use an appropriate Content Security Policy and may replace the local token adapter with an external identity provider and protected cookie-based session flow.
- Background workers are trusted internal processes. They receive durable job IDs rather than user access tokens and preserve tenant ownership by processing the referenced document in place.

## Kubernetes Security

The checked-in Kubernetes configuration is deployment scaffolding and does not represent validation of a live production cluster.

- Kubernetes manifests reference Secrets rather than containing deployable credentials.
- `secret.example.yaml` contains placeholders only.
- A populated `deploy/kubernetes/secret.yaml` is ignored by Git and must not be committed.
- Non-sensitive configuration is supplied separately through ConfigMaps.
- Workloads disable privilege escalation.
- Linux capabilities are dropped where configured.
- Containers use non-root identities.
- Workloads define bounded CPU and memory requests and limits.
- Read-only root filesystems are used with explicit ephemeral writable mounts where required.
- API and worker temporary files use ephemeral volumes while durable document storage remains external.
- Only internal ClusterIP Services are defined by the current scaffolding.
- PostgreSQL, Redis, and S3-compatible object storage are treated as externally configured dependencies.
- NetworkPolicy, ingress, TLS, image-registry controls, external secret management, admission policy, infrastructure encryption, backup policy, and cluster-level security remain deployment-operator responsibilities.
- The repository does not claim that static manifest validation constitutes production-cluster security validation.

## Dependency Security

- The final local Milestone 3 hardening pass reported zero known vulnerabilities from both `pip-audit` and `npm audit`.
- Audit results are point-in-time dependency checks and are not a guarantee against future vulnerabilities or advisories.
- Dependency updates should be reviewed and tested rather than applying destructive or broad automated upgrades.
- npm may still report deprecated development-only transitive packages through the development toolchain even when the audited dependency graph contains no known vulnerabilities.
- Starlette's legacy `TestClient` layer currently emits an upstream HTTPX transition warning. Production request handling does not depend on `TestClient`, and direct asynchronous integration tests use HTTPX's supported `ASGITransport`.

## Security Testing

- Mock external providers in unit tests where real infrastructure is unnecessary.
- Include failure-case tests to verify safe behavior when storage providers, brokers, processing components, or other dependencies fail.
- Test authentication and role enforcement at the backend rather than relying solely on frontend behavior.
- Test cross-tenant access attempts to verify tenant isolation.
- Test duplicate job deliveries and processing retries to verify durable job lifecycle behavior.
- Test retrieval and grounded Q&A with tenant-scoped data.
- Unit and focused tests may use lightweight local database configuration where appropriate.
- Full integration verification uses PostgreSQL with `asyncpg` through the project's Docker-based development environment.
- Alembic is used to apply and validate database schema migrations.
- Docker, Compose, and Kubernetes configuration should be validated as part of release-oriented verification.

## Security Limitations

The repository demonstrates application-level security controls and deployment scaffolding, but it should not be interpreted as a fully operated production security environment.

A production deployment would additionally require infrastructure-specific controls such as:

- TLS and certificate management
- Network policies and segmentation
- External secret management
- Production identity-provider integration where appropriate
- Secure cookie/session configuration where applicable
- Content Security Policy and other browser hardening
- Image registry and supply-chain controls
- Infrastructure monitoring and alerting
- Backup and disaster-recovery procedures
- Centralized audit logging and retention policies
- Cloud/IAM policy
- Rate limiting and abuse protection
- Regular dependency and container-image vulnerability scanning
- Production penetration and security testing

These controls depend on the environment in which the application is deployed and are intentionally not represented as completed merely because Kubernetes or Docker configuration exists in the repository.

## Reporting Security Issues

If you discover a security issue, avoid opening a public issue containing sensitive exploit details, credentials, private data, or information that could unnecessarily expose users or infrastructure.

Report the issue privately to the repository owner so it can be investigated before public disclosure.
