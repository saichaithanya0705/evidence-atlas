$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $root ".venv\Scripts\python.exe"
$frontend = Join-Path $root "frontend"
$logs = Join-Path $root "logs"
$backendLog = Join-Path $logs "dev-backend.log"
$backendErrorLog = Join-Path $logs "dev-backend.err.log"
$frontendLog = Join-Path $logs "dev-frontend.log"
$frontendErrorLog = Join-Path $logs "dev-frontend.err.log"
$statePath = Join-Path $logs "dev-processes.json"

New-Item -ItemType Directory -Force -Path $logs | Out-Null

if (-not (Test-Path -LiteralPath $python)) {
    throw "The virtual environment is missing: $python`nRun .\start.bat once to install project dependencies."
}
if (-not (Test-Path -LiteralPath (Join-Path $frontend "node_modules"))) {
    throw "Frontend dependencies are missing: $frontend\node_modules`nRun 'npm install' from the frontend directory."
}

function Test-ListeningPort([int]$port) {
    return [bool](Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
}

function Wait-ForPort([int]$port, [System.Diagnostics.Process]$process, [int]$seconds = 75) {
    for ($attempt = 0; $attempt -lt ($seconds * 2); $attempt++) {
        if (Test-ListeningPort $port) { return $true }
        if ($process -and $process.HasExited) { return $false }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

$env:PYTHONPATH = $root
$env:PYTHONUTF8 = "1"

$backendProcess = $null
$frontendProcess = $null
$startedProcesses = @()
function Save-State {
    if ($startedProcesses.Count -eq 0) {
        Set-Content -LiteralPath $statePath -Value "[]" -Encoding utf8
    } else {
        $startedProcesses | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding utf8
    }
}

if (Test-ListeningPort 8000) {
    Write-Host "Backend already listening on http://127.0.0.1:8000"
} else {
    $backendArgs = @("-m", "uvicorn", "backend.app.main:app", "--host", "127.0.0.1", "--port", "8000")
    $backendProcess = Start-Process -FilePath $python -ArgumentList $backendArgs -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput $backendLog -RedirectStandardError $backendErrorLog -PassThru
    if (-not (Wait-ForPort 8000 $backendProcess)) {
        $errorTail = if (Test-Path -LiteralPath $backendErrorLog) { (Get-Content -LiteralPath $backendErrorLog -Tail 12) -join "`n" } else { "No backend error log was written." }
        throw "Backend did not start on port 8000.`n$errorTail"
    }
    $startedProcesses += [pscustomobject]@{ pid = $backendProcess.Id; started_at = (Get-Date).ToUniversalTime().ToString("o") }
    Save-State
    Write-Host "Backend started (PID $($backendProcess.Id)) at http://127.0.0.1:8000"
}

if (Test-ListeningPort 5173) {
    Write-Host "Frontend already listening on http://127.0.0.1:5173"
} else {
    $frontendArgs = @("run", "dev", "--", "--host", "127.0.0.1", "--port", "5173")
    $frontendProcess = Start-Process -FilePath "npm.cmd" -ArgumentList $frontendArgs -WorkingDirectory $frontend -WindowStyle Hidden -RedirectStandardOutput $frontendLog -RedirectStandardError $frontendErrorLog -PassThru
    if (-not (Wait-ForPort 5173 $frontendProcess)) {
        $errorTail = if (Test-Path -LiteralPath $frontendErrorLog) { (Get-Content -LiteralPath $frontendErrorLog -Tail 12) -join "`n" } else { "No frontend error log was written." }
        throw "Frontend did not start on port 5173.`n$errorTail"
    }
    $startedProcesses += [pscustomobject]@{ pid = $frontendProcess.Id; started_at = (Get-Date).ToUniversalTime().ToString("o") }
    Save-State
    Write-Host "Frontend started (PID $($frontendProcess.Id)) at http://127.0.0.1:5173"
}

Write-Host ""
Save-State
Write-Host "Evidence Atlas is ready: http://127.0.0.1:5173"
Write-Host "Logs: $backendLog and $frontendLog"
Write-Host "Stop newly started processes with: .\stop-dev.ps1"
