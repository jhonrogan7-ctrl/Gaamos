"""Normalized multi-source photo search + download over the three finders, for
the image re-roll. One uniform candidate shape: {url, page, credit, source}.
Finders are called via module attribute so tests can patch them."""
from menu.pipeline import find_commons, find_openverse, find_pexels

SOURCES = ['pexels', 'commons', 'openverse']

_COMMONS_WIKI = 'https://commons.wikimedia.org/wiki/'


def search(source, term, limit=20):
    if source == 'pexels':
        return [{'url': c['url'], 'page': c.get('page', ''),
                 'credit': c.get('photographer', ''), 'source': 'pexels'}
                for c in find_pexels.search(term, per_page=limit)]
    if source == 'commons':
        out = []
        for title, thumb, _mime in find_commons.search(term, limit=limit):
            out.append({'url': thumb, 'page': _COMMONS_WIKI + title.replace(' ', '_'),
                        'credit': title, 'source': 'commons'})
        return out
    if source == 'openverse':
        return [{'url': c['url'], 'page': c.get('landing_url', ''),
                 'credit': c.get('creator') or c.get('attribution', ''),
                 'source': 'openverse'}
                for c in find_openverse.search(term, page_size=limit)]
    raise ValueError(f'unknown source: {source}')


def download(source, url, dest):
    if source == 'pexels':
        return find_pexels.download(url, dest)
    if source == 'commons':
        return find_commons.download(url, dest)
    if source == 'openverse':
        return find_openverse.download(url, dest)
    raise ValueError(f'unknown source: {source}')
