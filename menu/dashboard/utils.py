import os
import qrcode
from qrcode.constants import ERROR_CORRECT_H
from PIL import Image, ImageDraw, ImageFont
from django.conf import settings

COMPANY_NAME = "Twenty Two Tech Company"


def generate_qr_for_branch(branch):
    # NOTE: In multi-tenant Gaamos the QR URL will be subdomain-rooted, e.g.
    # https://<company-slug>.gaamos.com/?branch=<branch-slug>. For now we keep
    # the same URL shape as the donor while Phase 4 (custom domains) lands.
    url = f"https://thejuicerycafe.cafe/?branch={branch.slug}"
    # High error correction (~30%) so the centred logo doesn't break scanning.
    qr = qrcode.QRCode(
        version=None,
        error_correction=ERROR_CORRECT_H,
        box_size=10,
        border=4,
    )
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#1a1a2e", back_color="white").convert("RGB")

    # Embed the Juicery logo in the centre, on a white pad for contrast.
    logo_path = os.path.join(settings.BASE_DIR, 'static', 'images', 'juicery_logo.png')
    if os.path.exists(logo_path):
        logo = Image.open(logo_path).convert("RGBA")
        qr_w, qr_h = img.size
        box_size = int(qr_w * 0.32)                      # white square footprint (kept)
        pad = max(4, int(box_size * 0.05))               # thin white margin
        logo_target = box_size - pad * 2                 # logo fills the square
        logo.thumbnail((logo_target, logo_target), Image.LANCZOS)
        lw, lh = logo.size
        box = Image.new("RGB", (box_size, box_size), "white")
        box.paste(logo, ((box_size - lw) // 2, (box_size - lh) // 2), logo)
        img.paste(box, ((qr_w - box_size) // 2, (qr_h - box_size) // 2))

    # Caption the company name centred below the QR.
    qr_w, qr_h = img.size
    font_size = max(20, qr_w // 22)
    try:
        font = ImageFont.load_default(size=font_size)
    except TypeError:                                    # very old Pillow
        font = ImageFont.load_default()
    pad = int(font_size * 0.9)                            # breathing room above/below text
    measure = ImageDraw.Draw(img)
    bbox = measure.textbbox((0, 0), COMPANY_NAME, font=font)
    text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    canvas = Image.new("RGB", (qr_w, qr_h + text_h + pad * 2), "white")
    canvas.paste(img, (0, 0))
    draw = ImageDraw.Draw(canvas)
    draw.text(
        ((qr_w - text_w) // 2 - bbox[0], qr_h + pad - bbox[1]),
        COMPANY_NAME, fill="#1a1a2e", font=font,
    )
    img = canvas

    dest_dir = os.path.join(settings.MEDIA_ROOT, 'qr')
    os.makedirs(dest_dir, exist_ok=True)
    filename = f"branch_{branch.slug}.png"
    path = os.path.join(dest_dir, filename)
    img.save(path)

    branch.qr_image = f"qr/{filename}"
    branch.save(update_fields=['qr_image'])
    return path


def generate_qr_pdf(branch):
    from PIL import Image
    import io
    qr_path = os.path.join(settings.MEDIA_ROOT, branch.qr_image)
    img = Image.open(qr_path).convert('RGB')
    pdf_bytes = io.BytesIO()
    img.save(pdf_bytes, format='PDF')
    return pdf_bytes.getvalue()
