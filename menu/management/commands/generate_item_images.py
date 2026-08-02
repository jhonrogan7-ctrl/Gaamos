"""Generate a venue's menu images from a hand-written prompt sheet and deposit
them in the global ImageAsset pool as `pending` rows for human verification.

The sheet (vault: `menius/<venue>/…-items-and-image-prompts.md`) carries a short
subject prompt per item; `prompt_sheet.full_prompt` appends the shared style
block so the whole set looks like one photoshoot. Images come from the hosted
FLUX endpoint — the working generator while Gemini image gen is blocked on
billing.

Resumable and idempotent: a row whose section-qualified key already has an asset
from this source is skipped, so a partial run is resumed by re-running. One
failed generation never aborts the run — re-run to pick up the stragglers.

Embeddings are NOT computed by default (that is the separate, currently
billing-blocked Gemini embed API); pass --embed once it is back.

Example:
  python manage.py generate_item_images \
      --prompts /root/zxyn/gaamos/menius/tranquilityinn/tranquility-items-and-image-prompts.md \
      --limit 5
"""
import os
import re
import tempfile
import time
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils.text import slugify

from menu.models import ImageAsset
# Imported as modules, not names, so tests can patch the collaborators.
from menu.pipeline import (dish_lexicon, generate_flux, images, intake,
                           prompt_sheet, throttle)


def _tags(row):
    """Light initial tags for browse/filter: section + item words."""
    raw = [slugify(row['section'])] + row['slug'].split('-')
    seen, out = set(), []
    for t in raw:
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _is_rate_limited(exc):
    """Distinguish "slow down" from "this prompt produced nothing"."""
    if getattr(exc, 'code', None) == 429:
        return True
    text = str(exc).lower()
    return '429' in text or 'rate limit' in text or 'too many requests' in text


def covered_slugs(listing_path):
    """Item slugs already shot elsewhere, read from a listing of filenames.

    The venue's own image folder lives on the file server, not in this
    container, so the interface is a listing (`ls > names.txt`) rather than a
    directory. Names are bare item names with an optional `_1`/`_2` variant
    suffix: `Simple Breakfast_2.jpg` covers `Simple Breakfast`.
    """
    out = set()
    for line in Path(listing_path).read_text().splitlines():
        stem = os.path.splitext(line.strip())[0]
        stem = re.sub(r'_\d+$', '', stem)
        if stem:
            out.add(slugify(stem))
    return out


def _to_webp(raw_bytes, size):
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / 'raw'
        dest = Path(tmp) / 'out.webp'
        src.write_bytes(raw_bytes)
        images.to_thumbnail(str(src), str(dest), size)
        return dest.read_bytes()


