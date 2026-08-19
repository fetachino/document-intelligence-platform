# Document Intelligence Platform

[![CI](https://github.com/fetachino/document-intelligence-platform/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/fetachino/document-intelligence-platform/actions/workflows/ci.yml) [![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org/) [![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/) [![React](https://img.shields.io/badge/React-20232A?logo=react&logoColor=61DAFB)](https://react.dev/) [![PostgreSQL](https://img.shields.io/badge/PostgreSQL-4169E1?logo=postgresql&logoColor=white)](https://www.postgresql.org/) [![Docker](https://img.shields.io/badge/Docker-2496ED?logo=docker&logoColor=white)](https://www.docker.com/)

A full-stack document processing workspace that turns uploaded PDFs, images, and DOCX files into searchable, reviewable data. The platform runs OCR, classification, structured extraction, vector indexing, and citation-grounded Q&A through durable background jobs, with tenant isolation and role-based access enforced by the backend.

This repository is a portfolio project focused on understandable service boundaries, deterministic local providers, auditability, and end-to-end verification. Kubernetes deployment scaffolding is included for the current API, frontend, and worker; production infrastructure, ingress, TLS, managed services, and a live deployment are intentionally not included.

**Quick Links:** [Application Demo](#application-demo) · [Architecture](#architecture) · [Running Locally](#running-locally) · [Security](SECURITY.md)

## What this proves

- Full-stack delivery across React, FastAPI, PostgreSQL, workers, and Docker
- Document-processing workflows with OCR, deterministic extraction, review,
  and page-level provenance
- Retrieval and grounded Q&A with explicit insufficient-evidence behavior
- Secure multi-tenant application boundaries with authentication, RBAC, audit
  history, and repeatable CI verification

**Local demo:** follow [Running Locally](#running-locally), then open the
document workspace at <http://localhost:5173> and API docs at
<http://localhost:8000/docs> when the stack is running.

## Why I Built This

This project demonstrates production-oriented full-stack engineering across document processing, OCR, vector retrieval, grounded Q&A, human review, authentication and tenant isolation, background workers, storage abstractions, CI, and containerized deployment scaffolding.

## Application Demo

The screenshots below follow the primary workflow from document processing and review through retrieval and grounded question answering.

### Document Processing & Review

Shows successful processing, automatic/effective contract classification, structured extraction status, and durable job history.

![Document Processing & Review](docs/screenshots/document-review.png)

### Semantic Search

Shows selected-document semantic retrieval with ranked source chunks, page/chunk provenance, embedding model metadata, and cosine distance.

![Semantic Search](docs/screenshots/semantic-search.png)

### Grounded Q&A

Shows a grounded answer retrieved from the selected document with citation provenance and supporting document evidence.

![Grounded Q&A](docs/screenshots/grounded-qa.png)

### Demo Video

A short walkthrough demonstrating document upload and processing, document classification/review, semantic search, and grounded Q&A with source citations.

[▶ Watch the full demo](docs/demo/document-intelligence-platform-demo.mp4)

## Core Capabilities

| Area | Implemented behavior |
| --- | --- |
| Ingestion and storage | Validated document upload with local filesystem or private S3-compatible object storage |
| OCR and text | Native PDF/DOCX extraction, Tesseract OCR fallback, and per-page text persistence |
| Classification | Replaceable classifier with `invoice`, `resume`, `contract`, `other`, and `unknown` types |
| Structured extraction | Deterministic invoice, resume, and contract field extraction with page provenance |
| Human review | Classification correction plus structured-field corrections with append-only audit history |
| Retrieval | Page-bounded chunking, deterministic local embeddings, pgvector storage, and cosine search |
| Grounded Q&A | Retrieval-separated answer generation, stored-provenance citations, and explicit insufficient-evidence responses |
| Background processing | Durable queued/running/succeeded/failed jobs, atomic claiming, bounded retries, and reprocessing history |
| Worker transport | Local FastAPI background tasks by default or Redis/RQ delivery to a standalone worker |
| Frontend | React document library and workspace with job polling, review interfaces, semantic search, and grounded Q&A |
| Access control | Local authentication, tenant-scoped data access, and centralized viewer/reviewer/admin RBAC |

## Technology Stack

| Layer | Technologies |
| --- | --- |
| Backend | Python 3.12, FastAPI, SQLModel, SQLAlchemy async, Uvicorn, Pydantic |
| Frontend | React 18, TypeScript, Vite |
| Database and vector search | PostgreSQL, pgvector, asyncpg, Alembic |
| Background processing | Durable PostgreSQL job records, FastAPI `BackgroundTasks`, Redis, RQ |
| Document processing | pypdf, pypdfium2, Tesseract/pytesseract, Pillow, python-docx |
| Storage | Local filesystem provider, boto3-based S3-compatible provider |
| Authentication | Argon2 password hashing with pwdlib, signed access tokens with PyJWT |
| Testing and quality | pytest, Vitest, Testing Library, Ruff, mypy, ESLint, TypeScript checks, Alembic migration checks, coverage |
| Containers and CI | Docker, Docker Compose, GitHub Actions |

## Architecture

```mermaid
flowchart LR
    B[Browser] --> F[React frontend]
    F --> A[FastAPI API]
    A --> I[Authentication and tenant RBAC]
    A --> D[(PostgreSQL and pgvector)]
    A --> S[Local or S3-compatible storage]
    A --> J[Durable processing job]
    J --> T{Job transport}
    T -->|Local| L[FastAPI background task]
    T -->|Distributed| R[Redis and RQ]
    R --> W[Standalone worker]
    L --> P[Document processing pipeline]
    W --> P
    P --> S
    P --> O[OCR and native text extraction]
    O --> C[Classification and structured extraction]
    C --> E[Chunking and embeddings]
    E --> D
    D --> Q[Semantic search and grounded Q&A]
    Q --> A
```

PostgreSQL is authoritative for processing lifecycle and retry state. Queue transports carry durable job IDs only. Workers load the document and storage reference from the database, claim work atomically, and run the same processing pipeline whether delivery is local or through RQ.

## Document Processing Flow

1. An authenticated admin uploads a validated document.
2. The API stores the object and creates a durable queued job.
3. A local or standalone worker atomically claims the job.
4. Native text extraction runs first; image-only content falls back to Tesseract OCR.
5. Per-page text is classified and passed to the matching structured extraction schema.
6. Page text is chunked, embedded, and indexed in pgvector.
7. Semantic search retrieves tenant-scoped chunks; grounded Q&A answers only from that context.
8. Reviewers can correct classifications and extracted fields without replacing automatic provenance or prior audit entries.

Reprocessing is idempotent: automatic outputs and stale chunks are replaced transactionally, while applicable human corrections and historical job records remain auditable.

## Repository Structure

```text
backend/             FastAPI application, processing providers, worker entrypoint, tests, and evaluation data
frontend/            React/TypeScript workspace, centralized API client, and Vitest suites
alembic/             Versioned PostgreSQL schema migrations
scripts/             Repository verification and local diagnostic scripts
.github/workflows/   GitHub Actions CI workflow
docker-compose.yml   PostgreSQL/pgvector, Redis, API, worker, and frontend services
```

Project configuration and lock files remain at the repository root so Poetry and Docker can use the monorepo build context without packaging the root as a Python library.

## Running Locally

### Prerequisites

- Python 3.12
- Poetry
- Node.js and npm
- Docker Desktop with the Linux container engine running
- PowerShell for the repository verification script

The Compose workflow is the simplest way to run the complete stack because the backend image already includes Tesseract.

### 1. Configure the environment

```powershell
Copy-Item .env.example .env
```

Edit `.env` and set at minimum:

```dotenv
AUTH_TOKEN_SECRET=replace-with-a-random-value-of-at-least-32-characters
BOOTSTRAP_TENANT_NAME=Local workspace
BOOTSTRAP_TENANT_SLUG=local
BOOTSTRAP_ADMIN_EMAIL=admin@example.test
BOOTSTRAP_ADMIN_PASSWORD=replace-with-at-least-12-characters
```

Bootstrap creation is opt-in and idempotent. Credentials are read from the environment, and only the Argon2 password hash is stored.

Optional provider settings:

- Set `JOB_TRANSPORT=rq` to dispatch API-created jobs through Redis to the standalone worker. The default is `local`.
- Set `STORAGE_BACKEND=s3` and the documented `S3_*` variables to use a generic S3-compatible private bucket. The default is `local`.

### 2. Start the stack

```powershell
docker compose up --build
```

Open:

- Frontend workspace: `http://localhost:3000`
- FastAPI documentation: `http://localhost:8000/docs`
- Health endpoint: `http://localhost:8000/api/v1/health`

Sign in with the workspace slug, email, and password configured above.

### 3. Stop services

```powershell
docker compose stop
```

This stops the services without deleting the PostgreSQL or upload volumes.

## Kubernetes Scaffolding

Plain Kubernetes manifests are available in `deploy/kubernetes` for the frontend, API,
standalone RQ worker, and one-shot Alembic migration Job. They use ConfigMaps for non-secret
settings and reference an operator-created Secret for database, broker, token-signing, bootstrap,
and optional S3 credentials.

The manifests intentionally omit ingress, domains, certificates, and managed infrastructure.
PostgreSQL, Redis, and S3-compatible storage remain external dependencies, and image names must
be replaced or loaded for the target cluster. See
[`deploy/kubernetes/README.md`](deploy/kubernetes/README.md) for local validation and apply steps.
Docker Compose remains the supported local development workflow.

## Important API Endpoints

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `POST` | `/api/v1/auth/login` | Local workspace login |
| `GET` | `/api/v1/auth/me` | Current authenticated identity and role |
| `POST` | `/api/v1/documents/upload` | Upload and queue a document; admin only |
| `GET` | `/api/v1/documents/` | List documents in the current tenant |
| `GET` | `/api/v1/documents/{document_id}/pages` | Retrieve per-page extracted text |
| `GET/PATCH` | `/api/v1/documents/{document_id}/classification` | Read or correct document classification |
| `GET` | `/api/v1/documents/{document_id}/extraction` | Retrieve automatic and effective structured fields |
| `PATCH` | `/api/v1/documents/{document_id}/extraction/fields/{field_name}/{value_index}` | Correct a supported field |
| `GET` | `/api/v1/documents/{document_id}/extraction/reviews` | Retrieve append-only correction history |
| `GET` | `/api/v1/search` | Tenant-scoped semantic chunk retrieval |
| `POST` | `/api/v1/qa` | Tenant-scoped grounded Q&A with citations |
| `GET` | `/api/v1/documents/{document_id}/jobs` | Processing job history and stable errors |
| `POST` | `/api/v1/documents/{document_id}/process` | Queue idempotent reprocessing; admin only |

All document-derived endpoints enforce tenant ownership on the backend. Review actions require reviewer or admin access; upload and reprocessing require admin access.

## Security and Design Decisions

- Passwords are hashed with Argon2; plaintext passwords are never persisted.
- Access tokens are signed, bounded in lifetime, and configured with an environment-only secret.
- Each authenticated request reloads the active user, tenant, and role from PostgreSQL.
- RBAC is centralized in FastAPI dependencies. Frontend role checks improve usability but are not a security boundary.
- Document lookups, review operations, semantic search, and Q&A enforce tenant ownership server-side.
- Search filters by tenant before result limiting, and Q&A citations are assembled only from stored tenant-scoped chunk provenance.
- The answering provider receives retrieved text, not database, SQL, shell, filesystem, or arbitrary tool access.
- Storage credentials remain environment-only. Object keys are generated internally and work with local or private S3-compatible providers.
- Workers are trusted internal processes. Queue payloads contain job IDs, not document bytes, credentials, or user-selected functions.

See [SECURITY.md](SECURITY.md) for trust boundaries and [ARCHITECTURE.md](ARCHITECTURE.md) for implementation details.

## Verification and Testing

Run the repository-level verification from the project root:

```powershell
powershell -ExecutionPolicy Bypass -NoProfile -File .\scripts\verify.ps1
```

The script installs locked backend and frontend dependencies, runs Ruff, mypy, PostgreSQL/Alembic migrations, pytest, ESLint, TypeScript checks, Vitest with coverage, the frontend production build, and both repository-root Docker image builds. GitHub Actions runs the corresponding checks for pushes and pull requests targeting `main`.

Focused tools can also be run independently:

```powershell
poetry run pytest backend/tests -q --maxfail=1
poetry run ruff check .
poetry run mypy backend
$env:DATABASE_URL='postgresql+asyncpg://docuser:docpass@localhost:5432/docdb'
poetry run alembic check
npm.cmd --prefix frontend run test -- --run
```

## Local Q&A Evaluation

`backend/evaluation/qa_dataset.json` contains a five-case deterministic synthetic dataset covering answerable and unanswerable questions, citation provenance, document scoping, and retrieval relevance. Its tests validate the local pipeline only; the dataset is not a production benchmark and does not measure performance on representative real-world document collections.

## Project Status

| Milestone | Status | Scope |
| --- | --- | --- |
| Milestone 1 | Complete | Repository foundation, ingestion, database, frontend baseline, tests, containers, and CI |
| Milestone 2 | Complete | OCR, classification, extraction, review, embeddings, semantic search, grounded Q&A, and local evaluation |
| Milestone 3 | Complete | Durable/distributed workers, S3-compatible storage, document workspace, authentication/RBAC, Kubernetes scaffolding, and local release hardening |

## Current Limitations

- Embeddings use a deterministic local token-hash provider rather than a learned production embedding model.
- Answer generation uses a deterministic local extractive provider; no external production LLM is integrated.
- OCR, extraction, and evaluation are intentionally conservative and do not include production accuracy claims.
- Kubernetes manifests are static scaffolding only and have not been exercised against a production cluster.
- Dependency audits report no known Python or npm vulnerabilities. npm still reports deprecated
  development-only transitive packages from the ESLint 8 and Vitest coverage toolchains.
- Starlette's legacy TestClient compatibility layer emits an upstream `httpx2` migration warning;
  application HTTPX integrations use the supported ASGI transport API.
- Local browser authentication stores the short-lived access token in browser storage; the security documentation describes this trust boundary and future hardening options.

## Additional Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md): component boundaries and implemented processing slices
- [ROADMAP.md](ROADMAP.md): milestone status and remaining work
- [SECURITY.md](SECURITY.md): security controls and trust boundaries
- [AGENTS.md](AGENTS.md): worker responsibilities and processing invariants
