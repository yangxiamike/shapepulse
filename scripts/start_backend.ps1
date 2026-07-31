$ErrorActionPreference = "Stop"
$env:PYTHONIOENCODING = "utf-8"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot

$uvCommand = Get-Command uv -ErrorAction SilentlyContinue
if (-not $uvCommand) {
    throw "uv was not found. Install uv first: https://docs.astral.sh/uv/"
}

$candidates = @()
if ($env:ZER0SHARE_ROOT) {
    $candidates += $env:ZER0SHARE_ROOT
}
if ($env:USERPROFILE) {
    $candidates += Join-Path $env:USERPROFILE "Documents\zer0share"
}
$candidates += Join-Path (Split-Path -Parent $ProjectRoot) "zer0share"

$Zer0ShareRoot = $candidates |
    Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Container) } |
    Select-Object -First 1

if (-not $Zer0ShareRoot) {
    throw "zer0share was not found. Set ZER0SHARE_ROOT to your local zer0share directory."
}

$Zer0ShareRoot = (Resolve-Path -LiteralPath $Zer0ShareRoot).Path
$Zer0ShareConfig = if ($env:ZER0SHARE_CONFIG) {
    $env:ZER0SHARE_CONFIG
} else {
    Join-Path $Zer0ShareRoot "config\settings.toml"
}

if (-not (Test-Path -LiteralPath $Zer0ShareConfig -PathType Leaf)) {
    throw "zer0share settings were not found: $Zer0ShareConfig"
}

$env:ZER0SHARE_ROOT = $Zer0ShareRoot
$env:ZER0SHARE_CONFIG = (Resolve-Path -LiteralPath $Zer0ShareConfig).Path
& $uvCommand.Source run --project $Zer0ShareRoot python -m server @args
