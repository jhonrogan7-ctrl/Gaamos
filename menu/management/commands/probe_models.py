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
import io
import time

from django.conf import settings
from django.core.management.base import BaseCommand

from menu.pipeline import item_embed, nv

_STAGES = ('vision', 'embed', 'text')


def _tiny_png():
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (64, 64), (250, 250, 250)).save(buf, format='PNG')
    return buf.getvalue()


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
            note = getattr(self, f'_probe_{stage}')()
        except nv.NotAvailable as exc:
            return self._line(stage, model, 'UNAVAILABLE', str(exc), started,
                              self.style.ERROR)
        except Exception as exc:                    # noqa: BLE001 — report, never raise
            return self._line(stage, model, 'ERROR',
                              f'{type(exc).__name__}: {exc}', started,
                              self.style.ERROR)
        style = self.style.WARNING if note else self.style.SUCCESS
        return self._line(stage, model, 'WRONG WIDTH' if note else 'OK', note,
                          started, style)

    def _probe_vision(self):
        from menu.pipeline import extract_nv
        extract_nv.extract_menu(_tiny_png(), 'image/png')
        return ''

    def _probe_embed(self):
        from menu.pipeline import embed_nv
        width = len(embed_nv.embed('black tea', kind='passage'))
        if width != item_embed.DIMENSIONS:
            return (f'returned {width}-d, the catalog column stores '
                    f'{item_embed.DIMENSIONS}-d')
        return ''

    def _probe_text(self):
        from menu.pipeline import text_nv
        text_nv.complete('Reply with the single word: ok')
        return ''

    def _line(self, stage, model, status, note, started, style):
        ms = int((time.monotonic() - started) * 1000)
        self.stdout.write(style(
            f'{stage:7} {model:42} {status:12} {ms:6} ms  {note}'))
