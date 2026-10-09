# Editor and text data contract

Do not change Text Normalization, Clipboard, Paste, Save or Vocabulary TSV
behavior without a direct instruction from the user. These rules are release
requirements, including for future AI-assisted changes.

- Novel normalization removes a line only when `line == ""`. Space-only,
  Tab-only and NBSP-only lines are content. Never use `strip()` or `rstrip()`
  to decide which lines to remove or to alter retained content.
- Never join two content lines, reorder lines, modify characters, or add spaces
  or tabs. Preserve supplied paste boundary separators beside existing text.
- User instruction, 2026-10-09 / v3.6.9: every TXT/MD/Markdown opened in an
  Editor uses `normalize_editor_text()` regardless of name or folder, including
  FDR.txt, FDRContext.md and FDRGlossary.txt. Apply on Open/Reload, Paste, Copy,
  Save/AutoSave and Recovery Restore. This explicit instruction supersedes the
  earlier Editor exemptions for Context sections, prompts/styles and vocabulary
  TXT blank lines. All characters, TSV tabs and empty columns remain protected.
  Files not opened in an Editor must not be scanned or rewritten by this rule.
- `normalize_novel_text()` is the single line rule. Source, translated,
  reviewed, polished, identifiable chapter TXT/Markdown, TXT Export, drafts,
  workflow Assembly and Preview use it through the data-type dispatcher.
- Outside the Editor, Prompt, Style, JSON, CSV, configuration and unidentified
  structured files retain their formatting. Workflow assembly still uses the
  data-type dispatcher; structured Context normalizes only explicitly named
  novel sections (`Novel Text`, `Source`, `Translation`, `Reviewed`, `Polished`,
  `เนื้อหานิยาย`, `ต้นฉบับ`, `คำแปล`, `เกลาสำนวน`). Fenced data and other
  sections retain meaningful spacing.
- Vocabulary/Glossary/Characters/TSV, including TXT files and detected TSV
  content, preserve all tabs and empty columns. Never guess missing tabs or
  trim fields. A nonmodal status reports rows with a tab count other than 3.
- Prefer clipboard plain text over HTML. Compare incoming data with the
  editor, native outgoing clipboard, saved file and reopened file. Missing
  source tabs cannot be reconstructed safely; do not invent them.
- Open/Reload normalize the display and mark it unsaved without writing.
  Opening, changing tabs/pages/novels or closing an untouched normalized view
  must not cause autosave. A user edit or explicit save permits saving.
- Save/AutoSave normalize visibly using undoable separator deletions before
  persisting; retain undo history/cursor/selection, BOM and the detected original
  line ending (CRLF/LF/CR/Qt Unicode separators). Untouched structured files keep
  original bytes. Edited mixed-ending files use the most frequent original
  separator; the pure novel normalizer keeps retained individual separators.
- Preserve strict UTF-8 reads, SHA-256 conflict checks before/after staging,
  recovery snapshots, export rollback and Verified/Context accounting.
- Only one novel workspace may remain open. Save and capture per-novel file
  tabs/cursor/draft/workflow state before disposing the previous workspace;
  preserve every library profile. Failed saves block switching. Old sessions
  restore only the last active novel; file tabs within that novel remain multiple.
- Display the active profile's cover at 44 x 58 logical pixels beside its title
  and progress, with a placeholder for missing/invalid covers. Do not change
  text normalization, line height or font weight as part of cover display.
- Run the full regression suite and native Windows clipboard tests before
  release. Build/test upgrading from the previous installer, verify the published
  download through the application updater's origin, size and SHA-256 checks,
  and verify existing data and the installed runtime version.
