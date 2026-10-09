param([Parameter(Mandatory=$true)][string]$Version, [string]$InstallerPath)
$ErrorActionPreference = 'Stop'
if ($env:GITHUB_ACTIONS -ne 'true' -or -not $env:RUNNER_TEMP) {
    throw 'Run this installation test only on a disposable GitHub Actions runner.'
}
$taskRoot = Join-Path $env:RUNNER_TEMP ('palantir-upgrade-' + [guid]::NewGuid().ToString('N'))
$installDir = Join-Path $taskRoot 'existing installation'
$installer = if ($InstallerPath) { (Resolve-Path -LiteralPath $InstallerPath).Path } else { (Resolve-Path -LiteralPath "dist/NovelWorkflow-Setup-$Version.exe").Path }
New-Item -ItemType Directory -Path $taskRoot -Force | Out-Null

function Install-TestBuild([bool]$First, [string]$SetupPath) {
    $arguments = @('/VERYSILENT', '/SP-', '/NORESTART', '/PALANTIRUPDATE=1', '/TASKS=""', ('/LOG="' + (Join-Path $taskRoot 'setup.log') + '"'))
    if ($First) { $arguments += '/DIR="' + $installDir + '"' }
    $process = Start-Process -FilePath $SetupPath -ArgumentList $arguments -WindowStyle Hidden -PassThru -Wait
    if ($process.ExitCode -ne 0) { throw "Setup failed: $($process.ExitCode)" }
}

