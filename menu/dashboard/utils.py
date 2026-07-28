import io
import os
import re

from django.conf import settings

from . import poster


def request_base_url(request):
    """Scheme + host the operator is on, e.g. https://testco.localhost:8005.
    The tenant is resolved from this host, so a QR encoded with it round-trips
    back to the same company's menu. (Phase 4 custom domains may add a canonical
    override; until then, mirror the operator's host.)"""
    return f"{request.scheme}://{request.get_host()}"


def general_qr_url(base_url, branch):
    return f"{base_url}/?branch={branch.slug}"


def table_qr_url(base_url, branch, table):
    return f"{base_url}/?branch={branch.slug}&t={table.code}"


# Punctuation an operator puts between a venue name and its locality, e.g.
# "Kaisha Restro - Thamel". Trimmed off whatever survives the repeat check so
# the second line never starts on a lone dash or bracket.
_EDGE_PUNCT = ' \t-–—_,;:|/\\·•&()[]{}।'

# Words are "runs of anything that isn't a separator" rather than \w+: \w
# excludes Devanagari combining vowel signs, so \w+ chops रेस्ट्रो in two and
# leaves a stray matra behind on the poster.
_TOKEN_RE = re.compile(r'[^\s' + re.escape(_EDGE_PUNCT + '.!?\'"“”‘’«»…॥') + r']+')


def _words(text):
    """Word spans of ``text``, Unicode-aware so Devanagari names split too."""
    return list(_TOKEN_RE.finditer(text))


def _strip_repeated_venue(venue, name):
    """``name`` with a leading or trailing repeat of ``venue`` removed.

    Compared word-by-word, casefolded and ignoring punctuation, because the
    repeat is retyped by hand: "Kaisha Restro Thamel", "Kaisha Restro -
    Lakeside" and "KAISHA  RESTRO" are all the venue name said twice. Only a
    whole-name repeat at one end counts — a branch that merely shares a word
    ("Kaisha Bakery") keeps its name intact.
    """
    v = [m.group().casefold() for m in _words(venue)]
    marks = _words(name)
    b = [m.group().casefold() for m in marks]
    if not v or not b:
        return name
    if b[:len(v)] == v:
        rest = name[marks[len(v) - 1].end():] if len(b) > len(v) else ''
    elif len(b) > len(v) and b[-len(v):] == v:
        rest = name[:marks[-len(v)].start()]
    else:
        return name
    return rest.strip(_EDGE_PUNCT)


def branch_poster_lines(branch):
    """Poster headings for a branch's general QR: the company name, then the
    branch name underneath.

    The branch line is suppressed when it only repeats the venue name, so a
    venue doesn't print its own name twice on one sheet. The ops signup form
    asks for the venue name and the first branch name separately, and operators
    routinely answer both with the restaurant's name — sometimes verbatim,
    sometimes with the locality appended — which is how a printed poster ended
    up with two titles.
    """
    venue = branch.company.name.strip()
    label = _strip_repeated_venue(venue, branch.name.strip())
    return venue, label


def table_poster_lines(branch, table):
    """Poster headings for a table QR. The label prints **verbatim** — there is
    no "Table"/"Room" prefix, because nothing in the data model distinguishes a
    restaurant's tables from a hotel's rooms. A venue that wants "Room 101"
    types exactly that as the label."""
    return branch.company.name, table.label


def render_branch_poster_png(base_url, branch, page=poster.DEFAULT_PAGE):
    venue, label = branch_poster_lines(branch)
    return poster.poster_png(general_qr_url(base_url, branch), venue, label,
                             company=branch.company, page=page)


def render_branch_poster_preview_png(base_url, branch, page=poster.DEFAULT_PAGE):
    """The same sheet as the download, at screen resolution.

    Rendering costs ~30ms, so the QR screens draw the live sheet rather than a
    file written at Generate time — a stored preview goes stale the moment a
    name changes or the poster design moves on, and the operator then prints
    from a download that looks nothing like what they approved on screen.
    """
    venue, label = branch_poster_lines(branch)
    return poster.poster_png(general_qr_url(base_url, branch), venue, label,
                             company=branch.company, page=page,
                             dpi=poster.PREVIEW_DPI)


def render_branch_poster_pdf(base_url, branch, page=poster.DEFAULT_PAGE):
    venue, label = branch_poster_lines(branch)
    return poster.poster_pdf(
        [(general_qr_url(base_url, branch), venue, label, branch.company)],
        page=page)


def render_table_poster_png(base_url, branch, table, page=poster.DEFAULT_PAGE):
    venue, label = table_poster_lines(branch, table)
    return poster.poster_png(table_qr_url(base_url, branch, table), venue, label,
                             company=branch.company, page=page)


def render_table_qr_pdf(base_url, branch, tables, page=poster.DEFAULT_PAGE):
    """One poster page per table, in a single PDF — a venue prints the whole
    set at once. Rendered on demand; nothing is stored."""
    pages = []
    for t in tables:
        venue, label = table_poster_lines(branch, t)
        pages.append((table_qr_url(base_url, branch, t), venue, label, branch.company))
    return poster.poster_pdf(pages, page=page)


def generate_qr_for_branch(branch, base_url):
    """Render and store the branch's general QR poster. The stored file is both
    the dashboard preview and the PNG download, so it is written at print
    resolution rather than screen size."""
    png = render_branch_poster_png(base_url, branch)
    dest_dir = os.path.join(settings.MEDIA_ROOT, 'qr')
    os.makedirs(dest_dir, exist_ok=True)
    # Branch slugs are only unique per company — the filename must carry the
    # company too, or same-slug branches in different tenants share one file.
    filename = f"branch_{branch.company.slug}_{branch.slug}.png"
    path = os.path.join(dest_dir, filename)
    with open(path, 'wb') as f:
        f.write(png)

    branch.qr_image = f"qr/{filename}"
    branch.save(update_fields=['qr_image'])
    return path
