"""`probe_models` must INVOKE each model, never trust the listing.

`nvidia/llama-3.2-nv-embedqa-1b-v1` and `snowflake/arctic-embed-l` are both in
`GET /v1/models` for this account and both 404 on invocation. A command built on
the listing would have reported them healthy and the failure would have surfaced
inside a 20-minute extraction instead.
"""
from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command

from menu.pipeline import nv


@pytest.fixture(autouse=True)
def _configured_key(settings):
    """Put a fake key back for this module only.

    conftest blanks NVIDIA_API_KEY for the whole suite so no test can reach a
    live endpoint, and this command refuses to run without one -- without this
    every test below would assert against the empty-key notice instead of a
    probe. Safe because all three adapters are patched in each test, so the key
    is never carried to a request.
    """
    settings.NVIDIA_API_KEY = 'probe-test-key'


def _out(**kw):
    buf = StringIO()
    call_command('probe_models', stdout=buf, stderr=buf, **kw)
    return buf.getvalue()


@pytest.mark.django_db
def test_it_invokes_every_configured_model():
    with patch('menu.pipeline.extract_nv.extract_menu') as vision, \
         patch('menu.pipeline.embed_nv.embed', return_value=[0.1] * 1024), \
         patch('menu.pipeline.text_nv.complete', return_value='ok'):
        vision.return_value = {'pages': [], 'items': []}
        body = _out()
    assert vision.called                     # not a listing lookup
    assert 'vision' in body and 'embed' in body and 'text' in body


@pytest.mark.django_db
def test_a_reachable_model_is_reported_with_its_latency():
    with patch('menu.pipeline.extract_nv.extract_menu',
               return_value={'pages': [], 'items': []}), \
         patch('menu.pipeline.embed_nv.embed', return_value=[0.1] * 1024), \
         patch('menu.pipeline.text_nv.complete', return_value='ok'):
        body = _out()
    assert 'OK' in body
    assert 'ms' in body


@pytest.mark.django_db
def test_a_model_this_account_cannot_invoke_is_reported_not_raised():
    """The whole point: an unreachable model switches its layer off, and the
    command still reports on the others."""
    with patch('menu.pipeline.extract_nv.extract_menu',
               side_effect=nv.NotAvailable('404 for this account')), \
         patch('menu.pipeline.embed_nv.embed', return_value=[0.1] * 1024), \
         patch('menu.pipeline.text_nv.complete', return_value='ok'):
        body = _out()
    assert 'UNAVAILABLE' in body
    assert 'OK' in body            # the other two still reported


@pytest.mark.django_db
def test_the_embed_width_is_checked_not_assumed():
    """A model that answers at the wrong width is worse than one that 404s: its
    vectors would be stored and would rank."""
    with patch('menu.pipeline.extract_nv.extract_menu',
               return_value={'pages': [], 'items': []}), \
         patch('menu.pipeline.embed_nv.embed', return_value=[0.1] * 768), \
         patch('menu.pipeline.text_nv.complete', return_value='ok'):
        body = _out()
    assert '768' in body
    assert 'WRONG WIDTH' in body


@pytest.mark.django_db
def test_one_stage_can_be_probed_alone():
    # text_nv is patched too, though this test never expects it to run: if
    # --model ever stopped being honoured, an unpatched stage would open a real
    # connection instead of just failing the assertion below.
    with patch('menu.pipeline.embed_nv.embed', return_value=[0.1] * 1024) as e, \
         patch('menu.pipeline.text_nv.complete', return_value='ok'), \
         patch('menu.pipeline.extract_nv.extract_menu') as vision:
        body = _out(model='embed')
    assert e.called
    assert not vision.called
    assert 'vision' not in body


@pytest.mark.django_db
def test_no_key_is_said_plainly_rather_than_probed_into_three_failures(settings):
    """Without this the command probes anyway and prints three UNAVAILABLE
    lines, which reads as three dead models rather than one unset variable."""
    settings.NVIDIA_API_KEY = ''
    with patch('menu.pipeline.extract_nv.extract_menu') as vision, \
         patch('menu.pipeline.embed_nv.embed') as embed, \
         patch('menu.pipeline.text_nv.complete') as text:
        body = _out()
    assert 'NVIDIA_API_KEY' in body
    assert not vision.called and not embed.called and not text.called
