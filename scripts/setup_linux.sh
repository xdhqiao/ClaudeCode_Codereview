#!/usr/bin/env sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
ENV_FILE=${ENV_FILE:-"$ROOT/.env"}

umask 077
if [ ! -f "$ENV_FILE" ]; then
  cp "$ROOT/.env.example" "$ENV_FILE"
  echo "Created $ENV_FILE"
else
  echo "Keeping existing $ENV_FILE"
fi

mkdir -p \
  "$ROOT/repositories" \
  "$ROOT/knowledge/standards" \
  "$ROOT/workspaces"
chmod 600 "$ENV_FILE"

cat <<EOF
Linux directories are ready.

Next:
1. Edit $ENV_FILE
2. For a model gateway on this Docker host, set:
   ANTHROPIC_BASE_URL=http://host.docker.internal:4000
3. Validate:
   docker compose -f docker-compose.airgap.yml run --rm reviewer \
     ai-code-review check-config --deployment docker
4. Start:
   docker compose -f docker-compose.airgap.yml up -d --build
EOF
