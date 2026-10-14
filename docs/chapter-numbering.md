# Manual-first Smart Chapter Numbering

## Scope
- Work on the active Chinese original TXT/MD file (e.g. FATE.txt), not Translator/Context/Downloader/Export.
- Scan recognized standalone chapter headings: 第559章, 第五百五十九章, Chapter 559, บทที่ 559, ตอนที่ 559.
- Display line numbers and detect duplicate, decreasing and jumping chapter labels; these are warnings, NOT proof that chapters are missing or mislabeled.
- `เรียงเลขต่อเนื่อง` is a proposal only. The user selects a starting number, reviews changes and confirms. `แก้ทั้งหมด` applies entered proposals, not an AI assumption.
- Replace only the exact numeral substring of recognized headings. Never change story prose, punctuation outside numeral, names, whitespace, paragraphs, TXT Export or Context.
- Preserve existing editor undo stack by making all numeral replacements in one QTextCursor edit block.
- Use current Editor's saving and external conflict detection; do not overwrite a file changed on disk since opened.
- Store a full pre-edit snapshot per operation and a history event in `profiles/<profile_id>/chapter_numbering/` for audit and restoration. A restore is refused if file content differs from recorded result.
- Do not auto-renumber on paste. No API, translation or external network calls are made.
- If only one heading is detected, such as 第430章 大結局, no change is proposed or made by default.
- Existing metadata, schema, manifest, exports, translation progress and statistics remain independent.

## Limitations
A manually supplied TXT file has no verified website chapter IDs or catalog ordering. Its chapter numbers and narrative alone cannot conclusively prove that missing chapters do not exist. Preserve gaps unless the user explicitly confirms a correction.
