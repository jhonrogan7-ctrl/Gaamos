import itertools

import pytest

from menu import tasks
from menu.models import (Company, ImageAsset, MenuBuild, MenuBuildRow,
                         MenuBuildSection)
from menu.pipeline import generate_flux

# Every state `generate_row_image` can write, so a state added to the task and
# forgotten in the model shows up here rather than downstream in a form/admin.
_STATES_THE_TASK_WRITES = {'generating', 'generated', 'failed'}

pytestmark = pytest.mark.django_db

PNG = (b'\x89PNG\r\n\x1a\n' + b'\x00' * 64)     # enough for the fake to return


_seq = itertools.count()


def _row(build=None, **kw):
    """One row, on a fresh build unless one is handed in.

    `Company.slug` is unique, so a helper that hardcodes it can only be called
    once per test. The counter keeps sibling rows in the SAME build where a
    test needs two of them.
    """
    if build is None:
        n = next(_seq)
        company = Company.objects.create(name=f'Venue {n}', slug=f'venue-{n}')
        build = MenuBuild.objects.create(company=company, status='generating')
    section = (build.sections.first()
               or MenuBuildSection.objects.create(build=build, name='Veg Snacks',
                                                  display_order=0))
    fields = dict(build=build, section=section,
                  display_order=build.rows.count(),
                  name='French Fries', price=250,
                  image_prompt='golden crispy french fries, no garnish')
    fields.update(kw)
    return MenuBuildRow.objects.create(**fields)


def test_a_generated_image_lands_on_the_row(monkeypatch):
    row = _row()
    monkeypatch.setattr(tasks.generate_flux, 'generate_image',
                        lambda *a, **k: PNG)
    monkeypatch.setattr(tasks.images, 'to_webp', lambda raw, size=800: b'webp')
    monkeypatch.setattr(tasks.throttle, 'acquire', lambda *a, **k: None)
    monkeypatch.setattr(tasks.intake, 'record',
                        lambda **kw: ImageAsset.objects.create(
                            name=kw['item_name'], file='imagelib/x.webp',
                            source='flux', status='pending'))

    tasks.generate_row_image(row.pk)

    row.refresh_from_db()
    assert row.image_state == 'generated'
    assert row.image_asset_id is not None


def test_a_refused_prompt_fails_the_row_and_is_not_retried(monkeypatch):
    row = _row()
    calls = []

    def refuse(*a, **k):
        calls.append(1)
        raise generate_flux.ContentFiltered('refused')

    monkeypatch.setattr(tasks.generate_flux, 'generate_image', refuse)
    monkeypatch.setattr(tasks.throttle, 'acquire', lambda *a, **k: None)

    tasks.generate_row_image(row.pk)

    row.refresh_from_db()
    assert row.image_state == 'failed'
    assert row.image_asset_id is None
    assert 'refused' in row.image_error.lower()
    assert len(calls) == 1                     # refusal repeats at every seed


def test_a_failed_row_never_stops_its_neighbours(monkeypatch):
    good = _row()
    bad = _row(build=good.build, name='Papad')
    monkeypatch.setattr(tasks.throttle, 'acquire', lambda *a, **k: None)
    monkeypatch.setattr(tasks.images, 'to_webp', lambda raw, size=800: b'webp')
    monkeypatch.setattr(tasks.intake, 'record',
                        lambda **kw: ImageAsset.objects.create(
                            name=kw['item_name'], file='imagelib/y.webp',
                            source='flux', status='pending'))

    def sometimes(prompt, **k):
        if 'papad' in prompt.lower():
            raise RuntimeError('endpoint exploded')
        return PNG

    monkeypatch.setattr(tasks.generate_flux, 'generate_image', sometimes)
    bad.image_prompt = 'crisp papad, no garnish'
    bad.save(update_fields=['image_prompt'])

    tasks.generate_row_image(good.pk)
    tasks.generate_row_image(bad.pk)

    good.refresh_from_db()
    bad.refresh_from_db()
    assert good.image_state == 'generated'
    assert bad.image_state == 'failed'


