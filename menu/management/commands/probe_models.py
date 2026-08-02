"""Invoke every configured NVIDIA model with a minimal payload and report.

    python manage.py probe_models
    python manage.py probe_models --model embed

Run this before anything depends on a model ID. It INVOKES rather than reading
`GET /v1/models`, because listing is not availability:
`nvidia/llama-3.2-nv-embedqa-1b-v1` and `snowflake/arctic-embed-l` are both
listed for this account and both return 404 on a real call.

Anything unreachable simply switches its layer off -- no embed model means the
matcher runs layers 0-2 and the wizard is none the wiser -- so this command
reports and never raises.
"""
import time

from django.conf import settings
from django.core.management.base import BaseCommand

from menu.pipeline import item_embed, nv

_STAGES = ('vision', 'embed', 'text')


def _probe_menu_png():
    """A card that prints two items, rendered rather than stored.

    ⚠ It must never go back to being a blank square. This probe used to send a
    uniform 64x64 near-white PNG, and the vision model does not abstain when
    there is nothing to read -- it invents. Asked to extract a menu from a blank
    image it fabricated one until it hit the cap (`finish_reason: 'length'` at
    every budget measured, 512 through 8192), so every probe spent the whole
    8192-token budget and routinely ended in `EngineCore encountered an issue`
    (HTTP 500) or past the 300s read timeout. Worse, when it did return, the
    command printed OK -- the only thing that had been proven was that
    `extract_menu` had not raised.

    Two printed items give the model something real to transcribe, so the guided
    array closes on its own in a few seconds, and the item count becomes
    evidence the pipeline actually read something.

    Rendered with `fitz`, already a dependency for rasterizing PDFs, so the
    probe carries no fixture file that could drift from the code beside it.
    """
    import fitz
    doc = fitz.open()
    page = doc.new_page(width=320, height=180)
    for y, (name, price) in enumerate([('TEA', '50'), ('COFFEE', '80')]):
        page.insert_text((40, 70 + y * 55), name, fontsize=30)
        page.insert_text((220, 70 + y * 55), price, fontsize=30)
    return page.get_pixmap(dpi=150).tobytes('png')


class Command(BaseCommand):
    help = 'Invoke each configured NVIDIA model and report reachable/unavailable.'

    def add_arguments(self, parser):
        parser.add_argument('--model', choices=_STAGES, dest='stage',
                            help='Probe one stage instead of all three.')

    def handle(self, *args, **opts):
        stages = [opts['stage']] if opts.get('stage') else list(_STAGES)
        if not settings.NVIDIA_API_KEY:
            self.stdout.write(self.style.ERROR(
                'NVIDIA_API_KEY is empty — every stage would report '
                'UNAVAILABLE for the wrong reason.'))
            return
        for stage in stages:
            self._probe(stage)

    def _probe(self, stage):
        model = {'vision': settings.NVIDIA_VISION_MODEL,
                 'embed': settings.NVIDIA_EMBED_MODEL,
                 'text': settings.NVIDIA_TEXT_MODEL}[stage]
        started = time.monotonic()
        try:
            status, note = getattr(self, f'_probe_{stage}')()
        except nv.NotAvailable as exc:
            return self._line(stage, model, 'UNAVAILABLE', str(exc), started,
                              self.style.ERROR)
        except Exception as exc:                    # noqa: BLE001 — report, never raise
            return self._line(stage, model, 'ERROR',
                              f'{type(exc).__name__}: {exc}', started,
                              self.style.ERROR)
        # Each stage names its own failure: 'WRONG WIDTH' and 'NO ITEMS' are
        # different problems and a reader needs to be told which one.
        style = self.style.SUCCESS if status == 'OK' else self.style.WARNING
        return self._line(stage, model, status, note, started, style)

    def _probe_vision(self):
        """Reachability AND comprehension: the probe card prints two items.

        Zero items back is a failure even though nothing raised -- see
        `_probe_menu_png` for why that distinction is the whole point here.
        """
        from menu.pipeline import extract_nv
        items = extract_nv.extract_menu(_probe_menu_png(), 'image/png')['items']
        if not items:
            return 'NO ITEMS', 'the probe card prints TEA 50 and COFFEE 80'
        return 'OK', f'{len(items)} items'

    def _probe_embed(self):
        from menu.pipeline import embed_nv
        width = len(embed_nv.embed('black tea', kind='passage'))
        if width != item_embed.DIMENSIONS:
            return 'WRONG WIDTH', (f'returned {width}-d, the catalog column '
                                   f'stores {item_embed.DIMENSIONS}-d')
        return 'OK', ''

    def _probe_text(self):
        from menu.pipeline import text_nv
        text_nv.complete('Reply with the single word: ok')
        return 'OK', ''

    def _line(self, stage, model, status, note, started, style):
        ms = int((time.monotonic() - started) * 1000)
        self.stdout.write(style(
            f'{stage:7} {model:42} {status:12} {ms:6} ms  {note}'))
