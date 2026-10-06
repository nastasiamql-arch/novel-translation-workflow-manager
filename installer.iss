#define MyAppName "Palantir: Novel"
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif
#define MyAppPublisher "Palantir Novel"
#define MyAppExeName "NovelWorkflow.exe"

[Setup]
AppId={{B93AE24C-43D9-4D38-A880-93A607EA8D41}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\NovelWorkflow
DefaultGroupName=Palantir Novel
DisableProgramGroupPage=yes
OutputDir=dist
OutputBaseFilename=NovelWorkflow-Setup-{#MyAppVersion}
SetupIconFile=assets\palantir_novel.ico
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
; Remove Qt files from older flat-layout builds before installing the isolated bundle.
Type: files; Name: "{app}\Qt6*.dll"
Type: files; Name: "{app}\shiboken6*.dll"
Type: filesandordirs; Name: "{app}\PySide6"
; Remove shortcuts from the previous product name during an in-place upgrade.
Type: files; Name: "{autoprograms}\NovelWorkflow.lnk"
Type: files; Name: "{autodesktop}\NovelWorkflow.lnk"

[Icons]
Name: "{autoprograms}\Palantir Novel"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"; IconIndex: 0
Name: "{autodesktop}\Palantir Novel"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"; IconIndex: 0; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"; Flags: unchecked

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch Palantir: Novel"; Flags: nowait postinstall; Check: IsManualInteractiveInstall


[Code]
function IsManualInteractiveInstall(): Boolean;
begin
  { In-app updates are relaunched by the detached helper after checking exit code. }
  Result := (not WizardSilent) and (ExpandConstant('{param:PALANTIRUPDATE|0}') <> '1');
end;
