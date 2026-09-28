$ErrorActionPreference = "Stop"
$appPath = Join-Path $PSScriptRoot "..\dist\NovelWorkflow\NovelWorkflow.exe"
if (-not (Test-Path -LiteralPath $appPath)) {
    throw "Packaged app was not found: $appPath"
}

$app = Start-Process -FilePath $appPath -PassThru
try {
    Start-Sleep -Seconds 5
    $app.Refresh()
    if ($app.HasExited) {
        throw "Packaged app exited during startup with code $($app.ExitCode)."
    }
    Write-Host "Packaged app started successfully."
}
finally {
    if (-not $app.HasExited) {
        Stop-Process -Id $app.Id -Force
    }
}
