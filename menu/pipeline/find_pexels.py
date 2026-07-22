"""Pexels image finder for the menu-from-pdf 'find' path.

Pexels (api.pexels.com) offers high-quality, commercially-usable photos with
NO attribution required. Free API key (in settings.PEXELS_API_KEY, from .env).
Generous limits (~200 req/hr). One HTTP call per term, no LLM tool calls.
Strong coverage — including regional/Nepali dishes.
"""
import json
import socket
import urllib.parse
import urllib.request

_UA = "gaamos-menu-importer/1.0 (contact: admin@zxyn.online)"
_API = "https://api.pexels.com/v1/search?"


def _key():
    from django.conf import settings
    key = settings.PEXELS_API_KEY
    if not key:
        raise RuntimeError("PEXELS_API_KEY not set in .env")
    return key


def search(term, per_page=5, orientation="square"):
    """Return candidate dicts for `term`. Each: {url, photographer, alt, page}.

    `url` is a direct image URL (the 'large' rendition). `orientation` is
    'square' | 'landscape' | 'portrait' | '' (any).
    """
    socket.setdefaulttimeout(25)
    params = {"query": term, "per_page": str(per_page)}
    if orientation:
        params["orientation"] = orientation
    req = urllib.request.Request(
        _API + urllib.parse.urlencode(params),
        headers={"Authorization": _key(), "User-Agent": _UA})
    with urllib.request.urlopen(req) as r:
        data = json.load(r)
    out = []
    for p in data.get("photos", []):
        src = p.get("src", {})
        url = src.get("large") or src.get("medium") or src.get("original")
        if url:
            out.append({"url": url, "photographer": p.get("photographer", ""),
                        "alt": p.get("alt", "") or "", "page": p.get("url", "")})
    return out


def download(url, dest_path):
    """Download an image URL to dest_path (raw bytes). Returns dest_path."""
    from pathlib import Path
    socket.setdefaulttimeout(40)
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req) as r:
        payload = r.read()
    Path(dest_path).parent.mkdir(parents=True, exist_ok=True)
    Path(dest_path).write_bytes(payload)
    return dest_path