def test_a_reroll_advances_the_seed(monkeypatch):
    row = _row()
    seeds = []
    monkeypatch.setattr(tasks.throttle, 'acquire', lambda *a, **k: None)
    monkeypatch.setattr(tasks.images, 'to_webp', lambda raw, size=800: b'webp')
    monkeypatch.setattr(tasks.intake, 'record',
                        lambda **kw: ImageAsset.objects.create(
                            name=kw['item_name'], file='imagelib/z.webp',
                            source='flux', status='pending'))
    monkeypatch.setattr(tasks.generate_flux, 'generate_image',
                        lambda prompt, seed=0, **k: seeds.append(seed) or PNG)

    tasks.generate_row_image(row.pk, attempt=0)
    tasks.generate_row_image(row.pk, attempt=1)

    assert len(seeds) == 2
    assert seeds[0] != seeds[1]


def test_the_shared_budget_is_taken_before_every_call(monkeypatch):
    row = _row()
    taken = []
    monkeypatch.setattr(tasks.throttle, 'acquire',
                        lambda model, **k: taken.append(model))
    monkeypatch.setattr(tasks.images, 'to_webp', lambda raw, size=800: b'webp')
    monkeypatch.setattr(tasks.generate_flux, 'generate_image',
                        lambda *a, **k: PNG)
    monkeypatch.setattr(tasks.intake, 'record',
                        lambda **kw: ImageAsset.objects.create(
                            name=kw['item_name'], file='imagelib/w.webp',
                            source='flux', status='pending'))

    tasks.generate_row_image(row.pk)

    assert len(taken) == 1


def test_a_throttle_failure_fails_the_row_instead_of_hanging_it(monkeypatch):
    row = _row()

    def boom(*a, **k):
        raise RuntimeError('redis down')

    monkeypatch.setattr(tasks.throttle, 'acquire', boom)

    tasks.generate_row_image(row.pk)                  # must not raise

    row.refresh_from_db()
    row.build.refresh_from_db()
    assert row.image_state == 'failed'
    assert row.image_error
    assert row.build.status != 'generating'


def test_every_state_the_task_writes_is_a_declared_image_state():
    declared = dict(MenuBuildRow.IMAGE_STATES)
    missing = _STATES_THE_TASK_WRITES - set(declared)
    assert not missing, f'IMAGE_STATES is missing: {missing}'


def test_an_intake_failure_fails_the_row_instead_of_hanging_it(monkeypatch):
    row = _row()
    monkeypatch.setattr(tasks.throttle, 'acquire', lambda *a, **k: None)
    monkeypatch.setattr(tasks.images, 'to_webp', lambda raw, size=800: b'webp')
    monkeypatch.setattr(tasks.generate_flux, 'generate_image',
                        lambda *a, **k: PNG)

    def boom(**kw):
        raise RuntimeError('gemini 429: prepayment credits depleted')

    monkeypatch.setattr(tasks.intake, 'record', boom)

    tasks.generate_row_image(row.pk)                  # must not raise

    row.refresh_from_db()
    row.build.refresh_from_db()
    assert row.image_state == 'failed'
    assert row.image_error
    assert row.build.status != 'generating'


def test_the_task_never_asks_intake_to_call_gemini(monkeypatch):
    row = _row()
    calls = []
    monkeypatch.setattr(tasks.throttle, 'acquire', lambda *a, **k: None)
    monkeypatch.setattr(tasks.images, 'to_webp', lambda raw, size=800: b'webp')
    monkeypatch.setattr(tasks.generate_flux, 'generate_image',
                        lambda *a, **k: PNG)

    def record(**kw):
        calls.append(kw)
        return ImageAsset.objects.create(name=kw['item_name'], file='imagelib/v.webp',
                                         source='flux', status='pending')

    monkeypatch.setattr(tasks.intake, 'record', record)

    tasks.generate_row_image(row.pk)

    assert len(calls) == 1
    embedder = calls[0].get('embedder')
    assert embedder is not None                      # real Gemini path unreachable
    assert embedder('anything') is None               # and it is a genuine no-op
