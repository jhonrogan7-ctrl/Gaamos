"""QR poster rendering — the printed sheet a venue puts on a table or a door.

Covers the contract the design depends on: real print geometry, the tenant
logo appearing only when they actually have one, the label printing verbatim,
and a wordmark never being clipped by the circular badge treatment.
"""
import io
import os

from django.conf import settings
from PIL import Image

from menu.dashboard import poster
from menu.dashboard.utils import (
    branch_poster_lines, render_branch_poster_pdf, render_table_qr_pdf,
    table_poster_lines,
)
from menu.models import Branch, Table
from menu.tests.base import TenantTestCase

URL = 'https://testco.zxyn.online/?branch=lake&t=abc123'


def _write_logo(name, size, colour):
    """Write a logo into the (isolated) test MEDIA_ROOT and return its URL."""
    d = os.path.join(settings.MEDIA_ROOT, 'logos')
    os.makedirs(d, exist_ok=True)
    Image.new('RGBA', size, colour).save(os.path.join(d, name))
    return f"{settings.MEDIA_URL}logos/{name}"


class _Co:
    """Stand-in for a Company — the renderer only ever reads ``logo_url``."""
    def __init__(self, logo_url=''):
        self.logo_url = logo_url
        self.name = 'Test Co'


class PosterGeometryTest(TenantTestCase):
    def test_a5_is_a_real_a5_sheet_at_300dpi(self):
        # 148x210mm. Getting this wrong prints a sheet that won't fit the page.
        self.assertEqual(poster.page_px('a5', 300), (1748, 2480))

    def test_a4_is_a_real_a4_sheet_at_300dpi(self):
        self.assertEqual(poster.page_px('a4', 300), (2480, 3508))

    def test_rendered_poster_matches_the_page_size(self):
        img = poster.render_poster(URL, 'Test Co', '101')
        self.assertEqual(img.size, poster.page_px('a5', 300))

    def test_page_is_the_dark_template_colour_not_white(self):
        img = poster.render_poster(URL, 'Test Co', '101')
        self.assertEqual(img.getpixel((5, 5)), (13, 13, 13))


class PosterLogoTest(TenantTestCase):
    def _logo_band(self, img):
        """The horizontal strip where the logo sits, as a set of colours."""
        W, H = img.size
        top, bot = round(0.10 * H), round(0.26 * H)
        return img.crop((round(0.30 * W), top, round(0.70 * W), bot))

    def test_no_logo_leaves_the_space_empty(self):
        # Founder's call: a venue without a logo gets black space, not a
        # placeholder and not a reflowed layout.
        img = poster.render_poster(URL, 'Test Co', '101', company=_Co(''))
        self.assertEqual(set(self._logo_band(img).getdata()), {(13, 13, 13)})

    def test_logo_is_drawn_when_the_tenant_has_one(self):
        url = _write_logo('badge.png', (400, 400), (200, 30, 30, 255))
        img = poster.render_poster(URL, 'Test Co', '101', company=_Co(url))
        self.assertIn((200, 30, 30), set(self._logo_band(img).getdata()))

    def test_cache_busting_query_is_stripped_from_the_logo_url(self):
        # save_logo_image appends ?v=<ts>; a naive path join would 404 on it.
        url = _write_logo('badge2.png', (400, 400), (10, 200, 90, 255))
        img = poster.render_poster(URL, 'Test Co', '1', company=_Co(url + '?v=12345'))
        self.assertIn((10, 200, 90), set(self._logo_band(img).getdata()))

    def test_missing_logo_file_renders_the_plain_sheet_instead_of_failing(self):
        # A logo row pointing at a deleted file must not 500 the download.
        img = poster.render_poster(URL, 'Test Co', '101',
                                   company=_Co(f'{settings.MEDIA_URL}logos/gone.png'))
        self.assertEqual(img.size, poster.page_px('a5', 300))
        self.assertEqual(set(self._logo_band(img).getdata()), {(13, 13, 13)})

    def test_wide_wordmark_is_not_clipped_by_the_circle(self):
        """A wordmark is fitted by its diagonal, so every pixel of it survives.

        Scaling a 4:1 logo to the circle's *width* would push its corners
        outside the circle and cut the first and last letters of the name.
        """
        url = _write_logo('wordmark.png', (800, 200), (0, 90, 255, 255))
        img = poster.render_poster(URL, 'Test Co', '101', company=_Co(url))

        band = self._logo_band(img)
        logo_px = sum(1 for p in band.getdata() if p == (0, 90, 255))
        W = img.size[0]
        d = 0.239 * W
        # Whole rectangle inside the circle => area is (d^2 * w*h)/(w^2+h^2).
        expected = (d ** 2) * (800 * 200) / (800 ** 2 + 200 ** 2)
        self.assertAlmostEqual(logo_px / expected, 1.0, delta=0.02)


