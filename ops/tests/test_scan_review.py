from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase

from menu.models import Item, MenuScan

APEX = settings.BASE_DOMAIN


def _emb(vec):
    return lambda text: vec


class ScanReviewTests(TestCase):
    def setUp(self):
        self.apex = {'HTTP_HOST': APEX}
        self.boss = User.objects.create_superuser('boss', 'b@x.io', 'pw-boss-1')
        self.scan = MenuScan.objects.create(source_cafe='Cafe', status='extracted',
                                            file='scans/x.pdf')
        self.tea = Item.objects.create(
            source_scan=self.scan, status='draft', name='Black Tea',
            description='hot milk tea', category='Hot Drinks', reference_price=50,
            raw_name='Black Tea', source_page=1, embedding=[0.2] * 768)
        self.client.force_login(self.boss)

    def _url(self, item):
        return f'/platform/scans/items/{item.pk}/action/'

    def test_review_requires_superuser(self):
        self.client.logout()
        self.assertEqual(
            self.client.get(f'/platform/scans/{self.scan.pk}/review/',
                            **self.apex).status_code, 302)

    def test_review_lists_draft_rows(self):
        body = self.client.get(f'/platform/scans/{self.scan.pk}/review/',
                               **self.apex).content.decode()
        self.assertIn('Black Tea', body)
        self.assertIn('Hot Drinks', body)

    def test_review_shows_flags_and_raw_price(self):
        Item.objects.create(source_scan=self.scan, status='draft', name='Red Bull Yellow',
                            category='Soft Drinks', reference_price=None,
                            raw_price_text='', needs_review=True, confidence=0.4)
        body = self.client.get(f'/platform/scans/{self.scan.pk}/review/',
                               **self.apex).content.decode()
        self.assertIn('needs review', body)

    def test_review_excludes_non_draft_rows(self):
        Item.objects.create(source_scan=self.scan, status='rejected', name='Ghost Item')
        body = self.client.get(f'/platform/scans/{self.scan.pk}/review/',
                               **self.apex).content.decode()
        self.assertNotIn('Ghost Item', body)

    def test_approve_activates_the_draft(self):
        resp = self.client.post(self._url(self.tea), {'action': 'approve'}, **self.apex)
        self.assertEqual(resp.status_code, 200)
        self.tea.refresh_from_db()
        self.assertEqual(self.tea.status, 'active')
        self.assertEqual(self.tea.reviewed_by, self.boss)

    def test_reject_marks_rejected(self):
        resp = self.client.post(self._url(self.tea), {'action': 'reject'}, **self.apex)
        self.assertEqual(resp.status_code, 200)
        self.tea.refresh_from_db()
        self.assertEqual(self.tea.status, 'rejected')

    def test_merge_links_to_the_active_item(self):
        keeper = Item.objects.create(name='Black Tea', category='Hot Drinks',
                                     status='active', embedding=[1.0] + [0.0] * 767)
        resp = self.client.post(self._url(self.tea),
                                {'action': 'merge', 'merge_into': str(keeper.pk)},
                                **self.apex)
        self.assertEqual(resp.status_code, 200)
        self.tea.refresh_from_db()
        self.assertEqual(self.tea.status, 'merged')
        self.assertEqual(self.tea.merged_into_id, keeper.pk)
        # D2: the duplicate survives as provenance rather than being discarded.
        self.assertEqual(Item.objects.filter(name='Black Tea').count(), 2)

    def test_merge_into_a_draft_is_rejected(self):
        other = Item.objects.create(name='Milk Tea', status='draft')
        resp = self.client.post(self._url(self.tea),
                                {'action': 'merge', 'merge_into': str(other.pk)},
                                **self.apex)
        self.assertEqual(resp.status_code, 400)
        self.tea.refresh_from_db()
        self.assertEqual(self.tea.status, 'draft')

    def test_unknown_action_is_400(self):
        resp = self.client.post(self._url(self.tea), {'action': 'explode'}, **self.apex)
        self.assertEqual(resp.status_code, 400)

    def test_action_requires_superuser(self):
        self.client.logout()
        resp = self.client.post(self._url(self.tea), {'action': 'approve'}, **self.apex)
        self.assertEqual(resp.status_code, 302)
        self.tea.refresh_from_db()
        self.assertEqual(self.tea.status, 'draft')

    def test_scan_becomes_reviewed_when_no_drafts_remain(self):
        self.client.post(self._url(self.tea), {'action': 'approve'}, **self.apex)
        self.scan.refresh_from_db()
        self.assertEqual(self.scan.status, 'reviewed')

    def test_scan_stays_extracted_while_drafts_remain(self):
        Item.objects.create(source_scan=self.scan, status='draft', name='Milk Tea')
        self.client.post(self._url(self.tea), {'action': 'approve'}, **self.apex)
        self.scan.refresh_from_db()
        self.assertEqual(self.scan.status, 'extracted')

    def test_review_offers_a_dedup_match(self):
        Item.objects.create(name='Black Tea', category='Hot Drinks', status='active',
                            embedding=[0.2] * 768)
        body = self.client.get(f'/platform/scans/{self.scan.pk}/review/',
                               **self.apex).content.decode()
        self.assertIn('Merge', body)

    def test_review_makes_no_embedding_calls(self):
        """Drafts already carry their vectors from extraction — rendering the
        review screen must not call Gemini once per row."""
        Item.objects.create(name='Black Tea', category='Hot Drinks', status='active',
                            embedding=[0.2] * 768)
        with patch('menu.pipeline.embed.embed',
                   side_effect=AssertionError('embedded during render')):
            resp = self.client.get(f'/platform/scans/{self.scan.pk}/review/', **self.apex)
        self.assertEqual(resp.status_code, 200)


