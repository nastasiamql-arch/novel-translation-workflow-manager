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

& $venvPython -m PyInstaller --noconfirm --clean (Join-Path $PSScriptRoot "NovelWorkflow.spec")
if ($LASTEXITCODE -ne 0) { throw "Could not build NovelWorkflow." }

$portableDir = Join-Path $PSScriptRoot "dist\NovelWorkflow"
if (-not (Test-Path -LiteralPath (Join-Path $portableDir "NovelWorkflow.exe"))) {
    throw "The Windows app executable was not created."
}
$zipPath = Join-Path $PSScriptRoot "dist\NovelWorkflow-windows.zip"
$portableFiles = Get-ChildItem -LiteralPath $portableDir -Force
Compress-Archive -Path $portableFiles.FullName -DestinationPath $zipPath -Force
Write-Output "Ready-to-run app: $zipPath"
