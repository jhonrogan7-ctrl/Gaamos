"""Project-wide pytest fixtures."""
import tempfile

import pytest
from django.conf import settings
from django.core.cache import cache


@pytest.fixture(autouse=True)
def _clear_cache():
    """Reset the cache before every test.

    RateLimitMiddleware counts requests per IP in the cache; without this the
    counter accumulates across the whole suite (every test hits the same test
    IP) and late tests eventually trip the 429 throttle. Clearing per test keeps
    each test's rate-limit window isolated."""
    cache.clear()
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
