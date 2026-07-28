from django.apps import AppConfig


class MenuConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'menu'

    def ready(self):
        # Registers the deployment checks (menu/checks.py). Imported for the
        # @register side effect only.
        from . import checks  # noqa: F401
