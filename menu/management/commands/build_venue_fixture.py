"""Build a venue's seed fixture + media directory from its prompt sheet.

The sheet (vault: `menius/<venue>/<venue>-items-and-image-prompts.md`) is the
venue's single source of truth: its `## Venue` block is the tenant, its `###`
headings are the categories, and its table rows are the priced items whose
image prompts named the generated assets.

That shared origin is what makes the join safe. The generator stored each image
under `slugify("<section> <item>")`; this command looks it up under exactly the
same string, so the exact-key pass carries the whole set and the fuzzy passes
only ever run for a venue that also handed us its own photographs.

Media files are written as `<join key>.webp`, i.e. `<category>-<item>`, so a
wrong pairing is visible from the filename alone rather than hidden behind a
content hash.

Example:
  python manage.py build_venue_fixture \
      --prompts /tmp/chillzone-items-and-image-prompts.md --company chillzone
"""
import difflib
import json
import os
import re
import shutil
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils.text import slugify

from menu.models import ImageAsset
from menu.pipeline import category_icons, images, prompt_sheet

FIXTURES = Path(settings.BASE_DIR) / 'menu' / 'fixtures'

# Above this, two names are the same dish spelled differently ("Bread Omellete"
# / "Bread Omelette"). Below it they are different dishes that happen to share
# words ("Chicken Fry" / "Chicken Finger") — those must NOT be paired.
_NAME_MATCH_CUTOFF = 0.82


def _stem_slug(filename):
    stem = re.sub(r'_\d+$', '', os.path.splitext(filename)[0])
    return slugify(stem)


def _item_key(it):
    """The join key. Explicit when the item slug had to be uniquified."""
    return it.get('key') or f"{it['cat']}-{it['slug']}"


def build_catalog(rows):
    """Sheet rows -> (categories, items, unpriced keys). Pure; no I/O.

    Item slugs are uniquified across the whole venue because `import_menu`
    upserts on (company, slug): two `Banana` rows in different sections are two
    dishes, and without this the pancake's price would overwrite the shake's.
    The join key stays the sheet key, so uniquifying cannot break the match.
    """
    categories, seen_cat = [], set()
    items, unpriced, taken = [], [], set()
    order_in_cat = {}
    for row in rows:
        section = row['section']
        cat_slug = slugify(section)
        if cat_slug not in seen_cat:
            seen_cat.add(cat_slug)
            categories.append({'slug': cat_slug, 'name': section,
                               'display_order': len(categories) + 1,
                               'icon_key': category_icons.for_section(section), 'hours_note': '',
                               'subcategories': []})
        if row['price'] is None:
            unpriced.append(row['key'])
            continue
        slug = row['slug']
        if slug in taken:
            slug = f"{row['slug']}-{cat_slug}"
        n = 2
        while slug in taken:
            slug = f"{row['slug']}-{cat_slug}-{n}"
            n += 1
        taken.add(slug)
        order_in_cat[cat_slug] = order_in_cat.get(cat_slug, 0) + 1
        items.append({'slug': slug, 'name': row['item'], 'cat': cat_slug,
                      'sub': None, 'description': row['description'],
                      'price': row['price'], 'tags': [], 'popular': False,
                      'featured': False, 'order': order_in_cat[cat_slug],
                      'key': row['key'], 'image': None})
    return categories, items, unpriced