class PosterTextTest(TenantTestCase):
    def setUp(self):
        super().setUp()
        self.branch = Branch.objects.create(company=self.company, name='Lake', slug='lake')

    def test_label_prints_verbatim_with_no_table_or_room_prefix(self):
        # Nothing in the data model says whether a venue has tables or rooms,
        # so the poster must not invent the noun.
        t = Table.objects.create(branch=self.branch, label='101', code='abc123')
        venue, label = table_poster_lines(self.branch, t)
        self.assertEqual(venue, self.company.name)
        self.assertEqual(label, '101')
        self.assertNotIn('Table', label)
        self.assertNotIn('Room', label)

    def test_venue_typing_room_101_gets_exactly_that(self):
        t = Table.objects.create(branch=self.branch, label='Room 101', code='def456')
        self.assertEqual(table_poster_lines(self.branch, t)[1], 'Room 101')

    def test_branch_label_suppressed_when_same_as_company(self):
        self.branch.name = self.company.name
        self.assertEqual(branch_poster_lines(self.branch)[1], '')

    def test_footer_is_the_product_brand(self):
        self.assertEqual(poster.BRAND, 'gaamos.io')

    def _title_gutter(self, img):
        """The strip between the inner border and the leftmost column type may
        occupy. Anything painted here has overflowed."""
        W, H = img.size
        return img.crop((round(0.092 * W), round(0.28 * H),
                         round(0.104 * W), round(0.33 * H)))

    def test_long_venue_name_shrinks_instead_of_overflowing(self):
        img = poster.render_poster(
            URL, 'The Extremely Long Restaurant And Guest House Name', '101')
        self.assertEqual(set(self._title_gutter(img).getdata()), {(13, 13, 13)})

    def test_maximum_length_name_is_truncated_not_run_off_the_sheet(self):
        """Company.name allows 120 chars. Shrinking alone bottoms out at the
        minimum readable size, so past that the name must be ellipsised —
        otherwise it prints straight through the border and off the paper."""
        img = poster.render_poster(URL, 'W' * 120, '101')
        self.assertEqual(set(self._title_gutter(img).getdata()), {(13, 13, 13)})

        W, H = img.size
        outer_margin = img.crop((0, round(0.28 * H), round(0.04 * W), round(0.33 * H)))
        self.assertEqual(set(outer_margin.getdata()), {(13, 13, 13)})

    def test_maximum_length_table_label_also_stays_on_the_sheet(self):
        t = Table.objects.create(branch=self.branch, label='9' * 40, code='zzz999')
        img = poster.render_poster(URL, 'Test Co', table_poster_lines(self.branch, t)[1])
        W, H = img.size
        gutter = img.crop((round(0.092 * W), round(0.34 * H),
                           round(0.104 * W), round(0.39 * H)))
        self.assertEqual(set(gutter.getdata()), {(13, 13, 13)})


class PosterPdfTest(TenantTestCase):
    def setUp(self):
        super().setUp()
        self.branch = Branch.objects.create(company=self.company, name='Lake', slug='lake')

    def test_branch_pdf_is_a_pdf(self):
        data = render_branch_poster_pdf('https://testco.localhost', self.branch)
        self.assertTrue(data.startswith(b'%PDF'))

    def test_all_tables_pdf_has_one_page_per_table(self):
        tables = [Table.objects.create(branch=self.branch, label=str(i))
                  for i in range(3)]
        data = render_table_qr_pdf('https://testco.localhost', self.branch, tables)
        self.assertTrue(data.startswith(b'%PDF'))
        self.assertEqual(data.count(b'/Type /Page\n'), 3)

    def test_no_tables_yields_empty_bytes_not_a_broken_pdf(self):
        self.assertEqual(render_table_qr_pdf('https://x', self.branch, []), b'')


