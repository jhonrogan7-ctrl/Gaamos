#!/usr/bin/env bash
# Push a built image to the prod-local registry over an SSH tunnel.
# The registry is loopback-only on prod; the tunnel is the only way in.
#
# Usage: bin/deploy/push.sh <tag>
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

TAG="${1:?usage: push.sh <tag>}"
REF="$IMAGE:$TAG"

docker image inspect "$REF" >/dev/null 2>&1 || die "image $REF not found locally — build first"

log "opening tunnel to prod registry"
tunnel_open || die "could not open SSH tunnel"
trap tunnel_close EXIT

log "pushing $REF"
docker push "$REF" >&2

log "verifying tag on registry"
tags="$(curl -s -m 8 http://127.0.0.1:5000/v2/gaamos-web/tags/list || true)"
echo "$tags" | grep -q "\"$TAG\"" || die "tag $TAG not visible in registry after push"
ok "pushed $REF (registry tags: $tags)"
