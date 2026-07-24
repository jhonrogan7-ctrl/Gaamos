# Venue prompt sheet — format

Path: `/root/zxyn/gaamos/menius/<venue>/<venue>-items-and-image-prompts.md`
Parsed by `menu/pipeline/prompt_sheet.py` (`parse`, `parse_venue`).

## Minimal worked example

    # Chill Zone — Item List + Image Generation Prompts

    **Source:** `menius/chillzone/WhatsApp Image 2026-07-23 at 14.25.01.jpeg`

    ## Venue

    | Field | Value |
    |---|---|
    | slug | chillzone |
    | name | Chill Zone |
    | tagline | Momo, coffee and cold beer in Thamel |
    | phone | |
    | branch.main.name | Chill Zone |
    | branch.main.address | Thamel, Kathmandu |
    | branch.main.tag | FLAGSHIP |

    ## Design vision

    Prose about the look of the image set. Not parsed.

    ## Card 1 — Page 1 (left)

    ### Hot Drinks

    | Item | Description | Price | Image prompt |
    |---|---|---|---|
    | Black Tea | Classic black tea, brewed strong. | 40 | a glass of black tea |
    | Milk Tea | Nepali milk tea with buffalo milk. | 60 | a glass cup of milk tea |

    ### Momo

    | Item | Description | Price | Image prompt |
    |---|---|---|---|
    | Jhol Momo (Veg) | Steamed veg momo in spiced soup. | 200 | veg jhol momo in broth |
    | Jhol Momo (Non Veg) | Steamed chicken momo in spiced soup. | 260 | chicken jhol momo in broth |

## Rules

**`## Venue`** — `| Field | Value |` rows.
`slug`, `name`, `tagline`, `phone`, `email`, `instagram`, `facebook`, `tiktok`
are the company. `branch.<slug>.<field>` builds the branch list in the order the
slugs first appear; fields are `name`, `address`, `tag`
(`FLAGSHIP` / `NEW` / empty). Anything else in the table is ignored. A blank
value is fine. `slug` must equal the `--company` argument or the build refuses.

**`## Card N — …`** — grouping only, recorded on each row as `card`. Not parsed
into anything downstream.

**`### <Section>`** — the category. `slugify(section)` is the category slug, and
display order is order of appearance. **Do not edit these after generating
images** — the section is half of every image key.

**Item tables** — columns are found by header, not position, so extra columns
and different orders are safe:

| Header starts with | Meaning |
|---|---|
| (first column, always) | Item name — `slugify(name)` is the item slug |
| `description` / `printed description` | Description. `—` or `-` means none |
| `price` | Integer Rs. `Rs 200`, `1,200` and `200` all parse. No decimals |
| `image prompt` / `prompt` | Short subject line; the style block is appended |

A second column headed anything else (e.g. `Spirit type`) is **not** a
description, but is kept as `col2` — it is what keys `*(reuse …)*` rows.

**Truthfulness** — the description and the prompt may only state what the item's
printed name commits to. `Jhol Momo (Veg)` → "steamed veg momo in spiced soup"
(*jhol* = soup, *momo* = dumpling). Banned in both columns: piece counts, sides,
dips, garnishes, cooking methods and ingredients the card does not print — the
generated photo is a claim about the dish, and the guest orders from it. Not
inferable → description `—`, prompt kept to the bare subject, item raised in the
closing summary. Rows asserting more than a literal reading get a trailing `⚠`.

**Prices** — a row with no price parses fine but is reported and not imported.
A split price on the card (`200/260` for veg/non-veg) becomes two rows.

**Directive prompts** — italic rows are instructions to a human, never sent to
the generator:
- `*skip — accessory, no image needed*` — no image for this item
- `*(reuse the vodka image)*` — share the image generated for another row in the
  same section with the same `col2` value

**Style blocks** are appended automatically by `prompt_sheet.full_prompt`; a
drink block is used when the *section* name contains drink/juice/lassi/shake/
beer/cocktail/wine. Do not paste style text into the prompt column.

## Keys

    asset key   = slugify(f"{section} {item}")        # generate_item_images
    fixture key = f"{slugify(section)}-{slugify(item)}"   # build_venue_fixture

These are equal by construction, which is what makes the exact-match join safe.
Item slugs are uniquified across the venue (a second `Banana` becomes
`banana-pancakes`) because `import_menu` upserts on `(company, item slug)`; the
join key stays the sheet key.
