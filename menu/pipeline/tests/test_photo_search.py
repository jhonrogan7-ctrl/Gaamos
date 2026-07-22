from unittest.mock import patch

import pytest

from menu.pipeline import photo_search


def test_search_pexels_normalizes():
    fake = [{'url': 'http://i/p.jpg', 'page': 'http://pexels/p', 'photographer': 'Ann', 'alt': 'a'}]
    with patch('menu.pipeline.find_pexels.search', return_value=fake) as m:
        out = photo_search.search('pexels', 'beer', limit=20)
    m.assert_called_once_with('beer', per_page=20)
    assert out == [{'url': 'http://i/p.jpg', 'page': 'http://pexels/p',
                    'credit': 'Ann', 'source': 'pexels'}]


def test_search_commons_normalizes_tuple_and_builds_wiki_page():
    fake = [('File:Budweiser beer.jpg', 'http://i/c.jpg', 'image/jpeg')]
    with patch('menu.pipeline.find_commons.search', return_value=fake) as m:
        out = photo_search.search('commons', 'Budweiser', limit=20)
    m.assert_called_once_with('Budweiser', limit=20)
    assert out == [{'url': 'http://i/c.jpg',
                    'page': 'https://commons.wikimedia.org/wiki/File:Budweiser_beer.jpg',
                    'credit': 'File:Budweiser beer.jpg', 'source': 'commons'}]


def test_search_openverse_normalizes():
    fake = [{'url': 'http://i/o.jpg', 'landing_url': 'http://ov/o', 'creator': 'Cy',
             'attribution': 'x', 'title': 't', 'license': 'cc0', 'source': 'flickr'}]
    with patch('menu.pipeline.find_openverse.search', return_value=fake) as m:
        out = photo_search.search('openverse', 'beer', limit=20)
    m.assert_called_once_with('beer', page_size=20)
    assert out == [{'url': 'http://i/o.jpg', 'page': 'http://ov/o',
                    'credit': 'Cy', 'source': 'openverse'}]


def test_search_unknown_source_raises():
    with pytest.raises(ValueError):
        photo_search.search('bing', 'beer')


def test_download_dispatches_by_source():
    with patch('menu.pipeline.find_commons.download', return_value='d') as m:
        assert photo_search.download('commons', 'http://i/c.jpg', '/tmp/x') == 'd'
    m.assert_called_once_with('http://i/c.jpg', '/tmp/x')
    with pytest.raises(ValueError):
        photo_search.download('bing', 'u', 'd')
