$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$RuntimeDir = Join-Path $ProjectRoot ".runtime"
New-Item -ItemType Directory -Path $RuntimeDir -Force | Out-Null

$pnpmCommand = Get-Command pnpm.cmd -ErrorAction SilentlyContinue
if (-not $pnpmCommand) {
    $fallback = "C:\Users\hp\.cache\codex-runtimes\codex-primary-runtime\dependencies\bin\fallback\pnpm.cmd"
    if (-not (Test-Path -LiteralPath $fallback)) {
        throw "pnpm was not found. Install Node.js and pnpm first."
    }
    $pnpm = $fallback
} else {
    $pnpm = $pnpmCommand.Source
}

$backend = $null
$frontend = $null
try { Invoke-WebRequest -Uri "http://127.0.0.1:8765/api/health" -UseBasicParsing -TimeoutSec 2 | Out-Null } catch {
    $backendCommand = "Set-Location -LiteralPath '$ProjectRoot'; powershell -ExecutionPolicy Bypass -File '.\scripts\start_backend.ps1' --port 8765"
    $backend = Start-Process powershell -ArgumentList "-NoProfile", "-Command", $backendCommand -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $RuntimeDir "backend.log") -RedirectStandardError (Join-Path $RuntimeDir "backend-error.log")
}
try { Invoke-WebRequest -Uri "http://localhost:3000/" -UseBasicParsing -TimeoutSec 2 | Out-Null } catch {
    $frontendCommand = "Set-Location -LiteralPath '$ProjectRoot'; & '$pnpm' dev"
    $frontend = Start-Process powershell -ArgumentList "-NoProfile", "-Command", $frontendCommand -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $RuntimeDir "frontend.log") -RedirectStandardError (Join-Path $RuntimeDir "frontend-error.log")
}

[pscustomobject]@{
    backend = if ($backend) { $backend.Id } else { $null }
    frontend = if ($frontend) { $frontend.Id } else { $null }
} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $RuntimeDir "processes.json") -Encoding UTF8

for ($attempt = 0; $attempt -lt 60; $attempt++) {
    try {
        Invoke-WebRequest -Uri "http://127.0.0.1:8765/api/health" -UseBasicParsing -TimeoutSec 2 | Out-Null
        Invoke-WebRequest -Uri "http://localhost:3000/" -UseBasicParsing -TimeoutSec 2 | Out-Null
        Start-Process "http://localhost:3000/"
        Write-Host "Local market workbench is ready: http://localhost:3000/"
        exit 0
    } catch { Start-Sleep -Seconds 1 }
}
throw "Startup timed out. Check logs in the .runtime directory."
