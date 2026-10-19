"""Shared helper: downscale + JPEG-compress a tile image before base64 encoding for any vision API."""
import base64
import io

try:
    from PIL import Image
except ImportError:
    Image = None

MAX_DIM = 512
JPEG_QUALITY = 80


def tif_to_data_url(path, max_dim=MAX_DIM, quality=JPEG_QUALITY):
    if Image is None:
        return ""
    im = Image.open(path).convert("RGB")
    im.thumbnail((max_dim, max_dim))
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=quality)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{b64}"
