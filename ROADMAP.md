Roadmap
=======

Milestone 1 - Complete and verified

- Configuration and environment examples
- Database connection and models for document metadata and processing status
- Health endpoints
- Secure file storage abstraction
- Document upload endpoint with validation and storage
- Document listing endpoint
- Basic React upload and document library screens
- Tests covering upload validation and listing
- Docker Compose with PostgreSQL + pgvector service
- CI: GitHub Actions for linting, type checks, and tests

Milestone 2 - Complete and verified
- OCR pipeline and per-page text storage (implemented in the first slice)
- Document classification service and API review flow (implemented)
- Structured field extractors for invoices, resumes, contracts (implemented)
- Structured field correction workflow (implemented as an API slice)
- Chunking + local embeddings storage in pgvector (implemented)
- Semantic search API (implemented)
- Grounded Q&A API with citation linking (implemented)
- Deterministic local evaluation dataset and computed metrics (implemented)

Milestone 3 - Complete and verified locally
- Document library, processing lifecycle, and reprocessing frontend foundation (implemented)
- Classification review frontend workflow (implemented)
- Structured-field correction and review-history frontend workflow (implemented)
- Semantic-search frontend workflow (implemented)
- Grounded Q&A frontend workflow (implemented)
- Observable worker/job architecture with replaceable dispatcher (local slice implemented)
- Redis/RQ transport and standalone worker process (implemented and exercised through local Compose)
- Kubernetes deployment scaffolding for API, frontend, worker, and migrations (implemented;
  production-cluster validation remains planned)
- S3-compatible private storage adapter (implemented)
- Local authentication, tenant isolation, and admin/reviewer/viewer RBAC (implemented)
- Dependency/security audit and end-to-end local release verification (implemented)

Future work
- Production-cluster and cloud-provider deployment validation
- Managed-service integration, load testing, and measured performance benchmarking
- External identity-provider integration and browser-token hardening
