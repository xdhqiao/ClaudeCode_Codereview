param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Manifest = Join-Path $Root "vendor\bundles\docker-images-linux-x86_64.zip.parts.json"
$Images = Join-Path $Root "vendor\images"

$LinuxWheels = Join-Path $Root "vendor\wheels\linux-x86_64"
if (-not (Get-ChildItem -Path $LinuxWheels -Filter "*.whl" -File -ErrorAction SilentlyContinue)) {
    & $Python (Join-Path $Root "scripts\restore_offline_artifacts.py") `
        --platform linux-x86_64-py312
    if ($LASTEXITCODE -ne 0) { throw "Failed to restore Linux wheelhouse" }
}
& $Python (Join-Path $Root "scripts\verify_offline_wheelhouse.py") `
    $LinuxWheels `
    --write-manifest (Join-Path $LinuxWheels "manifest.json")
if ($LASTEXITCODE -ne 0) { throw "Linux wheelhouse validation failed" }

& $Python (Join-Path $Root "scripts\offline_artifacts.py") restore `
    --manifest $Manifest `
    --destination $Images `
    --extract
if ($LASTEXITCODE -ne 0) { throw "Failed to restore Docker image archive" }

docker load -i (Join-Path $Images "ai-code-review-images.tar")
if ($LASTEXITCODE -ne 0) { throw "Failed to load Docker images" }

Write-Host "Docker images and Linux wheelhouse restored."
