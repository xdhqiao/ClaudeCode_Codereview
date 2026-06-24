#!/usr/bin/env sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PYTHON=${PYTHON:-python3}
MANIFEST="$ROOT/vendor/bundles/docker-images-linux-x86_64.zip.parts.json"
IMAGES="$ROOT/vendor/images"

WHEELS="$ROOT/vendor/wheels/linux-x86_64"
set -- "$WHEELS"/*.whl
if [ ! -e "$1" ]; then
  "$PYTHON" "$ROOT/scripts/restore_offline_artifacts.py" \
    --platform linux-x86_64-py312
fi
"$PYTHON" "$ROOT/scripts/verify_offline_wheelhouse.py" \
  "$WHEELS" \
  --write-manifest "$WHEELS/manifest.json"

"$PYTHON" "$ROOT/scripts/offline_artifacts.py" restore \
  --manifest "$MANIFEST" \
  --destination "$IMAGES" \
  --extract

docker load -i "$IMAGES/ai-code-review-images.tar"
echo "Docker images and Linux wheelhouse restored."
