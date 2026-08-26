import secrets
from django.utils import timezone
from .models import GuestSession

COOKIE = 'gaamos_gs'
_ALPHABET = [chr(c) for c in range(ord('A'), ord('Z') + 1)]

def _next_label(branch, table):
    n = GuestSession.objects.filter(branch=branch, table=table, closed_at__isnull=True).count()
    return f"Guest {_ALPHABET[n]}" if n < 26 else f"Guest {n + 1}"

def get_or_create_session(request, branch, table):
    token = request.COOKIES.get(COOKIE, '')
    if token:
        gs = GuestSession.objects.filter(token=token, closed_at__isnull=True).first()
        if gs:
            return gs, token, False
    token = secrets.token_urlsafe(24)
    gs = GuestSession.objects.create(branch=branch, table=table,
                                     token=token, label=_next_label(branch, table))
    return gs, token, True

def attach_cookie(response, token):
    response.set_cookie(COOKIE, token, max_age=60 * 60 * 12, httponly=True, samesite='Lax')
    return response
