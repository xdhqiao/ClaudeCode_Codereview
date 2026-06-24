#!/usr/bin/env sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PYTHON=${PYTHON:-python3}

PLATFORM=$("$PYTHON" -c "import platform,sys; print(f'{sys.version_info.major}.{sys.version_info.minor}|{platform.system()}|{platform.machine().lower()}')")
case "$PLATFORM" in
  3.12\|Linux\|x86_64|3.12\|Linux\|amd64) ;;
  *)
    echo "This bundle requires Linux x86_64 with Python 3.12; found $PLATFORM" >&2
    exit 2
    ;;
esac

WHEELS="$ROOT/vendor/wheels/linux-x86_64"
set -- "$WHEELS"/*.whl
if [ ! -e "$1" ]; then
  "$PYTHON" "$ROOT/scripts/restore_offline_artifacts.py" \
    --platform linux-x86_64-py312
fi
"$PYTHON" "$ROOT/scripts/verify_offline_wheelhouse.py" \
  "$WHEELS" \
  --write-manifest "$WHEELS/manifest.json"
"$PYTHON" -m pip install --no-index --find-links "$WHEELS" hatchling
"$PYTHON" -m pip install --no-index --find-links "$WHEELS" \
  --no-build-isolation "$ROOT"

echo "Offline installation completed."