def assign_images(items, *, generated_keys, vault_files, sheet):
    """Map each fixture item to an image, one image to one item.

    Returns {join key: ("generated", asset_key) | ("found", filename) | None}.

    Exact matches are settled first so that an item with no image of its own can
    never take the photo belonging to a similarly-named dish; only images left
    unclaimed are open to name matching. The one deliberate exception is the
    sheet's `*(reuse the … image)*` rows, where several spirits are meant to
    share one bottle shot.
    """
    keys = [_item_key(it) for it in items]
    out = {k: None for k in keys}

    # 0. `*skip — ask the venue*` rows are withheld on purpose and take no
    #    image from any pass. The asset pool is global and keyed on section +
    #    item, so another venue's `Breakfast / American Breakfast` is an exact
    #    match for this one — and a withheld row has no prompt precisely because
    #    the printed name does not determine the dish. Adopting the other
    #    venue's photo would put its sausage and cheese on this card.
    withheld = {k for k in keys if _is_withheld(sheet, k)}
    items = [it for it, key in zip(items, keys) if key not in withheld]
    keys = [k for k in keys if k not in withheld]

    # 1. Exact key match — sheet and fixture agree, which is now by construction.
    free_generated = set(generated_keys)
    for it, key in zip(items, keys):
        if key in free_generated:
            out[key] = ('generated', key)
            free_generated.discard(key)

    # 2. The venue's own photograph, matched on the bare item name.
    free_vault = list(vault_files)
    for it, key in zip(items, keys):
        if out[key]:
            continue
        target = slugify(it['name'])
        hit = next((f for f in free_vault if _stem_slug(f) == target), None)
        if hit is None:                       # `ndian Breakfast_1.jpg`
            close = difflib.get_close_matches(
                target, [_stem_slug(f) for f in free_vault], n=1,
                cutoff=_NAME_MATCH_CUTOFF)
            if close:
                hit = next(f for f in free_vault if _stem_slug(f) == close[0])
        if hit:
            out[key] = ('found', hit)
            free_vault.remove(hit)

    # 3. Name drift, but only ever within the item's own category, and only when
    #    exactly one candidate fits — "Plain" is the Pancakes image for "Plain
    #    Pancake", while an ambiguous shortlist is left alone rather than guessed.
    for it, key in zip(items, keys):
        if out[key] or not free_generated:
            continue
        prefix = it['cat'] + '-'
        cands = [k for k in sorted(free_generated) if k.startswith(prefix)]
        tokens = set(it['slug'].split('-'))
        hits = [k for k in cands
                if _tokens_nest(set(k[len(prefix):].split('-')), tokens)]
        if not hits:                          # `jp-imported-wine` / `j-p-imported-wine`
            hits = [k for k in cands
                    if difflib.SequenceMatcher(None, k[len(prefix):],
                                               it['slug']).ratio() >= 0.85]
        if len(hits) == 1:
            out[key] = ('generated', hits[0])
            free_generated.discard(hits[0])

    # 4. `*(reuse the whisky image)*` — sharing one shot across a spirit type is
    #    the sheet's explicit instruction, so this pass may reuse a claimed
    #    image. Keyed on (section, spirit type): a whisky must not inherit the
    #    rum photo just because both sit under Hard Drinks.
    shared_image = {}
    for key, chosen in out.items():
        row = sheet.get(key)
        if chosen and chosen[0] == 'generated' and row:
            shared_image.setdefault((row['section'], row['col2']), chosen[1])
            shared_image.setdefault((row['section'], None), chosen[1])
    for it, key in zip(items, keys):
        if out[key]:
            continue
        row = sheet.get(key) or _sheet_row_by_name(sheet, it['name'],
                                                   section_slug=it['cat'])
        if row and not row['generatable'] and 'reuse' in row['prompt'].lower():
            shared = shared_image.get((row['section'], row['col2']))
            if shared:
                out[key] = ('generated', shared)
    return out


def _is_withheld(sheet, key):
    """A `*skip — ask the venue*` row, as opposed to a `*(reuse …)*` one.

    Both are italic directives rather than prompts, but they mean opposite
    things: reuse says "this item shares that image", skip says "nothing may be
    drawn for this item at all".
    """
    row = sheet.get(key)
    if row is None or row.get('generatable'):
        return False
    prompt = (row.get('prompt') or '').strip()
    return (prompt.startswith('*') and prompt.endswith('*')
            and 'reuse' not in prompt.lower())


def _tokens_nest(a, b):
    """One name's words fully inside the other's — `Plain` within `Plain Pancake`."""
    return bool(a) and bool(b) and (a <= b or b <= a)


def _sheet_row_by_name(sheet, name, *, section_slug=None):
    """The sheet keys off the printed name; a venue photo may be filed under a
    corrected one — `Black Level` on the card is `Black Label` in the fixture.

    Narrowing to the item's own section first is what makes a loose threshold
    safe: `black-label`/`black-level` score only 0.82, but inside Hard Drinks
    there is nothing else it could plausibly be.
    """
    rows = list(sheet.values())
    if section_slug:
        scoped = [r for r in rows if slugify(r['section']) == section_slug]
        if scoped:
            rows = scoped
    target = slugify(name)
    for row in rows:
        if slugify(row['item']) == target:
            return row
    cutoff = 0.75 if section_slug else 0.85
    close = difflib.get_close_matches(target, [slugify(r['item']) for r in rows],
                                      n=1, cutoff=cutoff)
    if close:
        return next(r for r in rows if slugify(r['item']) == close[0])
    return None


