"""The batch runner: prompt sheet -> FLUX -> webp -> pending ImageAsset rows."""
import io

import pytest
from django.core.management import call_command
from PIL import Image

from menu.models import ImageAsset
from menu.pipeline import generate_flux

SHEET = """## Card 1 — Drinks, Snacks

### Hot Drinks

| Item | Printed description | Image prompt |
|---|---|---|
| Black Tea | — | a clear glass cup of strong black tea |
| Milk Tea | — | a glass cup of Nepali milk tea |

### Snacks

| Item | Printed description | Image prompt |
|---|---|---|
| Veg Momo | Steamed dumplings. | a bamboo steamer of vegetable momo |
| Extra Coil | — | *skip — accessory, no image needed* |
"""


def _png(colour=(200, 40, 40)):
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), colour).save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture
def sheet(tmp_path):
    path = tmp_path / "sheet.md"
    path.write_text(SHEET)
    return str(path)


@pytest.fixture(autouse=True)
def no_real_waiting(monkeypatch):
    """The command paces itself against a rate-limited endpoint by default;
    tests must not actually sleep. The pacing tests re-patch this to record."""
    monkeypatch.setattr("menu.management.commands.generate_item_images.time.sleep",
                        lambda seconds: None)


@pytest.fixture
def fake_flux(monkeypatch):
    """Stand-in for the hosted model: records prompts, returns distinct images."""
    calls = []

    def fake(prompt, **kwargs):
        calls.append(prompt)
        return _png((len(calls) * 20 % 255, 40, 40))

    monkeypatch.setattr(generate_flux, "generate_image", fake)
    return calls


@pytest.mark.django_db
def test_generates_a_pending_asset_for_every_generatable_row(sheet, fake_flux,
                                                             settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path / "media")

    call_command("generate_item_images", "--prompts", sheet)

    assert ImageAsset.objects.count() == 3          # the *skip* row is not generated
    tea = ImageAsset.objects.get(found_for_slug="hot-drinks-black-tea")
    assert tea.source == "flux"
    assert tea.status == "pending"
    assert tea.file.startswith("imagelib/")


@pytest.mark.django_db
def test_stores_the_full_prompt_including_the_style_block(sheet, fake_flux,
                                                          settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path / "media")

    call_command("generate_item_images", "--prompts", sheet)

    tea = ImageAsset.objects.get(found_for_slug="hot-drinks-black-tea")
    assert tea.prompt.startswith("a clear glass cup of strong black tea,")
    assert "beverage photography" in tea.prompt


@pytest.mark.django_db
def test_directive_rows_are_never_sent_to_the_model(sheet, fake_flux,
                                                    settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path / "media")

    call_command("generate_item_images", "--prompts", sheet)

    assert not any("accessory" in p for p in fake_flux)
    assert len(fake_flux) == 3


@pytest.mark.django_db
def test_limit_caps_the_number_of_generations(sheet, fake_flux, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path / "media")

    call_command("generate_item_images", "--prompts", sheet, "--limit", "2")

    assert len(fake_flux) == 2
    assert ImageAsset.objects.count() == 2


@pytest.mark.django_db
def test_dry_run_calls_nothing_and_writes_nothing(sheet, fake_flux, settings,
                                                  tmp_path):
    settings.MEDIA_ROOT = str(tmp_path / "media")

    call_command("generate_item_images", "--prompts", sheet, "--dry-run")

    assert fake_flux == []
    assert ImageAsset.objects.count() == 0


@pytest.mark.django_db
def test_rerunning_skips_rows_already_generated(sheet, fake_flux, settings,
                                                tmp_path):
    """Resume after a partial run must not pay for the same image twice."""
    settings.MEDIA_ROOT = str(tmp_path / "media")
    call_command("generate_item_images", "--prompts", sheet, "--limit", "2")

    call_command("generate_item_images", "--prompts", sheet)

    assert len(fake_flux) == 3                       # 2 then only the 1 remaining
    assert ImageAsset.objects.count() == 3


@pytest.mark.django_db
def test_one_failed_generation_does_not_abort_the_run(sheet, monkeypatch,
                                                      settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path / "media")
    calls = []

    def flaky(prompt, **kwargs):
        calls.append(prompt)
        if len(calls) == 1:
            raise RuntimeError("429 rate limited")
        return _png((len(calls) * 20 % 255, 40, 40))

    monkeypatch.setattr(generate_flux, "generate_image", flaky)

    call_command("generate_item_images", "--prompts", sheet, "--retries", "0")

    assert len(calls) == 3
    assert ImageAsset.objects.count() == 2


