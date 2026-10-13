# NovelWorkflow for VS Code

NovelWorkflow is being moved from the Python/PySide6 desktop application into a Visual Studio Code extension. The extension is designed to use VS Code's native file explorer and editor while preserving the existing novel profile data.

## Current implementation

- Uses the same data folder as the desktop app: `%LOCALAPPDATA%\NovelTranslationWorkflowManager`.
- Shows profiles, groups, workflow steps, and step files in a VS Code Activity Bar view.
- Supports independent profiles, three default Thai steps, custom steps, workflow templates, groups, launcher targets, covers, Context tracking, and chapter goals.
- Opens and edits text files in the native VS Code editor; links to external files continue to read the source file on every preview/copy.
- Supports current source/translated/reviewed chapter references. Chapter filenames may use any name that includes the chapter number; ambiguous matches are reported.
- `COPY STEP` writes the selected enabled files to the Windows file-drop clipboard (`CF_HDROP`) through Windows PowerShell and advances to the next step only after the clipboard operation succeeds. It does not convert the files into copied text.
- Preview opens an editor document with the assembled file contents and headings.
- Import Novel Launcher reads the selected `config.json` and merges its profiles, groups, launcher targets, goals, and covers without changing the input file.
- JSON updates are atomic and retain a `.bak` copy. Profile data is validated before it is shown.

## Install for development

1. Open this `vscode-extension` folder in VS Code.
2. Run `npm run check` in the integrated terminal.
3. Press `F5` to open an Extension Development Host.
4. Use the NovelWorkflow Activity Bar view. The `+` action creates a profile.

The development host points at the existing profile directory by default. Use the `novelWorkflow.dataRoot` setting to test with a disposable data folder.

## Package

With Node.js and `@vscode/vsce` available:

```powershell
npx --yes @vscode/vsce package --no-dependencies
```

Install the generated `.vsix` with **Extensions: Install from VSIX...**. Do not remove the desktop app until the user's real profiles and daily workflow have been validated in the extension.

## Commands

Open the Command Palette and search `NovelWorkflow:` for profile, step, file, group, import, and progress actions. The view's context menu shows actions relevant to the selected item. `Ctrl+Shift+C` copies enabled files from the current step while the NovelWorkflow view is focused. `Ctrl+P` previews and `Ctrl+R` refreshes while that view is focused.

## Verification boundary

`npm run check` exercises the profile storage, dynamic chapter resolution, preview assembly, Context-based chapter tracking, Windows clipboard command construction, and checks that contributed commands are registered. It does not itself prove that a browser accepts pasted files or that every VS Code command has been clicked in a live Extension Development Host.
