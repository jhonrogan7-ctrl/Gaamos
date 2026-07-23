"""Wikimedia Commons image finder for the menu-from-pdf 'find' path.

License-safe, scriptable (one HTTP call per term, no LLM tool calls). Returns
candidate (title, thumb_url, mime) tuples so a human/controller can curate
before downloading. Nepali local brands usually have no Commons match -> those
items route to generation instead.
"""
import json
import socket
import urllib.parse
import urllib.request

_UA = {"User-Agent": "gaamos-menu-importer/1.0 (contact: admin@zxyn.online)"}
_API = "https://commons.wikimedia.org/w/api.php?"


def search(term, limit=3, width=800):
    """Return up to `limit` (title, thumb_url, mime) candidates for `term`."""
    socket.setdefaulttimeout(20)
    q = urllib.parse.urlencode({
        "action": "query", "generator": "search",
        "gsrsearch": "filetype:bitmap " + term, "gsrnamespace": "6",
        "gsrlimit": str(limit), "prop": "imageinfo",
        "iiprop": "url|mime", "iiurlwidth": str(width), "format": "json"})
    req = urllib.request.Request(_API + q, headers=_UA)
    with urllib.request.urlopen(req) as r:
        data = json.load(r)
    pages = (data.get("query") or {}).get("pages") or {}
    # preserve search rank
    ordered = sorted(pages.values(), key=lambda p: p.get("index", 999))
    out = []
    for p in ordered:
        ii = (p.get("imageinfo") or [{}])[0]
        if ii.get("thumburl"):
            out.append((p.get("title", ""), ii["thumburl"], ii.get("mime", "")))
    return out


def download(url, dest_path):
    """Download an image URL to dest_path (raw bytes). Returns dest_path."""
    from pathlib import Path
    socket.setdefaulttimeout(30)
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req) as r:
        payload = r.read()
    Path(dest_path).parent.mkdir(parents=True, exist_ok=True)
    Path(dest_path).write_bytes(payload)
    return dest_path
