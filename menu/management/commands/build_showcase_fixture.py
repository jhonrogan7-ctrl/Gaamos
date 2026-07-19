import json
import shutil
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

DONOR_FIXTURE = Path(settings.BASE_DIR) / 'menu' / 'fixtures' / 'seed.json'
OUT_FIXTURE = Path(settings.BASE_DIR) / 'menu' / 'fixtures' / 'showcase.json'
STATIC_THUMBS = Path(settings.BASE_DIR) / 'static' / 'seed' / 'showcase' / 'thumbs'
STATIC_URL_PREFIX = '/static/seed/showcase/thumbs/'


class Command(BaseCommand):
    help = ('Dev-only: build menu/fixtures/showcase.json + copy present thumbnails '
            'into static/seed/showcase/thumbs/ from the donor seed.json and qr_manu.')

    def add_arguments(self, parser):
        parser.add_argument(
            '--thumbs-src', default='/home/paperclip/qr_manu/media/menu_items/thumbs',
            help='Directory holding the donor .webp thumbnails.')

    def handle(self, *args, **options):
        src = Path(options['thumbs_src'])
        records = json.loads(DONOR_FIXTURE.read_text())
        by_model = {}
        for rec in records:
            by_model.setdefault(rec['model'].split('.')[-1], []).append(rec)

        # donor pk -> slug / (cat-slug, name)
        cat_slug = {r['pk']: r['fields']['slug'] for r in by_model['category']}
        sub_key = {r['pk']: (cat_slug[r['fields']['category']], r['fields']['name'])
                   for r in by_model['subcategory']}

        # canonical placement per item pk: first occurrence wins
        canon = {}
        for r in by_model.get('branchitemplacement', []):
            f = r['fields']
            canon.setdefault(f['menu_item'], (f['category'], f.get('sub_category')))

        # keep only items whose thumbnail file is present; copy those files.
        # `order` is the donor-dump position (verified monotonic for this data,
        # so relative order within each subcategory is preserved) — not the
        # donor's branchitemplacement.display_order. A future regeneration
        # against reordered donor data should switch to display_order.
        STATIC_THUMBS.mkdir(parents=True, exist_ok=True)
        kept_items, used_sub_keys, used_cat_slugs = [], set(), set()
        for order, r in enumerate(by_model['menuitem']):
            f = r['fields']
            url = f.get('image_url', '') or ''
            fname = url.rsplit('/', 1)[1] if url else ''
            if not fname or not (src / fname).is_file():
                continue  # imageless -> excluded
            if r['pk'] not in canon:
                self.stderr.write(f"skip (no placement): {f['slug']}")
                continue
            shutil.copyfile(src / fname, STATIC_THUMBS / fname)
            cpk, spk = canon[r['pk']]
            csl = cat_slug[cpk]
            sname = sub_key[spk][1] if spk else None
            used_cat_slugs.add(csl)
            if sname is not None:
                used_sub_keys.add((csl, sname))
            kept_items.append({
                'slug': f['slug'], 'name': f['name'],
                'description': f.get('description', ''), 'price': f['price'],
                'tags': f.get('dietary_tags', []),
                'image': STATIC_URL_PREFIX + fname,
                'popular': f.get('is_popular', False),
                'featured': f.get('is_featured', False),
                'cat': csl, 'sub': sname, 'order': order,
            })

        # categories/subcategories: only those actually used by kept items
        categories = []
        for r in sorted(by_model['category'],
                        key=lambda r: r['fields'].get('display_order', 0)):
            f = r['fields']
            if f['slug'] not in used_cat_slugs:
                continue
            subs = [{'name': s['fields']['name'],
                     'icon_key': s['fields'].get('icon_key', 'subAll'),
                     'display_order': s['fields'].get('display_order', 0)}
                    for s in by_model['subcategory']
                    if cat_slug[s['fields']['category']] == f['slug']
                    and (f['slug'], s['fields']['name']) in used_sub_keys]
            subs.sort(key=lambda s: s['display_order'])
            categories.append({
                'slug': f['slug'], 'name': f['name'],
                'icon_key': f.get('icon_key', ''),
                'hours_note': f.get('hours_note', ''),
                'display_order': f.get('display_order', 0),
                'subcategories': subs,
            })

        rest = (by_model.get('restaurant') or [{}])[0].get('fields', {})
        out = {
            'company': {k: rest.get(k, '') for k in
                        ('name', 'tagline', 'phone', 'email',
                         'instagram', 'facebook', 'tiktok')},
            'categories': categories,
            'items': kept_items,
        }
        OUT_FIXTURE.write_text(json.dumps(out, indent=2, ensure_ascii=False))
        self.stdout.write(self.style.SUCCESS(
            f"Wrote {OUT_FIXTURE.name}: {len(kept_items)} items, "
            f"{len(categories)} categories, "
            f"{sum(len(c['subcategories']) for c in categories)} subcategories; "
            f"copied thumbnails into {STATIC_THUMBS}."))
