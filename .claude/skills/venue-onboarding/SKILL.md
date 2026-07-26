---
name: venue-onboarding
description: Use when onboarding a new restaurant/venue onto gaamos from a photographed or scanned menu - transcribing it into the vault prompt sheet, generating item images, and seeding the tenant with its priced catalog.
---

# Venue Onboarding

## Overview

One document per venue is the source of truth: the vault sheet
`/root/zxyn/gaamos/menius/<venue>/<venue>-items-and-image-prompts.md`. It carries
the venue's identity, its sections, every item with description and price, and
the image prompt per item. Images, fixture, tenant and catalog are all derived
from it.

Never correct a name, price or category anywhere downstream. Fix the sheet and
re-run — the whole pipeline is idempotent and resumable.

**Why it matters:** the first venue was onboarded from two documents that
drifted (a prompt sheet with printed names, a fixture with corrected ones). That
drift forced fuzzy matching, a hand-written alias table, and six wrong image
pairings caught only by eye. With one document, the asset key
`slugify("<section> <item>")` and the fixture key `slugify(section)-slugify(item)`
are the same string **by construction**.

## The six phases

Work through them in order. Check the count at the end of each — a run that
"succeeded" with 0 items has happened.

### 1. Scan — get the menu readable

The venue's photos/PDF are in `/root/zxyn/gaamos/menius/<venue>/`, owned by
`DEVELOPER` with mode 750, so read them with `sudo -n` (`sudo -n cat …`,
`sudo -n ls …`). Read images with the Read tool after copying them somewhere
readable.

Do NOT route this through the scan/OCR workbench. The Gemini vision key is out
of prepay credit; the path is photo → human → sheet.

### 2. Sheet — transcribe into the vault

Write `/root/zxyn/gaamos/menius/<venue>/<venue>-items-and-image-prompts.md`
following `references/sheet-format.md`. Rules that matter:

- **`### ` headings ARE the category slugs.** `slugify(heading)` is the category
  slug and the first half of every image key. Renaming a heading after images
  are generated orphans every image in that section.
- **A split price (`JHOL MOMO (VEG/NON VEG) 200/260`) becomes two rows**, one
  per variant, each with its own price.
- **Item names are transcribed as printed.** Corrections belong in the sheet.
- **Every item needs a price** or it is reported and not imported.
- **Never invent a claim, in text or in image.** A description and a prompt may
  only state what the printed name already commits to. A generated photo is a
  claim about the dish and a guest orders from it, so an invented garnish is the
  same lie as an invented ingredient. No piece counts, sides, dips, garnishes,
  cooking methods or ingredients the card does not print. Not inferable from the
  name → leave the description `—`, keep the prompt to the bare subject, and ask
  the venue.
- Descriptions may be written by us; head that column `Description` (not
  `Printed description`) so the provenance is visible in the document. Mark any
  row asserting more than a literal reading of the name with a trailing `⚠` and
  repeat it in the closing summary, so the venue's review is a short list rather
  than a wall of rows.
- The vault is not a git repo — the sheet is never committed. The generated
  `menu/fixtures/<company>.json` is.

Verify: parse it before generating anything.

    docker compose exec -T web python -c "
    from pathlib import Path; from menu.pipeline import prompt_sheet
    t = Path('/tmp/<venue>-sheet.md').read_text()
    rows = prompt_sheet.parse(t)
    print('rows', len(rows), 'priced', sum(r['price'] is not None for r in rows),
          'generatable', sum(r['generatable'] for r in rows))
    print(prompt_sheet.parse_venue(t))"

Row count must match the card. Any unpriced row must be one you meant to leave
unpriced.

### 3. Generate — images into the asset pool

    docker compose exec -T web python manage.py generate_item_images \
        --prompts /tmp/<venue>-sheet.md --dry-run
    docker compose exec -T web python manage.py generate_item_images \
        --prompts /tmp/<venue>-sheet.md

Resumable and idempotent on the section-qualified key — re-run to pick up
stragglers. ~10s pacing plus call time, so ~125 items is 30–45 minutes; run it
in the background and check back.

**Content-filtered prompts are deterministic, not flaky.** The endpoint declined
9 Tranquility prompts over the word "fried". Re-running changes nothing — reword
the prompt in the sheet (`fried` → `crisp golden`, `pan-seared`) and re-run.
They are listed at the end of the run under `content-filtered`.

Do NOT pass `--embed` — Gemini embeddings are billing-blocked.

### 4. Review — the gate every image passes

Counts do not tell you whether a photo is the dish, and neither does a 200px
contact sheet: herbs on a "plain" omelette are invisible at that size, and all
11 Chill Zone hot drinks shipped cold before anyone noticed. Review at readable
size, with the prompt beside the picture — half of these defects are only
visible as a *mismatch* between the two.

    docker compose exec -T web python manage.py review_images \
        --prompts /tmp/<venue>-sheet.md --company <slug> \
        --out /tmp/<slug>-review.html

