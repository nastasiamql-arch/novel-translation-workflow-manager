# Persistent Workspace UX Implementation Plan

## Current-branch constraints
Work in the existing `feature/chapter-filename-padding` branch. Preserve the integrated group-goal, profile-order, and chapter-filename formatting changes. Keep all source work under `E:\\NovelWorkflow\\source`; do not touch deployment backups or user novel data in the E: root.

## Tasks
1. Audit current UI actions and identify dialogs used for normal destinations.
2. Establish persistent app shell with sidebar destinations and workspace tabs; keep Home fixed and resource tabs unique/closable.
3. Convert progress, groups, preferences, launcher, file list/editor, and preview into persistent pages or reusable widgets.
4. Keep workflow actions and profile ordering intact; connect navigation and contextual actions.
5. Add UI smoke coverage for navigation, unique/closable tabs, dirty editor/save, progress, and copy-step cycle.
6. Run project tests and UI smoke, inspect diff and repository hygiene, then commit and push the current feature branch.
7. Build/install the app only if the existing CI workflow supports a safe artifact path without staging generated build files.

## Verification
- `python -m pytest`
- `python tests/ui_smoke.py`
- Review `git diff --check`, staged paths, and secret/user-data hygiene.
- Verify pushed branch SHA and CI state.

## Review notes
Use the existing services and models. Avoid broad business-logic rewrites and new dependencies. Preserve the current app's feature behavior while replacing navigation destinations and routine modal flows.
