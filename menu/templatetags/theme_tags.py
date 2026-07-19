from django import template
from django.utils.safestring import mark_safe

from menu.themes import GROUP_LABELS, THEMES, get_theme

register = template.Library()


@register.simple_tag
def theme_style(slug=''):
    """Inline CSS custom properties for the resolved guest theme.

    Values are registry constants (hexes/gradients we author), safe to emit
    raw; unknown/blank slugs resolve to the platform default."""
    theme = get_theme(slug)
    return mark_safe(';'.join(f'{k}:{v}' for k, v in theme.tokens.items()))


@register.inclusion_tag('dashboard/_theme_picker.html')
def theme_picker(current='', include_inherit=False, alpine=False):
    """Shared 6-theme picker. alpine=True binds to the Branches modal's
    bTheme state; default emits submit buttons for the Settings form."""
    themes = [
        {'slug': slug, 'label': t.label, 'tagline': t.tagline,
         'group': t.group, 'group_label': GROUP_LABELS[t.group],
         'swatch': t.swatch}
        for slug, t in THEMES.items()
    ]
    return {'themes': themes, 'current': current,
            'include_inherit': include_inherit, 'alpine': alpine}
