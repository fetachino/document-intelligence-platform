Document Intelligence Platform (Milestone 2)

This repository implements Milestone 1 plus local OCR/per-page text storage and a
versioned local document classifier with API-based correction history. Deterministic
structured extraction is available for invoice, resume, and contract documents with
page provenance. An API-based field review workflow preserves automatic values and
append-only correction history. Page-bounded chunks, deterministic local development
embeddings, and pgvector cosine search are available through the retrieval API. Answer
generation is not implemented.

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
