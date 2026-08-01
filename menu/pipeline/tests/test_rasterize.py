"""PDF pages in, wire-sized JPEGs out.

The size cap is not cosmetic: a NIM endpoint rejects an oversized inline image
outright, and a real card page rasterizes to 7.3 MB before anyone downscales
it. Every assertion here is measured against that real page (3288x5138 at
150 dpi, 96 KB base64 at 1100 px / q72).
"""
import base64
import io

import fitz
import pytest
from PIL import Image

from menu.pipeline import rasterize


def _pdf(pages=2):
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page()
        page.insert_text((72, 144), f'MENU PAGE {i + 1}', fontsize=48)
    return doc.tobytes()


def _png(w, h, colour=(200, 60, 40)):
    buf = io.BytesIO()
    Image.new('RGB', (w, h), colour).save(buf, format='PNG')
    return buf.getvalue()


def test_every_pdf_page_becomes_its_own_image():
    pages = rasterize.pdf_to_pages(_pdf(3))
    assert len(pages) == 3
    for raw in pages:
        assert Image.open(io.BytesIO(raw)).size[0] > 0


def test_a_one_page_pdf_yields_one_page_not_a_bare_image():
    assert len(rasterize.pdf_to_pages(_pdf(1))) == 1


def test_a_big_page_is_downscaled_under_the_base64_cap():
    """The real failure: a 3288x5138 card page is 7.3 MB, and the endpoint
    rejects it rather than downscaling for us."""
    fitted = rasterize.fit_inline(_png(3288, 5138))
    assert len(base64.b64encode(fitted)) <= rasterize.INLINE_B64_CAP


def test_downscaling_preserves_the_aspect_ratio():
    fitted = rasterize.fit_inline(_png(3288, 5138))
    w, h = Image.open(io.BytesIO(fitted)).size
    assert max(w, h) <= 1100
    assert abs((w / h) - (3288 / 5138)) < 0.01


def test_a_small_image_is_not_upscaled():
    w, h = Image.open(io.BytesIO(rasterize.fit_inline(_png(400, 300)))).size
    assert (w, h) == (400, 300)


def test_the_output_is_jpeg_because_png_does_not_fit():
    fitted = rasterize.fit_inline(_png(3288, 5138))
    assert Image.open(io.BytesIO(fitted)).format == 'JPEG'


def test_quality_steps_down_until_a_hostile_image_fits():
    """Noise does not compress. Resizing alone leaves this over the cap, so the
    quality ladder is what actually closes the gap."""
    import random
    random.seed(7)
    img = Image.new('RGB', (2000, 2000))
    img.putdata([(random.randrange(256), random.randrange(256),
                  random.randrange(256)) for _ in range(2000 * 2000)])
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    fitted = rasterize.fit_inline(buf.getvalue())
    assert len(base64.b64encode(fitted)) <= rasterize.INLINE_B64_CAP


def test_pages_of_routes_a_pdf_through_the_rasterizer():
    assert len(rasterize.pages_of(_pdf(2), 'application/pdf')) == 2


def test_pages_of_passes_an_image_through_as_one_page():
    pages = rasterize.pages_of(_png(3288, 5138), 'image/png')
    assert len(pages) == 1
    assert len(base64.b64encode(pages[0])) <= rasterize.INLINE_B64_CAP


def test_an_unreadable_document_says_so_rather_than_returning_nothing():
    """Zero pages would read downstream as an empty menu -- a wrong answer
    rather than a failure."""
    with pytest.raises(ValueError, match='could not be read'):
        rasterize.pages_of(b'this is not a pdf', 'application/pdf')
