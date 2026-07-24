"""Dev-only: build the Tranquility Inn seed fixture + its media directory.

Same shape as `build_showcase_fixture`: take the existing preview fixture (163
priced items across 30 categories), attach an image to every item it can, and
emit a fixture `import_menu` can load into the tenant.

Images come from two places — the pipeline's generated ImageAssets and the
venue's own photos in the vault folder. Media files are written as
`<category>-<item>.webp`, i.e. the fixture key, so a wrong pairing is visible
from the filename alone rather than hidden behind a content hash.

Example:
  python manage.py build_tranquility_fixture --vault-listing /tmp/vaultfiles.txt \
      --vault-dir /tmp/vault --out menu/fixtures/tranquility-inn.json
"""
import difflib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils.text import slugify

from menu.models import ImageAsset
from menu.pipeline import images, prompt_sheet

PREVIEW = Path(settings.BASE_DIR) / 'menu' / 'fixtures' / 'tranquility-inn-preview.json'
DEFAULT_OUT = Path(settings.BASE_DIR) / 'menu' / 'fixtures' / 'tranquility-inn.json'
DEFAULT_MEDIA = (Path(settings.BASE_DIR) / 'menu' / 'fixtures' / 'media'
                 / 'tranquility-inn')

# Above this, two names are the same dish spelled differently ("Bread Omellete"
# / "Bread Omelette"). Below it they are different dishes that happen to share
# words ("Chicken Fry" / "Chicken Finger") — those must NOT be paired.
_NAME_MATCH_CUTOFF = 0.82

# The fixture's category slugs against the prompt sheet's section headings. The
# sheet keeps the card's own wording ("Continental (with French Fries)"), the
# fixture shortened it. Spelled out rather than fuzzy-matched: a category is
# picked once, by hand, and a wrong guess here mis-files a whole section.
CATEGORY_ALIASES = {
    'continental': 'continental-with-french-fries',
    'sandwich-and-burger': 'sandwich-and-burger-with-french-fries',
    'hookah': 'hukka',
    'wine': 'wine-by-bottle',
    'soup': 'soup-with-garlic-bread',
    'thali': 'nepali-thali-set',
}


def _stem_slug(filename):
    stem = re.sub(r'_\d+$', '', os.path.splitext(filename)[0])
    return slugify(stem)


def assign_images(items, *, generated_keys, vault_files, sheet):
    """Map each fixture item to an image, one image to one item.

    Returns {fixture_key: ("generated", asset_key) | ("found", filename) | None}.

    Exact matches are settled first so that an item with no image of its own can
    never take the photo belonging to a similarly-named dish; only images left
    unclaimed are open to name matching. The one deliberate exception is the
    sheet's `*(reuse the … image)*` rows, where several spirits are meant to
    share one bottle shot.
    """
    keys = [f"{it['cat']}-{it['slug']}" for it in items]
    out = {k: None for k in keys}

    # 1. Exact key match — the fixture and the sheet agree on this item.
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
        prefix = CATEGORY_ALIASES.get(it['cat'], it['cat']) + '-'
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
        section_slug = CATEGORY_ALIASES.get(it['cat'], it['cat'])
        row = sheet.get(key) or _sheet_row_by_name(sheet, it['name'],
                                                   section_slug=section_slug)
        if row and not row['generatable'] and 'reuse' in row['prompt'].lower():
            shared = shared_image.get((row['section'], row['col2']))
            if shared:
                out[key] = ('generated', shared)
    return out


def _tokens_nest(a, b):
    """One name's words fully inside the other's — `Plain` within `Plain Pancake`."""
    return bool(a) and bool(b) and (a <= b or b <= a)


def _sheet_row_by_name(sheet, name, *, section_slug=None):
    """The sheet keys off the printed name; the fixture corrected it —
    `Black Level` on the card is `Black Label` in the fixture.

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
    help = ('Dev-only: build menu/fixtures/tranquility-inn.json + its media dir '
            'from the preview fixture, generated ImageAssets and venue photos.')

    def add_arguments(self, parser):
        parser.add_argument('--vault-listing', default=None,
                            help='File listing the venue folder (ls > names.txt).')
        parser.add_argument('--vault-dir', default=None,
                            help='Readable copy of the venue photo folder.')
        parser.add_argument('--prompts', default=None,
                            help='Prompt sheet, for the reuse-row instructions.')
        parser.add_argument('--out', default=str(DEFAULT_OUT))
        parser.add_argument('--media-out', default=str(DEFAULT_MEDIA))
        parser.add_argument('--size', type=int, default=800)

    def handle(self, *args, **opts):
        if not PREVIEW.exists():
            raise CommandError(f'Preview fixture not found: {PREVIEW}')
        data = json.loads(PREVIEW.read_text())
        items = data['items']

        assets = {a.found_for_slug: a for a in ImageAsset.objects.filter(source='flux')}
        vault_files = []
        if opts['vault_listing']:
            vault_files = [l.strip() for l in
                           Path(opts['vault_listing']).read_text().splitlines()
                           if l.strip() and not l.strip().endswith('.webp')]
        sheet = {}
        if opts['prompts']:
            sheet = {r['key']: r for r in
                     prompt_sheet.parse(Path(opts['prompts']).read_text())}

        chosen = assign_images(items, generated_keys=set(assets),
                               vault_files=vault_files, sheet=sheet)

        media_out = Path(opts['media_out'])
        media_out.mkdir(parents=True, exist_ok=True)
        counts = {'generated': 0, 'found': 0, 'none': 0}
        for it in items:
            key = f"{it['cat']}-{it['slug']}"
            pick = chosen[key]
            if not pick:
                it['image'] = None
                counts['none'] += 1
                continue
            kind, ref = pick
            dest = media_out / f'{key}.webp'
            if kind == 'generated':
                asset = assets[ref]
                src = Path(settings.MEDIA_ROOT) / asset.file
                shutil.copyfile(src, dest)
                it['image'] = {'file': dest.name, 'source': 'generated',
                               'origin_url': None, 'prompt': asset.prompt}
            else:
                if not opts['vault_dir']:
                    raise CommandError('--vault-dir is required for venue photos.')
                src = Path(opts['vault_dir']) / ref
                # Venue photos are ~1 MB JPEGs; the menu serves 800px webp.
                images.to_thumbnail(str(src), str(dest), opts['size'])
                it['image'] = {'file': dest.name, 'source': 'found',
                               'origin_url': None, 'prompt': None}
            counts[kind] += 1

        Path(opts['out']).write_text(json.dumps(data, ensure_ascii=False, indent=2))
        self.stdout.write(self.style.SUCCESS(
            f"{opts['out']}: {len(items)} items | generated {counts['generated']} "
            f"| venue photo {counts['found']} | no image {counts['none']}"))
        missing = [f"{it['cat']}-{it['slug']}" for it in items if not it['image']]
        if missing:
            self.stdout.write('no image: ' + ', '.join(missing))
