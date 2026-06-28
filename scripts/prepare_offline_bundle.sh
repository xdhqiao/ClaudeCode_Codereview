#!/usr/bin/env sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PYTHON=${PYTHON:-python3}
MAX_PART_SIZE_MB=${MAX_PART_SIZE_MB:-90}
INCLUDE_DOCKER_IMAGES=0

usage() {
  cat <<EOF
Usage: $0 [--include-docker-images]

Environment:
  PYTHON              Python 3.12 executable (default: python3)
  MAX_PART_SIZE_MB    Split archive part size (default: 90)
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --include-docker-images)
      INCLUDE_DOCKER_IMAGES=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

VERSION=$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
if [ "$VERSION" != "3.12" ]; then
  echo "Python 3.12 is required; found $VERSION" >&2
  exit 2
fi

REQUIREMENTS="$ROOT/requirements/offline-runtime.txt"
STAGING_ROOT="$ROOT/vendor/staging"
DOWNLOAD="$STAGING_ROOT/linux-x86_64-py312-download"
BUNDLES="$ROOT/vendor/bundles"
WHEELS="$ROOT/vendor/wheels/linux-x86_64"
BACKUP="$ROOT/vendor/wheels/.linux-x86_64.previous"

mkdir -p "$STAGING_ROOT" "$BUNDLES" "$ROOT/vendor/wheels"
rm -rf "$DOWNLOAD"
mkdir -p "$DOWNLOAD"

"$PYTHON" -m pip download \
  --dest "$DOWNLOAD" \
  --only-binary=:all: \
  --implementation cp \
  --python-version 312 \
  --abi cp312 \
  --platform manylinux_2_17_x86_64 \
  --platform manylinux2014_x86_64 \
  -r "$REQUIREMENTS"

"$PYTHON" "$ROOT/scripts/verify_offline_wheelhouse.py" \
  "$DOWNLOAD" \
  --write-manifest "$DOWNLOAD/manifest.json"

"$PYTHON" "$ROOT/scripts/wheelhouse_manifest.py" \
  --wheelhouse "$DOWNLOAD" \
  --output "$BUNDLES/linux-x86_64-py312-packages.json" \
  --require-claude-cli

"$PYTHON" "$ROOT/scripts/offline_artifacts.py" pack \
  --source "$DOWNLOAD" \
  --output "$BUNDLES/linux-x86_64-py312-wheels.zip" \
  --max-part-size-mb "$MAX_PART_SIZE_MB"

rm -rf "$BACKUP"
if [ -d "$WHEELS" ]; then
  mv "$WHEELS" "$BACKUP"
fi
if mv "$DOWNLOAD" "$WHEELS"; then
  rm -rf "$BACKUP"
else
  if [ -d "$BACKUP" ]; then
    mv "$BACKUP" "$WHEELS"
  fi
  exit 1
fi

if [ "$INCLUDE_DOCKER_IMAGES" -eq 1 ]; then
  docker build -f "$ROOT/Dockerfile.base" \
    -t ai-code-review-base:python3.12 "$ROOT"
  docker build -f "$ROOT/Dockerfile.offline" \
    -t ai-code-review:offline "$ROOT"
  docker pull mongo:7

  IMAGE_DIRECTORY="$STAGING_ROOT/docker-images"
  rm -rf "$IMAGE_DIRECTORY"
  mkdir -p "$IMAGE_DIRECTORY"
  docker save -o "$IMAGE_DIRECTORY/ai-code-review-images.tar" \
    ai-code-review-base:python3.12 \
    ai-code-review:offline \
    mongo:7
  "$PYTHON" "$ROOT/scripts/offline_artifacts.py" pack \
    --source "$IMAGE_DIRECTORY" \
    --output "$BUNDLES/docker-images-linux-x86_64.zip" \
    --max-part-size-mb "$MAX_PART_SIZE_MB" \
    --remove-source
fi

for manifest in "$BUNDLES"/*.parts.json; do
  [ -e "$manifest" ] || continue
  "$PYTHON" "$ROOT/scripts/offline_artifacts.py" verify \
    --manifest "$manifest"
done

echo "Offline bundles: $BUNDLES"
echo "Docker-ready Linux wheelhouse: $WHEELS"
