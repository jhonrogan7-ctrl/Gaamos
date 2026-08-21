#!/usr/bin/env bash
#
# Redeploy after pulling, WITHOUT rebuilding the image.
#
# The base docker-compose.yml bind-mounts the repo at .:/app, so a `git pull`
# already puts fresh code inside the running container. What a pull does NOT do
# is re-run the one-time boot steps (CSS build, migrations, compilemessages,
# collectstatic) or reload the worker — uvicorn --reload only picks up Python
# changes. This script runs those steps against the live container and reloads
# it, so pulled changes actually take effect.
#
# Usage:
#   bin/deploy.sh            # git pull --ff-only, then refresh the running web container
#   SKIP_PULL=1 bin/deploy.sh   # you already pulled; just refresh the container
#
# Env overrides:
#   COMPOSE_CMD   compose invocation      (default: "docker compose")
#   WEB_SERVICE   web service name         (default: "web")
#
set -euo pipefail

# Run from the repo root regardless of where the script is called from.
cd "$(dirname "$0")/.."

COMPOSE="${COMPOSE_CMD:-docker compose}"
SERVICE="${WEB_SERVICE:-web}"

before="$(git rev-parse HEAD)"

if [ "${SKIP_PULL:-0}" != "1" ]; then
  echo "==> git pull --ff-only"
  git pull --ff-only
fi

after="$(git rev-parse HEAD)"
changed="$(git diff --name-only "$before" "$after" 2>/dev/null || true)"

# Python deps and the Dockerfile are baked into the image, not the mounted tree.
# If either changed, the mount alone can't deliver it — rebuild is required.
if echo "$changed" | grep -qE '^(requirements(-dev)?\.txt|Dockerfile)$'; then
  echo "==> requirements/Dockerfile changed — rebuilding image (mount can't carry deps)"
  $COMPOSE up -d --build "$SERVICE"
else
  # Make sure the mounted stack is up (no-op if already running).
  $COMPOSE up -d "$SERVICE"
fi

echo "==> build CSS"
$COMPOSE exec -T "$SERVICE" bash bin/build-css.sh build

echo "==> migrate"
$COMPOSE exec -T "$SERVICE" python manage.py migrate --noinput

echo "==> compilemessages (i18n)"
$COMPOSE exec -T "$SERVICE" python manage.py compilemessages

echo "==> collectstatic"
$COMPOSE exec -T "$SERVICE" python manage.py collectstatic --noinput

# Reload the worker so new Python code is picked up cleanly. Dev's uvicorn
# --reload would eventually notice, but prod runs --workers with no reload, so
# an explicit restart is the reliable path in both.
echo "==> restart $SERVICE"
$COMPOSE restart "$SERVICE"

if [ "$before" = "$after" ]; then
  echo "==> done (no new commits; container refreshed at $after)"
else
  echo "==> done: $before -> $after"
fi
