$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ProcessFile = Join-Path $ProjectRoot ".runtime\processes.json"
if (-not (Test-Path -LiteralPath $ProcessFile)) {
    Write-Host "No local process record was found."
    exit 0
}
$state = Get-Content -LiteralPath $ProcessFile -Raw | ConvertFrom-Json
function Stop-ProcessTree([int]$ProcessId) {
    $children = Get-CimInstance Win32_Process -Filter "ParentProcessId=$ProcessId" -ErrorAction SilentlyContinue
    foreach ($child in $children) {
        Stop-ProcessTree -ProcessId $child.ProcessId
    }
    Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
}
foreach ($processId in @($state.backend, $state.frontend)) {
    if ($processId) { Stop-ProcessTree -ProcessId $processId }
}
Write-Host "Local market workbench has stopped."
