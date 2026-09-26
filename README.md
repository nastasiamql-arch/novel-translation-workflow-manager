# Novel Translation Workflow Manager

A Windows desktop context manager for manual novel translation work. Create independent novel profiles, configure custom workflow steps, attach ordered files or dynamic chapter references, preview the assembled context, and copy it to the clipboard. Version 1 does not call AI or translation APIs and does not require GitHub authentication.

## Run from source

Requires Python 3.10 or newer.

    py -m venv .venv
    .\.venv\Scripts\Activate.ps1
    python -m pip install -e ".[dev]"
    python -m novel_workflow.main

## Use

Create a profile, choose the Novel Translation Basic workflow, add files to the step, and add CURRENT_SOURCE_CHAPTER (or translated/reviewed chapter). Chapter files resolve as source/chapter_25.txt, translated/chapter_25.txt, and reviewed/chapter_25.txt; Markdown and JSON extensions are also supported. Change the chapter number without editing the workflow step. Ctrl+P previews the exact output and Ctrl+Shift+C copies it.

Profile data and settings live in %LOCALAPPDATA%/NovelTranslationWorkflowManager. Each profile has separate prompts, glossary, characters, style, source, translated, reviewed, notes, reference, and custom directories. Removing a step attachment does not delete the file. Paths are constrained to the profile folder. JSON recovery only retries unambiguous trailing commas against a temporary copy; original data is preserved.

## Tests and Windows build

    python -m pytest
    .\build_windows.ps1

The build creates dist/NovelTranslationWorkflowManager.exe. GitHub Actions runs pytest and builds the Windows executable on main updates and v* tags. Tagged builds publish the executable as a GitHub Release asset.
