"""Detached Windows updater: wait, verify again, install, log and relaunch.

The helper is written outside the installation so Setup can replace the bundle.
No credentials are passed to the helper or installer.
"""
from pathlib import Path
import json
import os
import subprocess
import sys
from .storage import write_json
from .updater import UpdateError

APP_ID = 'B93AE24C-43D9-4D38-A880-93A607EA8D41'


def installer_arguments(install_dir, log_path):
    return ['/VERYSILENT', '/SP-', '/NORESTART', '/CLOSEAPPLICATIONS',
            '/NORESTARTAPPLICATIONS', '/PALANTIRUPDATE=1',
            f'/DIR={Path(install_dir).resolve()}', f'/LOG={Path(log_path).resolve()}']


HELPER = r'''
param([string]$Manifest)
$ErrorActionPreference = 'Stop'
$task = Get-Content -LiteralPath $Manifest -Raw | ConvertFrom-Json
$resultPath = $task.result
$exitCode = -1
$canRestart = $false
try {
    $oldProcess = Get-Process -Id $task.pid -ErrorAction SilentlyContinue
    if ($oldProcess -and -not $oldProcess.WaitForExit(120000)) { throw 'Palantir did not close within two minutes. Update cancelled.' }
    $canRestart = $true
    $installer = Get-Item -LiteralPath $task.installer
    if ($installer.Length -ne $task.size) { throw 'Installer size changed after download.' }
    $stream = [System.IO.File]::OpenRead($task.installer)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try { $digest = [System.BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-', '').ToLowerInvariant() }
    finally { $stream.Dispose(); $sha.Dispose() }
    if ($digest -ne $task.sha256) { throw 'Installer SHA-256 changed after download.' }
    $arguments = @('/VERYSILENT', '/SP-', '/NORESTART', '/CLOSEAPPLICATIONS', '/NORESTARTAPPLICATIONS', '/PALANTIRUPDATE=1', ('/DIR="' + $task.install_dir + '"'), ('/LOG="' + $task.log + '"'))
    $setup = Start-Process -FilePath $task.installer -ArgumentList $arguments -WindowStyle Hidden -PassThru -Wait
    $exitCode = $setup.ExitCode
    if ($exitCode -ne 0) { throw ('Installer failed with exit code ' + $exitCode + '. See ' + $task.log) }
    if (-not (Test-Path -LiteralPath $task.executable)) { throw 'Installed executable is missing.' }
    $probe = Start-Process -FilePath $task.executable -ArgumentList @('--check-runtime', '--expected-version', $task.version) -WindowStyle Hidden -PassThru -Wait
    if ($probe.ExitCode -ne 0) { throw ('Installed executable failed version/runtime verification for v' + $task.version + '. See ' + $task.log) }
    $result = @{success=$true; version=$task.version; log=$task.log; exit_code=$exitCode}
} catch {
    $result = @{success=$false; version=$task.version; log=$task.log; exit_code=$exitCode; error=$_.Exception.Message}
}
$tempResult = $resultPath + '.part'
$result | ConvertTo-Json | Set-Content -LiteralPath $tempResult -Encoding UTF8
Move-Item -LiteralPath $tempResult -Destination $resultPath -Force
try {
    if ($canRestart) { Start-Process -FilePath $task.executable -WindowStyle Hidden }
    else { throw $result.error }
} catch {
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show(('Palantir could not restart. ' + $result.error + ' See ' + $task.log), 'Palantir update')
}
'''


def launch_update(installer, update, data_dir, executable=None):
    if executable is None and not getattr(sys, 'frozen', False):
        raise UpdateError('อัปเดตในโปรแกรมได้เฉพาะรุ่นที่ติดตั้งแล้ว')
    executable = Path(executable or sys.executable).resolve()
    directory = Path(data_dir) / 'updates'
    directory.mkdir(parents=True, exist_ok=True)
    script = directory / 'apply-update.ps1'
    script.write_text(HELPER, encoding='utf-8-sig')
    manifest = directory / 'pending-update.json'
    write_json(manifest, dict(pid=os.getpid(), installer=str(Path(installer).resolve()),
        executable=str(executable), install_dir=str(executable.parent), size=update.size,
        sha256=update.sha256, version=update.version,
        result=str(directory / 'result.json'), log=str(directory / 'installer.log')))
    return subprocess.Popen(['powershell.exe', '-NoProfile', '-NonInteractive',
        '-ExecutionPolicy', 'Bypass', '-File', str(script), '-Manifest', str(manifest)],
        close_fds=True, creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))


def read_update_result(data_dir):
    path = Path(data_dir) / 'updates' / 'result.json'
    if not path.is_file(): return None
    try: result = json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError): return None
    path.unlink(missing_ok=True)
    return result
