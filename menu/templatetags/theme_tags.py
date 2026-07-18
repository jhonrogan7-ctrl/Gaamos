from django import template
from django.utils.safestring import mark_safe

from menu.themes import get_theme

register = template.Library()


@register.simple_tag
def theme_style(slug=''):
    """Inline CSS custom properties for the resolved guest theme.

    Values are registry constants (hexes/gradients we author), safe to emit
    raw; unknown/blank slugs resolve to the platform default."""
    theme = get_theme(slug)
    return mark_safe(';'.join(f'{k}:{v}' for k, v in theme.tokens.items()))
