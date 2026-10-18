# Changelog

All notable changes to Palantir: Novel are documented here.

## 4.3.0 - 2026-10-19

- Connect the TXT vocabulary mode to enabled attachments of the existing novel-specific vocabulary step only. Prompt and vocabulary files no longer require separate configuration, and unrelated stages are never included.
- Select the source from the vocabulary-stage file list, suggest it when unambiguous, and read linked combined TXT novels for chapter preview without manual paste. Preserve the manual paste fallback.
- Copy the current numbered batch with the non-source vocabulary attachments as real independent files in one click, preserving chapter gaps, missing-file warnings, source selection, scroll position, and no ZIP or workflow advancement.
- Add integration tests for enabled/disabled attachments, linked combined 100-chapter source, file copying and novel-specific source selection.


## 4.2.0 - 2026-10-19

- Show each novel's independent Translator Export goal and compact progress bar directly beneath its title in the workspace editor header, including completed and over-target counts.
- Add per-novel Edit/Set Goal and confirmed Reset actions in the same header; setting 0 disables only that goal. Keep chapter Export events, history, daily totals and Verified goals untouched.
- Refresh the active novel header after a completed Translator Export, goal edits, reset and switching novels; retain the goal across app restarts.
- Style the new controls with light/dark contrast tokens and add focused header, persistence, switch and reset regression tests.

## 4.1.1 - 2026-10-18

- Fix TXT vocabulary batch copying to place the actual separate chapter and glossary files on the Windows Explorer clipboard (CF_HDROP), in one click per batch. No text merging, ZIP, Export or workflow advancement.
- Simplify each batch card to chapter range, counts and a single copy button. Long Chinese filenames and reference details stay collapsed until requested.
- Add an independently scrollable, always-visible scrollbar, load batch cards progressively for large novels, and jump to a chapter number without paging through previous batches.
- Keep the scroll position after copying, validate every attached file before touching the clipboard, preserve missing-chapter warnings and deduplicate repeated reference paths.
- Reuse the existing workflow file clipboard helper and add Windows CF_HDROP integration tests, 1,000-chapter scroll tests, clipboard-preservation and regression coverage.


## 4.1.0 - 2026-10-18

- Add TXT vocabulary preparation inside each novel workspace with a manual/TXT switch, numeric chapter batches (five by default), two independently copied glossary references and per-novel saved settings.
- Add a paste-and-preview workflow for multiple Chinese, Thai and English numbered chapters, preserving all pasted text and creating separate UTF-8 TXT files only after confirmation.
- Detect chapter gaps, duplicates, invalid encodings and existing chapter numbers; skip conflicts by default or explicitly back up and replace them. Do not create ZIPs, auto-copy or advance translation stages.
- Add dedicated batching, splitting, safety and UI regression tests.

## 4.0.0 - 2026-10-18

- **BREAKING:** Remove the Novel Downloader feature entirely, including both per-profile and standalone implementations, TomatoMTL, automatic Raw copy, visible Chrome/Edge control, login/Session UI, manifests, download jobs, settings and navigation links.
- Remove downloader-only HTTP, HTML parsing and browser automation dependencies from the application and Windows installer. Remove old bundled browser-driver files on in-place upgrades from v3.20.2.
- Remove obsolete website binding from the active novel profile data model and profile JSON, first creating a lossless one-time local backup. Do not delete user documents, saved Chinese source TXT, Translator/Context/Export or application update history.
- Keep `source/`, `CURRENT_SOURCE_CHAPTER`, chapter numbering, all translation/export operations, clipboard/ZIP and GitHub in-app updates intact. Remove downloader-only test fixtures and add feature-removal regression coverage.
- The prior standalone Downloader's private `%LOCALAPPDATA%\\NovelWorkflow\\downloader` directory is left untouched on upgrade to protect user data. It may be deleted manually after backing up any needed files; no downloader code is shipped.

## 3.20.2 - 2026-10-18

- Add a dedicated, cancellable "Chrome Downloader sign-in" workflow. Keep the browser visibly open without a login timeout until the user confirms they have signed in, then verify TomatoMTL account navigation before closing the browser.
- Retain login cookies in Downloader's dedicated persistent Chrome/Edge profile across application restarts; never import the user's personal Chrome credentials or access the Windows clipboard.
- Show actionable Thai messages for waiting, failed confirmation, saved session and cancellation; maintain the existing isolated downloader and translation workflows.
- Add tests covering waiting without deadline, retrying the confirmation, and cancellation with browser cleanup.

## 3.20.1 - 2026-10-18

