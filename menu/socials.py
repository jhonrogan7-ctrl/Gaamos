"""Social handles/URLs as stored → a link the guest menu can safely render.

`Company.instagram` / `.facebook` / `.tiktok` hold whatever the venue typed.
Fixtures and `seed_venue` carry bare handles; an owner pasting from a browser
gives a full URL. Normalising on save would rewrite rows that already exist, so
this runs at render time instead and accepts both shapes.

⚠ Everything here is tenant-supplied text on its way into an `href` on a page
every guest opens. The rule that matters: nothing but `http`/`https` ever comes
back out. A value that cannot be made into one returns None, and None is what
hides the row.
"""
from urllib.parse import urlsplit

# domain used to build a URL from a bare handle, and whether the network's
# handles conventionally display with an "@" (Facebook pages do not).
NETWORKS = {
    'instagram': ('instagram.com', True),
    'facebook': ('facebook.com', False),
    'tiktok': ('tiktok.com', True),
}

_SAFE_SCHEMES = ('http', 'https')


def social_link(network, raw):
    """Return {'url', 'handle'} for a stored value, or None if there is nothing
    safe and useful to link."""
    domain_at = NETWORKS.get(network)
    if domain_at is None:
        return None
    domain, at_sign = domain_at

    value = (raw or '').strip()
    if not value:
        return None

    if '/' in value or ':' in value or value.startswith('www.'):
        url = _as_http_url(value)
        if url is None:
            return None
        handle = _handle_from_url(url, at_sign)
    else:
        handle = value.lstrip('@').strip()
        if not handle:
            return None
        url = f'https://{domain}/{handle}'
        handle = f'@{handle}' if at_sign else handle

    return {'url': url, 'handle': handle} if handle else None


def _as_http_url(value):
    """A pasted address as an https URL, or None if it isn't one.

    A scheme-less value is treated as a bare address (`instagram.com/x`) and
    given https — without a scheme the browser resolves the href against our
    own host and the row links the guest back into the menu.
    """
    parts = urlsplit(value)
    if parts.scheme:
        if parts.scheme.lower() not in _SAFE_SCHEMES:
            return None
        # http → https: these three networks all serve https, and a mixed
        # scheme is the kind of thing a venue pastes from an old bookmark.
        rebuilt = parts._replace(scheme='https')
        return rebuilt.geturl() if rebuilt.netloc else None

    parts = urlsplit(f'https://{value}')
    return parts.geturl() if parts.netloc else None


def _handle_from_url(url, at_sign):
    """The handle to print beside the icon.

    One path segment is a handle. Anything else — a numeric profile link, a
    deep path — has no handle to show, so print the trimmed address rather than
    inventing something the guest cannot search for.
    """
    parts = urlsplit(url)
    segments = [s for s in parts.path.split('/') if s]
    host = parts.netloc

    if len(segments) == 1 and not parts.query:
        handle = segments[0].lstrip('@')
        return f'@{handle}' if at_sign else handle
    if not segments:
        return host
    return f'{host}/{"/".join(segments)}'
