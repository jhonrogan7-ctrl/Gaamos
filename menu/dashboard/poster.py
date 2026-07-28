"""Print-ready QR poster rendering.

Draws the venue-facing "scan to view menu" sheet: near-black page, double
rounded border, the tenant's logo (when they have one), the venue name, the
table/room label verbatim, the QR itself, and the gaamos.io footer.

The palette is fixed for every tenant — a venue's logo is dropped in unchanged
rather than recolouring the page. A logo-derived accent was considered and
rejected: a pale logo colour would drag the QR's contrast under what scanners
need, and the failure would only show up on already-printed paper.

Geometry is expressed as fractions of the page, so the same code renders any
sheet size at any DPI.
"""
import io
import os

import qrcode
from qrcode.constants import ERROR_CORRECT_M
from PIL import Image, ImageChops, ImageDraw, ImageFont
from django.conf import settings

# --- palette (fixed for every tenant) ---------------------------------------
PAGE_BG = '#0d0d0d'
BORDER = '#e8e8e8'
TEXT = '#ffffff'
MUTED = '#9a9a9a'
QR_DARK = '#1a1a2e'      # navy, not pure black — matches the donor QR styling
QR_LIGHT = '#ffffff'

BRAND = 'gaamos.io'      # the product brand, deliberately not BASE_DOMAIN:
                         # printed paper outlives whatever host we run on today

# --- page sizes, in millimetres ---------------------------------------------
PAGE_SIZES_MM = {
    'a5': (148, 210),
    'a4': (210, 297),
}
DEFAULT_PAGE = 'a5'
PRINT_DPI = 300
PREVIEW_DPI = 150       # on-screen sheet: half the print size, still crisp on
                        # a retina dashboard, and half the bytes over the wire

# --- fonts ------------------------------------------------------------------
# Installed via the Dockerfile (fonts-crosextra-caladea, fonts-liberation,
# fonts-montserrat). Kept as a list per role so a missing package degrades to
# something readable instead of raising at render time.
#
# Both serifs are chosen for LINING figures. EB Garamond was tried first and
# rejected: its default oldstyle figures render room "101" as "ıoı", and with
# no libraqm in the image there is no way to force `lnum` on. A table number
# that prints wrong is worse than a less elegant face.
_SERIF_BOLD = [
    '/usr/share/fonts/truetype/crosextra/Caladea-Bold.ttf',
    '/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf',
]
_SERIF_BOLD_ITALIC = [
    '/usr/share/fonts/truetype/crosextra/Caladea-BoldItalic.ttf',
    '/usr/share/fonts/truetype/liberation/LiberationSerif-BoldItalic.ttf',
]
_SANS_BOLD = [
    '/usr/share/fonts/opentype/montserrat/Montserrat-Bold.otf',
    '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf',
]
_SANS_LIGHT = [
    '/usr/share/fonts/opentype/montserrat/Montserrat-Light.otf',
    '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
]


def _font(candidates, size):
    for path in candidates:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


def page_px(page=DEFAULT_PAGE, dpi=PRINT_DPI):
    """Pixel size of a sheet at the given DPI."""
    w_mm, h_mm = PAGE_SIZES_MM[page]
    return (round(w_mm / 25.4 * dpi), round(h_mm / 25.4 * dpi))


def _logo_path(company):
    """Filesystem path of the tenant's logo, or None when they have none.

    ``logo_url`` is a public URL carrying a cache-busting ``?v=`` — strip the
    query and the MEDIA_URL prefix to get back to disk. Returns None rather
    than raising when the row points at a file that is no longer there.
    """
    raw = (getattr(company, 'logo_url', '') or '').strip()
    if not raw:
        return None
    raw = raw.split('?', 1)[0]
    media_url = settings.MEDIA_URL or '/media/'
    if not raw.startswith(media_url):
        return None
    path = os.path.join(settings.MEDIA_ROOT, raw[len(media_url):])
    return path if os.path.exists(path) else None


