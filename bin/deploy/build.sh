#!/usr/bin/env bash
# Build the Gaamos web image on the BUILD VM and tag it <sha>-<env>.
# Verifies the two invariants the design requires: the image runs non-root
# and carries NO tenant media (media/ is .dockerignore'd).
#
# Usage: bin/deploy/build.sh            (prints the tag on stdout)
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

TAG="$(compute_tag)"
REF="$IMAGE:$TAG"

log "building $REF"
docker build -t "$REF" "$REPO_ROOT" >&2

log "verifying image invariants"
read -r uid mediacount < <(
  docker run --rm --entrypoint sh "$REF" -c \
    'printf "%s %s" "$(id -u)" "$(find /app/media -type f 2>/dev/null | wc -l)"'
)
[ "$uid" = "10001" ] || die "image runs as uid $uid, expected 10001 (non-root)"
[ "$mediacount" = "0" ] || die "image bakes $mediacount media files; media/ must be .dockerignore'd"
ok "image $REF — non-root (uid 10001), no baked media"

echo "$TAG"
