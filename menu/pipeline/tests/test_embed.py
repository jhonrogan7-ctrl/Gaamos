import io
import json

from menu.models import ImageAsset
from menu.pipeline import embed


def _fake_opener(payload):
    def opener(req, timeout=None):
        captured['url'] = req.full_url
        captured['body'] = json.loads(req.data.decode())
        return io.BytesIO(json.dumps(payload).encode())
    return opener


captured = {}


def _column_dimensions():
    """`ImageAsset`, not `Item`: this adapter is the image pool's, and only the
    image pool's. The catalog moved to 1024-d NVIDIA vectors behind
    `menu.pipeline.item_embed`, and the two spaces are not interchangeable."""
    return ImageAsset._meta.get_field('embedding').dimensions


def test_embed_returns_vector_and_calls_embedcontent():
    payload = {"embedding": {"values": [0.5] * 768}}
    vec = embed.embed("boiled egg", api_key="k", model="gemini-embedding-001",
                      opener=_fake_opener(payload))
    assert len(vec) == 768
    assert "gemini-embedding-001:embedContent" in captured['url']
    assert captured['body']['content']['parts'][0]['text'] == "boiled egg"


def test_requests_the_dimension_the_vector_column_stores():
    """The model is natively 3072-d and the column is 768 — the request must ask
    for the column's width or every write fails at the database."""
    embed.embed("boiled egg", api_key="k", model="m",
                opener=_fake_opener({"embedding": {"values": [0.5] * 768}}))
    assert captured['body']['outputDimensionality'] == _column_dimensions()


def test_returns_a_unit_vector():
    """Truncated Gemini embeddings arrive unnormalized; cosine search wants unit
    vectors, so the adapter normalizes before returning."""
    values = [3.0, 4.0] + [0.0] * 766
    vec = embed.embed("boiled egg", api_key="k", model="m",
                      opener=_fake_opener({"embedding": {"values": values}}))
    assert abs(sum(v * v for v in vec) ** 0.5 - 1.0) < 1e-9
    assert abs(vec[0] - 0.6) < 1e-9   # 3 / hypot(3, 4)


def test_all_zero_vector_survives_normalization():
    vec = embed.embed("", api_key="k", model="m",
                      opener=_fake_opener({"embedding": {"values": [0.0] * 768}}))
    assert vec == [0.0] * 768


def test_configured_model_is_one_the_api_still_serves():
    """text-embedding-004 was retired and returned 404 in production."""
    from django.conf import settings
    assert settings.GEMINI_EMBED_MODEL.startswith('gemini-embedding-')
