#define MyAppName "Novel Downloader"
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif
#define MyAppPublisher "Palantir Novel"
#define MyAppExeName "NovelDownloader.exe"

[Setup]
AppId={{DAF0342C-6D33-4E9B-8DE7-5BBD2B3DCC09}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\NovelDownloader
DefaultGroupName=Novel Downloader
DisableProgramGroupPage=yes
OutputDir=dist
OutputBaseFilename=NovelDownloader-Setup-{#MyAppVersion}
SetupIconFile=assets\palantir_novel.ico
UninstallDisplayIcon={app}\NovelDownloader.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
CloseApplications=yes
RestartApplications=no

[Files]
Source: "dist\NovelDownloader\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Novel Downloader"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"; IconIndex: 0
Name: "{autodesktop}\Novel Downloader"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"; IconIndex: 0; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"; Flags: unchecked

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch Novel Downloader"; Flags: nowait postinstall skipifsilent
