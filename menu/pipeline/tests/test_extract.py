import io
import json

from menu.pipeline import extract

captured = {}


def _fake_opener(payload):
    def opener(req, timeout=None):
        captured['url'] = req.full_url
        captured['body'] = json.loads(req.data.decode())
        # Gemini returns the JSON as text inside candidates[0].content.parts[0].text
        return io.BytesIO(json.dumps(payload).encode())
    return opener


def test_extract_menu_parses_gemini_json():
    menu = {"categories": [
        {"name": "Hot Drinks", "items": [
            {"name": "Black Tea", "description": "hot milk tea", "price": 50}]}]}
    gemini_resp = {"candidates": [
        {"content": {"parts": [{"text": json.dumps(menu)}]}}]}
    out = extract.extract_menu(b"PDFBYTES", "application/pdf",
                               api_key="k", model="gemini-2.5-flash",
                               opener=_fake_opener(gemini_resp))
    assert out == menu
    assert "gemini-2.5-flash:generateContent" in captured['url']
    # the document is sent inline with its mime type
    parts = captured['body']['contents'][0]['parts']
    assert any(p.get('inline_data', {}).get('mime_type') == 'application/pdf' for p in parts)
    # structured-output config requested
    assert captured['body']['generationConfig']['responseMimeType'] == 'application/json'
