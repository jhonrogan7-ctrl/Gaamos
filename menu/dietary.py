"""Controlled dietary vocabulary for the canonical menu-item model.

Fixed values rather than free text, so the guest menu can offer a real filter
and the dashboard a real picker. Buff and pork are separate entries because the
distinction is commercially and religiously significant in this market.
"""

DIETARY_VOCAB = ('veg', 'vegan', 'egg', 'chicken', 'buff', 'pork', 'fish', 'mutton')