- Add a visible Chrome/Edge Playwright adapter to the standalone TomatoMTL Downloader, using the rendered chapter list and the real "Copy Raw Text" button rather than the direct HTTP source adapter.
- Keep browser profile data isolated from translation projects and normal Chrome profiles, and capture the page copy internally without replacing the user's system clipboard.
- Stop safely on authentication/access challenges, source changes, and missing raw text. Close the browser after inspect/download, including cancellation and failures.
- Include the Playwright driver in the Windows installer and add browser adapter tests. This requires an installed Chrome or Edge.

## 3.20.0 - 2026-10-18

- Add the independent Novel Downloader navigation page, accessible without selecting or changing any translation novel profile. Keep Downloader book settings, cache, request history, and manifest under a separate data namespace.
- Support selecting chapter ranges and UTF-8 TXT outputs: separate files (A), combined `Novel_All.txt` (B), or both from one cached content copy (C). Include configurable filename padding and safe title handling.
- Add per-chapter resume and validation, atomic file writes, explicit refusal to overwrite differing user files, and abort on challenge or rate-limit errors. Minimum chapter interval is 10 seconds, with conservative persisted hourly/daily request budgets.
- Validate chapter headings and reject Arabic-number mismatches instead of silently changing source text; safely capture UI settings before background QThread operations.
- Source access is conditional: TomatoMTL's live Raw clipboard-button behavior and rights for automated retrieval are not yet verified; the existing HTML source adapter remains subject to access and content validation. No CAPTCHA or access-control bypass is included.
- Extend Downloader tests and update navigation regression expectations.

## 3.19.1 - 2026-10-17

- Disconnect chapter numbering entirely from automatic Translator-to-review workflow stage handoffs, copying, and clipboard actions.
- Use the actual Translator document as current progress; keep higher Export history informational only, never a blocking or fallback chapter reference.
- Propose the next source chapter after previously verified corrections, keeping corrected source chapters untouched when inspecting or auto-fixing appended chapters.
- Reuse identical review snapshots across the full history without resetting "ตรวจแล้ว". Capture changed-content versions in the same chapter range as revisions, preserving earlier history.
- Regression coverage for clipboard/stage isolation, stale Export events, append-only corrections and review history deduplication.


## 3.19.0 - 2026-10-17

- Add incremental source chapter numbering for one-chapter-at-a-time append workflows: newly pasted chapters continue after the last verified corrected source chapter, rather than rejecting the saved prefix as a gap. Only previously verified history snapshots can authorize preserving a prefix; never change earlier chapter numbers or story text.
- Clarify two per-novel modes: manual check and correction (sticky "needs review" indicator) or opt-in automatic renumbering. Manual review acknowledgement clears the indicator; pending state survives reopening the novel.
- Keep the existing Translator-based starting number, matching-file restrictions, multi-chapter safety checks, backup/undo history and Export/Context isolation. Regression tests cover repeated paste, Chinese numerals, noncontiguous appended chapters, tampered histories and reminder persistence.


## 3.18.4 - 2026-10-17

- Restrict automatic source chapter numbering to a same-codename source and Translator pair (SEG.txt ⇄ SEGTranslator.txt) with unique ownership. Ignore generic Novel.txt and unrelated TXT/MD tabs completely.
- Read the freshly saved Translator before calculating the next source chapter. If the paired Translator tab is still dirty, remember the pending source and automatically retry after Translator Auto Save, even if the user switches tabs.
- Reject unsafe discrepancies between saved Translator and confirmed Export history rather than guess. No changes to Translator, Context, Export, Backup or unrelated files.
- Add regression tests simulating actual editor paste and source/Translator autosave order.


## 3.18.3 - 2026-10-17

- Fix auto chapter renumbering silently skipping source files manually opened outside the project's source folder: allow unique same-codename Translator binding and show an actionable status if the source is not associated with the novel.
- Resolve a same-name Translator sibling in a verified novel folder, even without an extra file-binding step; never borrow Translator from another novel or an ambiguous shared directory.
- Prefill the manual chapter inspector from Translator on every open, with a separately persisted fallback for the last manually entered starting number when Translator is unavailable. Never use that fallback for automatic edits.
- Make check/fix diagnostics visible in the status bar, and add end-to-end tests for external Editor files and persistence. No changes to Export or Backup.


## 3.18.2 - 2026-10-17

- Add explicit per-novel check-only and opt-in auto-fix modes. Existing enabled profiles stay check-only on upgrade.
- Read the uniquely bound Translator chapter to find the next number. Safely renumber contiguous original-source chapters after Auto Save while preserving Chinese/Arabic/full-width script and story text.
- Refuse uncertain Translator, older chapters, duplicates, skipped or unsupported headings; provide backup and manual rollback. Never edit Translator/Context or Export/Backup.


## 3.18.1 - 2026-10-17

