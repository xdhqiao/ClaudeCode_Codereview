param(
    [string]$Python = ".\.venv\Scripts\python.exe",
    [switch]$IncludeWindows,
    [switch]$IncludeDockerImages,
    [int]$MaxPartSizeMB = 90
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$PythonPath = (Resolve-Path (Join-Path $Root $Python)).Path
$Requirements = Join-Path $Root "requirements\offline-runtime.txt"
$Staging = Join-Path $Root "vendor\staging"
$Bundles = Join-Path $Root "vendor\bundles"

New-Item -ItemType Directory -Force -Path $Staging, $Bundles | Out-Null

function Download-Wheelhouse {
    param(
        [string]$Name,
        [string[]]$PipArguments
    )

    $Destination = Join-Path $Staging $Name
    if (Test-Path $Destination) {
        Remove-Item -LiteralPath $Destination -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null

    & $PythonPath -m pip download `
        --dest $Destination `
        --only-binary=:all: `
        --implementation cp `
        --python-version 312 `
        --abi cp312 `
        @PipArguments `
        -r $Requirements
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to download wheelhouse: $Name"
    }

    if ($Name -eq "linux-x86_64-py312") {
        & $PythonPath (Join-Path $Root "scripts\verify_offline_wheelhouse.py") `
            $Destination `
            --write-manifest (Join-Path $Destination "manifest.json")
        if ($LASTEXITCODE -ne 0) {
            throw "Linux wheelhouse runtime validation failed"
        }
    }

    & $PythonPath (Join-Path $Root "scripts\wheelhouse_manifest.py") `
        --wheelhouse $Destination `
        --output (Join-Path $Bundles "$Name-packages.json") `
        --require-claude-cli
    if ($LASTEXITCODE -ne 0) {
        throw "Wheelhouse validation failed: $Name"
    }

    $Output = Join-Path $Bundles "$Name-wheels.zip"
    & $PythonPath (Join-Path $Root "scripts\offline_artifacts.py") pack `
        --source $Destination `
        --output $Output `
        --max-part-size-mb $MaxPartSizeMB `
        --remove-source
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to package wheelhouse: $Name"
    }
}

Download-Wheelhouse -Name "linux-x86_64-py312" -PipArguments @(
    "--platform", "manylinux_2_17_x86_64",
    "--platform", "manylinux2014_x86_64"
)

if ($IncludeWindows) {
    Download-Wheelhouse -Name "windows-x86_64-py312" -PipArguments @(
        "--platform", "win_amd64"
    )
}

if ($IncludeDockerImages) {
    docker build -f (Join-Path $Root "Dockerfile.base") `
        -t ai-code-review-base:python3.12 $Root
    if ($LASTEXITCODE -ne 0) { throw "Failed to build base image" }

    & $PythonPath (Join-Path $Root "scripts\restore_offline_artifacts.py") `
        --platform linux-x86_64-py312
    if ($LASTEXITCODE -ne 0) { throw "Failed to restore Linux wheelhouse" }

    docker build -f (Join-Path $Root "Dockerfile.offline") `
        -t ai-code-review:offline $Root
    if ($LASTEXITCODE -ne 0) { throw "Failed to build reviewer image" }

    docker pull mongo:7
    if ($LASTEXITCODE -ne 0) { throw "Failed to pull MongoDB image" }

    $ImageDirectory = Join-Path $Staging "docker-images"
    New-Item -ItemType Directory -Force -Path $ImageDirectory | Out-Null
    $ImageTar = Join-Path $ImageDirectory "ai-code-review-images.tar"
    docker save -o $ImageTar `
        ai-code-review-base:python3.12 `
        ai-code-review:offline `
        mongo:7
    if ($LASTEXITCODE -ne 0) { throw "Failed to export Docker images" }

    & $PythonPath (Join-Path $Root "scripts\offline_artifacts.py") pack `
        --source $ImageDirectory `
        --output (Join-Path $Bundles "docker-images-linux-x86_64.zip") `
        --max-part-size-mb $MaxPartSizeMB `
        --remove-source
    if ($LASTEXITCODE -ne 0) { throw "Failed to package Docker images" }
}

Get-ChildItem $Bundles -Filter "*.parts.json" | ForEach-Object {
    & $PythonPath (Join-Path $Root "scripts\offline_artifacts.py") verify `
        --manifest $_.FullName
    if ($LASTEXITCODE -ne 0) {
        throw "Artifact verification failed: $($_.Name)"
    }
}

Write-Host "Offline bundle preparation completed: $Bundles"
