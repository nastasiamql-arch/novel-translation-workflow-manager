# Vocabulary Implementation Plan

**Goal:** Deliver the approved per-novel Extract → Polish → Validate → Backup → Update panel.

**Architecture:** Separate model persistence, prompt/transaction service, provider/credential adapters and Qt panel. Preserve existing translation actions and updater.

**Tech Stack:** Python 3.10+, PySide6, urllib, Windows DPAPI, pytest, PyInstaller.

**Spec:** ../specs/2026-10-01-vocabulary-design.md

## Global Constraints

- Never write VOCAB from extraction; validate polished full rows first.
- Never rewrite a prompt original during deterministic JSON recovery.
- Store no plaintext API key in profiles/settings/logs.
- Keep existing translation and self-updater.

## Tasks

- [x] Add failing transaction and migration tests in tests/test_vocabulary.py; run them.
- [x] Add VocabularySettings and schema v2 migration in models.py/storage.py.
- [x] Implement vocabulary.py readers, NEW/UPDATE validation and backup/atomic transaction; run core tests.
- [x] Add providers.py HTTPS abstraction and credentials.py DPAPI storage with tests.
- [x] Add vocabulary_panel.py workers/settings and integrate workspace_window.py; test independent profiles and shutdown.
- [x] Bump pyproject.toml, document behavior and release steps in README/CHANGELOG.
- [ ] Run complete pytest suite, UI smoke, frozen build and runtime check; review diff and prepare draft PR.
