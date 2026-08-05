"""Turn a menu document into images small enough to inline in a model request.

Two facts drive this module:

* NVIDIA's VLM endpoints take images, not PDFs -- unlike Gemini, which accepted
  raw PDF bytes.
* An inline image is capped at roughly 180 KB of base64.

Measured across all 5 pages of a real card (`media/scans/1_Scanned Document
2.pdf`), every page rasterizing at 150 dpi to 3288x5138:

    page  PNG     b64 @q72   lands at
    1     12 MB    99,548     q72
    2     16 MB   150,988     q72
    3     50 MB   261,272     q40
    4     25 MB   175,436     q72
    5     26 MB   141,180     q72

Two things to take from that table before tuning any constant here. The quality
ladder is load-bearing on real input, not just on pathological input: page 3
does not fit at any quality above 40. And the margin is thin -- page 4 clears
the cap by 2.5%, so a slightly busier card steps down too. Downscaling further
by default would buy margin at the cost of the thin strokes the model reads
prices from, which is the wrong trade; the ladder is the right place to give.

Failing to fit raises rather than returning something oversized: the endpoint
would reject it anyway, and later is a worse place to find out.
"""
import base64
import io

from PIL import Image

INLINE_B64_CAP = 180_000
# Measured against 1100x1100 of pure RGB noise -- the worst case that still
# reaches this module, since noise is exactly what JPEG cannot compress. It is
# 212 KB of base64 at q30 and 136 KB at q20, so a ladder stopping at 30 raises
# on input it could have fitted. Below 20 is not worth a rung: a page that
# needs it has lost the thin strokes the model reads prices from, and a mushy
# image that "fits" yields a confidently wrong menu -- worse than a failure.
_QUALITY_LADDER = (72, 60, 50, 40, 30, 20)


def pdf_to_pages(data, *, dpi=150):
    """PDF bytes -> one PNG per page, in printed order."""
    import fitz
    try:
        doc = fitz.open(stream=data, filetype='pdf')
    except Exception as exc:                      # noqa: BLE001
        raise ValueError(f'document could not be read as a PDF: {exc}') from exc
    if doc.page_count == 0:
        raise ValueError('document could not be read: it has no pages')
    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)
    return [page.get_pixmap(matrix=matrix).tobytes('png') for page in doc]


def fit_inline(image, *, max_edge=1100, cap=INLINE_B64_CAP):
    """Any image -> JPEG bytes whose base64 fits under `cap`.

    Never upscales: a small image is already cheap, and enlarging it would
    invent detail the card does not have.
    """
    img = Image.open(io.BytesIO(image))
    if img.mode not in ('RGB', 'L'):
        img = img.convert('RGB')
    if max(img.size) > max_edge:
        scale = max_edge / max(img.size)
        img = img.resize((max(1, round(img.width * scale)),
                          max(1, round(img.height * scale))), Image.LANCZOS)
    for quality in _QUALITY_LADDER:
        buf = io.BytesIO()
        img.save(buf, format='JPEG', quality=quality, optimize=True)
        raw = buf.getvalue()
        if len(base64.b64encode(raw)) <= cap:
            return raw
    raise ValueError(
        f'page will not fit under {cap} base64 bytes even at quality '
        f'{_QUALITY_LADDER[-1]} -- reduce max_edge')


def pages_of(data, mime):
    """A document of any supported type -> wire-ready JPEG pages."""
    if (mime or '').lower() == 'application/pdf':
        return [fit_inline(p) for p in pdf_to_pages(data)]
    try:
        return [fit_inline(data)]
    except OSError as exc:
        raise ValueError(f'document could not be read as an image: {exc}') from exc