- Fix opt-in auto chapter checking not reacting to pasted original source: after the source editor saves, scan with the existing Chinese/Thai/English chapter heading validator after 2.5 seconds of idle time.
- Announce the checked chapter count and duplicates, descending or skipped chapter numbers. Open the existing original-source numbering dialog for issues, but never modify text or numbering without confirmation.
- Restrict automatic scanning to files owned by the current novel; ignore Translator, Context and unrelated documents. Source checking no longer requires configuring an unrelated translation workflow stage. Keep previous Translator workflow handoff and manual operation unchanged.

## 3.18.0 - 2026-10-17

- Add a per-novel, opt-in automatic handoff to an existing chapter-review workflow stage. Defaults to off; manual review-stage selection and copying remain unchanged.
- Choose translation and review steps explicitly, including custom names. After a bound Translator file is safely saved and idle for 12 seconds, prepare/copy the review stage once per saved content fingerprint.
- Never mark chapters reviewed automatically, judge translation quality, or alter Export, Backup, Context or translation files. Add settings and stage-guard regression tests.

## 3.17.0 - 2026-10-15

- Separate History clipboard ZIP from Workflow ZIP: History now has its own immediately saved checkbox directly on the History page. Only the clicked record is archived.
- On first upgrade from the combined ZIP preference, migrate the existing choice to History and restore ordinary Workflow copying; retain the separate Workflow ZIP toggle in Settings for deliberate use.
- Do not alter Export, history contents, or underlying translation files. Add independent-setting and clipboard UI regression coverage.

## 3.16.0 - 2026-10-15

- Make clipboard ZIP mode obvious on COPY STEP and each Polish History copy button; the ZIP contains only the chosen step or history record, including all linked files, never another record.
- Name clipboard archives after their step or chapter range, with unique suffixes for repeated copies and persistent cache backing for Windows Ctrl+V.
- Keep ordinary file copying selectable, remember the ZIP preference, and leave source files, history data and TXT Export unchanged. Add regression tests for per-step ZIP isolation and per-history clipboard copies.

## 3.14.0 - 2026-10-13

- Add explicit Polish History sorting by newest, actual chapter number descending or ascending, and manual move-up/down order. Each novel remembers its own selected mode and manual arrangement.
- Group a clean, unpadded row number, chapter title and Copy button together on the left; keep Delete and More at the far right. Review payloads, hashes, identities, Context and snapshot paths remain untouched.
- Maintain search, keyboard-accessible ordering controls, Light/Dark appearance and compact row height.

## 3.13.4 - 2026-10-13

- Enlarge Polish History sequence badges beside Copy from 44px/9pt to 64px/12pt bold, with stronger theme-aware contrast and a 34px minimum height.
- Keep chapter labels, delete/copy/menu actions and compact history rows intact; extend Light/Dark responsive UI regression tests.

## 3.13.3 - 2026-10-13

- Move the compact History row's visible ordinal to a subtle theme-aware badge immediately before Copy. Show chapter ranges clearly on the left without a number prefix.
- Preserve the continuous-on-delete numbering behavior, stable snapshot identities, Copy, Recycle and More actions, with Light/Dark and responsive geometry tests.

## 3.13.2 - 2026-10-13

- Show compact Polish History numbering as contiguous newest-to-oldest display ordinals; after deletion the remaining rows close the gap without rewriting immutable snapshot identities or metadata.
- When a stored History payload was intentionally edited, offer an explicit confirmation on Copy, preserve the original manifest hashes in a backup, validate ownership and file membership, then register new hashes and copy. Missing, extra, symlinked or structurally invalid files remain blocked.
- Preserve Context, Translator, historical snapshot data, byte-for-byte edited content and Windows in-place upgrade behavior.

## 3.13.1 - 2026-10-13

- Let Translator Export proceed when Context is only display-normalized; preserve pre-Export disk bytes and still block real unsaved edits and external conflicts.
- Reuse verified pre-Export old-Context snapshots for repeated review copies and automatic post-TXT-Export captures; explicit Save for Review still creates intentional revisions.
- Keep other steps' live files independent in multi-step ZIPs and refuse falsely labelled old-Context captures.

## 3.13.0 - 2026-10-13

- Count completed translation chapters only from successful Translator Export transactions; deduplicate actual chapter headings/ranges across exports, dates and profiles.
- Keep Context-derived activity as legacy data, separate from confirmed daily/weekly activity and translation goals. Goals keep overflow and reset only when requested.
- Replace the workspace header with a compact confirmed-export summary; remove the verified file-counter line while keeping TXT Submit and its goals/history intact.
- Stage TXT, Context, export status and statistics together with a durable recovery journal. Interrupted exports recover consistently; conflicting external changes are preserved and reported.

## 3.12.0 - 2026-10-13

