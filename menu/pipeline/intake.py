"""Deposit every downloaded/generated image into the global ImageAsset pool as
a `pending` row for later human verification. Dedups on origin_url (found) then
content_hash (generated). Skips origin_urls already tombstoned as rejected so a
bad source is never re-ingested."""
import hashlib
from pathlib import Path

from django.conf import settings

from menu.models import ImageAsset
from menu.pipeline import embed as _embed


def seed_caption(source_text, item_name):
    """Initial caption = item name + whatever the source called it. Humans refine."""
    parts = [p.strip() for p in (item_name, source_text) if p and p.strip()]
    return ". ".join(parts)


def record(*, source, webp_bytes, item_name, found_for_slug, source_text="",
           origin_url="", prompt="", license="", attribution="", name="",
           tags=None, embedder=None):
    if origin_url:
        existing = ImageAsset.objects.filter(origin_url=origin_url).first()
        if existing is not None:
            return None if existing.status == "rejected" else existing

    content_hash = hashlib.sha256(webp_bytes).hexdigest()
    existing = ImageAsset.objects.filter(content_hash=content_hash).first()
    if existing is not None:
        return None if existing.status == "rejected" else existing

    rel = f"imagelib/{content_hash}.webp"
    dest = Path(settings.MEDIA_ROOT) / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(webp_bytes)

    caption = seed_caption(source_text, item_name)
    do_embed = embedder or _embed.embed
    embedding = do_embed(caption)

    return ImageAsset.objects.create(
        name=name, caption=caption, tags=list(tags or []), embedding=embedding,
        source=source, origin_url=origin_url, prompt=prompt, license=license,
        attribution=attribution, file=rel, content_hash=content_hash,
        found_for_slug=found_for_slug, status="pending")
