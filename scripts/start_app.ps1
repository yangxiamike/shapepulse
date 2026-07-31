$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$RuntimeDir = Join-Path $ProjectRoot ".runtime"
New-Item -ItemType Directory -Path $RuntimeDir -Force | Out-Null

$pnpmCommand = Get-Command pnpm.cmd -ErrorAction SilentlyContinue
if (-not $pnpmCommand) {
    throw "pnpm was not found. Install Node.js and pnpm first."
}
$pnpm = $pnpmCommand.Source

function Test-LocalUrl([string]$Uri) {
    try {
        Invoke-WebRequest -Uri $Uri -UseBasicParsing -TimeoutSec 2 | Out-Null
        return $true
    } catch {
        return $false
    }
}

function Test-FrontendPath([string]$Path) {
    foreach ($baseUrl in @(
        "http://127.0.0.1:3000",
        "http://localhost:3000",
        "http://[::1]:3000"
    )) {
        if (Test-LocalUrl "$baseUrl$Path") {
            return $true
        }
    }
    return $false
}

$timelinePath = "/template-breadth-v3-timelines/fresh_breakout.json"
$defaultPage = "http://127.0.0.1:3000/template-breadth-v3"

$backend = $null
$frontend = $null
if (-not (Test-LocalUrl "http://127.0.0.1:8765/api/health")) {
    $backendCommand = "Set-Location -LiteralPath '$ProjectRoot'; powershell -ExecutionPolicy Bypass -File '.\scripts\start_backend.ps1' --port 8765"
    $backend = Start-Process powershell -ArgumentList "-NoProfile", "-Command", $backendCommand -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $RuntimeDir "backend.log") -RedirectStandardError (Join-Path $RuntimeDir "backend-error.log")
}

if ((Test-FrontendPath "/") -and -not (Test-FrontendPath $timelinePath)) {
    throw "Port 3000 is serving an older ShapePulse version or another app. Stop it before starting V2.7.1."
}

if (-not (Test-FrontendPath $timelinePath)) {
    $frontendCommand = "Set-Location -LiteralPath '$ProjectRoot'; & '$pnpm' dev --host 127.0.0.1 --port 3000"
    $frontend = Start-Process powershell -ArgumentList "-NoProfile", "-Command", $frontendCommand -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $RuntimeDir "frontend.log") -RedirectStandardError (Join-Path $RuntimeDir "frontend-error.log")
}

[pscustomobject]@{
    backend = if ($backend) { $backend.Id } else { $null }
    frontend = if ($frontend) { $frontend.Id } else { $null }
} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $RuntimeDir "processes.json") -Encoding UTF8

for ($attempt = 0; $attempt -lt 60; $attempt++) {
    if (
        (Test-LocalUrl "http://127.0.0.1:8765/api/health") -and
        (Test-FrontendPath $timelinePath)
    ) {
        Start-Process $defaultPage
        Write-Host "ShapePulse V2.7.1 is ready: $defaultPage"
        exit 0
    }
    Start-Sleep -Seconds 1
}
throw "Startup timed out. Check logs in the .runtime directory."
