# Changelog

All notable changes to Palantir: Novel are documented here.

## 3.4.4 - 2026-10-07

- Start novel reordering in Settings on the standard movement threshold, without a hold delay; show the dragged row beside the pointer using native Move drag/drop.
- Commit mouse selection on release rather than loading novel details on press; keep keyboard selection and persistent order consistent after a drop.
- Remove the remaining native profile focus frame and use neutral keyboard focus indicators throughout the app.
- Cache only parsed Context chapter results in a bounded cache keyed by file identity, timestamps and size; unchanged progress refreshes avoid repeated document reads/parsing, while external changes and rollback still refresh.

## 3.4.3 - 2026-10-07

- Keep main navigation permanently icon-only; remove the expand/collapse button while preserving named tooltips, keyboard access and legacy settings data.
- Replace native patterned scrollbar pages with solid tracks and clearly contrasting handles in Light/Dark, including hover and pressed states.
- Verify legacy expanded navigation, rendered scrollbar colors, mouse dragging and the four-scale UI geometry matrix.

## 3.4.2 - 2026-10-07

- Fix successful updates being reported as version mismatches when old application dist-info folders remain after upgrades.
- Embed the executable's version from pyproject.toml at build time instead of reading ambiguous installed distribution metadata in frozen builds.
- Remove only stale NovelWorkflow package metadata in the installation directory during upgrade; preserve user data and unrelated files.
- Verify installed executable runtime and expected version before updater success/relaunch, and display actual/expected versions on mismatch.
- Add stale-metadata regression tests and an actual silent installer upgrade check in Windows release builds.

## 3.4.1 - 2026-10-07

- Introduce a white/soft-gray Light theme, coordinated neutral Dark theme, and original scalable line navigation icons.
- Separate neutral item selection from blue text selection and current-line highlighting; use high-contrast monochrome primary actions.
- Remove mouse-click focus rectangles, retain keyboard-only focus indicators, and fix export panel styles overriding Submit colors and dark menu-bar colors.
- Remove the redundant workspace cover rail; retain library profile navigation, sessions and remembered workflow sidebar width/visibility.
- Default new settings to Light while preserving existing theme preferences. Validate contrast, real keyboard/mouse focus, primary action rendering and the four-scale geometry matrix.

## 3.4.0 - 2026-10-07

- Compose MainShell from shared management actions instead of stacking two MainWindow implementations; introduce named library/workspace/statistics/settings surfaces and reusable navigation, header and responsive editor toolbar.
- Move navigation into a resizable, remembered sidebar; bring Context chapter, daily translation and verified progress into Novel Header. Keep vocabulary preparation separate from translation stages and retain custom workflows.
- Introduce restrained blue selection/focus tokens for Light/Dark, explicit cover/stage indicators, and content-driven layouts with overflow menus for narrow windows.
- Keep document tabs on one row, elide long names, preserve order/session, and pin the permanent TXT Export tab last. Add Ctrl+Tab/Ctrl+Shift+Tab.
- Add active-editor Undo/Redo controls, standard keyboard editing, and alternate redo. Fix shortcut actions accidentally receiving Qt's checked flag. Preserve undo history through autosave.
- Track successful verified export events and daily history per profile. Add unlimited manual-reset goal cycles, archived achievements and over-target progress; rotating filename numbers remain independent.
- Add rollback when a staged TXT/Context/metadata replacement fails and bounded recovery before overwriting existing documents. Preserve legacy export ranges, preferences and unknown nested fields in additive schema 7 migration.
- Retry transient Windows locks during transaction replacement/recovery; persistent locks roll back without increasing counters.
- Simplify TXT Export with Advanced settings, persistent drafts and immediate progress refresh; provide status-action toast undo and file recovery.
- Replace interactive update launching with a detached silent in-place helper that waits for app exit, rechecks SHA-256/size, logs installer exit status and relaunches. Preserve installer AppId, install directory, tasks, shortcuts and user data.
- Extend behavior tests, actual QTest keyboard coverage, Windows helper simulations and a four-scale Light/Dark geometry matrix before CI builds and release.

