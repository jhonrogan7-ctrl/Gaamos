# Gaamos — Engineer Agent Skills

> Session initialization checklist and context map.
> Load this file at the start of every Claude Code session on this project.

---

## Session Init Checklist

Before doing any work, complete these steps in order:

1. **Read** `/root/zxyn/gaamos/INDEX.md` — project index and quick-reference table
2. **Read** `CLAUDE.md` — overview, target stack, doc system, the Thamel gate, commit policy
3. **Check** `/root/zxyn/gaamos/daily/current-sprint.md` — active sprint tasks
4. **Check** git status: `git status` + `git log --oneline -5`

> **Remember the hard gate:** no platform/re-platform code until the Thamel 3-of-5 validation
> passes. Until then this is a planning/docs home — work happens in specs and plans, not code.

---

## Critical Files — Always Available in Context

| File | Why |
|---|---|
| `CLAUDE.md` | Overview, target stack, doc system, validation gate, commit policy |
| `/root/zxyn/gaamos/INDEX.md` | Vault entry point, task-to-file routing |
| `/root/zxyn/gaamos/daily/current-sprint.md` | Active work, blockers, priorities |
| `/root/zxyn/gaamos/superpowers/specs/` | The 5-phase multi-tenant SaaS specs |
| `/root/zxyn/gaamos/dev-notes/stack-description.md` | Donor-product stack reference |

---

## Documentation Workflow (see CLAUDE.md for full detail)

- **Specs** → `/root/zxyn/gaamos/superpowers/specs/YYYY-MM-DD-<topic>-design.md`
- **Plans** → `/root/zxyn/gaamos/superpowers/plans/YYYY-MM-DD-<topic>.md`
- **Council** → `/root/zxyn/gaamos/council/YYYY-MM-DD-<topic-slug>/`
- **Digests** → `/root/zxyn/gaamos/digest/{sessions,features,sprints,audits}/`
- After writing ANY vault doc, add a one-line entry to `/root/zxyn/gaamos/INDEX.md`.

---

## Commits

- Format: `type(scope): description`
- Always confirm with developer before committing
- Never batch unrelated changes in one commit
