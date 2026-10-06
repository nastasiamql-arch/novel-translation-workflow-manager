param([Parameter(Mandatory=$true)][string]$Version)
$ErrorActionPreference = 'Stop'
if ($env:GITHUB_ACTIONS -ne 'true' -or -not $env:RUNNER_TEMP) {
    throw 'Run this installation test only on a disposable GitHub Actions runner.'
}
$taskRoot = Join-Path $env:RUNNER_TEMP ('palantir-upgrade-' + [guid]::NewGuid().ToString('N'))
$installDir = Join-Path $taskRoot 'existing installation'
$installer = (Resolve-Path -LiteralPath "dist/NovelWorkflow-Setup-$Version.exe").Path
New-Item -ItemType Directory -Path $taskRoot -Force | Out-Null

function Install-TestBuild([bool]$First) {
    $arguments = @('/VERYSILENT', '/SP-', '/NORESTART', '/PALANTIRUPDATE=1', '/TASKS=""', ('/LOG="' + (Join-Path $taskRoot 'setup.log') + '"'))
    if ($First) { $arguments += '/DIR="' + $installDir + '"' }
    $process = Start-Process -FilePath $installer -ArgumentList $arguments -WindowStyle Hidden -PassThru -Wait
    if ($process.ExitCode -ne 0) { throw "Setup failed: $($process.ExitCode)" }
}

Install-TestBuild $true
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
$probe = Start-Process -FilePath $executable -ArgumentList @('--check-runtime', '--expected-version', $Version) -WindowStyle Hidden -PassThru -Wait
if ($probe.ExitCode -ne 0) { throw 'Stale metadata changed executable version.' }
$wrongVersion = Start-Process -FilePath $executable -ArgumentList @('--check-runtime', '--expected-version', '1.12.0') -WindowStyle Hidden -PassThru -Wait
if ($wrongVersion.ExitCode -eq 0) { throw 'Version verification accepted the wrong version.' }

$dataDir = Join-Path $env:LOCALAPPDATA 'NovelWorkflow'
New-Item -ItemType Directory -Path $dataDir -Force | Out-Null
$sentinel = Join-Path $dataDir ('upgrade-test-' + [guid]::NewGuid().ToString('N') + '.json')
Set-Content -LiteralPath $sentinel -Value '{"profile":"preserved","context":"unchanged"}' -Encoding UTF8
$dataBefore = Get-FileHash -LiteralPath $sentinel -Algorithm SHA256
$unrelated = Join-Path $installDir 'user-note.txt'
Set-Content -LiteralPath $unrelated -Value 'retain unrelated files' -Encoding UTF8
$shortcut = Join-Path $env:APPDATA 'Microsoft/Windows/Start Menu/Programs/Palantir Novel.lnk'
$shortcutBefore = (New-Object -ComObject WScript.Shell).CreateShortcut($shortcut).TargetPath
if ($shortcutBefore -ne $executable) { throw 'Shortcut points to another installation.' }
$exeBefore = (Get-FileHash -LiteralPath $executable -Algorithm SHA256).Hash
# Make replacement observable without corrupting the executable used for the first probe.
Set-Content -LiteralPath $executable -Value 'old executable placeholder' -Encoding UTF8

# No /DIR: UsePreviousAppDir must select the installation from the first run.
Install-TestBuild $false
if ((Get-FileHash -LiteralPath $executable -Algorithm SHA256).Hash -ne $exeBefore) { throw 'Executable was not replaced in the existing directory.' }
if ((Get-FileHash -LiteralPath $sentinel -Algorithm SHA256).Hash -ne $dataBefore.Hash) { throw 'User data changed.' }
if (-not (Test-Path -LiteralPath $unrelated)) { throw 'Unrelated install file was deleted.' }
foreach ($folder in $oldMetadata) { if (Test-Path -LiteralPath $folder) { throw "Stale metadata remains: $folder" } }
$metadata = @(Get-ChildItem -LiteralPath (Join-Path $installDir '_internal') -Directory -Filter 'novelworkflow-*.dist-info')
if ($metadata.Count -ne 1 -or $metadata[0].Name -ne "novelworkflow-$Version.dist-info") { throw 'Incorrect installed metadata.' }
if ((New-Object -ComObject WScript.Shell).CreateShortcut($shortcut).TargetPath -ne $shortcutBefore) { throw 'Shortcut target changed.' }
$probe = Start-Process -FilePath $executable -ArgumentList @('--check-runtime', '--expected-version', $Version) -WindowStyle Hidden -PassThru -Wait
if ($probe.ExitCode -ne 0) { throw 'Upgraded executable version/runtime verification failed.' }
Write-Output 'Silent installer upgrade PASS: stale metadata, executable, previous directory, shortcut and user data.'
