"""Render a venue's generated images as one self-contained HTML page for review.

Counts never told us whether a photo is the dish. A 200px contact sheet did not
either — herbs on a "plain" omelette are invisible at that size, and every hot
drink was served cold for eleven images before anyone noticed. So this page
shows each image large, beside the printed name, the printed price, and the
prompt that produced it: roughly half these defects are only visible as a
MISMATCH between the two.

Read-only. It records nothing; `verify_images` applies the verdict.
"""
import base64
import html
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from menu.models import ImageAsset
from menu.pipeline import prompt_sheet

_PAGE = """<!doctype html>
<meta charset="utf-8">
<title>Image review — {company}</title>
<style>
 body {{ font: 15px/1.5 system-ui, sans-serif; margin: 0; background: #faf8f5; }}
 header {{ position: sticky; top: 0; background: #fff; border-bottom: 1px solid #ddd;
           padding: 12px 20px; z-index: 2; }}
 h2 {{ margin: 28px 20px 8px; font-size: 15px; text-transform: uppercase;
       letter-spacing: .08em; color: #96603a; }}
 .row {{ display: flex; gap: 18px; align-items: flex-start; background: #fff;
         margin: 10px 20px; padding: 14px; border-radius: 10px;
         border: 1px solid #e8e2da; }}
 .row.missing {{ background: #fff6f4; }}
 img {{ width: 260px; height: 260px; object-fit: cover; border-radius: 8px; }}
 .meta {{ flex: 1; min-width: 0; }}
 .name {{ font-size: 20px; font-weight: 600; }}
 .price {{ color: #96603a; font-weight: 600; }}
 .prompt {{ font-family: ui-monospace, monospace; font-size: 12px; color: #555;
            background: #f4f1ec; padding: 8px; border-radius: 6px;
            margin-top: 8px; white-space: pre-wrap; word-break: break-word; }}
 .key {{ font-family: ui-monospace, monospace; font-size: 11px; color: #999; }}
 label {{ display: inline-flex; gap: 6px; align-items: center; margin-top: 10px;
          font-weight: 600; color: #b3261e; cursor: pointer; }}
 textarea {{ width: 100%; height: 60px; font-family: ui-monospace, monospace;
             font-size: 12px; }}
</style>
<header>
 <strong>{company}</strong> — {n} image(s). Tick anything that is not the dish,
 has the wrong count, or shows something the card never printed.
 <div><textarea id="out" readonly placeholder="rejected keys appear here"></textarea></div>
 <code>verify_images --prompts &lt;sheet&gt; --company {company} --reject &lt;paste&gt;</code>
</header>
{body}
<script>
 const out = document.getElementById('out');
 const boxes = [...document.querySelectorAll('input[type=checkbox]')];
 const sync = () => out.value = boxes.filter(b => b.checked)
                                     .map(b => b.value).join(',');
 boxes.forEach(b => b.addEventListener('change', sync));
</script>
"""


def _data_uri(asset):
    path = Path(settings.MEDIA_ROOT) / asset.file
    if not path.exists():
        return None
    return 'data:image/webp;base64,' + base64.b64encode(path.read_bytes()).decode()


class Command(BaseCommand):
    help = ('Write a self-contained HTML review page for a venue\'s generated '
            'images. Read-only; use verify_images to record the verdict.')

    def add_arguments(self, parser):
        parser.add_argument('--prompts', required=True,
                            help='Path to the venue prompt sheet (markdown).')
        parser.add_argument('--company', required=True,
                            help='Company slug; must match the sheet.')
        parser.add_argument('--source', default='flux',
                            help='ImageAsset.source to review (default: flux).')
        parser.add_argument('--out', default=None,
                            help='Output path (default: /tmp/<company>-review.html).')

    def handle(self, *args, **opts):
        rows, company = read_sheet(opts['prompts'], opts['company'])
        # The newest NON-REJECTED asset per key: a re-roll adds a row rather
        # than replacing the one it supersedes, and the model's default
        # ordering (`-created_at`) would show the rejected image — making the
        # re-roll invisible on the very page meant to confirm it.
        assets = {a.found_for_slug: a for a in ImageAsset.objects.filter(
            source=opts['source'],
            found_for_slug__in=[r['key'] for r in rows])
            .exclude(status='rejected').order_by('created_at')}

        parts, section, shown = [], None, 0
        for row in rows:
            if not row['generatable']:
                continue
            if row['section'] != section:
                section = row['section']
                parts.append(f'<h2>{html.escape(section)}</h2>')
            asset = assets.get(row['key'])
            uri = _data_uri(asset) if asset else None
            price = f"Rs {row['price']}" if row['price'] is not None else 'no price'
            if uri:
                shown += 1
                img = f'<img src="{uri}" alt="">'
                box = (f'<label><input type="checkbox" value="{html.escape(row["key"])}">'
                       f'reject</label>')
                cls = 'row'
            else:
                img = '<div style="width:260px"></div>'
                box = '<em>no image generated</em>'
                cls = 'row missing'
            parts.append(
                f'<div class="{cls}">{img}<div class="meta">'
                f'<div class="name">{html.escape(row["item"])}</div>'
                f'<div class="price">{price}</div>'
                f'<div class="key">{html.escape(row["key"])}</div>'
                f'<div class="prompt">{html.escape(asset.prompt if asset else row["prompt"])}</div>'
                f'{box}</div></div>')

        out = Path(opts['out'] or f'/tmp/{company}-review.html')
        out.write_text(_PAGE.format(company=html.escape(company), n=shown,
                                    body='\n'.join(parts)))
        self.stdout.write(self.style.SUCCESS(
            f'{out}: {shown} image(s) for review'))


def read_sheet(path, company):
    """Parse the sheet and cross-check its declared slug. Shared with
    verify_images so the two commands can never disagree about which venue's
    keys they are operating on."""
    sheet_path = Path(path)
    if not sheet_path.exists():
        raise CommandError(f'Prompt sheet not found: {sheet_path}')
    text = sheet_path.read_text()
    venue = prompt_sheet.parse_venue(text)
    if venue['slug'] and venue['slug'] != company:
        raise CommandError(
            f"Sheet declares slug '{venue['slug']}' but --company is "
            f"'{company}'. Fix the sheet, not the command.")
    return prompt_sheet.parse(text), company