class Command(BaseCommand):
    help = ('Dev-only: build menu/fixtures/<company>.json + its media dir from '
            'a venue prompt sheet, generated ImageAssets and venue photos.')

    def add_arguments(self, parser):
        parser.add_argument('--prompts', required=True,
                            help='Path to the venue prompt sheet (markdown).')
        parser.add_argument('--company', required=True,
                            help='Company slug; names the fixture and media dir.')
        parser.add_argument('--vault-listing', default=None,
                            help='File listing the venue photo folder (ls > names.txt).')
        parser.add_argument('--vault-dir', default=None,
                            help='Readable copy of the venue photo folder.')
        parser.add_argument('--source', default='flux',
                            help='ImageAsset.source to draw from (default: flux).')
        parser.add_argument('--require-verified', action='store_true',
                            help='Refuse to build if any chosen image is still '
                                 'pending review.')
        parser.add_argument('--out', default=None)
        parser.add_argument('--media-out', default=None)
        parser.add_argument('--size', type=int, default=800)

    def handle(self, *args, **opts):
        sheet_path = Path(opts['prompts'])
        if not sheet_path.exists():
            raise CommandError(f'Prompt sheet not found: {sheet_path}')
        text = sheet_path.read_text()
        rows = prompt_sheet.parse(text)
        venue = prompt_sheet.parse_venue(text)
        company_slug = opts['company']
        if venue['slug'] and venue['slug'] != company_slug:
            raise CommandError(
                f"Sheet declares slug '{venue['slug']}' but --company is "
                f"'{company_slug}'. Fix the sheet, not the command.")
        venue['slug'] = company_slug

        categories, items, unpriced = build_catalog(rows)
        if not items:
            raise CommandError('Sheet produced 0 priced items — check the '
                               'Price column header and the `###` headings.')

        # The newest NON-REJECTED asset per key. Both clauses matter: a re-roll
        # adds a row rather than replacing the old one, so a re-rolled key has
        # two assets sharing `found_for_slug`, and the model's default ordering
        # (`-created_at`) would hand the lookup to the oldest — the very image
        # the reviewer rejected.
        assets = {a.found_for_slug: a
                  for a in ImageAsset.objects.filter(source=opts['source'])
                  .exclude(status='rejected').order_by('created_at')}
        vault_files = []
        if opts['vault_listing']:
            vault_files = [l.strip() for l in
                           Path(opts['vault_listing']).read_text().splitlines()
                           if l.strip() and not l.strip().endswith('.webp')]
        sheet = {r['key']: r for r in rows}

        chosen = assign_images(items, generated_keys=set(assets),
                               vault_files=vault_files, sheet=sheet)

        if opts['require_verified']:
            # Only the images this fixture would actually ship — an unreviewed
            # asset elsewhere in the shared pool is not this venue's problem.
            unreviewed = {
                ref for pick in chosen.values()
                if pick and pick[0] == 'generated'
                for ref in [pick[1]]
                if assets[ref].status != 'verified'}
            # A key whose every asset is rejected was excluded from `assets`
            # above, so it is not in `chosen` either — it would ship imageless
            # without a word. Name it too rather than let it pass quietly.
            only_rejected = set(
                ImageAsset.objects.filter(source=opts['source'],
                                          status='rejected',
                                          found_for_slug__in=set(chosen))
                .values_list('found_for_slug', flat=True)) - set(assets)
            blocked = sorted(unreviewed | only_rejected)
            if blocked:
                raise CommandError(
                    f'{len(blocked)} image(s) not verified — review them '
                    f'first (`review_images` then `verify_images`): '
                    + ', '.join(blocked))

        media_out = Path(opts['media_out'] or (FIXTURES / 'media' / company_slug))
        media_out.mkdir(parents=True, exist_ok=True)
        counts = {'generated': 0, 'found': 0, 'none': 0}
        for it in items:
            key = _item_key(it)
            pick = chosen[key]
            if not pick:
                counts['none'] += 1
                continue
            kind, ref = pick
            dest = media_out / f'{key}.webp'
            if kind == 'generated':
                asset = assets[ref]
                shutil.copyfile(Path(settings.MEDIA_ROOT) / asset.file, dest)
                it['image'] = {'file': dest.name, 'source': 'generated',
                               'origin_url': None, 'prompt': asset.prompt}
            else:
                if not opts['vault_dir']:
                    raise CommandError('--vault-dir is required for venue photos.')
                # Venue photos are ~1 MB JPEGs; the menu serves 800px webp.
                images.to_thumbnail(str(Path(opts['vault_dir']) / ref),
                                    str(dest), opts['size'])
                it['image'] = {'file': dest.name, 'source': 'found',
                               'origin_url': None, 'prompt': None}
            counts[kind] += 1

        for it in items:
            it.pop('key')                  # a build-time join key, not fixture data
        out = Path(opts['out'] or (FIXTURES / f'{company_slug}.json'))
        out.write_text(json.dumps({'venue': venue, 'categories': categories,
                                   'items': items},
                                  ensure_ascii=False, indent=2))
        self.stdout.write(self.style.SUCCESS(
            f"{out}: {len(items)} items in {len(categories)} categories | "
            f"generated {counts['generated']} | venue photo {counts['found']} "
            f"| no image {counts['none']}"))
        if unpriced:
            self.stdout.write(self.style.WARNING(
                f'no price, NOT imported ({len(unpriced)}): '
                + ', '.join(unpriced)))
        missing = [i['slug'] for i in items if not i['image']]
        if missing:
            self.stdout.write('no image: ' + ', '.join(missing))
