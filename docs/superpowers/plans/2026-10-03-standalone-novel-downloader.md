# Standalone Novel Downloader Implementation Plan

> **For agentic workers:** Execute this plan inline in the current task, preserving the user's pre-existing `theme.py` changes.

**Goal:** Deliver Novel Downloader as an independent Windows application with its own library, settings, manifests, and output folders; remove embedded downloader UI from Palantir: Novel; publish both installers through the existing GitHub release process.

**Architecture:** Reuse the downloader source adapters and worker, but move persistence and service behavior behind a Downloader-owned repository under `%LOCALAPPDATA%/NovelDownloader`. Add a separate Qt entry point and installer, make both update assets discoverable by their respective apps, and remove all downloader navigation from the main app while retaining legacy profile fields for compatibility.

**Tech Stack:** Python 3.12, PySide6, httpx, selectolax, PyInstaller, Inno Setup, GitHub Actions.

**Spec:** User-approved direction in this conversation: standalone app, independent data, user-selected output root with a subfolder per novel, no downloader mode in the main app, same existing GitHub repository.

## Global Constraints

- Keep the existing GitHub repository as the source of truth; do not create another repository.
- Do not read or write Palantir profile storage or automatically connect downloaded files to `source/`.
- Store Downloader configuration, library, source configs, and manifests under its own local application data directory.
- Write chapter files as UTF-8 using `0001 Chapter title.txt` names beneath one subfolder per novel in the chosen output root.
- Never bypass TomatoMTL anti-bot protections; report the challenge and allow the user to open the source page.
- Preserve existing Palantir profiles and the unrelated uncommitted `src/novel_workflow/theme.py` change.
- Bump semantic version from the verified current 2.4.0 to 2.5.0 only for the release after version/tag checks.

---

### Task 1: Give Downloader independent persistence and service boundaries

**Files:**
- Modify: `src/novel_workflow/downloader/models.py`
- Create: `src/novel_workflow/downloader/storage.py`
- Modify: `src/novel_workflow/downloader/service.py`
- Modify: `src/novel_workflow/downloader/manifest.py`
- Test: `tests/test_downloader_storage.py`
- Modify: `tests/test_downloader_service.py`

- [ ] Define a persisted Downloader book model with a generated ID, source binding, and per-book destination folder.
- [ ] Implement a repository rooted at `%LOCALAPPDATA%/NovelDownloader` that safely loads/saves the book library, app settings, source JSON, and per-book manifests without importing `ProjectRepository` or `NovelProfile`.
- [ ] Update `DownloadService` to persist its own book records and place chapter files in that book's configured output subfolder.
- [ ] Keep atomic chapter writes, safe filename rules, resume, skip-existing, explicit overwrite, and manifest repair behavior.
- [ ] Add tests proving Downloader data uses only its own root and separate books do not share output or manifests.
- [ ] Update service tests to exercise the standalone repository.

### Task 2: Build the standalone Downloader application UI

**Files:**
- Create: `src/novel_workflow/downloader_ui/window.py`
- Modify: `src/novel_workflow/downloader_ui/panel.py`
- Modify: `src/novel_workflow/downloader_ui/source_manager.py`
- Create: `src/novel_workflow/downloader_main.py`
- Create: `run_downloader.py`
- Modify: `pyproject.toml`
- Test: `tests/downloader_ui_smoke.py`

- [ ] Add a `novel-downloader` script entry point that creates a Qt app with its own organization/application names and storage namespace.
- [ ] Create a standalone library window to add books by URL, select a saved book, choose an output root, check updates, download new/ranged chapters, resume, cancel, and manage configurable sources.
- [ ] Have the UI use only the Downloader repository and service; do not accept a Palantir owner/window/profile.
- [ ] On a TomatoMTL challenge, show a clear blocked status and an explicit open-in-browser action without pretending the browser session authorizes Downloader requests.
- [ ] Add a UI smoke test proving the app starts with its own empty library and its actions do not create or access Palantir profiles.

### Task 3: Remove embedded downloader mode from Palantir: Novel

**Files:**
- Modify: `src/novel_workflow/workspace_window.py`
- Modify: `src/novel_workflow/downloader_ui/__init__.py`
- Modify: `tests/ui_smoke.py`
- Modify: `README.md`

- [ ] Remove the web-source button, `open_downloader` utility route, and downloader-specific close cleanup from the main window.
- [ ] Keep the legacy `NovelSourceBinding` profile field readable/writable so existing profile data is not lost, but do not expose or use it in the main app.
- [ ] Replace integrated-workflow README instructions with the separate Downloader application and manual file handoff description.
- [ ] Update the Palantir UI smoke test to assert normal translation/library behavior and absence of the downloader utility entry point.

### Task 4: Package and release two independent installers

**Files:**
- Create: `NovelDownloader.spec`
- Create: `downloader_installer.iss`
- Modify: `build_windows.ps1`
- Modify: `.github/workflows/ci.yml`
- Modify: `src/novel_workflow/updater.py`
- Modify: `src/novel_workflow/workspace_window.py`
- Test: `tests/test_updater.py`
- Modify: `tests/test_update_ui.py`

- [ ] Build and runtime-check separate PyInstaller bundles named `NovelWorkflow` and `NovelDownloader`.
- [ ] Create unique Inno Setup installers and app IDs for `NovelWorkflow-Setup-{version}.exe` and `NovelDownloader-Setup-{version}.exe`; install under separate directories and create separate shortcuts.
- [ ] Keep the main updater asset name unchanged and let the Downloader use its own verified installer asset name from the same private GitHub Release.
- [ ] Add tests confirming each updater selects only its own asset and validates the same repository URL, file size, and SHA-256.
- [ ] Make CI build, upload both artifacts, and publish both installers on `[release]` pushes to main.

### Task 5: Documentation, version, validation, and release

**Files:**
- Modify: `pyproject.toml`
- Modify: `CHANGELOG.md`
- Modify: `README.md`

- [ ] Confirm current version and existing tags/releases, then bump to 2.5.0 once.
- [ ] Document the independent Downloader install, storage location, output layout, private GitHub download/update access, and TomatoMTL challenge limitation.
- [ ] Run focused Downloader tests, `pytest -q`, both UI smoke tests, and `build_windows.ps1`.
- [ ] Review the complete diff, verify the pre-existing theme change is excluded, and scan committed changes for credential-shaped strings.
- [ ] Commit and push the feature branch, verify PR CI, merge with `[release]` in the squash title, and verify the v2.5.0 tag, Release, and both installer assets.
