"""Openverse image finder for the menu-from-pdf 'find' path.

Openverse (api.openverse.org) aggregates CC-licensed images from Unsplash,
Flickr and others. Free, no API key. One HTTP call per term, no LLM tool calls.
Returns candidates with license + attribution so provenance is auditable and
CC-BY credit can be surfaced in production.

Prefers no-attribution licences (cc0, pdm) first, then attribution ones
(by, by-sa) — matching the sourcing policy.
"""
import json
import socket
import urllib.parse
import urllib.request

_UA = {"User-Agent": "gaamos-menu-importer/1.0 (contact: admin@zxyn.online)"}
_API = "https://api.openverse.org/v1/images/?"

# licences we accept for a commercial menu (all allow commercial use + mods)
_NO_ATTRIB = ("cc0", "pdm")
_ATTRIB = ("by", "by-sa", "sa")


def _query(term, licenses, page_size):
    params = urllib.parse.urlencode({
        "q": term, "license": ",".join(licenses),
        "page_size": str(page_size), "mature": "false"})
    req = urllib.request.Request(_API + params, headers=_UA)
    with urllib.request.urlopen(req) as r:
        return json.load(r)


def search(term, page_size=5):
    """Return candidate dicts for `term`, no-attribution licences first.

    Each candidate: {title, url, license, attribution, creator, source,
    landing_url}. `url` is the direct image URL.
    """
    socket.setdefaulttimeout(25)
    out = []
    for licenses in (_NO_ATTRIB, _ATTRIB):
        try:
            data = _query(term, licenses, page_size)
        except Exception:
            continue
        for r in data.get("results", []):
            if not r.get("url"):
                continue
            out.append({
                "title": r.get("title", "") or "",
                "url": r["url"],
                "license": (r.get("license", "") + " " + str(r.get("license_version", ""))).strip(),
                "attribution": r.get("attribution", "") or "",
                "creator": r.get("creator", "") or "",
                "source": r.get("source", "") or "",
                "landing_url": r.get("foreign_landing_url", "") or "",
            })
        if out:  # stop as soon as a licence tier yields results
            break
    return out


def download(url, dest_path):
    """Download an image URL to dest_path (raw bytes). Returns dest_path."""
    from pathlib import Path
    socket.setdefaulttimeout(40)
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req) as r:
        payload = r.read()
    Path(dest_path).parent.mkdir(parents=True, exist_ok=True)
    Path(dest_path).write_bytes(payload)
    return dest_path
