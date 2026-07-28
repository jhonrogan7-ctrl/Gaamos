"""Deployment sanity checks.

These run on every `manage.py` invocation, which includes the `migrate` the
container executes at boot — so a misconfigured deployment announces itself in
the startup log instead of failing silently weeks later.

Web Push is the case that motivated this: without keys it goes quietly inert.
Orders are still taken and the queue still updates, so nothing looks broken —
staff just never get notified, and there is no error to notice.
"""
from django.conf import settings
from django.core.checks import Warning, register


@register()
def vapid_keys_configured(app_configs, **kwargs):
    """Warn when Web Push is unconfigured or half-configured.

    A warning, never an error: a deployment that deliberately doesn't use push
    is legitimate and must still boot.
    """
    public = getattr(settings, 'VAPID_PUBLIC_KEY', '')
    private = getattr(settings, 'VAPID_PRIVATE_KEY', '')
    issues = []

    # Half-configured is always wrong, in any environment: subscribing needs the
    # public key and sending needs the private one, so one without the other
    # means push is wired up to fail rather than to be off.
    if bool(public) != bool(private):
        missing = 'VAPID_PRIVATE_KEY' if public else 'VAPID_PUBLIC_KEY'
        issues.append(Warning(
            f'Web Push is half-configured — {missing} is not set.',
            hint='Both keys must come from the SAME keypair. Generate one with '
                 '`manage.py generate_vapid_keys` and set both in the '
                 'environment. A mismatched pair makes every send fail 403.',
            id='menu.W002',
        ))
    elif not public and not settings.DEBUG:
        # Only nag in production-like settings; a dev box without push is fine.
        issues.append(Warning(
            'Web Push is not configured — dashboard staff will not be notified '
            'of new orders.',
            hint='Run `manage.py generate_vapid_keys` on this host and add the '
                 'printed VAPID_* lines to the environment, then recreate the '
                 'web AND worker services (`docker compose up -d web worker` — '
                 '`restart` reuses the old environment). Both services need the '
                 'keys: subscribing happens in web, sending in worker.',
            id='menu.W001',
        ))

    return issues
