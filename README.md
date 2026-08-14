Document Intelligence Platform (Milestone 2)

This repository implements Milestone 1 plus local OCR/per-page text storage and a
versioned local document classifier with API-based correction history. Deterministic
structured extraction is available for invoice, resume, and contract documents with
page provenance. An API-based field review workflow preserves automatic values and
append-only correction history. Page-bounded chunks, deterministic local development
embeddings, and pgvector cosine search are available through the retrieval API. Answer
generation uses a deterministic local extractive provider that either returns cited
source sentences or an insufficient-evidence response. A checked-in synthetic evaluation
dataset exercises grounding and retrieval behavior without claiming production quality.

Grounded Q&A API
- `POST /api/v1/qa` accepts a question, optional document IDs, and a retrieval limit.
- Answers include stored chunk citations and ranked retrieval metadata.
- The answering provider receives retrieved text only and has no database or tool access.

Local deterministic evaluation
- The included synthetic dataset contains five development cases for answerability,
  refusal, multiple citations, document scoping, and retrieval relevance.
- Latest verified results on this included dataset are 5/5 for answer status, expected
  answer content, citation accuracy, citation grounding, and retrieval relevance.
- These are deterministic fixture results only, not production benchmarks or claims about
  performance on real-world documents.

OCR runtime
- PDFs use native text when available and local Tesseract OCR for image-only pages.
- PNG and JPEG uploads use local Tesseract OCR.
- DOCX uploads are stored as one native-text page because DOCX has no stable page model.
- The backend Docker image includes Tesseract. Direct host execution requires the
  `tesseract` executable to be installed and available on `PATH`.

Poetry dependency management
- pyproject.toml is the single source of truth.
- To generate a lock file locally and pin dependencies, run:
  poetry lock
  git add poetry.lock
  git commit -m "chore: lock dependencies"

Running verification
- Use the provided verification script to run the same checks as CI:
  .\scripts\verify.ps1

If you prefer to run steps manually, follow the commands in scripts/verify.ps1.
