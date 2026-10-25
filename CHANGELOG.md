## v6.6.0 — Persistent Batch Copy History and Smart Resume

- Persist per-novel copy events for vocabulary and translation batches only after Windows file Clipboard accepts the files.
- Restore batch status by selected source, revision, chapter range and actual chapter numbers; flag changed or regrouped sources for review.
- Add batch progress summaries, status filters, latest copied and next uncopied navigation, and saved search and scroll position.
- Persist vocabulary split output metadata and keep large pasted drafts in atomic, profile-scoped files outside `settings.json`.
- Keep copy history independent of Translator Export, translation progress, workflow stage changes and existing Clipboard modes.
- Add copy history, source revision, restart restoration and draft persistence regression coverage.

## v6.5.1 — Fixed Settings Sidebar and Novel List Scrolling

- Keep the seven Settings categories fixed while scrolling only the novel list.
- Keep novel management buttons anchored below the list and let the list shrink to available height.
- Verify Settings sidebar geometry at 100%, 125%, 150%, and 200% DPI across supported window sizes and Light/Dark themes.

## v6.5.0 — Smart File Setup and Polish Resume Tracking

- Added bounded folder scanning for role-matched novel files, including nested `Project` files, Unicode names, multiple extensions, and exclusions for backup and recovery areas.
- Added a review-before-save setup dialog that keeps existing links, supports explicit file picks, records the novel code and main folder, and links the selected Context through the existing profile field used by Translator Export.
- Added additive profile and app settings for vocabulary instruction files, shared instruction defaults, per-profile and per-step history copy events, and resume positions.
- Split novel settings into focused sections for novel details, files and folders, workflow steps, working tabs, and TXT export.
- Added Polish History summary, latest item navigation, next available range suggestion, copy event recording, and independent resume position controls.
- Added scanner and history regression coverage.

## v6.4.2 — Library list-only presentation

- Open the novel library in list mode, including for saved legacy gallery preferences.
- Remove gallery/list toggle buttons without changing stored covers, novel profiles, search, filtering or drag ordering.
- Add list-only and legacy-preference regression tests; capture only list layouts in Windows Light/Dark visual QA.

## v5.9.0 — Palantir Slate Blue / Translation Planner

- Add Today dashboard with manual focus, daily goals, finish goals, rest days and seven-day scheduling.
- Store planner history independently of profiles and compute counts from confirmed effective Translator Export events.
- Respect duplicate exports, retranslation reset/undo and missing chapters before a declared final chapter.
- Add reversible manual finish acknowledgement, novel covers and quick workspace opening.
- Establish shared Light/Dark Slate Blue semantic palettes, group filter and cached library covers.
- Extend Statistics with planner completion; add dedicated persistence and regression coverage.
- Preserve profile data, source, Translator, Context, workflows, clipboard and existing updater identity.

## v5.8.5 — Restore punctuation in real Chinese chapter titles

- Correct the chapter-only scanner so a genuine first heading like `第1章 钱在银行，人在天堂。` is accepted instead of falsely reporting preface text.
- Continue rejecting prose sentences starting with chapter-like words without a heading separator, and ignore `第三节课` (third class period) inside the story.
- Verify all 100 chapter headings and lossless chapter content with a CMR-style 100-chapter fixture; preserve UTF-8 source bytes.
- No changes to the user's original files, translations, clipboard, history, or export behavior.

## v5.8.3 — Only treat actual chapter headings as chapter boundaries

- Fix false duplicate-chapter errors in combined Chinese TXT novels: prose such as "第三节课的上课铃..." describes a class period, not chapter 0003.
- Recognize numbered Chinese 章 and 回 headings; do not reinterpret 节/節 sections or lesson text as chapter boundaries.
- Conservatively exclude full-line sentences containing Chinese prose punctuation or exceptionally long heading-like lines, while keeping all original source text unchanged within its true chapter.
- Add parsing, translation-stage source, UI/background-worker and lossless-text regression tests for CMR-style novels.
- Preserve the existing duplicate-location diagnostics for genuine repeated chapter headings.

## v5.8.2 — Explain duplicate source headings with exact locations

- Show the real resolved TXT source path when checking translation batch chapters, including a file selected from the translation workflow step.
- Report both line numbers and actual heading excerpts when the chapter-heading detector finds a repeated number, even across different Chinese/English heading styles.
- Make multiline diagnostics wrap and be text-selectable in the translation batch view; preserve source bytes, copy settings, batch progression and clipboard state.
- Add parsing, source-resolution and background-UI regression tests for chapter 0003, including a valid one-occurrence case.

