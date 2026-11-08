<#
.SYNOPSIS
    Starts the SentinelAI backend and frontend for this folder.

.DESCRIPTION
    Reads API_PORT and WEB_PORT from the repo-root .env (each agent folder has its own),
    starts uvicorn on API_PORT and the Vite dev server on WEB_PORT, and stops both on Ctrl+C.
    Uses backend\.venv when it exists, otherwise the python on PATH.

.EXAMPLE
    .\scripts\dev.ps1
.EXAMPLE
    .\scripts\dev.ps1 -BackendOnly
#>
[CmdletBinding()]
param(
    [switch]$BackendOnly,
    [switch]$FrontendOnly,
    [switch]$NoReload
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if ($BackendOnly -and $FrontendOnly) {
    throw 'Use -BackendOnly or -FrontendOnly, not both.'
}

$RepoRoot = Split-Path -Parent $PSScriptRoot
$BackendDir = Join-Path $RepoRoot 'backend'
$FrontendDir = Join-Path $RepoRoot 'frontend'
$EnvFile = Join-Path $RepoRoot '.env'
$OnWindows = [System.IO.Path]::DirectorySeparatorChar -eq '\'

function Read-DotEnv([string]$Path) {
    $values = @{}
    foreach ($line in Get-Content -LiteralPath $Path) {
        if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$') {
            $values[$Matches[1]] = $Matches[2].Trim('"', "'")
        }
    }
    return $values
}

function Get-Port([hashtable]$Values, [string]$Name, [int]$Default) {
    $raw = $Values[$Name]
    if ([string]::IsNullOrWhiteSpace($raw)) { return $Default }
    $port = 0
    if (-not [int]::TryParse($raw, [ref]$port) -or $port -lt 1 -or $port -gt 65535) {
        throw "$Name in .env must be a port number, got '$raw'."
    }
    return $port
}

# Node resolves "localhost" to ::1 on recent versions, so Vite may listen on IPv6 only.
$LoopbackAddresses = @([System.Net.IPAddress]::Loopback, [System.Net.IPAddress]::IPv6Loopback)

function Test-PortOpen([int]$Port) {
    foreach ($address in $LoopbackAddresses) {
        $client = [System.Net.Sockets.TcpClient]::new($address.AddressFamily)
        try {
            if ($client.ConnectAsync($address, $Port).Wait(300) -and $client.Connected) { return $true }
        } catch {
        } finally { $client.Dispose() }
    }
    return $false
}

function Wait-Port([int]$Port, [System.Diagnostics.Process]$Process, [int]$TimeoutSeconds = 60) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if ($Process.HasExited) { return $false }
        if (Test-PortOpen $Port) { return $true }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

function Stop-Tree([System.Diagnostics.Process]$Process) {
    if ($null -eq $Process -or $Process.HasExited) { return }
    if ($OnWindows) {
        & taskkill.exe /PID $Process.Id /T /F 2>&1 | Out-Null
    } else {
        $Process.Kill($true)
    }
}

if (-not (Test-Path -LiteralPath $EnvFile)) {
    throw "No .env in $RepoRoot. Run: Copy-Item .env.example .env, then set API_PORT and WEB_PORT for this folder."
}

$dotenv = Read-DotEnv $EnvFile
$ApiPort = Get-Port $dotenv 'API_PORT' 8000
$WebPort = Get-Port $dotenv 'WEB_PORT' 5173

$runBackend = -not $FrontendOnly
$runFrontend = -not $BackendOnly

foreach ($check in @(@{ Run = $runBackend; Port = $ApiPort; Name = 'API_PORT' },
                     @{ Run = $runFrontend; Port = $WebPort; Name = 'WEB_PORT' })) {
    if ($check.Run -and (Test-PortOpen $check.Port)) {
        throw "$($check.Name) $($check.Port) is already in use. Stop whatever is on it, or check this folder's .env."
    }
}

# Vite's config reads these too; setting them here keeps both servers on the same ports.
$env:API_PORT = "$ApiPort"
$env:WEB_PORT = "$WebPort"

$processes = @()
try {
    if ($runBackend) {
        $venvPython = if ($OnWindows) { Join-Path $BackendDir '.venv\Scripts\python.exe' } else { Join-Path $BackendDir '.venv/bin/python' }
        $python = if (Test-Path -LiteralPath $venvPython) { $venvPython } else { 'python' }
        if (-not (Get-Command $python -ErrorAction SilentlyContinue)) {
            throw 'Python not found. Create backend\.venv (see README Setup) or put python on PATH.'
        }
        $uvicornArgs = @('-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', "$ApiPort")
        if (-not $NoReload) { $uvicornArgs += '--reload' }

        Write-Host "Backend:  $python $($uvicornArgs -join ' ')" -ForegroundColor Cyan
        $backend = Start-Process -FilePath $python -ArgumentList $uvicornArgs -WorkingDirectory $BackendDir -NoNewWindow -PassThru
        $null = $backend.Handle  # cache the handle so ExitCode is readable after exit
        $processes += $backend
        if (-not (Wait-Port $ApiPort $backend)) {
            throw "Backend did not start on port $ApiPort. Check the output above (missing packages? run python -m pip install -r backend\requirements.txt)."
        }
    }

    if ($runFrontend) {
        $npm = if ($OnWindows) { 'npm.cmd' } else { 'npm' }
        if (-not (Get-Command $npm -ErrorAction SilentlyContinue)) {
            throw 'npm not found. Install Node 20 or newer.'
        }
        if (-not (Test-Path -LiteralPath (Join-Path $FrontendDir 'node_modules'))) {
            Write-Host 'frontend\node_modules is missing, running npm install...' -ForegroundColor Yellow
            Start-Process -FilePath $npm -ArgumentList @('install') -WorkingDirectory $FrontendDir -NoNewWindow -Wait | Out-Null
        }

        Write-Host "Frontend: npm run dev (port $WebPort, proxies /api to $ApiPort)" -ForegroundColor Cyan
        $frontend = Start-Process -FilePath $npm -ArgumentList @('run', 'dev') -WorkingDirectory $FrontendDir -NoNewWindow -PassThru
        $null = $frontend.Handle
        $processes += $frontend
        if (-not (Wait-Port $WebPort $frontend)) {
            throw "Frontend did not start on port $WebPort. Check the output above."
        }
    }

    Write-Host ''
    if ($runBackend) { Write-Host "API:  http://localhost:$ApiPort/docs" -ForegroundColor Green }
    if ($runFrontend) { Write-Host "App:  http://localhost:$WebPort" -ForegroundColor Green }
    Write-Host 'Press Ctrl+C to stop.' -ForegroundColor Green

    while ($true) {
        $exited = $processes | Where-Object { $_.HasExited } | Select-Object -First 1
        if ($exited) {
            throw "A dev server exited with code $($exited.ExitCode); stopping the other one."
        }
        Start-Sleep -Seconds 1
    }
} finally {
    foreach ($process in $processes) { Stop-Tree $process }
}
