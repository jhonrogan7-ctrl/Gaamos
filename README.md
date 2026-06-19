# Gaamos

Self-serve **QR-menu SaaS for Nepali restaurants** — multiple companies, each managing their
own branches, categories, and menus, served via subdomain (plus paid custom domain).

Gaamos unifies the work previously split across the "QR Manu SaaS conversion" and the "Nepal"
project. The live single-tenant **[qr_manu](../qr_manu/)** app is the donor codebase.

## Status

**Planning / docs scaffold only — no platform code yet.**

Per the founder decision of 2026-06-16, no platform / re-platform code lands until **3-of-5
in-person Thamel restaurant demos say yes at the proposed price.** Until then this repo holds
the workflow (`CLAUDE.md`, `SKILLS.md`); all specs and plans live in the vault.

## Target Stack

Django + PostgreSQL + Tailwind + HTMX + Cloudflare R2 + PWA, bilingual NP/EN, eSewa (NPR)
billing, shared-schema row-level tenancy (no `django-tenants`).

## Documentation

All documentation lives in the ZXYN vault, **not** in this repo:

- Index / entry point → `/root/zxyn/gaamos/INDEX.md`
- Specs → `/root/zxyn/gaamos/superpowers/specs/`
- Plans → `/root/zxyn/gaamos/superpowers/plans/`

See `CLAUDE.md` for the full context-loading and documentation workflow.
