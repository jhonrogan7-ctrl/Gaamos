"""First-priority image finder: the internal library. Embeds the item text and
returns verified ImageAssets ranked by cosine similarity, above the configured
threshold. Same shape as find_pexels/find_openverse/find_commons (search +
download) so the pipeline can try it before any external source. download() is
a local file copy — no network, no re-normalize."""
import shutil
from pathlib import Path

from pgvector.django import CosineDistance

from menu.models import ImageAsset
from menu.pipeline import embed as _embed


def search(item_text, *, limit=5, threshold=None, embedder=None):
    if threshold is None:
        from django.conf import settings
        threshold = settings.LIBRARY_MATCH_THRESHOLD
    do_embed = embedder or _embed.embed
    vec = do_embed(item_text)
    qs = (ImageAsset.objects.filter(status="verified")
          .exclude(embedding=None)
          .annotate(distance=CosineDistance("embedding", vec))
          .order_by("distance")[:limit])
    out = []
    for a in qs:
        similarity = 1.0 - float(a.distance)
        if similarity >= threshold:
            out.append({"asset_id": a.id, "file": a.file, "name": a.name,
                        "caption": a.caption, "similarity": similarity})
    return out


def download(asset_id, dest_path):
    from django.conf import settings
    asset = ImageAsset.objects.get(pk=asset_id)
    src = Path(settings.MEDIA_ROOT) / asset.file
    dest = Path(dest_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest)
    return dest_path
