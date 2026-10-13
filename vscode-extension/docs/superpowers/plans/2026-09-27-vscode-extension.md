# NovelWorkflow VS Code Extension Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use inline implementation with the current approved migration scope. Steps use checkbox syntax for tracking.

**Goal:** Move NovelWorkflow's existing profile and translation management into an installable VS Code Extension without losing user data or the existing file-copy workflow.

**Architecture:** A dependency-free JavaScript extension uses native Tree Views, commands, Quick Picks, and the editor. A tested core module reads the existing LocalAppData JSON schema; a Windows clipboard adapter sets the OS file-drop list.

**Tech Stack:** VS Code Extension API, Node.js built-in modules and `node:test`, Windows PowerShell STA for file clipboard.

**Spec:** `docs/superpowers/specs/2026-09-27-vscode-extension-design.md`

## Global Constraints

- Keep NovelWorkflow user data at `%LOCALAPPDATA%\NovelTranslationWorkflowManager` by default.
- Do not delete or rewrite external files when removing profile or workflow references.
- Copy Step must set file references on the clipboard, not replace the file list with text.
- Do not advance steps after file resolution or clipboard errors.
- Keep custom workflows; the default template has three steps.
- Do not add Gemini or translation API calls.
- Keep the desktop app available until VS Code extension parity is verified against user data.

---

### Task 1: Port and test compatible data/path operations

**Files:** `src/core.js`, `test/core.test.js`

- [x] Read the existing Python models, storage path, workflow service, and Context progress behavior.
- [x] Implement JSON reading with trailing-comma recovery on a temporary in-memory copy, atomic write with `.bak`, profile validation, profile listing, and profile-contained path checks.
- [x] Implement dynamic chapter resolution, preview assembly, profile creation, template reads, and Context chapter tracking.
- [x] Run `npm run check`; all 8 core cases must pass.

### Task 2: Build the native VS Code navigation and primary workflow actions

**Files:** `package.json`, `src/extension.js`, `src/clipboard.js`, `media/icon.svg`, `test/manifest.test.js`

- [x] Register the NovelWorkflow Activity Bar Tree View and contributed commands.
- [x] Add profile and step selection, copy/preview, file open, dynamic file addition, and file enable/disable actions.
- [x] Add a PowerShell STA adapter using `SetFileDropList`; keep step selection unchanged if it fails.
- [x] Add static manifest tests for commands referenced by menus and keybindings.
- [x] Run syntax and unit checks; all 10 current tests must pass.
- [ ] Run the extension inside a VS Code Extension Development Host and paste files into the user's normal attachment workflow.

### Task 3: Complete profile, file, group, launcher, and progress management

**Files:** `src/extension.js`, `src/core.js`, `package.json`, `test/core.test.js`, `test/manifest.test.js`

- [x] Add create/rename/duplicate/delete profile, cover, current chapter, Context, goals, step CRUD/order/templates, file import/create/replace/label/order/delete, group import/create/edit/delete/open, launcher targets, and search commands.
- [x] Update profile-owned and external paths after VS Code file rename/delete events.
- [x] Import Novel Launcher groups, covers, launcher targets, goals, and Context checkpoints without changing the source JSON.
- [ ] Review each handler for canceled, empty, missing-file, duplicate-name, and access-denied paths; add regression tests for any issue found.
- [ ] Verify existing settings defaults and settings changes in VS Code.

### Task 4: Package and validate a first VSIX

**Files:** `README.md`, `.github/workflows/extension.yml`, package metadata.

- [ ] Document development, command usage, profile location, import behavior, and verification boundaries.
- [ ] Add CI that runs `npm run check` and packages a Windows `.vsix` artifact.
- [ ] Build and install the VSIX into a separate Extension Development Host or isolated VS Code profile.
- [ ] Use a disposable test profile for UI tests; inspect but do not mutate the user's production profiles.
- [ ] Verify file clipboard paste, dynamic chapter selection, profile isolation, Context progress, and VS Code reload persistence.

### Task 5: Complete migration only after parity review

**Files:** user-facing installation instructions and extension documentation.

- [ ] Compare all current desktop screens/actions against the feature matrix in the design spec.
- [ ] Resolve any missing feature before instructing the user to retire the standalone application.
- [ ] Keep the current desktop executable and data backup intact during the trial period.
