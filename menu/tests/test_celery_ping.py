def test_ping_task_body_runs_directly():
    from menu.tasks import ping
    assert ping() == "pong"


def test_celery_app_importable():
    from config import celery_app
    assert celery_app.main == "gaamos"
