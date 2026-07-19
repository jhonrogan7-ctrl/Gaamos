"""Guest-menu theme registry — the single source of truth for the 6 palettes.

Consumers: model choices (menu/models.py), guest theme resolution
(menu/views.py), the shared dashboard picker + inline token emission
(menu/templatetags/theme_tags.py), the ops tenant form, and the theme tests.
Adding or tuning a theme means editing this file only.

Design record: superpowers/specs/2026-07-18-guest-theme-palettes-design.md
"""
from typing import NamedTuple


class Theme(NamedTuple):
    label: str
    group: int          # 1 = Appetite Stimulators, 2 = Trust & Comfort
    tagline: str
    swatch: tuple       # the 3 core hexes shown as picker chips
    tokens: dict        # CSS custom properties emitted inline on guest <html>


GROUP_LABELS = {1: 'Appetite Stimulators', 2: 'Trust & Comfort'}

# Emission order for the inline style; every theme must define exactly these.
TOKEN_KEYS = (
    '--brand', '--brand-deep', '--brand-soft', '--brand-ink', '--grad',
    '--price', '--paper', '--cream', '--card',
    '--ink', '--ink-2', '--ink-3', '--line', '--line-2',
)

THEMES = {
    # ── Group 1 — Appetite Stimulators ──
    'fastfood': Theme(
        label='Classic Fast Food', group=1, tagline='Bold · fast · hungry',
        swatch=('#E53E3E', '#FFC93C', '#FFFFFF'),
        tokens={
            '--brand': '#E53E3E', '--brand-deep': '#C53030',
            '--brand-soft': '#FDE8E8', '--brand-ink': '#FFFFFF',
            '--grad': 'linear-gradient(135deg,#FFC93C,#E53E3E)',
            '--price': '#C53030',
            '--paper': '#FFFFFF', '--cream': '#FFF9F0', '--card': '#FFFFFF',
            '--ink': '#1F1A17', '--ink-2': '#5F574C', '--ink-3': '#8A8073',
            '--line': '#F0E4D3', '--line-2': '#E2D3BC',
        }),
    'citrus': Theme(
        # Solid brand deepened one step from the approved #F97316: white CTA
        # text on #F97316 is 2.8:1, under the spec's own 3.0 floor. The
        # gradient and swatch keep #F97316 so the visual identity holds.
        label='Citrus Charge', group=1, tagline='Fresh · zesty · friendly',
        swatch=('#F97316', '#FACC15', '#FFF8E7'),
        tokens={
            '--brand': '#EA580C', '--brand-deep': '#C2410C',
            '--brand-soft': '#FFEDD5', '--brand-ink': '#FFFFFF',
            '--grad': 'linear-gradient(135deg,#FACC15,#F97316)',
            '--price': '#C2410C',
            '--paper': '#FFF8E7', '--cream': '#FFFCF2', '--card': '#FFFFFF',
            '--ink': '#241A0F', '--ink-2': '#6B5E42', '--ink-3': '#93855F',
            '--line': '#F2E6C9', '--line-2': '#E6D5AC',
        }),
    'contrast': Theme(
        label='Energetic Contrast', group=1, tagline='Punchy · grounded · late-night',
        swatch=('#E53E3E', '#EA580C', '#2B1B12'),
        tokens={
            '--brand': '#E53E3E', '--brand-deep': '#B91C1C',
            '--brand-soft': '#FBE3D4', '--brand-ink': '#FFFFFF',
            '--grad': 'linear-gradient(135deg,#EA580C,#E53E3E)',
            '--price': '#B91C1C',
            '--paper': '#FCF3EA', '--cream': '#FFF9F2', '--card': '#FFFFFF',
            '--ink': '#2B1B12', '--ink-2': '#6E5A4C', '--ink-3': '#8C7A6B',
            '--line': '#EBD9C8', '--line-2': '#DEC6AF',
        }),
    # ── Group 2 — Trust & Comfort ──
    'eco': Theme(
        label='Ecological Clean', group=2, tagline='Calm · organic · fresh',
        swatch=('#2D6A4F', '#A3B18A', '#EFEAD8'),
        tokens={
            '--brand': '#2D6A4F', '--brand-deep': '#1B4332',
            '--brand-soft': '#DCE7DB', '--brand-ink': '#FFFFFF',
            '--grad': 'linear-gradient(135deg,#A3B18A,#2D6A4F)',
            '--price': '#1B4332',
            '--paper': '#EFEAD8', '--cream': '#F7F4E9', '--card': '#FDFCF7',
            '--ink': '#1F2A22', '--ink-2': '#5A6357', '--ink-3': '#878E7F',
            '--line': '#D8D2BC', '--line-2': '#C7BFA4',
        }),
    'cozy': Theme(
        label='Gourmet Cozy', group=2, tagline='Warm · premium · indulgent',
        swatch=('#4E342E', '#8A6423', '#F8F1E5'),
        tokens={
            '--brand': '#8A6423', '--brand-deep': '#6B4C1B',
            '--brand-soft': '#F3E4C8', '--brand-ink': '#FFFFFF',
            '--grad': 'linear-gradient(135deg,#8A6423,#4E342E)',
            '--price': '#8A6423',
            '--paper': '#F8F1E5', '--cream': '#FFFDF8', '--card': '#FFFDF8',
            '--ink': '#33261D', '--ink-2': '#64513E', '--ink-3': '#7D6B54',
            '--line': '#E3D5BC', '--line-2': '#D3BF9C',
        }),
    'herbal': Theme(
        label='Natural Herbal', group=2, tagline='Earthy · natural · soothing',
        swatch=('#5F7233', '#B85C38', '#FAF6EF'),
        tokens={
            '--brand': '#B85C38', '--brand-deep': '#9C4A28',
            '--brand-soft': '#F0DED2', '--brand-ink': '#FFFFFF',
            '--grad': 'linear-gradient(135deg,#5F7233,#4A5A26)',
            '--price': '#9C4A28',
            '--paper': '#FAF6EF', '--cream': '#FCFAF4', '--card': '#FFFFFF',
            '--ink': '#2A2B22', '--ink-2': '#565744', '--ink-3': '#6E6A58',
            '--line': '#E2DCCB', '--line-2': '#D2C9AF',
        }),
}

DEFAULT_THEME = 'eco'
THEME_CHOICES = [(slug, t.label) for slug, t in THEMES.items()]


def get_theme(slug):
    """Resolve a slug to a Theme. Unknown/legacy/blank slug falls back to the
    default — fail-safe: the guest menu must always render."""
    if slug in THEMES:
        return THEMES[slug]
    return THEMES[DEFAULT_THEME]


def resolve_slug(slug):
    """Normalise any stored/requested slug to a registered one."""
    return slug if slug in THEMES else DEFAULT_THEME
