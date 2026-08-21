---
name: deploy
description: Use when deploying Gaamos to production — shipping committed stage changes to live gaamos.io. Runs the build→push→release→smoke pipeline (bin/deploy/*) with a human confirmation gate before the live step and automatic rollback if smoke fails. Also use to roll back a bad release.
---

# Gaamos production deploy

Ship stage changes to live **gaamos.io** deterministically. The whole pipeline
is six atomic scripts under `bin/deploy/` — run them in order, never improvise.
Config (prod host, rootless-Docker access, registry, compose project) lives in
`bin/deploy/lib.sh`; read it if you need a value.

## The model (do not violate)

- **Prod only RECEIVES.** Build on the build VM, push to the prod-local registry
  over an SSH tunnel, drive prod's rootless Docker over SSH. **Never build or
  edit anything on prod.** A problem is fixed on **stage**, committed, and
  redeployed through this pipeline — that is the rule.
- **Never bake tenant media into the image.** `media/` is `.dockerignore`'d;
  `build.sh` fails the build if any media is baked. Prod keeps the media the
  live stack accumulated (volume `gaamos-v2_media`) — never wipe it.
- **Data & media volumes are sacred.** Never touch `gaamos-v2_pgdata` /
  `gaamos-v2_media`. Migrations run at boot (forward-only).
- **Image runs non-root** (uid 10001); `build.sh` enforces it.
- **Tag = `<git-sha>[-dirty]-<env>`**, unique per build. **Rollback is a
  re-tag, never a rebuild** — the previous image is still in the registry.
- **A deploy is not done until smoke is green.**

## Preconditions

1. Changes are committed on `main` (the tag traces to a commit; a dirty tree
   tags `-dirty`, which is a smell — commit first unless deliberately testing).
2. You are on the build VM with the deploy SSH key (`~/.ssh/id_ed25519_gaamos`).
3. `git push origin main` if you want origin to match what you deploy.

## Deploy (the normal flow)

Run the steps yourself, one at a time — do not shortcut to `deploy.sh --yes`,
because the human confirmation gate (step 3) is the point.

1. **Build** — `bin/deploy/build.sh` → capture the printed `TAG`. It verifies
   non-root + no baked media and refuses otherwise.
2. **Push** — `bin/deploy/push.sh "$TAG"` → image into the prod registry over
   the tunnel; verifies the tag landed.
3. **CONFIRM (human gate).** This is the only live-affecting boundary. Ask the
   developer with AskUserQuestion: *"Release `<TAG>` to live gaamos.io? (brief
   restart of web/worker; rollback available)"*. **Do not proceed without an
   explicit yes.**
4. **Release** — `bin/deploy/release.sh "$TAG"` → records the previous tag for
   rollback, flips `WEB_TAG`, recreates web+worker (pull → migrate → up),
   appends to the on-prod audit log `deploy.log`.
5. **Smoke** — `bin/deploy/smoke.sh`. Green → **report done** (tag, what
   changed). Non-zero → step 6.
6. **Auto-rollback** — on smoke failure run `bin/deploy/rollback.sh` (no arg =
   previous tag), which re-tags and re-smokes. Then report: what failed, that
   it rolled back, and whether the rollback smoke is green. If rollback smoke
   is also red, stop and escalate to the human — do not keep trying.

`bin/deploy/deploy.sh` chains all of this for a human at a terminal (it prompts
before the live step and auto-rolls-back). The agent should prefer the explicit
steps so the confirmation is a real AskUserQuestion.

## Rollback on demand

`bin/deploy/rollback.sh [tag]` — no arg rolls back to the tag the last release
recorded; pass a tag to target a specific earlier image. It re-smokes after.

## After a deploy

- Report the tag, the commit, and a one-line summary of what shipped.
- The prod audit trail is `/srv/appuser/app/gaamos-v2/deploy.log`.
- The previous stack (compose project `Gaamos`, port 8005) is kept stopped for
  emergency rollback of the whole cutover; leave it until a deploy has been
  stable for a while, then clean up (see the memory note `gaamos-deploy`).
