"""🛡️ REAL-IMAGE VALIDATOR — never let "NO IMAGE" / fake thumbnails into the DB.

`/warmup_thumbs` (and the `/api/thumb` probe) fetches thumb bytes from Telegram.
The mere presence of `thumbs[0].file_id` is not enough: Telegram sometimes returns
a generated placeholder ("NO IMAGE" card), a 1×1 pixel, a blank solid-colour frame
or an error body. That is why the reference warmup worker downloaded the bytes and
re-uploaded them with `send_photo` — Telegram only accepts a genuine image.

fsv1 takes that guarantee one step further: it validates the bytes **before**
uploading (magic bytes / real dimensions / minimum size / colour variance /
placeholder markers). Anything that fails is never saved as `TG_ID:` — it is
marked `NO_THUMB`, so a fake "no image" poster never appears on the web.

Pillow is in `requirements.txt`, but a pure-Python fallback runs when it is
unavailable (PNG/JPEG header parsing + PNG IDAT variance) — an import error
must never stop the thumbnail pipeline.
"""

import io
import logging
import zlib

logger = logging.getLogger(__name__)

# Telegram thumbnails are usually ≥ 90px; placeholders tend to be 1×1 or 16×16
DEFAULT_MIN_BYTES = 512
DEFAULT_MIN_DIM = 48
DEFAULT_MIN_STDDEV = 6.0

# Some bots embed these literal strings in a placeholder image (PNG tEXt chunk)
_PLACEHOLDER_MARKERS = (
    b"NO IMAGE", b"NO-IMAGE", b"NO_IMAGE", b"NO THUMB",
    b"NO THUMBNAIL", b"NO POSTER", b"NO_PREVIEW",
)

try:
    from PIL import Image, ImageStat
except Exception:                                    # pragma: no cover
    Image = ImageStat = None


def is_image_magic(data: bytes) -> bool:
    """JPEG / PNG / WEBP only — no SVG, HTML error page, JSON or GIF tracking pixel."""
    if not data or len(data) < 12:
        return False
    return (
        data.startswith(b"\xff\xd8\xff")
        or data.startswith(b"\x89PNG\r\n\x1a\n")
        or (data[:4] == b"RIFF" and data[8:12] == b"WEBP")
    )


def _png_dims(data):
    if len(data) >= 24 and data[12:16] == b"IHDR":
        return (int.from_bytes(data[16:20], "big"),
                int.from_bytes(data[20:24], "big"))
    return 0, 0


def _jpeg_dims(data):
    pos, end = 2, len(data)
    while pos + 9 < end:
        if data[pos] != 0xFF:
            pos += 1
            continue
        marker = data[pos + 1]
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            pos += 2
            continue
        length = int.from_bytes(data[pos + 2:pos + 4], "big")
        if length < 2:
            break
        # SOF0..SOF15 (C4/C8/CC are DHT/JPG/DAC, not frames)
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            return (int.from_bytes(data[pos + 7:pos + 9], "big"),
                    int.from_bytes(data[pos + 5:pos + 7], "big"))
        pos += 2 + length
    return 0, 0