class PosterQrTest(TenantTestCase):
    def test_qr_is_square_and_exact_requested_size(self):
        img = poster._qr_image(URL, 600)
        self.assertEqual(img.size, (600, 600))

    def test_qr_has_a_white_quiet_zone(self):
        # Scanners need the light border; drawing the code flush to the plate
        # edge is a classic way to make a printed QR unreadable.
        img = poster._qr_image(URL, 600).convert('RGB')
        self.assertEqual(img.getpixel((2, 2)), (255, 255, 255))
        self.assertEqual(img.getpixel((597, 597)), (255, 255, 255))

    def test_different_tables_produce_different_codes(self):
        a = poster._qr_image('https://x/?branch=b&t=aaa', 400).tobytes()
        b = poster._qr_image('https://x/?branch=b&t=bbb', 400).tobytes()
        self.assertNotEqual(a, b)


class QrDownloadFreshnessTest(TenantTestCase):
    """Downloads must render the current design, never a stale stored file."""

    def setUp(self):
        super().setUp()
        from django.contrib.auth.models import User
        self.branch = Branch.objects.create(company=self.company, name='Lake', slug='lake')
        self.user = User.objects.create_user('boss', password='pass')
        self.make_owner(self.user)
        self.login_as(self.user)

    def _stale_stored_qr(self):
        """Simulate a branch whose stored QR predates the poster design."""
        import os
        from django.conf import settings
        d = os.path.join(settings.MEDIA_ROOT, 'qr')
        os.makedirs(d, exist_ok=True)
        name = f'branch_{self.company.slug}_{self.branch.slug}.png'
        Image.new('RGB', (370, 421), 'white').save(os.path.join(d, name))
        self.branch.qr_image = f'qr/{name}'
        self.branch.save(update_fields=['qr_image'])

    def test_png_download_ignores_the_stale_stored_file(self):
        # Regression: the download served branch.qr_image verbatim, so every
        # branch generated before the poster kept handing out the old plain QR
        # until somebody happened to press Regenerate.
        self._stale_stored_qr()
        r = self.client.get(f'/dashboard/qr/{self.branch.pk}/download/?format=png')
        self.assertEqual(r.status_code, 200)
        img = Image.open(io.BytesIO(r.content))
        self.assertEqual(img.size, poster.page_px('a5', 300))
        self.assertEqual(img.convert('RGB').getpixel((5, 5)), (13, 13, 13))

    def test_pdf_download_is_a_pdf(self):
        self._stale_stored_qr()
        r = self.client.get(f'/dashboard/qr/{self.branch.pk}/download/?format=pdf')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.content.startswith(b'%PDF'))
        self.assertIn('attachment', r['Content-Disposition'])


class TableQrPreviewPageTest(TenantTestCase):
    """The table QR link must land on a page with navigation, not a bare image."""

    def setUp(self):
        super().setUp()
        from django.contrib.auth.models import User
        self.branch = Branch.objects.create(company=self.company, name='Lake', slug='lake')
        self.table = Table.objects.create(branch=self.branch, label='7', code='abc123')
        self.user = User.objects.create_user('boss', password='pass')
        self.make_owner(self.user)
        self.login_as(self.user)
        self.url = f'/dashboard/branch/{self.branch.slug}/table/{self.table.code}/qr/'

    def test_preview_is_an_html_page_not_a_raw_image(self):
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)
        self.assertIn('text/html', r['Content-Type'])

    def test_preview_offers_a_way_back(self):
        # The complaint that prompted this: the bare image left the operator
        # with nothing but the browser back button.
        body = self.client.get(self.url).content.decode()
        self.assertIn(f'/dashboard/branch/{self.branch.slug}/qr/', body)

    def test_preview_links_both_downloads(self):
        body = self.client.get(self.url).content.decode()
        self.assertIn('?format=pdf', body)
        self.assertIn('?format=png', body)

    def test_png_format_still_returns_the_image(self):
        r = self.client.get(self.url + '?format=png')
        self.assertEqual(r['Content-Type'], 'image/png')
        self.assertEqual(Image.open(io.BytesIO(r.content)).size,
                         poster.page_px('a5', 300))

    def test_pdf_format_still_returns_the_pdf(self):
        r = self.client.get(self.url + '?format=pdf')
        self.assertEqual(r['Content-Type'], 'application/pdf')
        self.assertTrue(r.content.startswith(b'%PDF'))
