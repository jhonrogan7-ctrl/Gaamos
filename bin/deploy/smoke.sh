#!/usr/bin/env bash
# Smoke test the released stack. Green is the deploy gate: a deploy is not
# "done" until this passes. Checks the v2 web internally (prod loopback, with
# the X-Forwarded-Proto the tunnel would set) AND the real public gaamos.io.
#
# Exit 0 = all green. Non-zero = something failed (deploy.sh will roll back).
#
# Usage: bin/deploy/smoke.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

fails=0
check() { # <label> <expected> <actual>
  if [ "$2" = "$3" ]; then ok "$1 ($3)"; else err "$1 — got $3, want $2"; fails=$((fails+1)); fi
}

# ── internal (prod loopback; XFP https so SECURE_SSL_REDIRECT does not 301) ──
ihdr=(-H "Host: $PUBLIC_HOST" -H "X-Forwarded-Proto: https")
icode() { ssh_prod "curl -s -m 10 -o /dev/null -w '%{http_code}' \
            -H 'Host: $PUBLIC_HOST' -H 'X-Forwarded-Proto: https' '$INTERNAL_URL$1'"; }

log "internal smoke ($INTERNAL_URL)"
check "internal /healthz" 200 "$(icode /healthz)"
check "internal /en/"     200 "$(icode /en/)"

# media: fetch a REAL logo path from the DB, so the check is data-driven and
# proves the production media route (the bug that DEBUG-only routing hid).
mediapath="$(prun <<'EOF' 2>/dev/null | tail -1
printf '%s\n' "select split_part(logo_url,'?',1) from menu_company where logo_url is not null and logo_url<>'' limit 1;" \
 | docker exec -i gaamos-v2-db-1 psql -tA -U gaamos -d gaamos 2>/dev/null | tr -d '[:space:]'
EOF
)"
if [ -n "$mediapath" ]; then
  check "internal media ($mediapath)" 200 "$(icode "$mediapath")"
else
  log "no company logo in DB — skipping media check"
fi

# ── public (real gaamos.io through Cloudflare) ──────────────────────────────
lcode() { curl -s -m 12 -o /dev/null -w '%{http_code}' "$LIVE_URL$1"; }
log "public smoke ($LIVE_URL)"
check "live /en/" 200 "$(lcode /en/)"
check "live /ka/" 200 "$(lcode /ka/)"

# content sanity: the current design is the blue palette, not the old red.
body="$(curl -s -m 12 "$LIVE_URL/en/" || true)"
echo "$body" | grep -q '#1C3F73' && ok "live palette: blue #1C3F73 present" \
  || { err "live palette: blue #1C3F73 missing"; fails=$((fails+1)); }
echo "$body" | grep -q '#8E2B23' && { err "live palette: old red #8E2B23 still present"; fails=$((fails+1)); } \
  || ok "live palette: old red absent"

if [ "$fails" -eq 0 ]; then ok "SMOKE GREEN"; exit 0; else err "SMOKE FAILED ($fails)"; exit 1; fi
