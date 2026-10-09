# Editor and text data contract

Do not change Text Normalization, Clipboard, Paste, Save or Vocabulary TSV
behavior without a direct instruction from the user. These rules are release
requirements, including for future AI-assisted changes.

- Novel normalization removes a line only when `line == ""`. Space-only,
  Tab-only and NBSP-only lines are content. Never use `strip()` or `rstrip()`
  to decide which lines to remove or to alter retained content.
- Never join two content lines, reorder lines, modify characters, or add spaces
  or tabs. Preserve supplied paste boundary separators beside existing text.
- `normalize_novel_text()` is the single novel rule. Source, translated,
  reviewed, polished, identifiable chapter TXT/Markdown, TXT Export, drafts,
  workflow Assembly and Preview use it through the data-type dispatcher.
- Prompt, Style, JSON, CSV, configuration and unidentified structured files
  retain their formatting. Structured Context normalizes only explicitly named
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
- Run the full regression suite and native Windows clipboard tests before
  release. Build/test upgrading from the previous installer, verify the published
  download through the application updater's origin, size and SHA-256 checks,
  and verify existing data and the installed runtime version.