## 3.3.6 - 2026-10-04

- Replace the Stage E mark with the selected N monogram across the app icon, installer, SVG masters, favicon, and desktop/mobile exports.

## 3.3.5 - 2026-10-04

- Save editor documents by writing a complete temporary file and atomically replacing the original, preserving the last saved copy if Windows blocks the replacement.
- Retry failed automatic saves and keep the document marked as unsaved until the write succeeds.
- Adopt the selected Stage E mark as the Palantir: Novel icon, with monochrome light/dark SVG masters, favicon sizes, and desktop/mobile PNG exports.

## 3.3.4 - 2026-10-04

- Prevent workflow stage buttons from extending into the next row by removing vertical padding that made them taller than their list items.
- Add a UI smoke assertion that each workflow button remains inside its own row.

## 3.3.3 - 2026-10-04

- Remove the underline and bottom border from COPY STEP hover and keyboard focus states while retaining a clear text-color focus indicator.
- Replace the painted workflow-stage arrow with a simple active-row background to prevent it from colliding with the stage label.
- Remove the selected-item border beneath novel covers.

## 3.3.2 - 2026-10-04

- Fix duplicated workflow step labels in the workspace sidebar and expose each step name directly to assistive technology.
- Restyle COPY STEP as a flat text action that matches surrounding labels instead of a filled button.

## 3.3.1 - 2026-10-04

- Replace the warm amber palette with a restrained grayscale theme across the editor, navigation, selections, search matches, focus indicators, and status bar in both Dark and Light appearances.
- Keep success, warning, and error colors distinct so status meaning remains easy to recognize.

## 3.3.0 - 2026-10-04

- Redesign the app-wide Dark and Light palettes with a warm neutral workbench, coordinated amber focus/action colors, and consistent editor, dialog, notification, and progress surfaces.
- Keep disabled controls readable, make keyboard focus easier to locate, and enlarge base text and common control targets across the application.
- Align the Editor toolbar, editor tabs, cover rail, notifications, and native Qt palette with the shared theme tokens.

## 3.2.0 - 2026-10-04

- Improve readability across the full application with larger base text, stronger inactive/disabled states, clearer keyboard focus, and larger toolbar targets.
- Clarify navigation hierarchy with more legible page headings, tabs, toolbar labels, and status-bar text.
- Make updater progress easier to follow: show the percentage once outside the progress fill and give the download dialog enough room for its message and cancel action.

## 3.1.0 - 2026-10-04

- Refresh the full interface with flat Visual Studio Code Dark+ colors and keep a matching Light theme available in settings.
- Remove decorative cards, rounded frames, and pill-shaped controls throughout the app; retain clear input borders, keyboard focus, and selection indicators.
- Restyle editor tabs, find controls, notifications, progress indicators, and the status bar as flat workbench elements.

## 3.0.1 - 2026-10-04

- Improve readability across light and dark themes with clearer text, stronger control borders, solid surfaces, and larger interface text.
- Keep progress values beside their bars and make update progress text remain legible.
- Make editor text wrap to the available width and change search matches to subtle underlines with a distinct active result.

## 3.0.0 - 2026-10-03

- Remove the standalone web novel Downloader and its adapters, library, configuration, installer, updater path, and related workflow integration.
- Keep Palantir: Novel focused on translation workflows and existing source, translated, and reviewed chapter references.

## 2.4.0 - 2026-10-03

- Migrate old profile documents additively and preserve unrecognized legacy fields.

## 2.3.2

- Add a confirmed **ยกเลิกเป้าหมายทั้งหมด** action to clear goal targets across every novel while keeping chapter history and daily activity.

## 2.3.1

- Refresh an open Context editor tab immediately after Submit and cancel stale Auto Save for the replaced text.
- Show an on-screen completion notification after a successful Submit.
- Rename the export number label to **เลขถัดไป** to clarify which number will be used next.

## 2.3.0

- Add a **กำลังเช็กกับเว็บ** novel status and library category, with a count and a card label.
- Add a workspace action to move a novel into this category; use **กลับไปแปล** to move it back.

