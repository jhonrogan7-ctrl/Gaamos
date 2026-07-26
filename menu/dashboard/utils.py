import io
import os

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


def branch_poster_lines(branch):
    """Poster headings for a branch's general QR: the company name, then the
    branch name underneath. Suppressed when the two are the same string, so a
    single-branch venue doesn't print its own name twice."""
    venue = branch.company.name
    label = branch.name if branch.name != venue else ''
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
