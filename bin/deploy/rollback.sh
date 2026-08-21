#!/usr/bin/env bash
# Roll the live stack back to a previous image tag. A rollback is a pure
# re-tag — the previous image is still in the registry — never a rebuild.
# Runs the same smoke as a deploy afterwards (rule: rollback is tested like
# a deploy).
#
# Usage: bin/deploy/rollback.sh [tag]
#   With no arg, rolls back to the tag recorded by the last release.
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

TARGET="${1:-}"
if [ -z "$TARGET" ]; then
  TARGET="$(ssh_prod "sudo cat $PROD_DIR/.deploy_prev_tag 2>/dev/null" | tr -d '[:space:]')"
  [ -n "$TARGET" ] || die "no previous tag recorded (.deploy_prev_tag empty) — pass a tag explicitly"
fi
log "rolling back to tag: $TARGET"

prun <<EOF
set -e
curl -s -m 8 http://127.0.0.1:5000/v2/gaamos-web/tags/list | grep -q '"$TARGET"' \
  || { echo "tag $TARGET not in registry — cannot roll back to it"; exit 1; }
CUR=\$(grep -E '^WEB_TAG=' .env | cut -d= -f2)
echo "\$CUR" > .deploy_prev_tag
sed -i "s/^WEB_TAG=.*/WEB_TAG=$TARGET/" .env
docker compose -p $PROJECT -f $COMPOSE_FILE up -d web worker
printf '%s  ROLLBACK tag=%s  from=%s\n' "\$(date -Is)" "$TARGET" "\$CUR" >> deploy.log
EOF

log "re-smoking after rollback"
if "$(dirname "${BASH_SOURCE[0]}")/smoke.sh"; then
  ok "rolled back to $TARGET and smoke is green"
else
  die "rolled back to $TARGET but smoke STILL failing — needs a human"
fi