- Reconcile persisted Translator export status with the successful SHA-256 after restart and session restore; undo to the saved baseline preserves BOM/CRLF and avoids normalization-only autosaves.
- Freeze current workflow attachments before copying normal files or ZIPs; save actual editor edits, reject external conflicts, verify dynamic references and archive payloads, and keep clipboard/step unchanged on failure.
- Compact Polish History rows with permanent per-novel numbers, stable legacy migration, direct recycle-only deletion, and immutable historical clipboard payloads.
- Require modern Windows Recycle Bin support (Send2Trash and pywin32), serialize history operations, and verify native recycling from both tests and the packaged executable.

## 3.11.1 - 2026-10-12

- Translator Editor Export now confirms first, snapshots the configured review
  step and verifies its payload hashes before writing the TXT export or replacing
  the profile Context. The attached Context is preserved byte-for-byte at its
  pre-Export state; Export stops with a clear message when Context is not attached.
- Resolve the snapshot chapter range from Translator headings or ask the user to
  confirm one. Keep the existing timestamp-based TXT filename when headings are
  unavailable, and retain the existing atomic TXT/Context transaction.
- Use a shorter internal staging directory name to avoid Windows path-length
  failures while keeping the same readable published History folder layout.

## 3.11.0 - 2026-10-12

- Add `บันทึกไว้รอตรวจ` for the configured review step without changing workflow
  selection, clipboard, TXT exports or verified counters.
- Automatically save a pending snapshot after successful TXT export. Preserve
  unknown export ranges as editable `รอระบุช่วงบท` entries instead of guessing.
- Snapshot only files attached to the configured step, including Disabled,
  folder, dynamic and external attachments. Context is included only when the
  user explicitly attaches it to that step.
- Use readable `<ชื่อขั้นตอน> บท 6-10` folder names, retain verified older
  layouts, and add pending/reviewed status management to the existing History page.

## 3.10.1 - 2026-10-12

- Store Polish History directly under readable `<step name>-บท <range>` folders;
  add local timestamps, readable profile suffixes and numeric collision suffixes
  when needed, without exposing stable IDs in completed directory names.
- Keep schema-1 IDs and all snapshot bytes unchanged. Validate legacy v3.10.0
  manifests/payload hashes before and after atomic migration; retain originals
  on failure and defer moves while Clipboard references their paths.
- Rename chapter-range folders together with metadata, preserving payload hashes
  and a raw manifest backup. Verify legacy migration during Windows in-place
  upgrade from v3.10.0. Clipboard, editor, export and workflow behavior stay intact.

## 3.10.0 - 2026-10-12

- Add per-novel Polish History with automatic stage snapshots before the existing
  named workflow button copies files. Enable one stable Step ID in Settings;
  only unambiguous legacy polish names are detected automatically.
- Preserve every attached file (including Disabled, folders, external and dynamic
  references) and the profile's current Context as exact bytes with SHA-256 checks.
  Stage and verify before publishing under the novel's `Polish History` folder.
- Show chapter-range history in a full in-app page with one-click Copy Recovery,
  search, refresh, range rename, folder access, verified file counts and confirmed
  deletion. Preserve old snapshots across Context changes and application restart.
- Reuse unchanged snapshots only when step, chapter range, attachment metadata
  and all file hashes match. Keep incomplete/corrupt history visible for inspection;
  never prune history automatically or modify Context/export counters on recovery.
- Support persistent Windows file clipboard and existing ZIP delivery settings.
  Preserve editor, autosave, recovery, workflow and update behavior.
- Extend native clipboard, DPI/theme geometry and Windows installer upgrade tests,
  including byte preservation and snapshot validation by the installed runtime.
- Avoid reinstalling an unchanged global theme when opening another window,
  preventing unnecessary Qt repolishing and long regression-suite delays.

## 3.6.9 - 2026-10-09

- Compact only zero-character lines in every TXT/Markdown opened in the
  Editor, including external per-novel names such as FDR.txt, FDRContext.md
  and FDRGlossary.txt. Apply consistently on open/reload, paste, copy,
  save/autosave and recovery restore; preserve spaces, NBSP and every TSV tab.
  Opening alone does not rewrite disk; unopened files are not processed.
- Work on one novel at a time. Switching saves and closes the previous
  workspace, preserving each novel's file tabs, cursor, draft and workflow
  session; block switching if saving fails. Keep all novels in the library
  and restore only the last active novel from older multi-novel sessions.
- Show a small cover beside the active novel's title and progress, with a
  fallback for missing covers. Keep multiple file tabs within the current novel.
- Add regressions for arbitrary file names, unopened-file protection, single
  workspace sessions and cover display; test published upgrade from v3.6.8.

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
