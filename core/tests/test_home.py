import pytest

@pytest.mark.django_db
def test_home_renders_with_frontend_stack(client):
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "htmx.min.js" in body      # HTMX vendored
    assert "alpine.min.js" in body    # Alpine vendored
    assert "cdn.tailwindcss.com" in body  # Tailwind Play CDN (dev)
    assert "Gaamos" in body
