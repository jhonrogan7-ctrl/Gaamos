"""Read the icon keys out of the shared SVG map.

`static/js/icons.js` is the single definition of what an `icon_key` may be —
the guest menu and the dashboard picker both read it. Python needs to see the
same list so a key that renders as literal text cannot ship.
"""
import re
from pathlib import Path

from django.conf import settings

ICONS_JS = Path(settings.BASE_DIR) / 'static' / 'js' / 'icons.js'

# `  momo:     '<svg .../>',` — a two-space-indented key at the top level of
# the ICONS object literal. Anchored to the line start so an `svg` attribute
# containing a colon cannot be mistaken for a key.
_KEY = re.compile(r"^\s{2}([A-Za-z][A-Za-z0-9_]*):\s*'", re.M)


def defined_icon_keys():
    return set(_KEY.findall(ICONS_JS.read_text()))
