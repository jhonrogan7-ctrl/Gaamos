"""Subdomain slug rules — shared by the ops panel today and Phase 3 signup later."""
import re

from django.conf import settings
from django.core.exceptions import ValidationError

RESERVED_SLUGS = frozenset({
    'www', 'admin', 'api', 'app', 'mail', 'smtp', 'imap', 'ftp',
    'static', 'media', 'assets', 'platform', 'dashboard', 'ops',
    'billing', 'pay', 'help', 'docs', 'blog', 'status',
    'ns1', 'ns2', 'test', 'demo',
})

_SLUG_RE = re.compile(r'^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$')


def validate_subdomain_slug(slug):
    from menu.models import Company
    if not 2 <= len(slug) <= 40:
        raise ValidationError('Subdomain must be 2–40 characters.')
    if not _SLUG_RE.fullmatch(slug) or '--' in slug:
        raise ValidationError(
            'Use lowercase letters, digits and single hyphens '
            '(no leading/trailing hyphen).')
    reserved = RESERVED_SLUGS | set(getattr(settings, 'RESERVED_SLUGS', ()))
    if slug in reserved:
        raise ValidationError('This subdomain is reserved.')
    if Company.objects.filter(slug=slug).exists():
        raise ValidationError('This subdomain is already taken.')
