# Changelog

## 1.13.0

- Add a compact, collapsible right-side vocabulary panel per novel. Remember source, VOCAB, extract/polish prompt files, provider, model and panel size independently.
- Run Extract → Polish → deterministic validation → byte-exact backup → atomic VOCAB replacement in a background thread; cancel before commit. Extraction never writes VOCAB.
- Read TXT/MD/JSON and DOCX prompts. Repair only JSON trailing commas outside strings in temporary copies; never rewrite prompt originals.
- Support headered UTF-8 TSV and JSON row arrays, full-row NEW/UPDATE changes, strict identities/columns, concurrent-change detection and cooperating-writer lock.
- Add HTTPS OpenAI-compatible and Anthropic provider adapters. Encrypt per-profile keys with current-user Windows DPAPI; redact provider errors and reject redirects.
- Migrate profile schema to v2 without modifying translation workflows. Support TSV editing; guard stale editor autosaves during vocabulary runs and reload afterwards.
- Keep installer AppId, self-updater and versioned release asset naming unchanged.

Uploaded prompts were not available in the referenced conversation's attachment list. This release uses the selected local prompts; it does not claim to embed or reproduce unavailable uploaded instructions.
