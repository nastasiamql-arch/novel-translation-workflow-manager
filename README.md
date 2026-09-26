# NovelWorkflow

NovelWorkflow is a Windows desktop app that combines Novel Launcher project launching with a configurable novel translation workflow. It keeps novel profiles independent, opens each profile's project folder and selected files, apps, and websites, launches groups, and remembers the ordered files used in each translation step.

Version 1 does not call AI or translation APIs.

## Run from source

Requires Python 3.10 or newer.

    py -m venv .venv
    .\.venv\Scripts\Activate.ps1
    python -m pip install -e ".[dev]"
    python -m novel_workflow.main

## Launcher features

- Add a main folder plus application, file, folder, and website targets to each novel.
- Open all enabled targets for the active profile.
- Create groups of profiles, then open a group in one action.
- Import Novel Launcher configuration JSON. The importer maps existing novels by folder or punctuation-insensitive title, adds launcher targets and groups, copies each existing cover into that profile, skips duplicate entries, and leaves the source configuration untouched. Novel status, current chapter context, and translation goal metadata are preserved.
- Set a separate cover image for each novel profile; cover images are copied into that profile's local data.
- Workflow data remains attached to each profile. Profiles imported from Launcher receive the default translation workflow; matching existing profiles keep their existing workflow and files.

The previous application data folder remains `%LOCALAPPDATA%/NovelTranslationWorkflowManager` so existing profiles are reused after updating. Groups are stored in `groups.json` beside the profiles.

## Workflow features

Create independent novel profiles, configure custom workflow steps, attach ordered files or dynamic chapter references, preview assembled text, and copy selected files to the clipboard. Add File links the original file so edits made outside the app are read immediately. Add dynamic references for `CURRENT_SOURCE_CHAPTER`, `CURRENT_TRANSLATED_CHAPTER`, or `CURRENT_REVIEWED_CHAPTER`. Chapter files can have any name as long as the filename includes the chapter number.

## Translation progress

- The progress window shows chapters completed today, this week, and over the last seven days, with totals for each novel.
- Set a chapter goal for each novel. The app keeps the original starting chapter when an existing goal is edited, so its progress is preserved.
- NovelWorkflow checks each profile's Context file on startup and every 10 seconds. If the latest Context heading moves from `บทที่ 125` to `บทที่ 130`, it records five completed chapters.
- Daily activity is assigned to the Context file's last-modified date using the computer's local clock. The app stores each profile's checkpoint and activity separately, avoids counting the same chapter twice on the same day, and re-baselines when the Context file changes or its chapter number is reduced.
- The first scan establishes a baseline instead of treating a novel's entire existing history as today's work. If Context is edited on multiple different days while the app is closed, the file only retains its latest modification time, so those changes cannot be split back across earlier days.

## Importing Launcher data

Choose **Import Launcher** and select `config.json`, usually located at `%APPDATA%/com.novellauncher.desktop/config.json`. Import is additive: it does not edit that file or remove files from novel folders. Existing profiles are matched by main folder first and name second. Duplicate launch targets are skipped.

## Tests and Windows build

    python -m pytest
    .\build_windows.ps1

The build creates `dist/NovelWorkflow.exe`. GitHub Actions runs the test suite and builds the Windows executable on updates to `main` and `v*` tags. Tagged builds publish the executable as a GitHub Release asset.
