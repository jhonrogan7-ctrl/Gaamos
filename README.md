# Gaamos

Self-serve **QR-menu SaaS for Nepali restaurants**. Each company manages its own branches,
categories, and menu items, served to guests via a per-venue subdomain (plus optional paid
custom domain). Guests scan a QR code and get a fast, mobile-first, bilingual (NP/EN) menu;
operators manage everything from a dashboard.

## Status

**Active platform build.** The validation gate cleared on 2026-06-19, unblocking platform
code. Delivered so far:

- **Phase 1 — Tenancy foundation** — company FKs, per-company slugs, fail-closed tenant
  middleware
- **Phase 2 — Access control** — Company / Membership / roles (owner vs branch-scoped manager)
- **Guest menu layout system** — selectable `baseline` / `tabs` / `iconrail` layouts and a
  tenant-selectable theme system (Saffron Festival / Electric Berry / Tropical Juice)

**Next:** Phase 3 — signup & onboarding.

## Tech Stack

| Layer | Choice |
|---|---|
| Backend | Python 3 / Django 5.1 |
| Database | PostgreSQL 16 (shared schema, row-level company scoping) |
| Frontend | Django templates + Tailwind + HTMX + Alpine.js (no build step beyond CSS) |
| Server | uvicorn / ASGI (SSE-capable) |
| Media | Cloudflare R2 (tenant-scoped) |
| Edge / TLS | Cloudflare Tunnel (`cloudflared`) |
| Billing | eSewa (NPR) |
| Deployment | Docker Compose (web + Postgres + `cloudflared`) |

## Quick Start (Docker)

Requires Docker + Docker Compose.

```bash
# 1. Configure environment
cp .env.example .env        # dev defaults work out of the box

# 2. Build and start (web + Postgres)
docker compose up --build
```

The web service runs migrations, collects static, builds CSS, and serves on
**http://localhost:8005**.

Create an admin user:

```bash
docker compose exec web python manage.py createsuperuser
```

### Multi-tenant subdomains in dev

Tenants resolve as `<slug>.<BASE_DOMAIN>`. In development, `<slug>.localhost` also works
(e.g. `http://acme.localhost:8005`). Set `ALLOWED_HOSTS` / `BASE_DOMAIN` in `.env` — see
`.env.example` for the subdomain-friendly settings.

### Cloudflare edge (optional)

The `cloudflared` tunnel is behind a compose profile. Set `TUNNEL_TOKEN` in `.env`, then:

```bash
docker compose --profile edge up
```

## Tests

```bash
docker compose exec web pytest
```

Settings module is `config.settings` (configured in `pytest.ini`). Suite lives in
`menu/tests/`.

## Project Layout

```
config/     Django project (settings, ASGI, root URLs)
core/       Shared/base app pieces
menu/       Main app — models, tenancy, middleware, dashboard, guest views
templates/  Django templates (guest menu + dashboard)
static/     Tailwind source; built CSS is generated (not committed)
bin/        build-css.sh
docker-compose.yml, Dockerfile, cloudflared/
```

## Documentation

Detailed project documentation (specs, plans, digests, decisions) lives in the **ZXYN vault**,
not in this repo. See `CLAUDE.md` for the full context-loading and documentation workflow.
