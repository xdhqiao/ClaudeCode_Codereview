#!/usr/bin/env sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PYTHON=${PYTHON:-python3}
MANIFEST="$ROOT/vendor/bundles/docker-images-linux-x86_64.zip.parts.json"
IMAGES="$ROOT/vendor/images"

"$PYTHON" "$ROOT/scripts/offline_artifacts.py" restore \
  --manifest "$MANIFEST" \
  --destination "$IMAGES" \
  --extract

docker load -i "$IMAGES/ai-code-review-images.tar"
echo "Docker images loaded."
