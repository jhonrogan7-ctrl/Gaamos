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

FOOD_STYLE = (", professional food photography, 45-degree angle, natural window "
              "light, shallow depth of field, dark rustic wood table, fresh "
              "vibrant colours, appetising, high detail")
DRINK_STYLE = (", professional beverage photography, straight-on angle, soft "
               "natural light, condensation on the glass, clean neutral "
               "background, vibrant, high detail")

# Section-name keywords that make a section a drink section. Matched on the
# section, never the item: "Can Juice" sits in Soft Drinks, and "Hard Drinks"
# must land on the drink block too.
_DRINK_WORDS = ('drink', 'juice', 'lassi', 'shake', 'beer', 'cocktail', 'wine')

_SEPARATOR = re.compile(r'^:?-+:?$')
_NO_DESCRIPTION = ('', '-', '—', '–')


def _cells(line):
    return [c.strip() for c in line.strip().strip('|').split('|')]


def _is_separator(cells):
    return all(_SEPARATOR.match(c) for c in cells)


def is_drink(section):
    low = section.lower()
    return any(w in low for w in _DRINK_WORDS)


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
        item, prompt = cells[0], cells[2]
        # The middle column is `Spirit type` in the hard-drinks table — only a
        # real "Printed description" header means the cell is a description.
        described = len(header) > 1 and header[1].startswith('printed description')
        description = cells[1] if described else ''
        if description in _NO_DESCRIPTION:
            description = ''
        rows.append({
            'card': card, 'section': section, 'item': item,
            'description': description, 'prompt': prompt,
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
    """Subject line + the style block for the row's section."""
    return row['prompt'] + (DRINK_STYLE if row['drink'] else FOOD_STYLE)