def _draw_logo(canvas, company, cx, cy, diameter):
    """Draw the tenant logo inside a circle centred on (cx, cy).

    The logo is *contained*, never cropped to fill: tenant logos are arbitrary
    shapes and cropping a wide wordmark to a circle would cut the name in half.
    A venue with no logo leaves the space empty — the founder's call, so the
    sheet keeps the same proportions whether or not a logo exists.
    """
    path = _logo_path(company)
    if path is None:
        return False
    try:
        logo = Image.open(path).convert('RGBA')
    except OSError:
        return False

    aspect = logo.width / logo.height if logo.height else 1
    if 0.85 <= aspect <= 1.18:
        # Square-ish: a badge. Fill the circle and clip — a square canvas
        # holding circular art lands exactly on the circle, and a square photo
        # just gets its corners rounded.
        logo.thumbnail((diameter, diameter), Image.LANCZOS)
        clip = True
    else:
        # A wordmark. Fit its *diagonal* to the circle so the whole rectangle
        # sits inside — scaling only the width would push the far corners past
        # the circle's edge and clip the first and last letters of the name.
        scale = diameter / ((logo.width ** 2 + logo.height ** 2) ** 0.5)
        logo = logo.resize((max(1, round(logo.width * scale)),
                            max(1, round(logo.height * scale))), Image.LANCZOS)
        clip = False

    plate = Image.new('RGBA', (diameter, diameter), (0, 0, 0, 0))
    plate.paste(logo, ((diameter - logo.width) // 2,
                       (diameter - logo.height) // 2), logo)
    if clip:
        mask = Image.new('L', (diameter, diameter), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, diameter - 1, diameter - 1), fill=255)
        # Multiply rather than replace: a PNG logo with its own transparency
        # must keep it, and still be clipped to the circle.
        plate.putalpha(ImageChops.multiply(plate.getchannel('A'), mask))
    canvas.paste(plate, (round(cx - diameter / 2), round(cy - diameter / 2)), plate)
    return True


def _qr_image(url, side_px):
    """QR as a square RGB image of exactly ``side_px``, navy on white.

    box_size is derived from the module count so the code lands on whole
    pixels — a fractional module edge is what makes a printed QR fuzzy.
    """
    qr = qrcode.QRCode(version=None, error_correction=ERROR_CORRECT_M, border=4)
    qr.add_data(url)
    qr.make(fit=True)
    modules = qr.modules_count + qr.border * 2
    box = max(1, side_px // modules)
    qr.box_size = box
    img = qr.make_image(fill_color=QR_DARK, back_color=QR_LIGHT).convert('RGB')
    if img.size != (side_px, side_px):
        # NEAREST keeps module edges crisp; any smooth filter greys them.
        img = img.resize((side_px, side_px), Image.NEAREST)
    return img


def _fit_text(draw, text, font_paths, max_w, start_size, min_size):
    """Fit ``text`` inside ``max_w``, returning ``(font, text)``.

    Shrinks the face first, and if the name still doesn't fit at ``min_size``
    truncates it with an ellipsis. Company.name allows 120 characters — without
    the truncation floor a maximal name paints straight through the border and
    off the sheet.
    """
    size = start_size
    font = _font(font_paths, min_size)
    while size > min_size:
        candidate = _font(font_paths, size)
        if draw.textlength(text, font=candidate) <= max_w:
            return candidate, text
        size -= max(1, start_size // 40)

    if draw.textlength(text, font=font) <= max_w:
        return font, text
    ellipsis = '…'
    clipped = text
    while clipped and draw.textlength(clipped + ellipsis, font=font) > max_w:
        clipped = clipped[:-1]
    return font, (clipped.rstrip() + ellipsis) if clipped else ellipsis


def _draw_tracked(draw, text, cx, y, font, fill, tracking):
    """Centred text with letter-spacing (PIL has no tracking of its own)."""
    widths = [draw.textlength(ch, font=font) for ch in text]
    total = sum(widths) + tracking * (len(text) - 1)
    x = cx - total / 2
    for ch, w in zip(text, widths):
        draw.text((x, y), ch, font=font, fill=fill, anchor='lm')
        x += w + tracking


def render_poster(url, venue_name, label='', company=None,
                  page=DEFAULT_PAGE, dpi=PRINT_DPI):
    """Render one QR poster and return it as a Pillow image.

    ``venue_name`` is the big first line; ``label`` is the second line and is
    printed **verbatim** — there is no "Table"/"Room" prefix, because nothing
    in the data model says which noun a venue uses. A venue wanting "Room 101"
    types exactly that as the label.
    """
    W, H = page_px(page, dpi)
    canvas = Image.new('RGB', (W, H), PAGE_BG)
    draw = ImageDraw.Draw(canvas)
    cx = W / 2

    # Double rounded border.
    outer_m, inner_m = 0.048 * W, 0.088 * W
    draw.rounded_rectangle((outer_m, outer_m, W - outer_m, H - outer_m),
                           radius=0.038 * W, outline=BORDER,
                           width=max(1, round(0.0030 * W)))
    draw.rounded_rectangle((inner_m, inner_m, W - inner_m, H - inner_m),
                           radius=0.030 * W, outline=BORDER,
                           width=max(1, round(0.0016 * W)))

    # Logo (omitted entirely when the tenant has none).
    _draw_logo(canvas, company, cx, 0.181 * H, round(0.239 * W))

    # Venue name + label.
    text_max_w = W - 2 * inner_m - 0.04 * W
    name_font, name_text = _fit_text(draw, venue_name, _SERIF_BOLD, text_max_w,
                                     round(0.075 * W), round(0.030 * W))
    draw.text((cx, 0.300 * H), name_text, font=name_font, fill=TEXT, anchor='mm')
    if label:
        label_font, label_text = _fit_text(draw, label, _SERIF_BOLD, text_max_w,
                                           round(0.075 * W), round(0.030 * W))
        draw.text((cx, 0.360 * H), label_text, font=label_font, fill=TEXT,
                  anchor='mm')

    # QR, on its own white plate.
    qr_side = round(0.470 * W)
    qr_top = round(0.397 * H)
    canvas.paste(_qr_image(url, qr_side), (round(cx - qr_side / 2), qr_top))

    # Call to action + footer.
    cta_font = _font(_SERIF_BOLD_ITALIC, round(0.046 * W))
    draw.text((cx, 0.775 * H), 'SCAN TO VIEW MENU', font=cta_font,
              fill=TEXT, anchor='mm')

    powered_font = _font(_SANS_LIGHT, round(0.026 * W))
    _draw_tracked(draw, 'Powered By', cx, 0.843 * H, powered_font, MUTED,
                  tracking=0.011 * W)

    brand_font = _font(_SANS_BOLD, round(0.070 * W))
    draw.text((cx, 0.902 * H), BRAND, font=brand_font, fill=TEXT, anchor='mm')

    return canvas


def poster_png(url, venue_name, label='', company=None, page=DEFAULT_PAGE,
               dpi=PRINT_DPI):
    out = io.BytesIO()
    render_poster(url, venue_name, label, company, page, dpi).save(out, format='PNG')
    return out.getvalue()


def poster_pdf(pages, page=DEFAULT_PAGE):
    """One PDF from a list of ``(url, venue_name, label, company)`` tuples —
    a single sheet, or the whole set of tables in one printable document."""
    images = [render_poster(u, n, l, c, page) for u, n, l, c in pages]
    out = io.BytesIO()
    if images:
        images[0].save(out, format='PDF', save_all=True,
                       append_images=images[1:], resolution=PRINT_DPI)
    return out.getvalue()
