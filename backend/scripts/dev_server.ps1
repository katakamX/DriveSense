<#
.SYNOPSIS
    Development launcher for the DriveSense backend: frees the port, then starts.

.DESCRIPTION
    `run.py` starts uvicorn with --reload, which runs the application in a
    spawned child process. When the parent reloader dies with its terminal the
    child is orphaned, inherits the listening socket, and keeps serving.

    That orphan is hard to spot: the socket table still attributes the port to
    the *parent* PID, which no longer exists, so `Stop-Process` on the PID that
    netstat reports fails with "no such process" while the port stays occupied.
    A fresh `run.py` then loses the bind (WinError 10048), the error scrolls
    past, and requests keep hitting the stale process -- so tests pass against
    code that is no longer running.

    This script kills the listener owners *and their orphaned children*, then
    confirms the port is genuinely free by connecting to it rather than by
    trusting the socket table. If anything still answers it refuses to start,
    because starting is exactly what produces the silent false pass.

    Development only. Production runs the container image (docker-compose.yml).
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# Must match the port run.py binds.
$Port = 8000

$backendRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $backendRoot '.venv\Scripts\python.exe'
$entrypoint = Join-Path $backendRoot 'run.py'

if (-not (Test-Path $python)) {
    Write-Error "No virtualenv interpreter at $python. Create it first: python -m venv .venv; .venv\Scripts\pip install -e `".[dev]`""
}

# Ground truth. The socket table lies about orphaned children, a TCP connect
# does not.
function Test-PortOccupied {
    param([int]$Port)

    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $attempt = $client.BeginConnect('127.0.0.1', $Port, $null, $null)
        if (-not $attempt.AsyncWaitHandle.WaitOne(300)) { return $false }
        $client.EndConnect($attempt)
        return $true
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

# Listener owners plus any process parented to one of them. Windows keeps
# ParentProcessId after the parent exits, which is what makes the orphaned
# reload child findable at all.
function Get-PortHolder {
    param([int]$Port)

    $owners = @()
    try {
        $owners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop |
            Select-Object -ExpandProperty OwningProcess -Unique)
    } catch {
        return @()
    }
    if ($owners.Count -eq 0) { return @() }

    $children = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $owners -contains $_.ParentProcessId } |
        Select-Object -ExpandProperty ProcessId)

    return @($owners + $children | Select-Object -Unique)
}

for ($pass = 1; $pass -le 3 -and (Test-PortOccupied -Port $Port); $pass++) {
    $holders = Get-PortHolder -Port $Port
    if ($holders.Count -eq 0) {
        Write-Warning "Port $Port answers but reports no owner; retrying."
    }

    foreach ($holderId in $holders) {
        $process = Get-Process -Id $holderId -ErrorAction SilentlyContinue
        if ($process) {
            Write-Host "Stopping $($process.ProcessName) (PID $holderId) on port $Port"
        } else {
            # The dead reloader parent the socket table still points at.
            Write-Host "Clearing stale listener entry (PID $holderId) on port $Port"
        }
        try { Stop-Process -Id $holderId -Force -ErrorAction Stop } catch { }
    }

    # Sockets are released a moment after the owning process goes away.
    for ($i = 0; $i -lt 20 -and (Test-PortOccupied -Port $Port); $i++) {
        Start-Sleep -Milliseconds 250
    }
}

if (Test-PortOccupied -Port $Port) {
    Write-Error "Port $Port is still answering after cleanup. Refusing to start -- the server would fail to bind and requests would silently keep hitting the stale process. Investigate with: Get-NetTCPConnection -LocalPort $Port -State Listen"
}

Write-Host "Port $Port is free. Starting backend on http://127.0.0.1:$Port"
& $python $entrypoint
