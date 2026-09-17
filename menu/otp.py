import secrets
from datetime import timedelta
from django.utils import timezone
from django.contrib.auth.hashers import make_password, check_password
from .models import OtpChallenge

TTL = timedelta(minutes=5); MAX_ATTEMPTS = 5

def issue_code(session, phone):
    code = f"{secrets.randbelow(10000):04d}"
    OtpChallenge.objects.create(session=session, phone=phone,
        code_hash=make_password(code), expires_at=timezone.now() + TTL)
    return code

def verify_code(session, code):
    ch = OtpChallenge.objects.filter(session=session).order_by('-id').first()
    if not ch or ch.attempts >= MAX_ATTEMPTS or ch.expires_at < timezone.now():
        return False
    ch.attempts += 1; ch.save(update_fields=['attempts'])
    if not check_password(code, ch.code_hash):
        return False
    session.verified = True; session.contact = ch.phone
    session.save(update_fields=['verified', 'contact'])
    return True
