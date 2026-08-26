"""Project-wide pytest fixtures."""
import tempfile

import pytest
from django.conf import settings
from django.core.cache import cache
from django.test import override_settings

from menu.tenancy import set_current_company


@pytest.fixture(autouse=True)
def _reset_tenant_context():
    """Clear the active-company context after every test.

    Some pytest-style tests (e.g. menu/tests/test_guest_sessions.py,
    menu/tests/test_attribution.py) call `set_current_company()` directly to
    exercise tenant-scoped models, without pairing it with
    `reset_current_company()`. `_current_company` is a `contextvars.ContextVar`
    (menu/tenancy.py) that otherwise keeps whatever company was last set for
    every subsequent test run in the same worker/thread — so collection-order-
    dependent tests expecting *no* active company (or a fresh middleware-driven
    one) started failing depending on what ran just before them.

    Clearing to None after every test — regardless of how the context got set —
    keeps each test's tenant context isolated from the next. This is harmless
    for `TenantTestCase`-based tests (menu/tests/base.py): their own `tearDown`
    already resets the context to its pre-test value (None, since nothing else
    runs before `setUp`) before this fixture's teardown runs, so setting None
    again here is a no-op."""
    yield
    set_current_company(None)


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
    """Blank every model API key, so no test can reach a real endpoint.

    Same class of bug as `_isolated_media_root` below, and both keys have now
    been caught leaking:

    * NVIDIA — `item_embed.embed_text` falls back to `resolve_provider()`,
      which returns a live embedder whenever a key is configured, and the dev
      `.env` carries a real one. A test writing scan drafts without patching
      `PROVIDER` spent real quota and got a real vector, which is how
      `test_extraction_succeeds_with_no_embedder_configured` began failing: it
      asserts the vector layer is OFF and was being handed live embeddings.
    * GEMINI — a scan test that reached `extract_menu_scan` without patching
      the adapter called Google for real and came back `HTTP Error 429`. The
      429 is only because that account is out of prepay credit; with credit it
      would have been a silent, billed, slow success.

    Both adapters refuse an empty key with a local ValueError, so an unpatched
    call now fails loudly here instead of travelling. The whole suite is meant
    to be network-free; the live run is a hand-driven command, never a test. A
    test that genuinely wants a provider sets the key itself (the `settings`
    fixture applies on top of this) or patches the adapter.
    """
    with override_settings(NVIDIA_API_KEY='', GEMINI_API_KEY=''):
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
