"""Project-wide pytest fixtures."""
import tempfile

import pytest
from django.conf import settings
from django.core.cache import cache
from django.test import override_settings


@pytest.fixture(autouse=True)
def _clear_cache():
    """Reset the cache before every test.

    RateLimitMiddleware counts requests per IP in the cache; without this the
    counter accumulates across the whole suite (every test hits the same test
    IP) and late tests eventually trip the 429 throttle. Clearing per test keeps
    each test's rate-limit window isolated."""
    cache.clear()
    yield


@pytest.fixture(autouse=True)
def _no_live_model_calls():
    """Blank the NVIDIA key for every test, so none can reach a real endpoint.

    Same class of bug as `_isolated_media_root` below, and it already bit once:
    `item_embed.embed_text` falls back to `resolve_provider()`, which returns a
    live embedder whenever a key is configured — and the dev `.env` carries a
    real one. A test that writes scan drafts without patching `PROVIDER` then
    spends real quota and gets a real vector, which is how
    `test_extraction_succeeds_with_no_embedder_configured` started failing: it
    asserts the vector layer is OFF and was silently handed live embeddings.

    The whole suite is meant to be network-free; the live run is a hand-driven
    command, never a test. A test that genuinely wants a provider sets the key
    itself (the `settings` fixture applies on top of this) or patches
    `item_embed.PROVIDER`.
    """
    with override_settings(NVIDIA_API_KEY=''):
        yield


@pytest.fixture(scope='session', autouse=True)
def _isolated_media_root():
    """Point MEDIA_ROOT at a throwaway directory for the whole test session.

    The dev stack bind-mounts the repo and serves media/ live, so tests that
    save uploads or QR PNGs would otherwise write into (and overwrite) real
    tenant files — a test run once replaced a venue's branch QR with the
    testco fixture's URL."""
    old = settings.MEDIA_ROOT
    with tempfile.TemporaryDirectory(prefix='gaamos-test-media-') as tmp:
        settings.MEDIA_ROOT = tmp
        yield
    settings.MEDIA_ROOT = old
