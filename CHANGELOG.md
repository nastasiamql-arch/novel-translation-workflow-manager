# Changelog

All notable changes to Palantir: Novel are documented here.

## 3.6.8 - 2026-10-09

- Restore consistent novel cleanup on paste, open/reload, copy, save/autosave,
  draft restore, workflow preview and TXT Export: remove only zero-character
  lines, retaining whitespace, NBSP, tabs and every content character.
- Preserve vocabulary TSV columns and empty fields; prefer clipboard plain
  text over HTML and report incomplete rows without repairing user data.
- Normalize visible text before saving using undoable separator deletions;
  keep BOM/line endings, recovery and external conflict detection. Opening or
  closing an untouched normalized view never automatically overwrites disk.
- Protect structured Context and fenced data; indicate selected novel cards
  with a border without changing font size or weight.
- Add regression/native Windows TSV clipboard checks and verify the actual
  published updater download and installer upgrade from v3.6.7, including
  profiles, novel files, Context, settings, draft and recovery data.

## 3.6.7 - 2026-10-09

- Restore v3.5.6 line-break handling for blank lines pasted into novel text files, limited to CR/LF separators.
- Slightly reduce library cover and card sizes and scale down UI typography.

## 3.6.5 - 2026-10-09

- Let the novel list use the settings sidebar's full available height so more stories are visible at once.
- Keep story rows compact and increase the launch-target list viewport to reduce repeated scrolling.
- Compact blank clipboard lines when pasting into novel text files, while preserving untouched files and structured documents.

## 3.6.6 - 2026-10-09

- Recognize Unicode paragraph and line separators in pasted novel text before removing blank lines.

## 3.6.4 - 2026-10-09

- Give the novel list more room and wrap long titles instead of truncating them with an ellipsis.
- Enlarge the per-novel launch target list and show complete target paths in tooltips.

## 3.6.3 - 2026-10-09

- Combine each novel's profile, workflow, workflow files, working tabs and TXT Export preferences on one page.
- Open the selected novel's settings by default and keep that page active when switching novels in the settings sidebar.
- Retain General and Program Updates as separate settings pages.

## 3.6.2 - 2026-10-09

- Add per-novel Working Tabs ordering and an option to open those files automatically in the saved order.
- Add close controls to open novel tabs; save editor changes, keep the novel and its files, and remember closed tabs across restarts.
- Keep TXT Export pinned at the end while applying a novel's preferred working-file order.

## 3.6.1 - 2026-10-09

- Replace the Settings category dropdown with a preferences sidebar and open General by default.
- Consolidate all program preferences into General; retain separator, filename headings, deletion confirmation, last-novel startup, theme and ZIP settings without a duplicate dialog.
- Separate workflow step actions from attachment management while preserving vocabulary and profile selection.
- Round inputs, primary buttons, editor tabs and navigation controls consistently in Light and Dark; use integrated SpinBox arrows, scalable dropdown arrows and visible checkbox ticks.
- Scroll the preferences sidebar safely on small windows; test all seven categories in both themes at 100/125/150/200% DPI.
- Verify installation upgrades from the published 3.6.0 installer and preserve existing user data and appearance preferences.

## 3.6.0 - 2026-10-09

- White Minimal light palette, blue selections, rounded preference cards and seven settings categories.
- Optional lossless ZIP copy on the existing COPY STEP action; multiple steps through a context menu, disabled attachments, Unicode, binary and folder support.
- Preserve editor/export whitespace, tabs and NBSP; retain UTF-8 BOM and uniform CRLF; detect external file conflicts and persist recoverable unsaved text.
- Visible scalable SpinBox arrows and separate, tested up/down hit areas without wrapping.
- Add horizontal novel tabs, lazy independent workspace switching, persisted open novels and vocabulary mode.
- Cancel delayed automatic update checks when closing the application.
- Keep recovery ordering deterministic when Windows clock ticks repeat.
- Bound PySide6 below 6.12 after reproducing a Windows process-exit access violation with 6.12.0; Python 3.12 with 6.11.2 passes the same smoke test.
- Restore the repository's profile-based TomatoMTL downloader with resume, manifest, safe partial writes and independent source metadata. Live catalog works; Chinese raw download remains unverified because the tested source page did not expose verifiable raw text.
- Prefer final Context progress sections; ignore earlier chapter examples and following sections. Resolve downloaded zero-padded filenames in CURRENT_SOURCE_CHAPTER.
- Native Windows CF_HDROP validation and actual published v3.5.6-to-new-version silent installer upgrade coverage.
- Preserve existing sessions, verified goal overflow, export rollback, workflow click-copy and updater SHA-256 checks.

## 3.5.6 - 2026-10-08

- Remove empty and whitespace-only lines from novel paste, clipboard assembly, text saves, TXT exports, Context updates, and export drafts across profiles.
- Preserve spaces and tabs within every nonempty line, including empty vocabulary columns in CN/TH/SEX/NOTE TSV rows.
- Copy compact novel selections as plain text so rich-text applications cannot restore gaps from an alternate clipboard format.
- Clean existing plain text/TSV and novel Markdown in the editor without rewriting files merely on open; keep prompt/style and structured file formatting intact.
- Preserve undo for paste and explicit save cleanup, and leave temporary editor newlines/cursor positions intact during autosave.

## 3.5.5 - 2026-10-08

- Save the active profile, open editor tabs, tab order and selected document shortly after workspace changes so they survive an unexpected close.
- Keep atomic-save staging files inside a private hidden folder beside the destination, preventing `.part` files from cluttering Desktop and working folders while preserving same-volume replacement.
- Recover the supplied orphan `.SEG.txt._semw29v.part` to `SEG.txt`, verify matching SHA-256, then remove the redundant staging copy.

## 3.5.4 - 2026-10-07

- Suppress floating hover tooltips throughout Palantir, including the drag hint on novel lists.

## 3.5.3 - 2026-10-07

- Relaunch Palantir in the normal visible window state after in-app updates. The detached helper itself remains hidden.
- Add a regression check so the updated application cannot be relaunched with its window hidden.

## 3.5.2 - 2026-10-07

- Keep the duplicate custom Palantir title toolbar hidden on every page. Preserve the native Windows titlebar and the Program menu.
- Add navigation geometry coverage to ensure switching pages never restores the title strip.

## 3.5.1 - 2026-10-07

- Remove the duplicate brand toolbar while Workspace is active, reclaiming the top strip without hiding navigation or the update menu.
- Make the TXT Export writing surface span the content width; keep comfortable padding only around controls and Submit.
- Verify edge geometry in Light/Dark at both window sizes and all four DPI scales.

## 3.5.0 - 2026-10-07

- Add Ctrl/Shift/Ctrl+A multiple selection throughout file lists and explorer; batch attachment removal/order changes, working-file open/removal, launch-target removal and file-manager open/attach/delete.
- Preserve selected relative order and selection after moving attachment groups. File renaming requires one selected item; physical deletion retains confirmation and reports failures.
- Add nearest-slot cover drops, neutral insertion markers and gradual edge scrolling; canceled drags keep existing order. Defer progress disk refresh until the drag completes.
- Support selecting multiple application paths when preparing launch targets.

## 3.4.5 - 2026-10-07

- Enable desktop dragging on Library covers as well as Settings novels, with a cover preview and explicit model reordering on drop.
- Keep persistent order, active profile and later saves consistent after reordering; canceled drags leave order unchanged.
- Size Settings workflow/attachment lists from actual row/font metrics, show up to eight complete rows, and separate action grids from list content.
- Expand the four-scale Light/Dark geometry checks into nested Settings layouts with six Thai/CJK attachment rows.

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
