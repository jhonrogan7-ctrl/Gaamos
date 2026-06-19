# Gaamos — Project Context

## How to Load Context

1. Always start by reading `/root/zxyn/gaamos/INDEX.md`
2. Based on the current task, identify relevant topics from the index
3. Read ONLY the files listed under those topics
4. Never read files not listed in the index unless explicitly asked

## Overview

Gaamos is the consolidated **self-serve QR-menu SaaS for Nepali restaurants** — multiple
companies, each managing their own branches, categories, and menus, served via subdomain
(plus paid custom domain). It is the productisation of the work previously split across the
"QR Manu SaaS conversion" and the "Nepal" project, now unified under one name.

- **Repo (git):** `/home/paperclip/gaamos`
- **Vault (notes):** `/root/zxyn/gaamos/` — canonical home for ALL project documentation
- **Obsidian vault root:** `/root/zxyn/`
- **Donor codebase:** `/home/paperclip/qr_manu/` — the live, single-tenant QR menu (Django +
  Alpine + SQLite) whose working pieces (manager dashboard, server-side QR generation, menu
  data model, fail-closed tenant scoping) get ported during the re-platform.

## Status — PLATFORM BUILD ACTIVE (gate cleared 2026-06-19)

**Validation gate is MET — platform code is unblocked.** The founder confirmed the Thamel
demos passed (≥3-of-5 yes at the proposed price). gaamos is now an active platform build on
the locked target stack, re-platforming the donor-era specs phase by phase (starting Phase 1).
Decision record: `decisions/2026-06-19-validation-gate-cleared.md` (vault).

> **Gate history (now cleared):** the founder decision of 2026-06-16 blocked all platform /
> re-platform code until **3-of-5 in-person Thamel restaurant demos said yes at the proposed
> price.** That condition was met on 2026-06-19. The donor `qr_manu` repo stays live and
> single-tenant; gaamos is the new build.

## Core Decisions (target stack — never re-debate without a new decision record)

| Decision | Choice | Reason |
|---|---|---|
| Language | Python 3 / Django 5.x | Donor codebase + team familiarity |
| Database | PostgreSQL | Multi-tenant row-level scoping; production-grade |
| Frontend | Django templates + Tailwind + HTMX | No build step; incremental partial updates |
| Client interactivity | Alpine.js | Pairs with HTMX (server) for local UI state; no build step; donor reuse |
| Tenancy model | Shared schema, row-level company scoping | Rejected `django-tenants` (both councils) |
| Media | Cloudflare R2 | Tenant-scoped object storage |
| App shell | PWA | Installable, mobile-first guest experience |
| Responsive strategy | Mobile-first everywhere — guest menu AND dashboard | Both designed mobile-first; dashboard must also fully fit tablet & desktop (real layouts, not shrunk mobile) |
| Deployment | Fully dockerized via Docker Compose | One-command local + prod parity; web + Postgres + `cloudflared` as compose services |
| Edge / TLS | Cloudflare Tunnel (`cloudflared`) at the edge | TLS terminated at Cloudflare edge; no in-stack TLS proxy; covers subdomains + on-demand custom-domain TLS |
| Menu themes | Tenant-selectable theme system — Saffron Festival / Electric Berry / Tropical Juice | Bold, colourful guest menu; venue picks their gamut. Shared UX (ported from qr_manu), themed via CSS variables |
| Dashboard brand | Fixed **Saffron Festival** accent (neutral base) — same for every venue | Operator-side house brand; calm desktop-first work tool, not themed per venue |
| Localisation | Bilingual NP / EN | Nepali restaurant market |
| Billing | eSewa (NPR) | Local payment rail |
| Routing | Subdomain per venue + paid custom domain | On-demand TLS for custom domains |
| Price | Integer Rs / NPR only, no decimals | Inherited from donor product |

## Multi-Tenant Roadmap (donor-era specs — to be re-platformed)

The 5-phase SaaS architecture is specced under `superpowers/specs/2026-05-30-*`. These were
written against the donor stack (SQLite + Alpine SPA) and must be re-platformed onto the
target stack above. See the vault INDEX for the per-phase breakdown.

1. **Phase 1 — Tenancy foundation** — company FKs, per-company slugs, scoped manager, tenant middleware (fail-closed)
2. **Phase 2 — Access control** — Company / Membership / roles, owner vs branch-scoped manager
3. **Phase 3 — Signup & onboarding** — marketing / signup / login, slug validation, starter data
4. **Phase 4 — Plans, branding & media** — plan limits, branding, tenant-scoped media, QR URL change
5. **Phase 5 — Custom domains & billing** — custom domains, on-demand TLS, eSewa (NPR) billing

## Two-Layer Documentation System — ZXYN Vault (MANDATORY)

ALL project documentation is written to the vault at `/root/zxyn/gaamos/` — NOT to a `docs/`
folder in this repo. This overrides any skill default (superpowers brainstorming, writing-plans,
etc. save repo-relative by default — the vault paths below take precedence).

### Layer 1 — Superpowers (Technical)
- Specs (brainstorming output) → `/root/zxyn/gaamos/superpowers/specs/YYYY-MM-DD-<topic>-design.md`
- Plans (writing-plans output) → `/root/zxyn/gaamos/superpowers/plans/YYYY-MM-DD-<topic>.md`
- Council sessions (llm-council skill) → `/root/zxyn/gaamos/council/YYYY-MM-DD-<topic-slug>/` (the skill handles this itself)

### Layer 2 — Digest (Human Readable)
All audiences: devs, stakeholders. Tone: direct internal team, readable by non-engineers.
Paths relative to `/root/zxyn/gaamos/`:

| Type | Path | Trigger |
|---|---|---|
| Session digest | `digest/sessions/YYYY-MM-DD.md` | Every session |
| Feature digest | `digest/features/YYYY-MM-DD-[name].md` | After feature complete |
| Sprint digest | `digest/sprints/sprint-[N].md` | End of sprint |
| Audit report | `digest/audits/YYYY-MM-DD-[feature]-audit.md` | On demand |

### After writing ANY vault doc
Update `/root/zxyn/gaamos/INDEX.md` — add a one-line entry under the matching section. The
index is the single entry point for context loading; an unindexed doc is invisible to future
sessions.

## After Each Session

1. Write a brief summary to `/root/zxyn/gaamos/daily/YYYY-MM-DD.md`
2. Update `INDEX.md` if new notes were created
3. Update `daily/current-sprint.md` with progress

## Commit Policy

Every session with code changes MUST end with a structured commit.
Commits require developer confirmation before executing.

Format: `type(scope): description`
Types: `feat`, `fix`, `chore`, `docs`, `refactor`, `test`
Example: `feat(tenancy): add company FK to menu models`

## Origin

Consolidation decision (QR Manu SaaS + Nepal → one product, donor = qr_manu):
`/root/zxyn/nepal/decisions/2026-06-16-qr-manu-nepal-consolidation.md`
