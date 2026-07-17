from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase

from core.models import Lead
from menu.models import Company

APEX = settings.BASE_DOMAIN


class OpsLeadsTests(TestCase):
    def setUp(self):
        self.apex = {'HTTP_HOST': APEX}
        boss = User.objects.create_superuser('boss', 'b@x.io', 'pw')
        self.client.force_login(boss)
        self.lead = Lead.objects.create(
            name='Sita', venue_name='Momo Ghar', phone='9800000000',
            email='sita@x.np', venue_type='Café', message='Interested')

    def test_list_shows_lead_with_status_chip(self):
        resp = self.client.get('/platform/leads', **self.apex)
        self.assertContains(resp, 'Momo Ghar')
        self.assertContains(resp, 'ops-chip new')

    def test_status_filter(self):
        Lead.objects.create(name='B', venue_name='Rejected One',
                            phone='1', status='rejected')
        resp = self.client.get('/platform/leads?status=new', **self.apex)
        self.assertContains(resp, 'Momo Ghar')
        self.assertNotContains(resp, 'Rejected One')

    def test_set_status(self):
        resp = self.client.post(f'/platform/leads/{self.lead.id}/status',
                                {'status': 'contacted'}, **self.apex)
        self.assertEqual(resp.status_code, 302)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.status, 'contacted')

    def test_invalid_status_rejected(self):
        resp = self.client.post(f'/platform/leads/{self.lead.id}/status',
                                {'status': 'purchased'}, **self.apex)
        self.assertEqual(resp.status_code, 400)

    def test_create_tenant_link_prefills(self):
        resp = self.client.get('/platform/leads', **self.apex)
        self.assertContains(resp, f'/platform/tenants/new?lead={self.lead.id}')

    def test_new_pipeline_statuses_accepted(self):
        for status in ('follow_up', 'demo_scheduled'):
            resp = self.client.post(f'/platform/leads/{self.lead.id}/status',
                                    {'status': status}, **self.apex)
            self.assertEqual(resp.status_code, 302)
            self.lead.refresh_from_db()
            self.assertEqual(self.lead.status, status)

    def test_unknown_status_still_400s(self):
        resp = self.client.post(f'/platform/leads/{self.lead.id}/status',
                                {'status': 'archived'}, **self.apex)
        self.assertEqual(resp.status_code, 400)

    def test_converted_can_move_to_any_status_and_keeps_company(self):
        company = Company.objects.create(name='Momo Ghar Pvt', slug='momoghar')
        self.lead.status = 'converted'
        self.lead.company = company
        self.lead.save(update_fields=['status', 'company'])
        resp = self.client.post(f'/platform/leads/{self.lead.id}/status',
                                {'status': 'follow_up'}, **self.apex)
        self.assertEqual(resp.status_code, 302)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.status, 'follow_up')
        self.assertEqual(self.lead.company_id, company.id)  # FK never touched

    def test_status_choices_pipeline_order(self):
        self.assertEqual([k for k, _ in Lead.STATUS_CHOICES],
                         ['new', 'contacted', 'follow_up', 'demo_scheduled',
                          'converted', 'rejected'])

    def test_leads_page_renders_status_select_with_all_choices(self):
        body = self.client.get('/platform/leads', **self.apex).content.decode()
        self.assertIn('class="ops-status"', body)
        for value, label in Lead.STATUS_CHOICES:
            self.assertIn(f'value="{value}"', body)
        self.assertNotIn('Mark contacted', body)   # one-way buttons are gone

    def test_converted_lead_gets_select_but_no_create_tenant(self):
        company = Company.objects.create(name='Momo Ghar Pvt', slug='momoghar2')
        self.lead.status = 'converted'
        self.lead.company = company
        self.lead.save(update_fields=['status', 'company'])
        body = self.client.get('/platform/leads', **self.apex).content.decode()
        self.assertIn('class="ops-status"', body)
        self.assertNotIn(f'/platform/tenants/new?lead={self.lead.id}', body)
        self.assertIn('Momo Ghar Pvt', body)   # → Company annotation still shown

    def test_leads_page_renders_table_and_cards_variants(self):
        body = self.client.get('/platform/leads', **self.apex).content.decode()
        self.assertIn('ops-table', body)
        self.assertIn('ops-cards', body)
        # both variants carry the lead
        self.assertEqual(body.count('Momo Ghar'), 2)
