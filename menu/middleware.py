from django.conf import settings
from django.core.cache import cache
from django.http import Http404, HttpResponse
from django.shortcuts import render

from .models import Company
from .tenancy import set_current_company, reset_current_company


class RateLimitMiddleware:
    """Lightweight per-IP throttle for guest menu reads (anti bulk-enumeration, spec §7).
    Cloudflare/WAF fronts this in production; this is the in-app backstop."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        limit = getattr(settings, 'GUEST_RATE_LIMIT', 60)
        window = getattr(settings, 'GUEST_RATE_WINDOW', 60)
        ip = request.META.get('REMOTE_ADDR', '') or 'unknown'
        key = f'guest-rl:{ip}'
        count = cache.get(key, 0) + 1
        if count == 1:
            cache.set(key, count, window)
        else:
            cache.incr(key)
        if count > limit:
            return HttpResponse('Too Many Requests', status=429)
        return self.get_response(request)


class TenantMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            company = self.resolve(request)
        except Http404:
            return render(request, 'company_not_found.html', status=404)

        request.company = company
        token = set_current_company(company)
        try:
            return self.get_response(request)
        finally:
            reset_current_company(token)

    def resolve(self, request):
        host = request.get_host().split(':')[0].lower()  # strip port
        base = settings.BASE_DOMAIN.lower()
        reserved = settings.RESERVED_SUBDOMAINS

        label = None
        if host.endswith('.' + base):
            label = host[: -len('.' + base)].split('.')[0]
        elif host.endswith('.localhost'):
            label = host[: -len('.localhost')].split('.')[0]   # dev: <slug>.localhost

        # DEBUG-only override
        if settings.DEBUG and request.GET.get('company'):
            label = request.GET['company']

        if label and label not in reserved:
            company = Company.objects.filter(slug=label, status='active').first()
            if company is None:
                raise Http404('company not found')
            return company

        # reserved host / apex / bare localhost → no tenant.
        # Phase 1 compatibility shim: if exactly one company exists, use it.
        # (Removed in Phase 3 when real multi-company hosting goes live.)
        if Company.objects.count() == 1:
            return Company.objects.first()
        return None
