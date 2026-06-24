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
$Wheels = Join-Path $Root "vendor\wheels"

New-Item -ItemType Directory -Force -Path $Staging, $Bundles, $Wheels | Out-Null

function Download-Wheelhouse {
    param(
        [string]$Name,
        [string[]]$PipArguments,
        [string]$Destination,
        [switch]$KeepSource
    )

    $DownloadDestination = Join-Path $Staging "$Name-download"
    if (Test-Path $DownloadDestination) {
        Remove-Item -LiteralPath $DownloadDestination -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $DownloadDestination | Out-Null

    & $PythonPath -m pip download `
        --dest $DownloadDestination `
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
            $DownloadDestination `
            --write-manifest (Join-Path $DownloadDestination "manifest.json")
        if ($LASTEXITCODE -ne 0) {
            throw "Linux wheelhouse runtime validation failed"
        }
    }

    & $PythonPath (Join-Path $Root "scripts\wheelhouse_manifest.py") `
        --wheelhouse $DownloadDestination `
        --output (Join-Path $Bundles "$Name-packages.json") `
        --require-claude-cli
    if ($LASTEXITCODE -ne 0) {
        throw "Wheelhouse validation failed: $Name"
    }

    $Output = Join-Path $Bundles "$Name-wheels.zip"
    $PackArguments = @(
        (Join-Path $Root "scripts\offline_artifacts.py"),
        "pack",
        "--source", $DownloadDestination,
        "--output", $Output,
        "--max-part-size-mb", $MaxPartSizeMB
    )
    if (-not $KeepSource) {
        $PackArguments += "--remove-source"
    }
    & $PythonPath @PackArguments
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to package wheelhouse: $Name"
    }

    if ($KeepSource) {
        $Backup = "$Destination.previous"
        if (Test-Path $Backup) {
            Remove-Item -LiteralPath $Backup -Recurse -Force
        }
        if (Test-Path $Destination) {
            Move-Item -LiteralPath $Destination -Destination $Backup
        }
        try {
            Move-Item -LiteralPath $DownloadDestination -Destination $Destination
            if (Test-Path $Backup) {
                Remove-Item -LiteralPath $Backup -Recurse -Force
            }
        }
        catch {
            if (Test-Path $Destination) {
                Remove-Item -LiteralPath $Destination -Recurse -Force
            }
            if (Test-Path $Backup) {
                Move-Item -LiteralPath $Backup -Destination $Destination
            }
            throw
        }
    }
}

Download-Wheelhouse -Name "linux-x86_64-py312" -PipArguments @(
    "--platform", "manylinux_2_17_x86_64",
    "--platform", "manylinux2014_x86_64"
) -Destination (Join-Path $Wheels "linux-x86_64") -KeepSource

if ($IncludeWindows) {
    Download-Wheelhouse -Name "windows-x86_64-py312" -PipArguments @(
        "--platform", "win_amd64"
    ) -Destination (Join-Path $Staging "windows-x86_64-py312")
}

if ($IncludeDockerImages) {
    docker build -f (Join-Path $Root "Dockerfile.base") `
        -t ai-code-review-base:python3.12 $Root
    if ($LASTEXITCODE -ne 0) { throw "Failed to build base image" }

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
Write-Host "Docker-ready Linux wheelhouse: $(Join-Path $Wheels 'linux-x86_64')"
