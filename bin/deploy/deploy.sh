#!/usr/bin/env bash
# One-command deploy: build -> push -> (confirm) -> release -> smoke,
# with automatic rollback if smoke fails. This is the manual/terminal
# entry point; the `deploy` skill drives the same steps for the agent
# with an explicit human confirmation gate before the live step.
#
# Usage:
#   bin/deploy/deploy.sh          # prompts before the live step
#   bin/deploy/deploy.sh --yes    # non-interactive (assumes confirmation)
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
HERE="$(dirname "${BASH_SOURCE[0]}")"

TAG="$("$HERE/build.sh")"        # build.sh prints the tag on stdout
"$HERE/push.sh" "$TAG"

# ── live gate ───────────────────────────────────────────────────────────
if [ "${1:-}" != "--yes" ]; then
  printf '\033[1;33m[confirm]\033[0m Release %s to LIVE %s? [y/N] ' "$TAG" "$LIVE_URL" >&2
  read -r ans
  case "$ans" in y|Y|yes) ;; *) log "aborted before the live step (nothing changed on prod)"; exit 0;; esac
fi

"$HERE/release.sh" "$TAG"

# ── smoke gate + auto-rollback ──────────────────────────────────────────
if "$HERE/smoke.sh"; then
  ok "DEPLOY GREEN — $TAG is live"
else
  err "smoke failed after release — auto-rolling back"
  "$HERE/rollback.sh"
  die "deploy of $TAG failed smoke and was rolled back"
fi
