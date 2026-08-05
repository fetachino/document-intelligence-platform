Roadmap
=======

Milestone 1 (this run) - In progress (files created; tests not executed in-run due to environment limitations)

Verified actions performed locally:
- Created configuration and environment example (.env.example)
- Added database connection abstraction (sqlite default) and models for document metadata
- Implemented health endpoint
- Implemented secure file storage abstraction and upload validation
- Implemented document upload and listing endpoints (FastAPI)
- Backend updated to use async SQLModel/SQLAlchemy engine configured for asyncpg (ready for PostgreSQL + pgvector)
- Added Alembic migrations and a verification script to run the same checks as CI (scripts/verify.ps1)

- Added basic React upload UI and frontend skeleton
- Added Docker Compose with PostgreSQL + pgvector service
- Added GitHub Actions CI workflow file

Notes: To run the test suite and linters in this environment, a network-enabled install of Python packages is required; the runtime denied interactive package installation. See "Commands to run locally" below.
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

Milestone 2 (planned)
- OCR pipeline and per-page text storage
- Document classification service and UI review flow
- Structured field extractors for invoices, resumes, contracts
- Human review & correction workflow + audit trail
- Chunking + embeddings storage in pgvector
- Semantic search API and UI
- Grounded Q&A pipeline with citation linking
- Evaluation dataset and metrics reporting

Milestone 3 (planned)
- Scalable worker architecture (Celery/RQ/Kubernetes)
- S3-compatible storage adapter and signed URL support
- RBAC and multi-tenant features
- Deployment manifests for Kubernetes and cloud providers
- End-to-end performance and security tests
