from pathlib import Path
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


def test_fetch_thumbnail_downloads_then_normalizes_and_returns_bytes():
    seen = {}

    def fake_download(source, url, dest):
        seen['source'], seen['url'] = source, url
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        Path(dest).write_bytes(b'RAWJPEG')
        return dest

    def fake_thumb(src, dest, size=800):
        seen['raw'] = Path(src).read_bytes()
        seen['size'] = size
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        Path(dest).write_bytes(b'WEBPBYTES')
        return dest

    with patch('menu.pipeline.photo_search.download', side_effect=fake_download), \
         patch('menu.pipeline.images.to_thumbnail', side_effect=fake_thumb):
        out = photo_search.fetch_thumbnail('pexels', 'https://img/x.jpg')

    assert out == b'WEBPBYTES'
    assert seen['source'] == 'pexels'
    assert seen['url'] == 'https://img/x.jpg'
    assert seen['raw'] == b'RAWJPEG'
    assert seen['size'] == 800


def test_fetch_thumbnail_leaves_no_temp_files_behind():
    """The helper works in a TemporaryDirectory — nothing survives the call."""
    holder = {}

    def fake_download(source, url, dest):
        holder['dir'] = Path(dest).parent
        Path(dest).write_bytes(b'RAWJPEG')
        return dest

    def fake_thumb(src, dest, size=800):
        Path(dest).write_bytes(b'WEBPBYTES')
        return dest

    with patch('menu.pipeline.photo_search.download', side_effect=fake_download), \
         patch('menu.pipeline.images.to_thumbnail', side_effect=fake_thumb):
        photo_search.fetch_thumbnail('pexels', 'https://img/x.jpg')

    assert not holder['dir'].exists()


def test_fetch_thumbnail_rejects_unknown_source():
    with pytest.raises(ValueError):
        photo_search.fetch_thumbnail('nope', 'https://img/x.jpg')
