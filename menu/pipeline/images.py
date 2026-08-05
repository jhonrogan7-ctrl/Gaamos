from pathlib import Path

from PIL import Image


def to_thumbnail(src_path, dest_path, size=800):
    """Normalise any image to an RGB webp thumbnail (longest side <= size)."""
    with Image.open(src_path) as im:
        im = im.convert("RGB")
        im.thumbnail((size, size))
        Path(dest_path).parent.mkdir(parents=True, exist_ok=True)
        im.save(dest_path, "WEBP", quality=82, method=6)
    return dest_path


def to_webp(raw_bytes, size=800):
    """Raw generator bytes -> a thumbnailed webp, without touching MEDIA_ROOT.

    Lifted out of `generate_item_images` so the build worker can reuse it. The
    command kept it private, and a Celery task cannot import a management
    command's module-level helper without dragging the whole command in.
    """
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / 'raw'
        dest = Path(tmp) / 'out.webp'
        src.write_bytes(raw_bytes)
        to_thumbnail(str(src), str(dest), size)
        return dest.read_bytes()