@pytest.mark.django_db
def test_does_not_embed_by_default(sheet, fake_flux, settings, tmp_path):
    """Gemini embedding is a separate, currently-billing-blocked API — the run
    must not depend on it. Staff can verify assets without embeddings."""
    settings.MEDIA_ROOT = str(tmp_path / "media")

    call_command("generate_item_images", "--prompts", sheet)

    assert ImageAsset.objects.get(found_for_slug="hot-drinks-black-tea").embedding is None


@pytest.mark.django_db
def test_records_the_item_name_on_the_asset(sheet, fake_flux, settings, tmp_path):
    """Needed to export a generated file under a human-readable name."""
    settings.MEDIA_ROOT = str(tmp_path / "media")

    call_command("generate_item_images", "--prompts", sheet)

    assert ImageAsset.objects.get(found_for_slug="snacks-veg-momo").name == "Veg Momo"


@pytest.mark.django_db
def test_skip_names_excludes_items_already_shot_elsewhere(sheet, fake_flux,
                                                          settings, tmp_path):
    """The venue folder holds images made outside this pipeline. Its filenames
    are bare item names, with an optional `_1`/`_2` variant suffix."""
    settings.MEDIA_ROOT = str(tmp_path / "media")
    names = tmp_path / "names.txt"
    names.write_text("Black Tea.webp\nVeg Momo_2.jpg\n")

    call_command("generate_item_images", "--prompts", sheet,
                 "--skip-names", str(names))

    assert len(fake_flux) == 1
    assert ImageAsset.objects.get().found_for_slug == "hot-drinks-milk-tea"


@pytest.mark.django_db
def test_include_key_overrides_a_skip_names_match(sheet, fake_flux, settings,
                                                  tmp_path):
    """A bare filename can match the same item name in two sections — `Banana`
    is a milkshake in one and a pancake in another. The pancake still needs a
    picture, so an explicit key wins over the name match."""
    settings.MEDIA_ROOT = str(tmp_path / "media")
    names = tmp_path / "names.txt"
    names.write_text("Black Tea.jpg\n")

    call_command("generate_item_images", "--prompts", sheet,
                 "--skip-names", str(names),
                 "--include-key", "hot-drinks-black-tea")

    assert len(fake_flux) == 3
    assert ImageAsset.objects.filter(found_for_slug="hot-drinks-black-tea").exists()


@pytest.mark.django_db
def test_skip_key_excludes_one_key_by_hand(sheet, fake_flux, settings, tmp_path):
    """For covered items whose filename doesn't match — the venue folder has a
    truncated `ndian Breakfast.jpg` for `Indian Breakfast`."""
    settings.MEDIA_ROOT = str(tmp_path / "media")

    call_command("generate_item_images", "--prompts", sheet,
                 "--skip-key", "snacks-veg-momo")

    assert len(fake_flux) == 2
    assert not ImageAsset.objects.filter(found_for_slug="snacks-veg-momo").exists()


@pytest.mark.django_db
def test_waits_between_calls_to_respect_the_endpoint_rate_limit(sheet, fake_flux,
                                                                settings, tmp_path,
                                                                monkeypatch):
    settings.MEDIA_ROOT = str(tmp_path / "media")
    slept = []
    monkeypatch.setattr("menu.management.commands.generate_item_images.time.sleep",
                        slept.append)

    call_command("generate_item_images", "--prompts", sheet, "--delay", "9")

    assert len(fake_flux) == 3
    assert slept == [9, 9]          # between calls, not before the first or after the last


@pytest.mark.django_db
def test_retries_with_growing_backoff_before_giving_up_on_an_item(sheet, settings,
                                                                  tmp_path,
                                                                  monkeypatch):
    """A 429 is the endpoint asking us to slow down, not a dead item."""
    settings.MEDIA_ROOT = str(tmp_path / "media")
    slept, calls = [], []
    monkeypatch.setattr("menu.management.commands.generate_item_images.time.sleep",
                        slept.append)

    def flaky(prompt, **kwargs):
        calls.append(prompt)
        if len(calls) == 1:
            raise RuntimeError("429 Too Many Requests")
        return _png((len(calls) * 20 % 255, 40, 40))

    monkeypatch.setattr(generate_flux, "generate_image", flaky)

    call_command("generate_item_images", "--prompts", sheet, "--delay", "0",
                 "--retries", "2", "--backoff", "30")

    assert len(calls) == 4                       # 1 failure + 1 retry + 2 more items
    assert 30 in slept                           # backed off before retrying
    assert ImageAsset.objects.count() == 3       # the retried item still got made