Open the page. For every image ask:

- Is it the dish the name names?
- Does the count match the card? (`Egg (2Eggs)` came back with three halves.
  No sampler setting fixes counting — this check is the only thing that does.)
- Is there anything on the plate the card never printed?

Tick the failures, copy the key list, and record the verdict:

    docker compose exec -T web python manage.py verify_images \
        --prompts /tmp/<venue>-sheet.md --company <slug> \
        --reject <pasted keys>

Everything not rejected becomes `verified`. Rejected keys are re-rolled at a
new seed — a rejected asset no longer counts as done, and its bytes are
tombstoned so the same image can never come back:

    docker compose exec -T web python manage.py generate_item_images \
        --prompts /tmp/<venue>-sheet.md --reroll 1

Repeat until the page is clean.

**When the generator draws the wrong thing, fix the lexicon, not the row.**
`menu/pipeline/dish_lexicon.py` maps a menu head-word to the form the word
already denotes — `momo` → "steamed pleated dumplings", `masala` → "speckled
with chopped onion, chilli and coriander". A new entry needs founder sign-off,
because deciding what a word denotes is exactly where an invented claim would
enter. An item the run reports under `undefined head-word` either gains an
entry or becomes `*skip — ask the venue*`.

### 5. Build — sheet + assets become the fixture

    docker compose exec -T web python manage.py build_venue_fixture \
        --prompts /tmp/<venue>-sheet.md --company <slug> --require-verified

Writes `menu/fixtures/<slug>.json` and `menu/fixtures/media/<slug>/`. Read the
summary line: `generated` should be close to the item count, and `no image`
should only list items you know have no prompt.

`--require-verified` refuses to build while any image this fixture would ship is
still `pending` — it names the keys, and they go back through phase 4. Drop the
flag only for a venue whose set is knowingly unreviewed (Tranquility's is).

The asset pool is **global and reuse across venues is intentional** — a second
venue's "black tea" adopts the first venue's image by exact key. If a venue
supplies its own photographs, pass `--vault-listing` (an `ls > names.txt` of the
folder) and `--vault-dir`; the fuzzy passes exist only for that case.

### 6. Seed + import — the tenant

    docker compose exec -T web python manage.py seed_venue \
        --fixture menu/fixtures/<slug>.json
    docker compose exec -T web python manage.py import_menu \
        --company <slug> --fixture menu/fixtures/<slug>.json \
        --media-base menu/fixtures/media/<slug> --strict

`seed_venue` is the tenant shell only; `import_menu` owns the catalog and is
additive/idempotent. `--media-base` takes the local directory — no HTTP serving.

Verify on the live dev menu, not only in the command output: open
`https://<slug>.zxyn.online` (or `curl -H "Host: <slug>.zxyn.online"
http://localhost:8005/`) and check the category count, a few prices, and that
images render.

## Failure modes that cost time

| Symptom | Cause | Fix |
|---|---|---|
| Generation keeps declining one prompt | Content filter on `fried`/`fry` — deterministic | Reword in the sheet; do not retry |
| A whole section has no images | `###` heading edited after generating | Restore the heading, or re-generate |
| Template/HTML edit not visible on dev | Cached template loader; `--reload` watches only `.py` | `docker compose restart web` |
| A pipeline edit has no effect on a job | Celery has no autoreload | `docker compose restart worker` |
| A tenant's file overwritten | Media filename lacking the company | Media must live under `<company>/` |
| "succeeded" with 0 items | Wrong sheet path, or no `###` sections | Check counts at every phase |
| Every count green but photos are the wrong dish | The generator does not know `momo`, `thali`, `pakoda` | Name the form the word denotes; re-roll (phase 4) |
| `/platform/` route 404s under curl | Apex-only; wrong Host header, or port 8000 not 8005 | `-H "Host: zxyn.online" http://localhost:8005/…` |
| Every pale dish has a garnish nobody ordered | A style block asserting food content (`fresh vibrant colours, appetising`) | Style blocks describe camera and light only — guarded by a test |
| Hot drinks are served cold | `_DRINK_WORDS` contains `drink`, so `Hot Drinks` takes `DRINK_STYLE` | Temperature comes from the item via `DRINK_LEXICON`, never the style block |
| A whole section looks like one photo | Seed was the same for every item | `generate_flux.seed_for(key)` — one seed per item |
| Rejecting an image changes nothing | `done_keys` counted rejected as done | Fixed; re-roll with `--reroll N` |
| A venue went live on unreviewed images | `build_venue_fixture` ignored `status` | Build with `--require-verified` |

## Tests

The suite runs with `python -m pytest` **inside the web container** —
`manage.py test` silently misses pytest-style tests. A full run is ~7 minutes.

    docker compose exec -T web python -m pytest -q
