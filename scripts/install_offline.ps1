param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

$Version = & $Python -c "import platform,sys; print(f'{sys.version_info.major}.{sys.version_info.minor}|{platform.system()}|{platform.machine().lower()}')"
if ($Version -notmatch "^3\.12\|Windows\|(amd64|x86_64)$") {
    throw "This bundle requires Windows x86_64 with Python 3.12; found $Version"
}

& $Python (Join-Path $Root "scripts\restore_offline_artifacts.py") `
    --platform windows-x86_64-py312
if ($LASTEXITCODE -ne 0) { throw "Failed to restore Windows wheelhouse" }

$Wheels = Join-Path $Root "vendor\wheels\windows-x86_64"
& $Python -m pip install --no-index --find-links $Wheels hatchling
if ($LASTEXITCODE -ne 0) { throw "Failed to install offline build dependencies" }

& $Python -m pip install --no-index --find-links $Wheels `
    --no-build-isolation $Root
if ($LASTEXITCODE -ne 0) { throw "Failed to install project offline" }

Write-Host "Offline installation completed."
