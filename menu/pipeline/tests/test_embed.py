import io
import json

from menu.pipeline import embed


def _fake_opener(payload):
    def opener(req, timeout=None):
        captured['url'] = req.full_url
        captured['body'] = json.loads(req.data.decode())
        return io.BytesIO(json.dumps(payload).encode())
    return opener


captured = {}


def test_embed_returns_vector_and_calls_embedcontent():
    payload = {"embedding": {"values": [0.5] * 768}}
    vec = embed.embed("boiled egg", api_key="k", model="text-embedding-004",
                      opener=_fake_opener(payload))
    assert vec == [0.5] * 768
    assert "text-embedding-004:embedContent" in captured['url']
    assert captured['body']['content']['parts'][0]['text'] == "boiled egg"
