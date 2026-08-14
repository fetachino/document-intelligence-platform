Architecture Overview
=====================

Goals
- Process business documents into structured, searchable artifacts
- Keep a clear separation between ingestion, OCR, extraction, retrieval and UI
- Allow later replacement of local worker with distributed workers

High level components
- Frontend (React + TypeScript): upload UI and document library; review, search, and
  citation-grounded Q&A interfaces are planned
- Backend (FastAPI): API, DB models, document ingestion, processing orchestration, secure storage
- Storage: local file storage adapter for dev; S3-compatible adapter planned for production
- Database: PostgreSQL with pgvector for stored embeddings and cosine retrieval
- Worker: local FastAPI background tasks; distributed workers are planned
- Providers: replaceable local OCR, classification, extraction, embedding, and answer
  implementations; external providers are planned

Data flow
1. User uploads a document via the frontend
2. Backend validates and stores file metadata and the blob in secure storage
3. Worker picks up the document, extracts text (native or OCR), and stores per-page text
4. Deterministic classifiers and extractors produce reviewable types and structured fields
5. Text is chunked, embeddings are generated and stored in pgvector
6. Grounded Q&A selects answers from ranked source chunks and binds stored provenance

Notes
- All components use environment-based configuration
- Secrets must be injected via environment variables or secret stores
- Document text is never logged; logs contain request IDs and document IDs only
- The worker and AI provider interactions are abstracted for testability and mocking

Database strategy
- Development and unit tests use SQLite + aiosqlite for fast, isolated runs.
- PostgreSQL integration and the containerized runtime use pgvector with asyncpg.
- Schema changes are managed with Alembic migrations located in alembic/; do not rely on SQLModel.metadata.create_all() in production.

Storage
- Local file storage adapter is used for Milestone 1. Files are written off the event loop and filenames are sanitized. S3-compatible adapters will be added in a later milestone.

Current OCR slice
- Successful uploads enqueue document processing through a replaceable dispatcher.
- The initial dispatcher uses FastAPI background tasks and an idempotent local processor.
- Blocking PDF, image, DOCX, and Tesseract work runs off the event loop.
- Extracted text is stored in `document_page` by document ID and one-based page number.
- Native PDF text is preferred; image-only PDF pages and image uploads use Tesseract.
- Processing updates document status without logging extracted text.

Current classification slice
- A replaceable classifier consumes stored page text after OCR completes.
- The initial `local_keyword_v1` implementation classifies invoice, resume, contract,
  other, and unknown without presenting its keyword score as model confidence.
- `document_classification` stores the latest prediction and effective reviewed type.
- Human corrections remain authoritative during reprocessing and append an immutable
  `document_classification_review` record for later audit workflows.

Current structured extraction slice
- A replaceable extractor applies the schema selected by the effective classification.
- `local_regex_v1` extracts conservative invoice, resume, and contract fields from
  stored page text; other and unknown documents produce no fields.
- Each value stores its source page, deterministic method, and extractor version.
- Every run clears prior values before replacement, preventing stale fields after
  reprocessing, classification correction, or extraction failure.

Current structured field review slice
- Corrections are append-only records keyed to a document, field name, and value index.
- Each review records the automatic value seen, previous effective value, corrected
  value, local reviewer identifier, and timestamp without changing extraction provenance.
- Extraction responses expose automatic and effective values separately.
- Reprocessing preserves corrections for fields that still exist. Review history marks
  older corrections as superseded and missing current fields as orphaned.

Current embeddings and retrieval slice
- Page text is split into page-bounded chunks of up to 120 words with 20-word overlap.
- A replaceable provider initially produces deterministic 128-dimensional normalized
  token-hash vectors for local development; it is not presented as a learned model.
- `document_chunk` stores source text, page and chunk provenance, provider version, and
  pgvector embeddings with an HNSW cosine index.
- Successful indexing atomically replaces a document's prior chunks. Empty pages produce
  no embeddings, and successful empty reprocessing removes stale chunks.
- Semantic search returns ranked source chunks and genuine pgvector cosine distance only;
  retrieval remains separate from answer generation.

Current grounded Q&A and evaluation slice
- The answer generator receives only the question and retrieved text, with no database,
  filesystem, shell, SQL, or arbitrary tool access.
- `local_extractive_v1` selects source sentences deterministically and refuses when the
  selected evidence does not cover the question's content terms.
- The orchestration layer validates selected result indexes and builds citations from
  stored chunk provenance, so the provider cannot supply document or page identifiers.
- Responses include citations and the ranked retrieval set with pgvector distances.
- The checked-in synthetic evaluation dataset measures answer status, expected content,
  citations, provenance grounding, and retrieval relevance for local development only.
