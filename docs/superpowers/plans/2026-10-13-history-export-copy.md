# Palantir 3.12 Implementation Record

Goal: implement the user's approved Export, COPY STEP, compact history, permanent numbering and immediate recycle-only deletion requirements in the existing repository.

Architecture: reconcile export status from hashes of actual content; prepare immutable attachments after checking selected editor edits; extend the existing PolishHistory service and manifest rather than introduce another backup system. Keep Qt access on the GUI thread and serialize history filesystem operations.

Constraints: preserve user files, BOM/CRLF, existing export ordering, historical Context, installer identity and application data namespace. No permanent-delete fallback. Use a MINOR release after checking pyproject, tags and published releases.

- [x] Inspect clean main checkout, remote and releases; fast-forward from local 3.6.7 to published 3.11.1.
- [x] Reproduce persisted pending, normalized editor, live clipboard, missing numbering and missing direct deletion in regression tests.
- [x] Implement in workspace_window/editor, clipboard_bundle, polish_history/page and recycle_bin; test targeted regressions including native Windows recycling and both themes.
- [x] Run complete pytest suite (478 passed, 1 symlink privilege skip), native clipboard/smoke/DPI verification and packaged Recycle Bin probe.
- [ ] Review staged changes for secrets/data; commit 3.12.0 with [release] and push main.
- [ ] Verify Actions tests/build, v3.12.0 tag, Release installer, in-app update discovery and upgrade over v3.11.1.
