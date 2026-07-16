$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ProcessFile = Join-Path $ProjectRoot ".runtime\processes.json"
if (-not (Test-Path -LiteralPath $ProcessFile)) {
    Write-Host "No local process record was found."
    exit 0
}
$state = Get-Content -LiteralPath $ProcessFile -Raw | ConvertFrom-Json
foreach ($id in @($state.backend, $state.frontend)) {
    if ($id) { Stop-Process -Id $id -ErrorAction SilentlyContinue }
}
Write-Host "Local market workbench has stopped."
