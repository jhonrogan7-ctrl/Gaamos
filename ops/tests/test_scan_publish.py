from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase

from menu.models import Branch, Company, Item, MenuItem, MenuScan

APEX = settings.BASE_DOMAIN


class ScanPublishTests(TestCase):
    def setUp(self):
        self.apex = {'HTTP_HOST': APEX}
        self.boss = User.objects.create_superuser('boss', 'b@x.io', 'pw-boss-1')
        self.company = Company.objects.create(name='Kailash Parbat', slug='kailash')
        self.branch = Branch.all_objects.create(company=self.company, name='Thamel',
                                                slug='thamel')
        self.scan = MenuScan.objects.create(file='scans/x.pdf', status='reviewed',
                                            source_cafe='Kailash')
        self.tea = Item.objects.create(source_scan=self.scan, status='active',
                                       name='Black Tea', raw_name='Black Tea',
                                       category='Hot Drinks', reference_price=120)
        self.draft = Item.objects.create(source_scan=self.scan, status='draft',
                                         name='Undecided', raw_name='Undecided',
                                         category='Hot Drinks', reference_price=90)
        self.client.force_login(self.boss)
        self.url = f'/platform/scans/{self.scan.pk}/publish/'

    def _post(self, **extra):
        data = {'company': str(self.company.pk), 'branch': [str(self.branch.pk)],
                'item': [str(self.tea.pk)]}
        data.update(extra)
        return self.client.post(self.url, data, **self.apex)

    def test_publish_requires_superuser(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url, **self.apex).status_code, 302)
        self.assertEqual(self._post().status_code, 302)
        self.assertEqual(MenuItem.all_objects.count(), 0)

    def test_get_lists_companies_branches_and_active_items(self):
        body = self.client.get(self.url, **self.apex).content.decode()
        self.assertIn('Kailash Parbat', body)
        self.assertIn('Thamel', body)
        self.assertIn('Black Tea', body)

    def test_publish_creates_the_tenant_menu(self):
        resp = self._post()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(MenuItem.all_objects.filter(company=self.company).count(), 1)
        mi = MenuItem.all_objects.get(company=self.company)
        self.assertEqual(mi.name, 'Black Tea')
        self.assertEqual(mi.price, 120)

    def test_report_names_every_item_published_at_zero(self):
        zero = Item.objects.create(source_scan=self.scan, status='active',
                                   name='Pancake Banana', raw_name='Pancake Banana',
                                   category='Snacks', reference_price=None)
        body = self._post(item=[str(self.tea.pk), str(zero.pk)]).content.decode()
        self.assertIn('Pancake Banana', body)
        self.assertIn('Rs 0', body)

    def test_a_non_active_row_is_refused_even_if_ticked(self):
        """B6 — only status blocks a publish, and the screen cannot override it."""
        self._post(item=[str(self.tea.pk), str(self.draft.pk)])
        self.assertEqual(MenuItem.all_objects.filter(company=self.company).count(), 1)

    def test_publish_without_a_company_is_400(self):
        resp = self.client.post(self.url, {'branch': [str(self.branch.pk)],
                                           'item': [str(self.tea.pk)]}, **self.apex)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(MenuItem.all_objects.count(), 0)

    def test_publish_without_a_branch_is_400(self):
        resp = self.client.post(self.url, {'company': str(self.company.pk),
                                           'item': [str(self.tea.pk)]}, **self.apex)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(MenuItem.all_objects.count(), 0)

    def test_a_branch_of_another_company_is_refused(self):
        other = Company.objects.create(name='Chill Zone', slug='chillzone')
        stray = Branch.all_objects.create(company=other, name='Lakeside', slug='lakeside')
        resp = self._post(branch=[str(stray.pk)])
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(MenuItem.all_objects.count(), 0)

    def test_items_from_another_scan_cannot_be_published_here(self):
        stranger_scan = MenuScan.objects.create(file='scans/z.pdf')
        outsider = Item.objects.create(source_scan=stranger_scan, status='active',
                                       name='Outsider', raw_name='Outsider',
                                       category='Hot Drinks', reference_price=50)
        self._post(item=[str(self.tea.pk), str(outsider.pk)])
        names = set(MenuItem.all_objects.filter(company=self.company)
                    .values_list('name', flat=True))
        self.assertEqual(names, {'Black Tea'})

    def test_publishing_marks_the_scan_imported(self):
        self._post()
        self.scan.refresh_from_db()
        self.assertEqual(self.scan.status, 'imported')

    def test_republish_upserts_rather_than_duplicating(self):
        self._post()
        self.tea.reference_price = 150
        self.tea.save(update_fields=['reference_price'])
        self._post()
        self.assertEqual(MenuItem.all_objects.filter(company=self.company).count(), 1)
        self.assertEqual(MenuItem.all_objects.get(company=self.company).price, 150)
