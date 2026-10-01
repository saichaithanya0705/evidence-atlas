$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$statePath = Join-Path $root "logs\dev-processes.json"

if (-not (Test-Path -LiteralPath $statePath)) {
    Write-Host "No processes were recorded by start-dev.ps1. Nothing to stop."
    exit 0
}

$entries = @(Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json)
foreach ($entry in $entries) {
    $process = Get-Process -Id ([int]$entry.pid) -ErrorAction SilentlyContinue
    if (-not $process) { continue }
    $expectedStart = [DateTime]::Parse($entry.started_at).ToUniversalTime()
    $actualStart = $process.StartTime.ToUniversalTime()
    if ([Math]::Abs(($actualStart - $expectedStart).TotalSeconds) -gt 10) {
        Write-Host "Skipping reused PID $($entry.pid); its start time does not match the launcher record."
        continue
    }

    $processIds = New-Object System.Collections.Generic.List[int]
    $processIds.Add($process.Id)
    do {
        $foundChild = $false
        foreach ($candidate in Get-CimInstance Win32_Process) {
            if ($processIds.Contains([int]$candidate.ParentProcessId) -and -not $processIds.Contains([int]$candidate.ProcessId)) {
                $processIds.Add([int]$candidate.ProcessId)
                $foundChild = $true
            }
        }
    } while ($foundChild)

    foreach ($processId in ($processIds | Sort-Object -Descending)) {
        Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
    }
    Write-Host "Stopped launcher process tree rooted at PID $($entry.pid)."
}

Remove-Item -LiteralPath $statePath -Force -ErrorAction SilentlyContinue
