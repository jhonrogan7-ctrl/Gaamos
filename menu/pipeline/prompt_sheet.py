"""Parse a hand-written item + image-prompt worksheet (markdown) into rows.

The sheet lives in the vault, one per venue: `## Card N — …` headings, `### `
sections, and a pipe table per section whose last column is the image prompt.
It is written for a human to paste into a generator UI, so the parser tolerates
padded columns, prose and blockquotes between tables, em-dash "no description"
cells, and italic directive rows (`*skip — …*`, `*(reuse the vodka image)*`)
that are instructions rather than prompts.

The shared style blocks below are appended per row so every image in a venue's
set looks like it came from one photoshoot — that consistency is the whole
reason the sheet carries short subject-only prompts.
"""
import re

from django.utils.text import slugify

from menu.pipeline.prompts import (DRINK_STYLE, FOOD_STYLE, compose,  # noqa: F401
                                   is_drink)

_SEPARATOR = re.compile(r'^:?-+:?$')
_NO_DESCRIPTION = ('', '-', '—', '–')
_PRICE_CHARS = re.compile(r'[^\d]')

# A row asserting more than a literal reading of the printed name carries a
# trailing `⚠` so the venue's review is a short list. It is an annotation on
# the sheet and nothing more — left in place it reaches the guest menu as part
# of the description, and one venue's prompt went to the image model reading
# "…toast and cheese ⚠".
_REVIEW_MARKER = re.compile(r'\s*⚠\s*$')

# The venue block's scalar fields, in the order they are written out. Anything
# else in the table is ignored rather than guessed at.
VENUE_FIELDS = ('slug', 'name', 'tagline', 'phone', 'email',
                'instagram', 'facebook', 'tiktok')
BRANCH_FIELDS = ('name', 'address', 'tag')


def _cells(line):
    return [c.strip() for c in line.strip().strip('|').split('|')]


def _is_separator(cells):
    return all(_SEPARATOR.match(c) for c in cells)


def _column(header, *prefixes, default=None):
    """Index of the first header cell starting with any prefix, else `default`.

    Position is not reliable once the sheet gains a Price column: the prompt is
    the 3rd cell on Tranquility's sheet and the 4th on Chill Zone's.
    """
    for i, cell in enumerate(header or []):
        if any(cell.startswith(p) for p in prefixes):
            return i
    return default


def _price(cell):
    """`200` / `Rs 200` / `1,200` -> int. Anything with no digits -> None."""
    digits = _PRICE_CHARS.sub('', cell or '')
    return int(digits) if digits else None


def parse(text):
    """Return one row dict per table row: card, section, item, description,
    prompt, generatable, drink, slug."""
    rows, card, section, header = [], '', '', None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith('## ') and not stripped.startswith('### '):
            card, section, header = stripped[3:].strip(), '', None
            continue
        if stripped.startswith('### '):
            section, header = stripped[4:].strip(), None
            continue
        if not stripped.startswith('|'):
            header = None                 # any non-table line ends the table
            continue
        if not section:
            continue      # e.g. the sheet's own `Suggested settings` table
        cells = _cells(stripped)
        if header is None:
            header = [c.lower() for c in cells]
            continue
        if _is_separator(cells) or len(cells) < 3:
            continue
        # Header-driven, not positional: a `Price` column shifts the prompt
        # right, and `Spirit type` in the hard-drinks table is not a description.
        prompt_i = _column(header, 'image prompt', 'prompt', default=len(cells) - 1)
        desc_i = _column(header, 'description', 'printed description')
        price_i = _column(header, 'price')
        item = cells[0]
        prompt = cells[prompt_i] if prompt_i < len(cells) else ''
        description = cells[desc_i] if desc_i is not None and desc_i < len(cells) else ''
        prompt = _REVIEW_MARKER.sub('', prompt)
        description = _REVIEW_MARKER.sub('', description)
        if description in _NO_DESCRIPTION:
            description = ''
        rows.append({
            'card': card, 'section': section, 'item': item,
            'description': description, 'prompt': prompt,
            'price': _price(cells[price_i]) if price_i is not None
                     and price_i < len(cells) else None,
            # Raw, whatever the header called it: `Printed description` in most
            # tables, `Spirit type` in hard drinks — where it is the only record
            # of which shared bottle shot a reuse row belongs to.
            'col2': cells[1],
            'generatable': bool(prompt) and not _is_directive(prompt),
            'drink': is_drink(section), 'slug': slugify(item),
            # Section-qualified: `Banana` is a milkshake in one section and a
            # pancake in another. Bare slugs collide; this is the resume key.
            'key': slugify(f'{section} {item}'),
        })
    return rows


def _is_directive(prompt):
    """`*skip — …*` / `*(reuse the vodka image)*` — a note to the operator."""
    return prompt.startswith('*') and prompt.endswith('*')


def full_prompt(row):
    """This sheet row's prompt. Composition lives in `prompts`; re-exported here
    because `generate_item_images`, `review_images` and `build_venue_fixture`
    have always reached for it on the parser."""
    return compose(row['prompt'], name=row['item'], drink=row['drink'])


def parse_venue(text):
    """Read the sheet's `## Venue` table into the venue's identity.

    The block is `| Field | Value |` rows: the scalars in `VENUE_FIELDS`, plus
    `branch.<slug>.<field>` rows that build the branch list in the order the
    slugs first appear. A sheet without the block (Tranquility's predates it)
    returns empty strings rather than raising — the caller reports it.
    """
    venue = {f: '' for f in VENUE_FIELDS}
    branches, order = {}, []
    inside = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith('## '):
            inside = stripped[3:].strip().lower() == 'venue'
            continue
        if not inside or not stripped.startswith('|'):
            continue
        cells = _cells(stripped)
        if len(cells) < 2 or _is_separator(cells):
            continue
        field, value = cells[0].strip(), cells[1].strip()
        if field.lower() == 'field':          # the table's own header row
            continue
        if field.startswith('branch.'):
            parts = field.split('.')
            if len(parts) != 3 or parts[2] not in BRANCH_FIELDS:
                continue
            _, slug, prop = parts
            if slug not in branches:
                branches[slug] = {'slug': slug, 'name': '', 'address': '', 'tag': ''}
                order.append(slug)
            branches[slug][prop] = value
        elif field in VENUE_FIELDS:
            venue[field] = value
    venue['branches'] = [branches[s] for s in order]
    return venue
