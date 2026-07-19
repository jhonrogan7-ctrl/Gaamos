"""Signed one-time handoff tokens for platform-admin impersonation.

The apex ops panel issues a token (ops.views.tenant_impersonate); the tenant
host consumes it (menu.dashboard.views.impersonate). Sessions are host-only
cookies, so this token is what carries the admin across the host boundary.
Everything here fails closed by returning None.
"""
import secrets

from django.contrib.auth import get_user_model
from django.core import signing
from django.core.cache import cache

SALT = 'ops.impersonate'
MAX_AGE = 60      # seconds a handoff link stays valid
NONCE_TTL = 120   # nonce guard outlives MAX_AGE so a late replay still fails


def make_token(admin, company):
    return signing.dumps(
        {'u': admin.pk, 'c': company.pk, 'n': secrets.token_urlsafe(16)},
        salt=SALT)


def resolve_token(token, company):
    """Return the target superuser for a valid unused token bound to
    ``company``, else None. Consumes the nonce on success (single use).

    Locmem cache is per-process; we run a single uvicorn process. If workers
    are ever added, move the nonce store to the DB or a shared cache —
    MAX_AGE stays the hard backstop either way."""
    try:
        payload = signing.loads(token, salt=SALT, max_age=MAX_AGE)
    except signing.BadSignature:   # includes SignatureExpired
        return None
    # Company binding first: a token presented on the wrong host must not
    # burn its nonce.
    if company is None or payload.get('c') != company.pk:
        return None
    nonce = payload.get('n')
    if not nonce or not cache.add(f'ops-imp:{nonce}', 1, NONCE_TTL):
        return None
    return (get_user_model().objects
            .filter(pk=payload.get('u'), is_active=True, is_superuser=True)
            .first())
