from pathlib import Path

from django.conf import settings


def asset_version(request):
    """Cache-buster for the built stylesheet.

    `app.css` keeps a stable URL across rebuilds (WhiteNoise CompressedStaticFilesStorage
    does not hash filenames), so without a version query a browser holding an older cached
    `app.css` renders pages unstyled. The file's mtime changes on every CSS rebuild and on
    every image build (collectstatic), so it busts dev and prod caches alike.
    """
    css = Path(settings.BASE_DIR) / "static" / "css" / "app.css"
    try:
        version = int(css.stat().st_mtime)
    except OSError:
        version = "dev"
    return {"asset_v": version}