## 2.2.2

- Show a clear Submit success message with the exported filename and next export number.

## 2.2.1

- Combine TXT export and Context overwrite into a single **Submit** button.
- Stage both output files before replacing either destination, preserving existing files if staging fails.

## 2.2.0

- Add one-step **ส่งออก + อัปเดต Context** to write TXT Export text to the numbered TXT file and overwrite the current novel's Context file. The export number advances only when both writes succeed.

## 2.1.0

- Keep TXT Export filename, destination folder, number range, and current number independently for each novel profile. Existing profiles inherit the previous shared settings once when migrating.
- Remember editor tab order, including TXT Export, and restore the active tab when reopening the application.

## 2.0.0

- Restore vocabulary handling to the v1.12.0 file-based workflow step; remove AI vocabulary processing, provider/API settings, and the separate **เกลาศัพท์** mode. Legacy per-profile configuration is retained as inactive data, and source files are not deleted.

## 1.14.0

- Add a permanent TXT Export editor tab with UTF-8 export, rotating chapter numbers, copy actions, overwrite-on-export, and application-wide settings.
- Add a separate **เกลาศัพท์** workflow tool with independent files, profile migration, and workflow-template support.
- Stabilize CJK editor rendering by using one editor font family and default hinting; clarify active editor tabs in light and dark themes.
- Show the last chapter heading found in Context directly in the status bar, including ranges and Thai, Chinese, and English headings.
- Streamline verified in-app updates: after the user chooses **อัปเดตเลย**, save editor and application state and launch the installer without another prompt.

## 1.13.5

- Read headerless SEGGlossary text files without imposing a fixed field count or meaning; follow the selected prompts and preserve each row as provided. Use exact before/after row pairs to safely update repeated source terms in different contexts.

## 1.13.4

- Identify which vocabulary input failed during snapshot reading (source, VOCAB, Extract prompt, or Polish prompt) and explain common missing-file, encoding, DOCX, TSV, and JSON issues without showing file contents or credentials.

## 1.13.3

- Continue checking supported MaxPlus pool endpoints when one returns a temporary 5xx response, and report a temporary provider outage clearly if none responds.
- Show a readable connection hint for HTTP 401/403 and temporary HTTP 5xx responses; the saved-key placeholder remains explicit.

## 1.13.2

- Report which vocabulary pipeline phase failed, with safe guidance for API HTTP statuses and common file/validation failures. Never display prompt, source, model response or API key contents.
- Accept the MaxPlus API root URL and auto-resolve the pool route allowed by the entered key while fetching model IDs; store the resolved endpoint on Save.

## 1.13.1

- Add a background **Connect and fetch model list** action to provider settings. It requests `/models` using the entered or Windows-protected API key, lets the user select a returned model or type one manually, and never saves a key until Save is pressed.
- Keep API errors sanitized and provider settings usable while model discovery runs; the worker clears its temporary key after completion.

## 1.13.0

- Add a compact, collapsible right-side vocabulary panel per novel. Remember source, VOCAB, extract/polish prompt files, provider, model and panel size independently.
- Run Extract → Polish → deterministic validation → byte-exact backup → atomic VOCAB replacement in a background thread; cancel before commit. Extraction never writes VOCAB.
- Read TXT/MD/JSON and DOCX prompts. Repair only JSON trailing commas outside strings in temporary copies; never rewrite prompt originals.
- Support headered UTF-8 TSV and JSON row arrays, full-row NEW/UPDATE changes, strict identities/columns, concurrent-change detection and cooperating-writer lock.
- Add HTTPS OpenAI-compatible and Anthropic provider adapters. Encrypt per-profile keys with current-user Windows DPAPI; redact provider errors and reject redirects.
- Migrate profile schema to v2 without modifying translation workflows. Support TSV editing; guard stale editor autosaves during vocabulary runs and reload afterwards.
- Keep installer AppId, self-updater and versioned release asset naming unchanged.

Uploaded prompts were not available in the referenced conversation's attachment list. This release uses the selected local prompts; it does not claim to embed or reproduce unavailable uploaded instructions.
