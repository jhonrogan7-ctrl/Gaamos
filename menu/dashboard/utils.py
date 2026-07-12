import os
import qrcode
from qrcode.constants import ERROR_CORRECT_M
from PIL import Image, ImageDraw, ImageFont
from django.conf import settings

COMPANY_NAME = "Twenty Two Tech Company"


def render_qr_png(url, caption):
    """Render a plain captioned QR as PNG bytes (no disk write). No embedded
    logo: per-tenant QR branding arrives with Phase 4; the donor logo must not
    appear on tenant codes. Level M suffices without a centre overlay."""
    import io
    qr = qrcode.QRCode(
        version=None,
        error_correction=ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#1a1a2e", back_color="white").convert("RGB")

    # Caption centred below the QR.
    qr_w, qr_h = img.size
    font_size = max(20, qr_w // 22)
    try:
        font = ImageFont.load_default(size=font_size)
    except TypeError:                                    # very old Pillow
        font = ImageFont.load_default()
    pad = int(font_size * 0.9)                            # breathing room above/below text
    measure = ImageDraw.Draw(img)
    bbox = measure.textbbox((0, 0), caption, font=font)
    text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    canvas = Image.new("RGB", (qr_w, qr_h + text_h + pad * 2), "white")
    canvas.paste(img, (0, 0))
    draw = ImageDraw.Draw(canvas)
    draw.text(
        ((qr_w - text_w) // 2 - bbox[0], qr_h + pad - bbox[1]),
        caption, fill="#1a1a2e", font=font,
    )

    out = io.BytesIO()
    canvas.save(out, format='PNG')
    return out.getvalue()


def request_base_url(request):
    """Scheme + host the operator is on, e.g. https://testco.localhost:8005.
    The tenant is resolved from this host, so a QR encoded with it round-trips
    back to the same company's menu. (Phase 4 custom domains may add a canonical
    override; until then, mirror the operator's host.)"""
    return f"{request.scheme}://{request.get_host()}"


def general_qr_url(base_url, branch):
    return f"{base_url}/?branch={branch.slug}"


def generate_qr_for_branch(branch, base_url):
    url = general_qr_url(base_url, branch)
    png = render_qr_png(url, COMPANY_NAME)
    dest_dir = os.path.join(settings.MEDIA_ROOT, 'qr')
    os.makedirs(dest_dir, exist_ok=True)
    filename = f"branch_{branch.slug}.png"
    path = os.path.join(dest_dir, filename)
    with open(path, 'wb') as f:
        f.write(png)

    branch.qr_image = f"qr/{filename}"
    branch.save(update_fields=['qr_image'])
    return path


def table_qr_url(base_url, branch, table):
    return f"{base_url}/?branch={branch.slug}&t={table.code}"


def render_table_qr_pdf(base_url, branch, tables):
    """One PDF page per table QR. Rendered on demand; nothing is stored."""
    import io
    pages = []
    for t in tables:
        png = render_qr_png(table_qr_url(base_url, branch, t), f"{branch.name} — {t.label}")
        pages.append(Image.open(io.BytesIO(png)).convert('RGB'))
    out = io.BytesIO()
    if pages:
        pages[0].save(out, format='PDF', save_all=True, append_images=pages[1:])
    return out.getvalue()


def generate_qr_pdf(branch):
    from PIL import Image
    import io
    qr_path = os.path.join(settings.MEDIA_ROOT, branch.qr_image)
    img = Image.open(qr_path).convert('RGB')
    pdf_bytes = io.BytesIO()
    img.save(pdf_bytes, format='PDF')
    return pdf_bytes.getvalue()
