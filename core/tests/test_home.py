import pytest

@pytest.mark.django_db
def test_home_renders_with_frontend_stack(client):
    resp = client.get("/en/")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "htmx.min.js" in body      # HTMX vendored
    assert "alpine.min.js" in body    # Alpine vendored
    assert "css/app.css" in body      # compiled Tailwind (standalone CLI build)
    assert "Gaamos" in body
