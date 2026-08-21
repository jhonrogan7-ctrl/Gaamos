#!/usr/bin/env bash
# Point the live prod stack at a new image tag and recreate web + worker.
# This is the LIVE-AFFECTING step. Records the previous tag first so
# rollback is a pure re-tag, and appends to the on-prod deploy audit log.
#
# Usage: bin/deploy/release.sh <tag>
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

TAG="${1:?usage: release.sh <tag>}"

PREV="$(prod_current_tag || true)"
log "current tag: ${PREV:-<none>}  ->  new tag: $TAG"

# Confirm the tag actually exists in the registry before we touch live.
prun <<EOF
set -e
curl -s -m 8 http://127.0.0.1:5000/v2/gaamos-web/tags/list | grep -q '"$TAG"' \
  || { echo "tag $TAG not in registry"; exit 1; }
# Save the tag we are replacing, for rollback, then flip WEB_TAG.
echo "${PREV:-}" > .deploy_prev_tag
sed -i "s/^WEB_TAG=.*/WEB_TAG=$TAG/" .env
grep ^WEB_TAG= .env
echo "recreating web + worker..."
docker compose -p $PROJECT -f $COMPOSE_FILE up -d web worker
# audit
printf '%s  release  tag=%s  prev=%s  by=%s\n' "\$(date -Is)" "$TAG" "${PREV:-none}" "\${SUDO_USER:-deploy}" >> deploy.log
EOF

log "waiting for web to come up"
prun <<'EOF'
set -e
for i in $(seq 1 20); do
  st=$(docker inspect -f '{{.State.Status}}' gaamos-v2-web-1 2>/dev/null || echo missing)
  [ "$st" = running ] && { echo "web: running"; break; }
  sleep 2
done
EOF
ok "released $TAG (previous $PREV recorded for rollback)"
