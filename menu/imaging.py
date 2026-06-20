"""Content-aware focal-point detection (Pillow-only, no extra deps).

We never re-crop or re-encode the original image. Instead we compute a focal
point — the (x, y) percentage that should stay visible — and store it on the
MenuItem. The templates feed it to CSS `background-position`, so a tall glass of
juice or a wide plate keeps its main subject in frame instead of always cropping
to dead center.

The heuristic: food is usually the most colourful, high-detail region of the
photo, sitting on a neutral plate/table. So we weight edge energy (detail) by
colour saturation and take the weighted centroid. It is intentionally simple and
fast (operates on a ~256px downscale); when anything goes wrong it falls back to
the center, which is exactly today's behaviour.
"""

from PIL import Image, ImageFilter

# Clamp the result so the subject never hugs the very edge of the frame, which
# would crop awkwardly at narrow aspect ratios.
_MIN, _MAX = 15, 85
_CENTER = (50, 50)


def compute_focal_point(path, sample=256):
    """Return (focal_x, focal_y) as ints 0–100. Falls back to (50, 50)."""
    try:
        with Image.open(path) as im:
            im = im.convert('RGB')
            im.thumbnail((sample, sample))
            w, h = im.size
            if w < 2 or h < 2:
                return _CENTER

            # Detail map: edges on the greyscale image.
            edges = im.convert('L').filter(ImageFilter.FIND_EDGES)
            edge_px = edges.load()

            # Saturation map: how colourful each pixel is (HSV S channel).
            sat = im.convert('HSV').split()[1]
            sat_px = sat.load()

            sum_w = sum_x = sum_y = 0.0
            for y in range(h):
                for x in range(w):
                    # weight = detail * (colourfulness boosted so neutral
                    # plates/tables contribute little). +20 keeps a small floor
                    # so a pure-edge mono subject still registers.
                    weight = edge_px[x, y] * (sat_px[x, y] + 20)
                    if weight:
                        sum_w += weight
                        sum_x += weight * x
                        sum_y += weight * y

            if sum_w <= 0:
                return _CENTER

            fx = round(sum_x / sum_w / (w - 1) * 100)
            fy = round(sum_y / sum_w / (h - 1) * 100)
            fx = max(_MIN, min(_MAX, fx))
            fy = max(_MIN, min(_MAX, fy))
            return fx, fy
    except Exception:
        return _CENTER
