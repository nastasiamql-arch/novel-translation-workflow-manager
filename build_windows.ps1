$ErrorActionPreference = "Stop"

$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
$pythonIsUsable = $false
if ($pythonCommand) {
    try {
        & $pythonCommand.Source -c "import sys" 2>$null
        $pythonIsUsable = ($LASTEXITCODE -eq 0)
    } catch {
        # Windows Store execution aliases can exist on PATH without Python installed.
        $pythonIsUsable = $false
    }
}

$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$buildEnvReady = $false
if (Test-Path -LiteralPath $venvPython) {
    & $venvPython -c "import sys; raise SystemExit(sys.version_info < (3, 10))" 2>$null
    $buildEnvReady = ($LASTEXITCODE -eq 0)
}

if (-not $buildEnvReady) {
    if ($pythonIsUsable) {
        & $pythonCommand.Source -m venv .venv
    } elseif (Get-Command py -ErrorAction SilentlyContinue) {
        py -3 -m venv .venv
    } else {
        throw "Python 3.10 or newer is required. Install Python, then run this script again."
    }
    if ($LASTEXITCODE -ne 0) { throw "Could not create the build environment." }
}

if (-not (Test-Path -LiteralPath $venvPython)) {
    throw "Could not create the build environment."
}
& $venvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "Could not install pip." }

& $venvPython -m pip install -e ".[dev]"
if ($LASTEXITCODE -ne 0) { throw "Could not install the app dependencies." }

$version = & $venvPython -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])"
if ($LASTEXITCODE -ne 0 -or -not $version) {
    throw "Could not read the project version from pyproject.toml."
}
$version = $version.Trim()

$buildPath = $env:PATH
try {
    # PyInstaller resolves Qt's ICU imports using PATH. Keep unrelated tools
    # (for example Poppler's ICU 78 DLLs) out of that lookup so they cannot be
    # copied into the app bundle in place of Windows' compatible ICU runtime.
    $env:PATH = @(
        (Split-Path -Parent $venvPython),
        (Join-Path $env:SystemRoot "System32"),
        $env:SystemRoot
    ) -join [System.IO.Path]::PathSeparator
    & $venvPython -m PyInstaller --noconfirm --clean (Join-Path $PSScriptRoot "NovelWorkflow.spec")
    $pyInstallerExitCode = $LASTEXITCODE
} finally {
    $env:PATH = $buildPath
}
if ($pyInstallerExitCode -ne 0) { throw "Could not build NovelWorkflow." }

$appExe = Join-Path $PSScriptRoot "dist\NovelWorkflow\NovelWorkflow.exe"
if (-not (Test-Path -LiteralPath $appExe)) {
    throw "The Windows app executable was not created."
}

$runtimeCheck = @'
import ctypes
import os
import sys
from pathlib import Path

bundle = Path(sys.argv[1]).resolve()
directories = (bundle / "PySide6", bundle / "shiboken6")
handles = [os.add_dll_directory(str(directory)) for directory in directories if directory.is_dir()]
ctypes.WinDLL(str(bundle / "PySide6" / "Qt6Core.dll"))
import PySide6
import shiboken6
PySide6.__path__.insert(0, str(bundle / "PySide6"))
shiboken6.__path__.insert(0, str(bundle / "shiboken6"))
from PySide6 import QtCore, QtGui, QtWidgets
print("Packaged Qt runtime OK:", QtCore.qVersion(), QtCore.__file__)
'@
$runtimeCheckScript = Join-Path $PSScriptRoot "build\qt_runtime_check.py"
[System.IO.File]::WriteAllText(
    $runtimeCheckScript,
    $runtimeCheck,
    [System.Text.UTF8Encoding]::new($false)
)
& $venvPython $runtimeCheckScript (Join-Path $PSScriptRoot "dist\NovelWorkflow\_internal")
if ($LASTEXITCODE -ne 0) {
    throw "The packaged Qt runtime could not import PySide6 modules."
}
$runtimeProbe = Start-Process -FilePath $appExe -ArgumentList "--check-runtime" -PassThru -Wait -WindowStyle Hidden
if ($runtimeProbe.ExitCode -ne 0) {
    throw "The frozen app could not load its Qt runtime (exit $($runtimeProbe.ExitCode))."
}

$isccCandidates = @(
    (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
    (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe"),
    (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe")
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