## v5.8.1 — Prevent overlapping Thai text in the editor header

- Fix two unparented-by-layout Context retranslation controls introduced in v5.8.0. Both actions are now backed directly by the **...** menu instead of floating QToolButtons that could paint over one another and the editor header.
- Preserve Context review/reset, undo, workflow navigation, file selection, and all user data unchanged.
- Add a regression test for both menu actions and a DPI-matrix assertion that every visible editor-header QToolButton belongs to the layout.

## v5.8.0 — Context retranslation and safer clipboard/editor behavior

- Exclude codename-prefixed Glossary, Style, Prompt, Context, and other supporting documents from Chinese-source chapter correction. Preserve existing attachment and Clipboard selection.
- Add explicit Context-driven retranslation preview and opt-in chapter-count reset, with Undo in the workspace overflow menu. Historical Translator Export events and files remain intact.
- Recount completed, daily and goal progress using effective chapter histories; chapters exported anew become completed without restoring later chapters prematurely.
- Separate novel chapter headings from Markdown glossary and support sections; require manual confirmation of ambiguous Context markers.
- Protect rapid repeated pastes at the document end with atomic undo edits and separator handling; retain original per-file normalization policies.
- Keep Context actions in the compact toolbar overflow menu so DPI layouts remain stable. Add regression coverage for classification, Context resets and repeated paste.

## v5.7.4 — Cleaner stage selection and readable scan progress

- Remove the bright left selection stripe from workflow stage and navigation buttons while retaining active background and keyboard-focus visibility.
- Make the file-inspector scan progress a compact rounded track without overlaid text.
- Display the current scanned/total file count and percentage in a separate, readable status label, with clear completion, cancellation and failure states.
- Keep all translation stages, Clipboard behavior, file inspection and other workflow logic unchanged.
- Add UI/theme regression tests for both dark and light modes.

## v5.7.3 — Sidebar synchronization and faster chapter batch preparation

- Align workspace step/file sidebar with the active translation-batch view without invoking COPY STEP.
- Avoid redundant TXT vocabulary rescans while opening the existing page.
- Retain an initial full source fingerprint, then validate folder contents via metadata while fully hashing just the chapters included in each copied batch.
- Resolve translation-stage reference files off the main UI thread; leave all reference-selection and copy formats unchanged.
- Move chapter range, file count and copy actions together for easier batch scanning.
- Add regression coverage for navigation, unchanged clipboard contents, and detection of modified sources.

## v5.7.2 — Faster translation batches and clearer TXT workflows

- Perform translation batch source scanning and content fingerprinting in a background Qt worker to keep the main window responsive.
- Prepare verified translation clipboard files and ZIPs off the UI thread; publish the same exact files to the Windows clipboard only from the GUI thread.
- Preserve chapter selection, existing stage reference files, history, Export, and copy-format settings.
- Reuse vocabulary reference metadata across displayed batch rows rather than rescanning folders for every visible row.
- Improve labels and step-by-step cues on translation and vocabulary batch pages.
- Add an async clipboard regression test for exact chapter content and chapter count.

## v5.7.1 — Windows Qt test runner reliability

- Fix Windows CI handling of a fully passing pytest group that emits warnings before a known native Qt shutdown access violation.
- Add a regression test to ensure a warning-only successful summary is accepted while actual failed assertions remain rejected.
- Release the latest Inspector fixes without rewriting the existing v5.7.0 tag or installer.

## v5.7.0 — Single-screen Novel File Inspector and batch heading repair

- Simplify the dedicated inspector into a single main screen with a side-by-side table and read-only chapter reader; keep renumber preview and backup recovery accessible separately.
- Open TXT folders without selecting a novel, and automatically scan after selecting the directory. Support safe cancellation and a queued folder switch.
- Clarify distinct real-file issue totals, short chapters, missing positions, duplicates, heading mismatches, user review progress and repair candidates.
- Add a conservative preview-and-confirm batch heading repair using chapter numbers from filenames only after explicit approval. Preserve unrelated text, BOM and original line endings; create a separate inspected output directory.
- Retain the existing ZIP engine, renumbering engine and recoverable backup journal. Add regression tests for multi-file repairs, source fingerprints, Chinese text, BOM/CRLF and the single-screen UI.
- Windows installer publication and end-to-end in-app upgrade require passing GitHub Actions validation.

## v5.6.0 — Novel File Inspector

