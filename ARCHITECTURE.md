Architecture Overview
=====================

Goals
- Process business documents into structured, searchable artifacts
- Keep a clear separation between ingestion, OCR, extraction, retrieval and UI
- Allow later replacement of local worker with distributed workers

High level components
- Frontend (React + TypeScript): upload UI, library, preview, review workflow, semantic search, citation-grounded chat
- Backend (FastAPI): API, DB models, document ingestion, processing orchestration, secure storage
- Storage: local file storage adapter for dev; S3-compatible adapter planned for production
- Database: PostgreSQL with pgvector for embeddings and fast similarity search
- Worker(s): background workers for OCR, extraction, chunking, embeddings
- AI Providers: OpenAI for embeddings and grounded Q&A (abstracted behind provider interfaces)

Data flow
1. User uploads a document via the frontend
2. Backend validates and stores file metadata and the blob in secure storage
3. Worker picks up the document, extracts text (native or OCR), and stores per-page text
4. Extractors and classifiers run to produce structured fields and classifications with confidence scores
5. Text is chunked, embeddings are generated and stored in pgvector
6. RAG-style retrieval + citation-grounded generation for Q&A

Notes
- All components use environment-based configuration
- Secrets must be injected via environment variables or secret stores
- Document text is never logged; logs contain request IDs and document IDs only
- The worker and AI provider interactions are abstracted for testability and mocking

Database strategy
- Development and unit tests use SQLite + aiosqlite for fast, isolated runs.
- Production uses PostgreSQL with pgvector and the asyncpg driver.
- Schema changes are managed with Alembic migrations located in alembic/; do not rely on SQLModel.metadata.create_all() in production.

Storage
- Local file storage adapter is used for Milestone 1. Files are written off the event loop and filenames are sanitized. S3-compatible adapters will be added in a later milestone.
