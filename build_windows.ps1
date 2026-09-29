$ErrorActionPreference = "Stop"

$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
$pythonIsUsable = $false
if ($pythonCommand) {
    & $pythonCommand.Source -c "import sys" 2>$null
    $pythonIsUsable = ($LASTEXITCODE -eq 0)
}

if ($pythonIsUsable) {
    & $pythonCommand.Source -m venv .venv
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    py -3 -m venv .venv
} else {
    throw "Python 3.10 or newer is required. Install Python, then run this script again."
}
if ($LASTEXITCODE -ne 0) { throw "Could not create the build environment." }

$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
& $venvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "Could not install pip." }

& $venvPython -m pip install -e ".[dev]"
if ($LASTEXITCODE -ne 0) { throw "Could not install the app dependencies." }

$version = & $venvPython -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])"
if ($LASTEXITCODE -ne 0 -or -not $version) {
    throw "Could not read the project version from pyproject.toml."
}
$version = $version.Trim()

& $venvPython -m PyInstaller --noconfirm --clean (Join-Path $PSScriptRoot "NovelWorkflow.spec")
if ($LASTEXITCODE -ne 0) { throw "Could not build NovelWorkflow." }

$appExe = Join-Path $PSScriptRoot "dist\NovelWorkflow\NovelWorkflow.exe"
if (-not (Test-Path -LiteralPath $appExe)) {
    throw "The Windows app executable was not created."
}

$isccCandidates = @(
    (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
    (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe")
) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }

if (-not $isccCandidates) {
    throw "Inno Setup 6 is required to build the installer. Install it and run this script again."
}

$iscc = $isccCandidates | Select-Object -First 1
& $iscc "/DMyAppVersion=$version" (Join-Path $PSScriptRoot "installer.iss")
if ($LASTEXITCODE -ne 0) { throw "Could not build the Windows installer." }

$installer = Join-Path $PSScriptRoot "dist\NovelWorkflow-Setup-$version.exe"
if (-not (Test-Path -LiteralPath $installer)) {
    throw "The Windows installer was not created: $installer"
}

Write-Output "Installer ready: $installer"