class Command(BaseCommand):
    help = ("Generate menu images from a markdown prompt sheet via FLUX and "
            "deposit them as pending ImageAssets (resumable, idempotent).")

    def add_arguments(self, parser):
        parser.add_argument('--prompts', required=True,
                            help='Path to the markdown item + prompt sheet.')
        parser.add_argument('--limit', type=int, default=None,
                            help='Stop after N generations (trial runs).')
        parser.add_argument('--dry-run', action='store_true',
                            help='List what would be generated; call nothing.')
        parser.add_argument('--source', default='flux',
                            help='ImageAsset.source value (default: flux).')
        parser.add_argument('--size', type=int, default=800,
                            help='Longest thumbnail side in px (default: 800).')
        parser.add_argument('--embed', action='store_true',
                            help='Compute Gemini embeddings now (default: skip).')
        parser.add_argument('--skip-names', default=None,
                            help='File listing filenames already shot elsewhere; '
                                 'items whose name matches are not generated.')
        parser.add_argument('--include-key', action='append', default=[],
                            help='Generate this key even if --skip-names matched '
                                 'its bare name (repeatable).')
        parser.add_argument('--skip-key', action='append', default=[],
                            help='Never generate this key (repeatable).')
        parser.add_argument('--delay', type=float, default=10.0,
                            help='Advisory only since 2026-08-01: pacing now '
                                 'comes from the shared throttle budget for '
                                 'NVIDIA_IMAGE_MODEL.')
        parser.add_argument('--retries', type=int, default=3,
                            help='Retries per item on failure (default: 3).')
        parser.add_argument('--backoff', type=float, default=30.0,
                            help='First rate-limit backoff in seconds, doubling '
                                 'per retry (default: 30).')
        parser.add_argument('--error-retries', type=int, default=1,
                            help='Retries for non-rate-limit failures, e.g. a '
                                 'prompt the model declines (default: 1).')
        parser.add_argument('--error-backoff', type=float, default=5.0,
                            help='First backoff for non-rate-limit failures '
                                 '(default: 5).')
        parser.add_argument('--reroll', type=int, default=0,
                            help='Re-roll attempt number; advances the seed so '
                                 'a regenerated item cannot reproduce the image '
                                 'it is replacing (default: 0).')
        parser.add_argument('--steps', type=int, default=4,
                            help='Sampling steps (default: 4, which is also the '
                                 'endpoint maximum for the distilled klein '
                                 'model — a higher value is refused 422).')

    def _generate(self, prompt, opts, seed):
        """One image, retrying on failure. Two failure modes, two budgets: a 429
        is the endpoint asking us to slow down and deserves a long wait, while a
        declined prompt ("no image artifact") is a 200 that will not improve —
        waiting minutes on it just stalls the other 120 items."""
        limited_used = error_used = 0
        while True:
            try:
                return generate_flux.generate_image(prompt, seed=seed,
                                                    steps=opts['steps'])
            except generate_flux.ContentFiltered:
                raise                                 # a verdict, not a failure
            except Exception as exc:                  # noqa: BLE001
                if _is_rate_limited(exc):
                    if limited_used >= opts['retries']:
                        raise
                    wait = throttle.backoff_seconds(limited_used,
                                                    base=opts['backoff'])
                    limited_used += 1
                    kind = f"rate-limit {limited_used}/{opts['retries']}"
                else:
                    if error_used >= opts['error_retries']:
                        raise
                    wait = throttle.backoff_seconds(error_used,
                                                    base=opts['error_backoff'])
                    error_used += 1
                    kind = f"error {error_used}/{opts['error_retries']}"
                self.stderr.write(f"    retry ({kind}) in {wait:.0f}s "
                                  f"({type(exc).__name__}: {exc})")
                time.sleep(wait)

    def handle(self, *args, **opts):
        path = Path(opts['prompts'])
        if not path.exists():
            raise CommandError(f'Prompt sheet not found: {path}')
        rows = prompt_sheet.parse(path.read_text())
        source, limit = opts['source'], opts['limit']
        embedder = None if opts['embed'] else (lambda text: None)

        todo = [r for r in rows if r['generatable']]
        # `rejected` must NOT count as done. A rejected asset is a reviewer
        # saying "this is not the dish"; if its key blocked regeneration the
        # review gate would be decorative.
        done_keys = set(ImageAsset.objects.filter(source=source)
                        .exclude(status='rejected')
                        .values_list('found_for_slug', flat=True))
        covered = covered_slugs(opts['skip_names']) if opts['skip_names'] else set()
        include, skip_keys = set(opts['include_key']), set(opts['skip_key'])

        generated = skipped = failed = deduped = elsewhere = 0
        filtered = []
        for row in todo:
            if limit is not None and generated >= limit:
                break
            if row['key'] in done_keys or row['key'] in skip_keys:
                skipped += 1
                continue
            if row['slug'] in covered and row['key'] not in include:
                elsewhere += 1
                continue
            prompt = prompt_sheet.full_prompt(row)
            if opts['dry_run']:
                self.stdout.write(f"  would generate {row['key']}: {prompt[:70]}…")
                generated += 1
                continue
            # One budget for the image model, shared with every other caller.
            # The old `--delay` sleep only knew about this process, so a worker
            # generating at the same time doubled the real rate. No "skip the
            # first" guard is needed: an empty bucket returns 0 immediately.
            throttle.acquire(settings.NVIDIA_IMAGE_MODEL)
            try:
                seed = generate_flux.seed_for(row['key'], opts['reroll'])
                raw = self._generate(prompt, opts, seed)
                webp = _to_webp(raw, opts['size'])
            except generate_flux.ContentFiltered:
                # Not retryable at any seed. Report it so the prompt can be
                # reworded by hand, and keep going.
                self.stderr.write(f"  ⊘ {row['key']}: content-filtered")
                filtered.append(row['key'])
                continue
            except Exception as exc:                  # noqa: BLE001 — see below
                # A dead generation must not cost the run its other 144 images;
                # the row simply stays undone and the next run retries it.
                self.stderr.write(f"  ! {row['key']}: {type(exc).__name__}: {exc}")
                failed += 1
                continue
            asset = intake.record(
                source=source, webp_bytes=webp, item_name=row['item'],
                found_for_slug=row['key'], source_text=row['description'],
                prompt=prompt, tags=_tags(row), name=row['item'],
                embedder=embedder)
            if asset is None:
                deduped += 1                          # rejected tombstone
                continue
            generated += 1
            self.stdout.write(f"  ✓ {row['key']} → {asset.file}")

        undefined = [r['item'] for r in todo if dish_lexicon.needs_definition(r)]

        verb = 'would generate' if opts['dry_run'] else 'generated'
        self.stdout.write(self.style.SUCCESS(
            f"{verb} {generated} | skipped (already done) {skipped} | "
            f"skipped (shot elsewhere) {elsewhere} | failed {failed} | "
            f"content-filtered {len(filtered)} | rejected-dedup {deduped} | "
            f"generatable rows in sheet {len(todo)} of {len(rows)}"))
        if undefined:
            self.stdout.write(self.style.WARNING(
                f'undefined head-word, drawn from the name alone '
                f'({len(undefined)}): ' + ', '.join(undefined)))
            self.stdout.write('  → add a dish_lexicon entry (founder sign-off) '
                              'or make the row *skip — ask the venue*')
        if filtered:
            self.stdout.write("content-filtered (reword the prompt by hand): "
                              + ', '.join(filtered))
