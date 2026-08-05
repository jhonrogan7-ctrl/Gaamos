"""The catalog's embedding seam.

`Item.embedding` is 1024-d because that is what `nvidia/nv-embedqa-e5-v5`
returns (invocation-verified 2026-07-30). Vectors from different models do not
share a space, so a 768-d Gemini vector in this column is not a weaker match --
it is a meaningless one, and 77 of them are exactly why `find_library.search`
has never returned anything worth having.

Phase 2 wired the provider in: `resolve_provider` returns `embed_nv.embed` once
a key and a model are configured, and None otherwise. Nothing configured means
the matcher's vector layer is simply off and every other layer works without it
(spec D6).
"""

DIMENSIONS = 1024


def resolve_provider():
    """The catalog's embedder, or None when nothing is configured.

    Resolved lazily rather than at import: settings are patched per-test, and a
    module-level lookup would freeze whatever was true when Django started.
    """
    from django.conf import settings
    if not getattr(settings, 'NVIDIA_API_KEY', '') or \
            not getattr(settings, 'NVIDIA_EMBED_MODEL', ''):
        return None
    from menu.pipeline import embed_nv
    return lambda text: embed_nv.embed(text, kind='passage')


# Kept as an override seam: tests assign it, and `embed_text` prefers it.
PROVIDER = None


def embed_text(text, *, embedder=None):
    """-> a DIMENSIONS-wide vector, or None when no catalog embedder is configured."""
    provider = embedder or PROVIDER or resolve_provider()
    if provider is None:
        return None
    vector = provider(text)
    if vector is None:
        return None
    vector = list(vector)
    if len(vector) != DIMENSIONS:
        raise ValueError(
            f'catalog embedder returned {len(vector)}-d, expected {DIMENSIONS}: '
            f'a vector from another model does not share this space')
    return vector