$previousVersion = '3.6.8'
$previousName = "NovelWorkflow-Setup-$previousVersion.exe"
gh release download "v$previousVersion" --repo nastasiamql-arch/novel-translation-workflow-manager --pattern $previousName --dir $taskRoot
if ($LASTEXITCODE -ne 0) { throw 'Could not download previous published installer.' }
$previousInstaller = Join-Path $taskRoot $previousName
$release = gh api repos/nastasiamql-arch/novel-translation-workflow-manager/releases/tags/v$previousVersion | ConvertFrom-Json
$previousAsset = $release.assets | Where-Object { $_.name -eq $previousName }
$expectedHash = $previousAsset.digest -replace '^sha256:', ''
if (-not $expectedHash -or (Get-FileHash -LiteralPath $previousInstaller -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expectedHash) { throw 'Previous installer SHA-256 verification failed.' }
Install-TestBuild $true $previousInstaller
$executable = Join-Path $installDir 'NovelWorkflow.exe'
$oldMetadata = @(
    (Join-Path $installDir '_internal/novelworkflow-1.12.0.dist-info'),
    (Join-Path $installDir '_internal/novelworkflow-99.9.9.dist-info'),
    (Join-Path $installDir 'novelworkflow-2.0.0.dist-info')
)
foreach ($folder in $oldMetadata) {
    New-Item -ItemType Directory -Path $folder -Force | Out-Null
    Set-Content -LiteralPath (Join-Path $folder 'METADATA') -Value "Name: novelworkflow`nVersion: 1.12.0" -Encoding UTF8
}
$probe = Start-Process -FilePath $executable -ArgumentList @('--check-runtime', '--expected-version', $previousVersion) -WindowStyle Hidden -PassThru -Wait
if ($probe.ExitCode -ne 0) { throw 'Stale metadata changed executable version.' }
$wrongVersion = Start-Process -FilePath $executable -ArgumentList @('--check-runtime', '--expected-version', '1.12.0') -WindowStyle Hidden -PassThru -Wait
if ($wrongVersion.ExitCode -eq 0) { throw 'Version verification accepted the wrong version.' }

$dataDir = Join-Path $env:LOCALAPPDATA 'NovelWorkflow'
New-Item -ItemType Directory -Path $dataDir -Force | Out-Null
$sentinel = Join-Path $dataDir ('upgrade-test-' + [guid]::NewGuid().ToString('N') + '.json')
Set-Content -LiteralPath $sentinel -Value '{"profile":"preserved","context":"unchanged"}' -Encoding UTF8
$dataBefore = Get-FileHash -LiteralPath $sentinel -Algorithm SHA256
$profileId = [guid]::NewGuid().ToString('N')
$profileDir = Join-Path $dataDir "profiles/$profileId"
New-Item -ItemType Directory -Path $profileDir -Force | Out-Null
$contextPath = Join-Path $taskRoot 'Context.md'
$draft = "Thai draft 中文 日本語"
Set-Content -LiteralPath $contextPath -Value "# Chapter Progress`nChapter 125" -Encoding UTF8
$profilePath = Join-Path $profileDir 'profile.json'
@{id=$profileId; name='Upgrade fixture'; schema_version=7; context_path=$contextPath;
    txt_export_draft=$draft; verified_goal_count=12; verified_goal_target=5;
    verified_export_history=@(@{success=$true; filename='verified1.txt'});
    txt_export_settings=@{filename='verified'; current=13; start=1; end=100; directory=$taskRoot}
} | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $profilePath -Encoding UTF8
$settingsPath = Join-Path $dataDir 'settings.json'
@{appearance='Light'; last_profile_id=$profileId; editor_tabs=@{$profileId=@($contextPath)};
    editor_active_tab_keys=@{$profileId=$contextPath}; workspace_step_indices=@{$profileId=1}
} | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $settingsPath -Encoding UTF8
$novelDir = Join-Path $profileDir 'source'
New-Item -ItemType Directory -Path $novelDir -Force | Out-Null
$novelPath = Join-Path $novelDir 'chapter_1.txt'
Set-Content -LiteralPath $novelPath -Value "ไทย`n`n中文" -Encoding UTF8
$recoveryDir = Join-Path $dataDir 'recovery/editor'
New-Item -ItemType Directory -Path $recoveryDir -Force | Out-Null
$recoveryPath = Join-Path $recoveryDir "$profileId.json"
Set-Content -LiteralPath $recoveryPath -Value '{"text":"unsaved ไทย 中文"}' -Encoding UTF8
$preservedFiles = @($profilePath, $settingsPath, $contextPath, $novelPath, $recoveryPath)
$preservedHashes = @{}
foreach ($path in $preservedFiles) { $preservedHashes[$path] = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash }
$unrelated = Join-Path $installDir 'user-note.txt'
Set-Content -LiteralPath $unrelated -Value 'retain unrelated files' -Encoding UTF8
$shortcut = Join-Path $env:APPDATA 'Microsoft/Windows/Start Menu/Programs/Palantir Novel.lnk'
$shortcutBefore = (New-Object -ComObject WScript.Shell).CreateShortcut($shortcut).TargetPath
if ($shortcutBefore -ne $executable) { throw 'Shortcut points to another installation.' }
$exeBefore = (Get-FileHash -LiteralPath (Join-Path $PSScriptRoot '../dist/NovelWorkflow/NovelWorkflow.exe') -Algorithm SHA256).Hash
# Make replacement observable without corrupting the executable used for the first probe.
Set-Content -LiteralPath $executable -Value 'old executable placeholder' -Encoding UTF8

# No /DIR: UsePreviousAppDir must select the installation from the first run.
Install-TestBuild $false $installer
if ((Get-FileHash -LiteralPath $executable -Algorithm SHA256).Hash -ne $exeBefore) { throw 'Executable was not replaced in the existing directory.' }
if ((Get-FileHash -LiteralPath $sentinel -Algorithm SHA256).Hash -ne $dataBefore.Hash) { throw 'User data changed.' }
foreach ($path in $preservedFiles) {
    if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -ne $preservedHashes[$path]) {
        throw "Profile, settings, Context, draft, history or workspace session changed: $path"
    }
}
if (-not (Test-Path -LiteralPath $unrelated)) { throw 'Unrelated install file was deleted.' }
foreach ($folder in $oldMetadata) { if (Test-Path -LiteralPath $folder) { throw "Stale metadata remains: $folder" } }
$metadata = @(Get-ChildItem -LiteralPath (Join-Path $installDir '_internal') -Directory -Filter 'novelworkflow-*.dist-info')
if ($metadata.Count -ne 1 -or $metadata[0].Name -ne "novelworkflow-$Version.dist-info") { throw 'Incorrect installed metadata.' }
if ((New-Object -ComObject WScript.Shell).CreateShortcut($shortcut).TargetPath -ne $shortcutBefore) { throw 'Shortcut target changed.' }
$probe = Start-Process -FilePath $executable -ArgumentList @('--check-runtime', '--expected-version', $Version) -WindowStyle Hidden -PassThru -Wait
if ($probe.ExitCode -ne 0) { throw 'Upgraded executable version/runtime verification failed.' }
Write-Output 'Silent installer upgrade PASS: stale metadata, executable, previous directory, shortcut and user data.'
