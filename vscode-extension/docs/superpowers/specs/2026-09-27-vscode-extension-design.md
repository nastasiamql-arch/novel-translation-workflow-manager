# NovelWorkflow VS Code Extension Design

## Goal

Move NovelWorkflow's novel, file, workflow, progress, and launcher management into VS Code while retaining the Python application as a fallback until the extension has passed real-data validation.

## Confirmed existing behavior

- The application is a Windows Python 3.10+/PySide6 desktop application.
- Profile JSON, groups, templates, and settings live under `%LOCALAPPDATA%/NovelTranslationWorkflowManager`.
- Each profile folder has a 32-character hex ID and a `profile.json`; files are organized under prompts, glossary, characters, style, source, translated, reviewed, notes, reference, and custom folders.
- `WorkflowStep.files` includes ordered enabled state, labels, relative repository paths, external absolute paths, and dynamic references.
- Default workflow names are `หาศัพท์`, `แปล`, and `ตรวจคำแปล`; workflows can be customized.
- Dynamic chapter resolution uses the current chapter number and reports ambiguous filenames.
- Copy Step places enabled file paths on the Windows file clipboard and advances to the next workflow step only after a successful clipboard write.
- Preview assembles text from enabled file contents and configurable headings.
- Novel profiles also contain Context path/checkpoint, daily chapter activity, chapter goal, cover, main folder, and launch targets. Groups and Launcher imports use `groups.json` and the legacy launcher JSON.
- No AI/translation API is used. Gemini stays outside this extension's scope.

## Architecture

Use a dependency-free JavaScript VS Code extension. A native Tree View presents groups, profiles, workflow steps, and files. VS Code commands and Quick Picks perform CRUD actions; VS Code's editor handles text files. A small core module reads/writes compatible JSON, resolves safe paths, dynamic chapters, previews, and progress. The Windows clipboard adapter uses PowerShell STA plus `System.Windows.Forms.Clipboard.SetFileDropList` to preserve the existing file-list paste behavior. The extension reads the existing LocalAppData profile root by default, so it does not require a one-time destructive data conversion.

## Safety rules

- Keep the standalone desktop application and source data unchanged during the migration.
- Only write extension changes to the selected profile's JSON or profile-owned files.
- Keep external file references as absolute paths and never delete external targets.
- Removing a file from a workflow removes only the reference; deleting a profile-owned file is a separate confirmed action.
- Validate JSON, profile IDs, dynamic references, and paths; keep a backup before replacing JSON.
- Never advance the selected workflow step if file resolution or clipboard write fails.

## Acceptance criteria

1. Two profiles remain independent and persist across VS Code reloads.
2. Editing a linked file in VS Code is reflected in Preview immediately.
3. Dynamic references resolve a renamed chapter file from the selected current chapter and reject ambiguous matches.
4. Copy Step places file references rather than a text-only result on Windows clipboard, then advances exactly once.
5. Import Launcher merges supported profiles/groups/targets without changing the selected source config.
6. Settings, progress, profile management, workflow management, file management, and launcher actions are available through functioning VS Code commands.
7. The `.vsix` can be packaged and installed before the desktop application is retired.

## Verification limits

The initial Node unit tests verify data and command logic. Windows clipboard behavior must be verified in a real VS Code Extension Development Host and tested with the user's normal paste/attach workflow before claiming full parity.
