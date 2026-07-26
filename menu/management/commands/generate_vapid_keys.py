"""Generate a VAPID keypair for Web Push.

Run once per deployment. The keypair identifies this app server to the browser
push services: the public half is stored inside each subscription at subscribe
time, and every push must be signed by the matching private key, so a leaked
endpoint alone cannot be used to notify a venue's staff.

Rotating the keys is *recoverable* but not free. Existing subscriptions were
made against the old public key, so the push service rejects our signature
(401/403); `menu.push` treats that as stale and deletes the row, and the browser
re-registers against the current key the next time the operator opens the
dashboard. Nobody has to re-grant permission — but a device that never opens the
dashboard again stays silent, so treat the private key as worth backing up.
"""
import base64

from cryptography.hazmat.primitives import serialization
from django.core.management.base import BaseCommand


def generate_keypair():
    """Return (public_key, private_key) as base64url strings, no padding.

    The public key is the uncompressed P-256 point the browser expects as
    `applicationServerKey`; the private key is the raw 32-byte scalar, which is
    the form pywebpush accepts as `vapid_private_key`.
    """
    from py_vapid import Vapid01

    v = Vapid01()
    v.generate_keys()

    private_raw = v.private_key.private_numbers().private_value.to_bytes(32, 'big')
    public_raw = v.public_key.public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint)

    b64 = lambda raw: base64.urlsafe_b64encode(raw).decode().rstrip('=')  # noqa: E731
    return b64(public_raw), b64(private_raw)


class Command(BaseCommand):
    help = 'Generate a VAPID keypair for Web Push, as .env lines.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--email', default='admin@gaamos.io',
            help='Contact address push services may use to reach you about '
                 'this app server. Must be a real inbox.')

    def handle(self, *args, **opts):
        from django.conf import settings

        if settings.VAPID_PUBLIC_KEY or settings.VAPID_PRIVATE_KEY:
            self.stderr.write(self.style.WARNING(
                'NOTE: this environment already has VAPID keys configured.\n'
                'Replacing them invalidates every existing subscription. Devices\n'
                're-register automatically the next time someone opens the\n'
                'dashboard (no permission prompt), but any device that never\n'
                'opens it again stays silent. Prefer restoring the old private\n'
                'key from backup over generating a new one.\n'))

        public, private = generate_keypair()
        self.stdout.write('')
        self.stdout.write('Add these to the production .env (never commit them):')
        self.stdout.write('')
        self.stdout.write(f'VAPID_PUBLIC_KEY={public}')
        self.stdout.write(f'VAPID_PRIVATE_KEY={private}')
        self.stdout.write(f"VAPID_ADMIN_EMAIL={opts['email']}")
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            'Then restart web + worker so both read the new values. '
            'Back the private key up somewhere safe.'))
