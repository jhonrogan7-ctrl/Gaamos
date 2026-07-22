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