@pytest.mark.django_db
def test_a_refused_prompt_fails_fast_instead_of_backing_off(sheet, settings,
                                                            tmp_path, monkeypatch):
    """`no image artifact` is a 200 response the model declined to fill — it is
    not the endpoint asking us to slow down, so waiting minutes for it is pure
    dead time. One item must not be able to stall the whole run."""
    settings.MEDIA_ROOT = str(tmp_path / "media")
    slept, calls = [], []
    monkeypatch.setattr("menu.management.commands.generate_item_images.time.sleep",
                        slept.append)

    def refused(prompt, **kwargs):
        calls.append(prompt)
        raise ValueError("NVIDIA response contained no image artifact")

    monkeypatch.setattr(generate_flux, "generate_image", refused)

    call_command("generate_item_images", "--prompts", sheet, "--delay", "0",
                 "--retries", "4", "--backoff", "60",
                 "--error-retries", "1", "--error-backoff", "5")

    assert len(calls) == 6                   # 3 items x (1 try + 1 quick retry)
    assert slept == [5, 5, 5]                # never the 60s rate-limit backoff
    assert max(slept) < 60


@pytest.mark.django_db
def test_a_content_filtered_prompt_is_abandoned_without_any_retry(sheet, settings,
                                                                  tmp_path,
                                                                  monkeypatch):
    """The safety filter's verdict does not change on retry — any seed, same
    refusal. Spending even one more call on it is waste."""
    settings.MEDIA_ROOT = str(tmp_path / "media")
    slept, calls = [], []
    monkeypatch.setattr("menu.management.commands.generate_item_images.time.sleep",
                        slept.append)

    def filtered_first(prompt, **kwargs):
        calls.append(prompt)
        if len(calls) == 1:
            raise generate_flux.ContentFiltered("CONTENT_FILTERED")
        return _png((len(calls) * 20 % 255, 40, 40))

    monkeypatch.setattr(generate_flux, "generate_image", filtered_first)

    call_command("generate_item_images", "--prompts", sheet, "--delay", "0",
                 "--error-retries", "3", "--retries", "4")

    assert len(calls) == 3                   # 1 filtered + 2 others, no retries
    assert slept == []                       # and no waiting at all
    assert ImageAsset.objects.count() == 2


@pytest.mark.django_db
def test_a_real_rate_limit_still_gets_the_long_backoff(sheet, settings, tmp_path,
                                                       monkeypatch):
    settings.MEDIA_ROOT = str(tmp_path / "media")
    slept, calls = [], []
    monkeypatch.setattr("menu.management.commands.generate_item_images.time.sleep",
                        slept.append)

    def limited(prompt, **kwargs):
        calls.append(prompt)
        if len(calls) == 1:
            raise RuntimeError("HTTP Error 429: Too Many Requests")
        return _png((len(calls) * 20 % 255, 40, 40))

    monkeypatch.setattr(generate_flux, "generate_image", limited)

    call_command("generate_item_images", "--prompts", sheet, "--delay", "0",
                 "--retries", "4", "--backoff", "60",
                 "--error-retries", "1", "--error-backoff", "5")

    assert 60 in slept
    assert ImageAsset.objects.count() == 3


@pytest.mark.django_db
def test_gives_up_on_an_item_after_the_retry_budget(sheet, settings, tmp_path,
                                                    monkeypatch):
    settings.MEDIA_ROOT = str(tmp_path / "media")
    calls = []
    monkeypatch.setattr("menu.management.commands.generate_item_images.time.sleep",
                        lambda s: None)

    def always_fail(prompt, **kwargs):
        calls.append(prompt)
        raise RuntimeError("429 Too Many Requests")

    monkeypatch.setattr(generate_flux, "generate_image", always_fail)

    call_command("generate_item_images", "--prompts", sheet, "--delay", "0",
                 "--retries", "2")

    assert len(calls) == 9                       # 3 items x (1 try + 2 retries)
    assert ImageAsset.objects.count() == 0


@pytest.mark.django_db
def test_normalises_output_to_a_webp_thumbnail(sheet, monkeypatch, settings,
                                               tmp_path):
    """FLUX returns a full-size JPEG; the pool stores <=800px webp."""
    settings.MEDIA_ROOT = str(tmp_path / "media")
    buf = io.BytesIO()
    Image.new("RGB", (1024, 1024), (10, 90, 200)).save(buf, "JPEG")
    monkeypatch.setattr(generate_flux, "generate_image",
                        lambda prompt, **kw: buf.getvalue())

    call_command("generate_item_images", "--prompts", sheet, "--limit", "1")

    asset = ImageAsset.objects.get()
    stored = tmp_path / "media" / asset.file
    with Image.open(stored) as im:
        assert im.format == "WEBP"
        assert max(im.size) <= 800
