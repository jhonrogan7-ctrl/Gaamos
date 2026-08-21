#!/usr/bin/env bash
# Shared config + helpers for the Gaamos agent-driven deploy pipeline.
#
# Runs on the BUILD VM (this machine). Prod only RECEIVES: we build here,
# push to a prod-local registry over an SSH tunnel, and drive prod's
# rootless Docker over SSH. Nothing is ever built or edited on prod.
#
# Secrets never live here — prod's .env stays on prod. Auth is the deploy
# SSH key only.
set -euo pipefail

# ── prod target ──────────────────────────────────────────────────────────
PROD_HOST="${PROD_HOST:-178.238.229.234}"
PROD_USER="${PROD_USER:-deploy}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/id_ed25519_gaamos}"

# prod runs Docker ROOTLESS under user appuser (uid 999). No system daemon.
APP_DOCKER_HOST="unix:///run/user/999/docker.sock"
APP_XDG="/run/user/999"

# ── registry / image / stack ─────────────────────────────────────────────
REGISTRY="127.0.0.1:5000"                 # prod-local, loopback only
IMAGE="$REGISTRY/gaamos-web"
PROJECT="gaamos-v2"                       # compose project (new prod stack)
PROD_DIR="/srv/appuser/app/gaamos-v2"
COMPOSE_FILE="docker-compose.v2.yml"

# ── smoke targets ────────────────────────────────────────────────────────
INTERNAL_URL="http://127.0.0.1:8006"      # v2 web, loopback on prod
LIVE_URL="https://gaamos.io"
PUBLIC_HOST="gaamos.io"

# ── local repo ───────────────────────────────────────────────────────────
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV="${ENV:-prod}"

log()  { printf '\033[1;34m[deploy]\033[0m %s\n' "$*" >&2; }
ok()   { printf '\033[1;32m[ ok  ]\033[0m %s\n' "$*" >&2; }
err()  { printf '\033[1;31m[fail ]\033[0m %s\n' "$*" >&2; }
die()  { err "$*"; exit 1; }

# The image tag for a build: <git-short-sha>[-dirty]-<env>. Unique per build,
# traceable to a commit (rule 2/3 of the design doc).
compute_tag() {
  local sha dirty=""
  sha="$(git -C "$REPO_ROOT" rev-parse --short HEAD)"
  [ -n "$(git -C "$REPO_ROOT" status --porcelain)" ] && dirty="-dirty"
  echo "${sha}${dirty}-${ENV}"
}

ssh_prod() { ssh -i "$SSH_KEY" -o PreferredAuthentications=publickey \
                 -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15 \
                 "$PROD_USER@$PROD_HOST" "$@"; }

# Run a bash script (from stdin) on prod AS appuser, with the rootless Docker
# env already exported and cwd at the v2 project dir.
prun() {
  ssh_prod "sudo -u appuser env DOCKER_HOST=$APP_DOCKER_HOST XDG_RUNTIME_DIR=$APP_XDG \
            bash -c 'cd $PROD_DIR && bash -s'"
}

# Open / close the SSH tunnel that exposes the prod-local registry at
# 127.0.0.1:5000 on the build VM. Uses a control socket so it is cleanly closed.
TUN_CTL="${TMPDIR:-/tmp}/gaamos-deploy-tun.sock"
tunnel_open() {
  ssh -i "$SSH_KEY" -o PreferredAuthentications=publickey \
      -o StrictHostKeyChecking=accept-new -fN -M -S "$TUN_CTL" \
      -L 127.0.0.1:5000:127.0.0.1:5000 "$PROD_USER@$PROD_HOST"
  ssh -S "$TUN_CTL" -O check "$PROD_USER@$PROD_HOST" 2>/dev/null
}
tunnel_close() { ssh -S "$TUN_CTL" -O exit "$PROD_USER@$PROD_HOST" 2>/dev/null || true; }

# Read / write the WEB_TAG currently released on prod (drives rollback).
prod_current_tag() { ssh_prod "sudo grep -E '^WEB_TAG=' $PROD_DIR/.env | cut -d= -f2"; }
