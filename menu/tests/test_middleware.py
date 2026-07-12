from django.test import TestCase, RequestFactory, override_settings

from menu.models import Company
from menu.middleware import TenantMiddleware
from menu.tenancy import get_current_company


@override_settings(BASE_DOMAIN='zxyn.online',
                   RESERVED_SUBDOMAINS={'app', 'www', 'menu', 'admin', 'api', 'static', 'media'})
class TenantMiddlewareTest(TestCase):
    def setUp(self):
        self.rf = RequestFactory()
        self.captured = []
        # the inner view records the company that was active mid-request
        self.mw = TenantMiddleware(lambda req: self._capture(req))

    def _capture(self, req):
        from django.http import HttpResponse
        self.captured.append(get_current_company())
        return HttpResponse('ok')

    def test_subdomain_resolves_company(self):
        juicery = Company.objects.create(name='Juicery', slug='juicery', status='active')
        req = self.rf.get('/', HTTP_HOST='juicery.zxyn.online')
        self.mw(req)
        self.assertEqual(req.company, juicery)
        self.assertEqual(self.captured[-1], juicery)

    def test_reserved_host_no_company(self):
        req = self.rf.get('/', HTTP_HOST='app.zxyn.online')
        self.mw(req)
        self.assertIsNone(req.company)

    def test_unknown_slug_returns_404(self):
        req = self.rf.get('/', HTTP_HOST='ghost.zxyn.online')
        resp = self.mw(req)
        self.assertEqual(resp.status_code, 404)

    def test_apex_no_tenant_even_with_single_company(self):
        # The Phase-1 single-company shim was removed: apex/reserved hosts always
        # resolve to no tenant (→ marketing landing), even when exactly one company
        # exists. Tenants are only reached via their own <slug>.<base> subdomain.
        Company.objects.create(name='Only', slug='only')
        req = self.rf.get('/', HTTP_HOST='zxyn.online')  # apex, no subdomain
        self.mw(req)
        self.assertIsNone(req.company)

    def test_context_reset_between_requests(self):
        a = Company.objects.create(name='A', slug='a')
        Company.objects.create(name='B', slug='b')
        self.mw(self.rf.get('/', HTTP_HOST='a.zxyn.online'))
        # context must already be None here — before request B touches it
        self.assertIsNone(get_current_company())
        self.mw(self.rf.get('/', HTTP_HOST='b.zxyn.online'))
        self.assertIsNone(get_current_company())
        self.assertEqual(self.captured[0], a)
