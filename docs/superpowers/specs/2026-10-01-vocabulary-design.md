# Vocabulary pipeline design

The user's approved design adds a compact right panel to each NovelProfile with independent persistent source, VOCAB, extract prompt, polish prompt, provider and model settings. One button reads snapshots, calls Extract then Polish, validates deterministically, backs up original bytes, and atomically replaces VOCAB. Extraction never writes VOCAB. Translation and updater remain available.

Prompts support UTF-8 TXT/MD/JSON and DOCX body paragraphs/tables. The referenced conversation exposes no attachments; no uploaded prompt content is assumed. Selected user prompts are passed verbatim as instructions, with a machine-readable output contract appended. JSON repair removes trailing commas outside strings in a temporary copy only; no semantic guessing.

VOCAB supports headered UTF-8 TSV (first column identity, all columns preserved) and JSON arrays of string-valued objects (first field identity). NEW/UPDATE are full rows keyed by exact identity. Reject duplicates, empty identities/translations, unknown fields, malformed tables, unknown updates and existing NEW. Preserve untouched rows, encoding BOM and TSV newline style. Check original bytes before replacement, use an exclusive cooperating-writer lock, keep byte-exact backup and clean temporary files on failure. Cancellation before commit leaves original untouched; commit is indivisible.

Providers implement a common complete(model, prompt, key) interface. OpenAI-compatible and Anthropic adapters use HTTPS, bounded requests and sanitized errors. Per-profile keys are encrypted with Windows DPAPI; no plaintext fallback. Background Qt workers report phases; closing waits for cancellation without destroying a running thread.

Tests cover persisted migration, prompt readers, strict validation, backup/replace failure, concurrent edit, cancellation, provider errors, secret persistence and UI wiring. Version 1.13.0 follows existing installer naming and CI release process.
