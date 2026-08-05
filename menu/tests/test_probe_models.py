"""`probe_models` must INVOKE each model, never trust the listing.

`nvidia/llama-3.2-nv-embedqa-1b-v1` and `snowflake/arctic-embed-l` are both in
`GET /v1/models` for this account and both 404 on invocation. A command built on
the listing would have reported them healthy and the failure would have surfaced
inside a 20-minute extraction instead.
"""
import io
from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command

from menu.management.commands import probe_models
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


# What a healthy vision probe returns. Tests below are about reachability and
# about the OTHER stages, so their vision mock must read the probe card
# successfully -- an empty item list now means NO ITEMS, a different assertion.
_READ = {'pages': [{'index': 1}], 'items': [{'name': 'Tea', 'price': 50}]}


def _out(**kw):
    buf = StringIO()
    call_command('probe_models', stdout=buf, stderr=buf, **kw)
    return buf.getvalue()


def test_the_probe_image_actually_prints_a_menu():
    """The defect this pins, measured 2026-08-02: the probe image used to be a
    uniform 64x64 near-white square. This model fabricates rather than abstains,
    so asked to extract a menu from a blank image it invented one and never
    stopped -- `finish_reason: 'length'` at every cap tested -- burning the full
    8192-token budget on every probe. At 8192 that reliably drove the host into
    `EngineCore encountered an issue` (HTTP 500) or past the 300s read timeout.
    A probe that reported OK did so because `extract_menu` had not raised, not
    because anything was read.

    A blank image has exactly one distinct pixel value. Something with printing
    on it does not.
    """
    from PIL import Image
    png = probe_models._probe_menu_png()
    colours = Image.open(io.BytesIO(png)).convert('L').getcolors(maxcolors=65536)
    assert len(colours) > 1, 'the probe image is blank — the model will invent a menu'


@pytest.mark.django_db
def test_a_vision_model_that_reads_nothing_is_not_reported_ok():
    """Zero items off a card that plainly prints two is a failure, not a pass.
    The old command could not tell the difference: any return at all was OK."""
    with patch('menu.pipeline.extract_nv.extract_menu',
               return_value={'pages': [], 'items': []}), \
         patch('menu.pipeline.embed_nv.embed', return_value=[0.1] * 1024), \
         patch('menu.pipeline.text_nv.complete', return_value='ok'):
        body = _out(model='vision')
    assert 'NO ITEMS' in body
    assert 'OK' not in body


@pytest.mark.django_db
def test_the_vision_probe_reports_what_it_read():
    """The count is the evidence. Without it the line cannot be distinguished
    from the blank-image probe that "passed" for weeks."""
    with patch('menu.pipeline.extract_nv.extract_menu', return_value={
            'pages': [{'index': 1}],
            'items': [{'name': 'Tea', 'price': 50}, {'name': 'Coffee', 'price': 80}]}), \
         patch('menu.pipeline.embed_nv.embed', return_value=[0.1] * 1024), \
         patch('menu.pipeline.text_nv.complete', return_value='ok'):
        body = _out(model='vision')
    assert '2 items' in body
    assert 'OK' in body


@pytest.mark.django_db
def test_it_invokes_every_configured_model():
    with patch('menu.pipeline.extract_nv.extract_menu') as vision, \
         patch('menu.pipeline.embed_nv.embed', return_value=[0.1] * 1024), \
         patch('menu.pipeline.text_nv.complete', return_value='ok'):
        vision.return_value = _READ
        body = _out()
    assert vision.called                     # not a listing lookup
    assert 'vision' in body and 'embed' in body and 'text' in body


@pytest.mark.django_db
def test_a_reachable_model_is_reported_with_its_latency():
    with patch('menu.pipeline.extract_nv.extract_menu', return_value=_READ), \
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
    with patch('menu.pipeline.extract_nv.extract_menu', return_value=_READ), \
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