def _webp_dims(data):
    chunk = data[12:16]
    if chunk == b"VP8X" and len(data) >= 30:
        return (int.from_bytes(data[24:27], "little") + 1,
                int.from_bytes(data[27:30], "little") + 1)
    if chunk == b"VP8 " and len(data) >= 30:
        return (int.from_bytes(data[26:28], "little") & 0x3FFF,
                int.from_bytes(data[28:30], "little") & 0x3FFF)
    if chunk == b"VP8L" and len(data) >= 25:
        bits = int.from_bytes(data[21:25], "little")
        return ((bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1)
    return 0, 0


def image_dimensions(data: bytes):
    """(w, h) — from Pillow when available, otherwise header parsing (fail-soft)."""
    if not is_image_magic(data):
        return 0, 0
    if Image is not None:
        try:
            with Image.open(io.BytesIO(data)) as img:
                return int(img.size[0]), int(img.size[1])
        except Exception:
            pass
    if data.startswith(b"\x89PNG"):
        return _png_dims(data)
    if data[:4] == b"RIFF":
        return _webp_dims(data)
    return _jpeg_dims(data)


def _png_pixel_stddev(data: bytes):
    """Per-channel stddev of PNG pixels in pure Python, when Pillow is missing.

    ⚠️ Even a solid-colour image has raw scanline bytes `0, r,g,b, r,g,b…`,
    so byte variance over the whole buffer cannot detect a blank placeholder.
    Channel-wise variance gives ≈ 0 for a flat image and ≫ 0 for a real frame.
    """
    if not data.startswith(b"\x89PNG") or len(data) < 33:
        return None
    w = int.from_bytes(data[16:20], "big")
    h = int.from_bytes(data[20:24], "big")
    depth, color = data[24], data[25]
    if depth != 8 or color not in (2, 6) or not (0 < w <= 8192 and 0 < h <= 8192):
        return None                       # palette / 16-bit → leave it to Pillow
    bpp = 3 if color == 2 else 4
    stride = w * bpp
    compressed, pos = bytearray(), 8
    while pos + 8 <= len(data):
        length = int.from_bytes(data[pos:pos + 4], "big")
        typ = data[pos + 4:pos + 8]
        if typ == b"IDAT":
            compressed.extend(data[pos + 8:pos + 8 + length])
        pos += 12 + length
        if typ == b"IEND":
            break
    try:
        raw = zlib.decompress(bytes(compressed))
    except Exception:
        return None
    # Undo PNG filter types 0–4, otherwise filtered delta bytes produce misleading
    # variance. On large images we sample only every k-th row so the pure-Python
    # loop does not get expensive when Pillow is unavailable.
    step = max(1, (w * h) // 400_000)
    pixels, prev, pos = bytearray(), bytearray(stride), 0
    for y in range(h):
        if pos + 1 + stride > len(raw):
            break
        ft = raw[pos]
        pos += 1
        line = bytearray(raw[pos:pos + stride])
        pos += stride
        if ft:
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                if ft == 1:
                    pred = a
                elif ft == 2:
                    pred = b
                elif ft == 3:
                    pred = (a + b) // 2
                elif ft == 4:
                    p = a + b - c
                    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                    pred = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                else:
                    pred = 0
                line[i] = (line[i] + pred) & 255
        prev = line
        if y % step == 0:
            pixels.extend(line)
    if len(pixels) < bpp * 8:
        return 0.0
    best = 0.0
    for channel in range(bpp):
        vals = pixels[channel::bpp]
        mean = sum(vals) / len(vals)
        var = sum((v - mean) ** 2 for v in vals) / len(vals)
        best = max(best, var ** 0.5)
    return best


def _stddev(data: bytes):
    """RGB channel stddev — a blank placeholder ≈ 0, a real video frame ≫ 0.

    Pillow (in `requirements.txt`) decodes every format. Without it PNG is
    checked in pure Python; for JPEG/WEBP the variance check is skipped and we
    rely on magic bytes + dimensions + min size + marker checks.
    """
    if Image is not None:
        try:
            with Image.open(io.BytesIO(data)) as img:
                img.load()
                return max(ImageStat.Stat(img.convert("RGB")).stddev)
        except Exception:
            return None
    if data.startswith(b"\x89PNG"):
        return _png_pixel_stddev(data)
    return None


def validate_thumb(data, *, min_bytes=DEFAULT_MIN_BYTES,
                   min_dim=DEFAULT_MIN_DIM, min_stddev=DEFAULT_MIN_STDDEV):
    """`(ok, info)` — info holds reason / width / height / stddev / bytes.

    `ok=False` ⇒ never write `TG_ID:` to the DB; mark the file `NO_THUMB` instead.
    """
    info = {"bytes": len(data or b""), "width": 0, "height": 0, "stddev": 0.0, "reason": ""}
    if not data or len(data) < min_bytes:
        info["reason"] = "too-small-or-empty"
        return False, info
    if not is_image_magic(data):
        info["reason"] = "not-a-real-image"
        return False, info

    head = data[:8192].upper()
    if any(marker in head for marker in _PLACEHOLDER_MARKERS):
        info["reason"] = "placeholder-marker"
        return False, info

    # structure check: Pillow's verify() catches truncated / corrupt JPEG-PNG data
    if Image is not None:
        try:
            with Image.open(io.BytesIO(data)) as img:
                if img.size[0] > 8192 or img.size[1] > 8192:
                    info["reason"] = "oversized"
                    return False, info
                img.verify()
        except Exception:
            info["reason"] = "corrupt-image"
            return False, info

    w, h = image_dimensions(data)
    info["width"], info["height"] = w, h
    if w < min_dim or h < min_dim or w > 8192 or h > 8192:
        info["reason"] = "tiny-or-invalid-dimensions"
        return False, info

    sd = _stddev(data)
    if sd is not None:
        info["stddev"] = round(float(sd), 2)
        if sd < min_stddev:
            info["reason"] = "blank-uniform-placeholder"
            return False, info

    info["reason"] = "ok"
    return True, info
