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
- Automatic numbering is OFF by default. In explicit per-novel auto-fix mode, pasting and saving a recognized, uniquely paired source (e.g. SEG.txt / SEGTranslator.txt) can renumber a contiguous incoming batch. Generic Novel.txt and unrelated tabs are never scanned. No API, translation or network calls are made.
- If only one heading is detected, such as 第430章 大結局, no change is proposed or made by default.
- Existing metadata, schema, manifest, exports, translation progress and statistics remain independent.

## Limitations
A manually supplied TXT file has no verified website chapter IDs or catalog ordering. Its chapter numbers and narrative alone cannot conclusively prove that missing chapters do not exist. Preserve gaps unless the user explicitly confirms a correction.

## Translator-based start suggestion (v3.15.1)
- When opening the manual Chinese source chapter inspector, locate the uniquely bound Translator file for the **same novel profile**, rather than reading a global Translator or Context.
- Parse the highest chapter heading from that Translator's visible text (including unsaved in-editor content); propose `latest + 1` as the starting chapter. When the Translator has no readable headings, only use its own committed Export events as a fallback.
- Display the actual reference filename, latest chapter and next suggested chapter above the review table.
- On an isolated, sequential batch of incoming source chapters at or after the suggested start, prefill proposals, but never save without the user's explicit confirmation.
- If the Translator binding is missing, ambiguous, malformed or contradicted by higher confirmed Export history, leave the source numbers unchanged and allow manual entry. No changes to Translator, Context, Export counts or Downloader.


## Volume-aware checking (v6.8.0)
- Leading Chinese full-width spaces (U+3000) before a chapter heading are recognized (e.g. \`　　第2章分割遗产\`) without changing original whitespace or text.
- Volume headers such as \`第一卷\`, \`第二卷\`, \`第3册\` and \`卷四\` define independent local chapter-number sequences. A repeated number in a *different* recognized volume is not a duplicate.
- When a TXT has no volume headers, select the first chapter of the new volume in the chapter-review table, then choose **กำหนด / ยกเลิกจุดเริ่มเล่มที่เลือก**. This stores line/title-validated boundaries in the novel profile's \`chapter_numbering/volume_boundaries.json\`, not in the source file. Stale anchors are ignored.
- A backward jump alone is never silently assumed to be a volume transition. Unconfirmed jumps remain warnings until reviewed; proposals restart only at explicit or user-confirmed boundaries.
- Bulk review preserves separately repeated local numbers in different volumes. Automatic contiguous renumbering refuses multiple volumes; manual changes still require a preview, confirmation and a recoverable snapshot.
