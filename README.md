Document Intelligence Platform (Milestone 1)

This repository implements Milestone 1: document upload, storage, metadata, and basic listing.

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
