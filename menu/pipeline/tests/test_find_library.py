import pytest

from menu.models import ImageAsset
from menu.pipeline import find_library


def _vec(a, b):
    """A 768-d vector whose first two dims are (a, b), rest zero."""
    v = [0.0] * 768
    v[0], v[1] = a, b
    return v


def _make(status, embedding, **kw):
    return ImageAsset.objects.create(
        source="pexels", status=status, embedding=embedding,
        file=kw.get("file", "imagelib/x.webp"), name=kw.get("name", "x"),
        caption=kw.get("caption", "cap"))


@pytest.mark.django_db
def test_search_ranks_verified_by_similarity_and_honors_threshold():
    query = _vec(1.0, 0.0)
    near = _make("verified", _vec(0.99, 0.14), name="near")      # sim ~0.99
    far = _make("verified", _vec(0.0, 1.0), name="far")          # sim ~0.0
    results = find_library.search("boiled egg", threshold=0.75,
                                  embedder=lambda t: query)
    ids = [r["asset_id"] for r in results]
    assert near.id in ids and far.id not in ids
    assert results[0]["asset_id"] == near.id
    assert results[0]["similarity"] >= 0.75


@pytest.mark.django_db
def test_search_excludes_pending_and_rejected():
    query = _vec(1.0, 0.0)
    _make("pending", _vec(1.0, 0.0), name="pending")
    _make("rejected", _vec(1.0, 0.0), name="rejected")
    results = find_library.search("egg", threshold=0.5, embedder=lambda t: query)
    assert results == []


@pytest.mark.django_db
def test_download_copies_stored_webp(tmp_path, settings):
    settings.MEDIA_ROOT = str(tmp_path)
    src = tmp_path / "imagelib" / "y.webp"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"WEBPDATA")
    asset = _make("verified", _vec(1.0, 0.0), file="imagelib/y.webp")
    dest = tmp_path / "out" / "copy.webp"
    find_library.download(asset.id, str(dest))
    assert dest.read_bytes() == b"WEBPDATA"
