param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Manifest = Join-Path $Root "vendor\bundles\docker-images-linux-x86_64.zip.parts.json"
$Images = Join-Path $Root "vendor\images"

& $Python (Join-Path $Root "scripts\offline_artifacts.py") restore `
    --manifest $Manifest `
    --destination $Images `
    --extract
if ($LASTEXITCODE -ne 0) { throw "Failed to restore Docker image archive" }

docker load -i (Join-Path $Images "ai-code-review-images.tar")
if ($LASTEXITCODE -ne 0) { throw "Failed to load Docker images" }

Write-Host "Docker images loaded."
