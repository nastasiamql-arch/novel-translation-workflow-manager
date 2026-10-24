#define MyAppName "Valhalla"
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif
#define MyAppPublisher "Valhalla"
#define MyAppExeName "NovelWorkflow.exe"

[Setup]
AppId={{B93AE24C-43D9-4D38-A880-93A607EA8D41}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\NovelWorkflow
DefaultGroupName=Valhalla
DisableProgramGroupPage=yes
OutputDir=dist
OutputBaseFilename=NovelWorkflow-Setup-{#MyAppVersion}
SetupIconFile=assets\valhalla.ico
UninstallDisplayIcon={app}\NovelWorkflow.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
CloseApplications=yes
RestartApplications=no
UsePreviousAppDir=yes
UsePreviousTasks=yes
UsePreviousGroup=yes

[Files]
Source: "dist\NovelWorkflow\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; Only application package metadata, never user documents/settings or all app files.
Type: filesandordirs; Name: "{app}\_internal\novelworkflow-*.dist-info"
Type: filesandordirs; Name: "{app}\novelworkflow-*.dist-info"
; Remove only obsolete AI Web Workspace payloads from previous installed bundles.
; Never touch per-user profiles, session caches or any other application package.
Type: filesandordirs; Name: "{app}\_internal\playwright"
Type: filesandordirs; Name: "{app}\_internal\playwright-*.dist-info"
Type: filesandordirs; Name: "{app}\_internal\novel_workflow\ai_workspace"
; Purge third-party web-downloader/browser packages left by older bundled builds.
; All targets are within the application install directory, never user data.
Type: filesandordirs; Name: "{app}\_internal\selectolax"
Type: filesandordirs; Name: "{app}\_internal\httpx"
Type: filesandordirs; Name: "{app}\_internal\httpcore"
Type: filesandordirs; Name: "{app}\_internal\novel_workflow\downloader"
Type: filesandordirs; Name: "{app}\_internal\novel_workflow\downloader_ui"
; Remove Qt files from older flat-layout builds before installing the isolated bundle.
Type: files; Name: "{app}\Qt6*.dll"
Type: files; Name: "{app}\shiboken6*.dll"
Type: filesandordirs; Name: "{app}\PySide6"
; Remove obsolete shortcuts only; preserve legacy install identity and executable.
Type: files; Name: "{autoprograms}\Palantir Novel.lnk"
Type: files; Name: "{autodesktop}\Palantir Novel.lnk"
; Remove shortcuts from the previous product name during an in-place upgrade.
Type: files; Name: "{autoprograms}\NovelWorkflow.lnk"
Type: files; Name: "{autodesktop}\NovelWorkflow.lnk"

[Icons]
Name: "{autoprograms}\Valhalla"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"; IconIndex: 0
Name: "{autodesktop}\Valhalla"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"; IconIndex: 0; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"; Flags: unchecked

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch Valhalla"; Flags: nowait postinstall; Check: IsManualInteractiveInstall


[Code]
function IsManualInteractiveInstall(): Boolean;
begin
  { In-app updates are relaunched by the detached helper after checking exit code. }
  Result := (not WizardSilent) and (ExpandConstant('{param:PALANTIRUPDATE|0}') <> '1');
end;