- Add a standalone “ตรวจสอบไฟล์นิยาย” navigation page without changing existing translation, vocabulary, clipboard, export or history behavior.
- Inspect TXT folders and ZIP archives for chapter gaps, duplicate numbers, character count (1,500 by default), size anomalies, unreadable files, and duplicate content.
- Provide read-only full-chapter review, persistent keep/exclude choices, separate history, numeric renumber preview, and optional conservative heading changes.
- Default to separate output folders/ZIP; in-place changes require confirmation, backup and durable recovery journal. Block unsafe archives, filename collisions and modified input fingerprints.
- Scan in the background with cancellation; support cached incremental detection.

## v5.5.0 — Translation Batch Workflow

- เพิ่มหน้า "แปลหลายบท" แยกจากหาศัพท์และตรวจคำแปล: เลือกต้นฉบับรวม, โฟลเดอร์ TXT, ต้นฉบับจากขั้นตอนแปล หรือวางข้อความได้
- แบ่งชุด 1–100 บท, ค้นหาช่วงบท และคัดลอกชุดเก่าซ้ำได้โดยไม่ Export หรือเปลี่ยนขั้นตอน
- แนบไฟล์ Enabled จากขั้นตอน "แปล" เดิมใน ZIP หรือไฟล์ปกติ พร้อมตรวจสอบความสมบูรณ์ก่อนคัดลอก
- บันทึก Draft และการตั้งค่าแยกตาม Novel Profile

# Changelog

All notable changes to Palantir: Novel are documented here.

## 5.4.1 - 2026-10-20

- Restore one-click clipboard copying when selecting any named workflow stage, including vocabulary, translation, review, and user-created stages; keep COPY STEP / Ctrl+Shift+C working.
- Preserve the current stage after copying without automatic Export, review snapshots, or advancing to another stage. Keep existing clipboard data intact when file validation or copying fails.
- Update stage-button guidance and add Windows UI regression coverage for regular files, ZIP mode, custom stages, repeated clicks, and failure safety.

## 4.6.0 - 2026-10-19

- Reduce Library cards to the saved novel cover and the novel title only, including after background progress refresh; preserve category tabs, search, reordering and opening novels.
- Redesign the translation progress page with real novel covers, titles, the last Translator Export, goals, progress bars and existing goal-edit/reset actions.
- Display only today's and this week's chapter totals in the top metrics. Hide all Verified counts, per-story daily counts, and explanatory footer notes from the progress page without altering saved records.
- Add UI regression checks for covers, text visibility and persistent goal controls.

## 4.5.0 - 2026-10-19

- Allow selecting an existing directory of individually numbered TXT chapters directly from the vocabulary TXT batch screen, including when no source file has been linked to the vocabulary step.
- Remember the selected TXT source folder independently per novel and automatically scan numeric files like 0601.txt through 0629.txt into five-chapter batches, without a manual paste, splitting, rewriting or renaming operation.
- Continue to include only enabled vocabulary-stage prompts and reference files alongside selected chapter files for normal clipboard and ZIP copying; skip linked source-novel files instead of adding them to the batch.
- Retain the existing linked-source selector and combined-text splitting workflow, safe empty/duplicate directory warnings, compact rows and independent per-novel ZIP choice.
- Add regression tests covering 29 Chinese TXT chapters, seven-file clipboard, six-file last batch ZIP, preference persistence, cancel/error safety, and switching between folder and linked-source modes.


## 4.4.1 - 2026-10-19

- Correct eligible Chinese source chapter headings as soon as Auto Save completes, without the additional 2.5-second review delay.
- Treat COPY STEP / COPY ZIP as a synchronous chapter-numbering checkpoint: save pasted source, finish auto correction and audit snapshot, then copy the corrected bytes. If the reference is missing or a correction fails, keep the existing clipboard untouched and show a clear warning.
- Process separately saved source files in a per-workspace queue rather than replacing the last queued path; keep Translator/Context unchanged and avoid building large manual-review tables during automatic correction.
- Cover immediate ordinary/ZIP copying, unsafe numbers and multiple queued source files with regression tests.

## 4.4.0 - 2026-10-19

- Add an optional per-novel "คัดลอกเป็น ZIP" setting only for vocabulary TXT batches; the existing copy button delivers a persistent, validated single ZIP instead of ordinary independent files when enabled. Default remains ordinary files and the general Workflow ZIP preference is unchanged.
- Keep chapter and enabled vocabulary-step attachment files byte-perfect inside separate archive directories; preserve Unicode names, resolve filename collisions, and verify CRC and source hashes before publishing.
- Replac