class ScanCombineTests(TestCase):
    def setUp(self):
        self.apex = {'HTTP_HOST': APEX}
        self.boss = User.objects.create_superuser('boss', 'b@x.io', 'pw-boss-1')
        self.scan = MenuScan.objects.create(source_cafe='Kailash Parbat',
                                            status='extracted', file='scans/k.pdf')
        line = 'Coke/Fanta/Sprite/Dew/Slice'
        self.coke, self.fanta, self.sprite = (
            Item.objects.create(source_scan=self.scan, status='draft', name=name,
                                category='Soft Drinks', reference_price=100,
                                raw_name=line, split_from=line, embedding=[0.1] * 768)
            for name in ('Coke', 'Fanta', 'Sprite'))
        self.client.force_login(self.boss)
        self.url = f'/platform/scans/{self.scan.pk}/combine/'

    def test_combine_folds_siblings_into_the_keeper(self):
        with patch('menu.pipeline.embed.embed', _emb([0.3] * 768)):
            resp = self.client.post(
                self.url, {'keep': str(self.coke.pk),
                           'sibling': [str(self.fanta.pk), str(self.sprite.pk)]},
                **self.apex)
        self.assertEqual(resp.status_code, 302)
        self.coke.refresh_from_db()
        self.fanta.refresh_from_db()
        self.sprite.refresh_from_db()
        # the keeper takes back the full printed line
        self.assertEqual(self.coke.name, 'Coke/Fanta/Sprite/Dew/Slice')
        self.assertEqual(self.coke.variant_label, '')
        self.assertEqual(list(self.coke.embedding), [0.3] * 768)   # re-embedded
        self.assertEqual(self.fanta.status, 'merged')
        self.assertEqual(self.fanta.merged_into_id, self.coke.pk)
        self.assertEqual(self.sprite.merged_into_id, self.coke.pk)

    def test_combine_needs_at_least_one_sibling(self):
        resp = self.client.post(self.url, {'keep': str(self.coke.pk)}, **self.apex)
        self.assertEqual(resp.status_code, 400)
        self.coke.refresh_from_db()
        self.assertEqual(self.coke.name, 'Coke')

    def test_keeper_must_be_a_draft_of_this_scan(self):
        other = Item.objects.create(name='Elsewhere', status='draft')
        resp = self.client.post(self.url, {'keep': str(other.pk),
                                           'sibling': [str(self.fanta.pk)]}, **self.apex)
        self.assertEqual(resp.status_code, 400)

    def test_siblings_from_another_scan_are_ignored(self):
        stranger = MenuScan.objects.create(file='scans/z.pdf')
        outsider = Item.objects.create(source_scan=stranger, status='draft', name='Outsider')
        with patch('menu.pipeline.embed.embed', _emb([0.3] * 768)):
            resp = self.client.post(
                self.url, {'keep': str(self.coke.pk),
                           'sibling': [str(self.fanta.pk), str(outsider.pk)]}, **self.apex)
        self.assertEqual(resp.status_code, 302)
        outsider.refresh_from_db()
        self.assertEqual(outsider.status, 'draft')

    def test_combine_requires_superuser(self):
        self.client.logout()
        resp = self.client.post(self.url, {'keep': str(self.coke.pk),
                                           'sibling': [str(self.fanta.pk)]}, **self.apex)
        self.assertEqual(resp.status_code, 302)
        self.fanta.refresh_from_db()
        self.assertEqual(self.fanta.status, 'draft')
