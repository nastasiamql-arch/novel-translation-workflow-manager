#define MyAppName "NovelWorkflow"
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif
#define MyAppPublisher "NovelWorkflow"
#define MyAppExeName "NovelWorkflow.exe"

[Setup]
AppId={{B93AE24C-43D9-4D38-A880-93A607EA8D41}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\NovelWorkflow
DefaultGroupName=NovelWorkflow
DisableProgramGroupPage=yes
OutputDir=dist
OutputBaseFilename=NovelWorkflow-Setup-{#MyAppVersion}
SetupIconFile=assets\novelworkflow.ico
UninstallDisplayIcon={app}\NovelWorkflow.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
CloseApplications=yes
RestartApplications=no

[Files]
Source: "dist\NovelWorkflow\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; Remove Qt files from older flat-layout builds before installing the isolated bundle.
Type: files; Name: "{app}\Qt6*.dll"
Type: files; Name: "{app}\shiboken6*.dll"
Type: filesandordirs; Name: "{app}\PySide6"

[Icons]
Name: "{autoprograms}\NovelWorkflow"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\NovelWorkflow"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"; Flags: unchecked

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch NovelWorkflow"; Flags: nowait postinstall skipifsilent
