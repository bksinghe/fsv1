"""🌐 Root / landing page + ▶ signed watch & download (HTTP Range) streaming."""

import asyncio
import logging
import math
import mimetypes
import secrets
from urllib.parse import quote, urlencode

from aiohttp import web

from info import ALLOW_UNSIGNED_LINKS
from utils import temp
from web.utils.custom_dl import TGCustomYield, chunk_size, offset_fix
from web.utils.media_info import get_media_info
from web.utils.render_template import media_watch
from web.web_assets import get_auth, page
from web.welcome_assets import GUEST_BODY_CLASS, landing_body
from stream_security import verify

logger = logging.getLogger(__name__)
routes = web.RouteTableDef()


# ======================================================
# 🏠 ROOT — send logged-in users straight to /search, everyone else to the landing page
# ======================================================
@routes.get("/", allow_head=True)
async def root_route_handler(request):
    role, _ = await get_auth(request)
    if role:
        return web.HTTPFound("/search")

    bot_username = temp.U_NAME or "AutoFilterBot"
    return page(
        "FAST FINDER — Web File Search",
        landing_body(bot_username),
        GUEST_BODY_CLASS,
    )


# ======================================================
# 🔐 SIGNED LINK CHECK
# ======================================================
def _signed_channel_id(request):
    raw = request.query.get("c")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _allowed(request, message_id: int) -> bool:
    e, s = request.query.get("e"), request.query.get("s")
    if "c" in request.query:
        channel_id = _signed_channel_id(request)
        if channel_id is not None and verify(message_id, e, s, chat_id=channel_id):
            return True
    elif verify(message_id, e, s):
        return True
    # Opt-in switch for old unsigned links (issued before this deployment).
    # Never let an unsigned URL choose an arbitrary Telegram chat.
    return ALLOW_UNSIGNED_LINKS and not e and not s and "c" not in request.query


def _signed_query(request) -> str:
    e, s = request.query.get("e"), request.query.get("s")
    if not e or not s:
        return ""
    params = {"e": e, "s": s}
    if "c" in request.query:
        params["c"] = request.query.get("c")
    return urlencode(params)


# ======================================================
# ▶️ WATCH PAGE (signed player)
# ======================================================
@routes.get("/watch/{message_id}")
async def watch_handler(request):
    try:
        message_id = int(request.match_info["message_id"])
    except ValueError:
        return web.Response(status=400, text="Invalid Message ID")
    if not _allowed(request, message_id):
        return web.Response(status=403, text="Link expired or invalid")

    try:
        return web.Response(
            text=await media_watch(
                message_id,
                query=_signed_query(request),
                poster=request.query.get("poster", ""),
                chat_id=_signed_channel_id(request),
            ),
            content_type="text/html",
            charset="utf-8",
        )
    except Exception as e:
        logger.error(f"Watch page error: {e}")
        return web.Response(status=500, text="Watch page unavailable")


# ======================================================
# 📐 RANGE PARSER (hardened)
# ======================================================
def parse_range(header, file_size):
    """(first, last, length, is_partial) or None (=416 unsatisfiable)."""
    partial = bool(header)
    try:
        if header:
            spec = header.replace("bytes=", "").split(",")[0].strip()
            a, b = spec.split("-", 1)
            if a == "":                                  # suffix range bytes=-N
                first, last = max(file_size - int(b), 0), file_size - 1
            else:
                first = int(a)
                last = int(b) if b else file_size - 1
        else:
            first, last = 0, file_size - 1
    except Exception:
        first, last, partial = 0, file_size - 1, False

    last = min(last, file_size - 1)
    if first < 0 or last < first or file_size <= 0:
        return None
    return first, last, last - first + 1, partial


# ======================================================
# 📥 DOWNLOAD / STREAM CORE
# ======================================================
@routes.get("/download/{message_id}", allow_head=True)
async def download_handler(request):
    try:
        message_id = int(request.match_info["message_id"])
    except ValueError:
        return web.Response(status=400, text="Invalid Message ID")
    if not _allowed(request, message_id):
        return web.Response(status=403, text="Link expired or invalid")
    return await media_download(request, message_id, chat_id=_signed_channel_id(request))


async def media_download(request, message_id: int, chat_id=None):
    # ── 1) SETUP (before the body starts, so errors can still return 4xx/5xx) ──
    try:
        info = await get_media_info(message_id, chat_id=chat_id)
        if not info:
            return web.Response(status=404, text="Media Not Found")

        file_size = int(info.file_size or 0)
        parsed = parse_range(request.headers.get("Range"), file_size)
        if parsed is None:
            return web.Response(
                status=416, text="416: Range Not Satisfiable",
                headers={"Content-Range": f"bytes */{file_size}"},
            )
        fb, ub, req_len, partial = parsed

        ncs = await chunk_size(req_len)
        offset = await offset_fix(fb, ncs)
        first_cut = fb - offset
        last_cut = (ub % ncs) + 1
        parts = math.ceil((req_len + first_cut) / ncs)

        is_video = info.is_video or str(info.mime_type or "").startswith("video/")
        file_name = info.file_name or (
            f"video_{secrets.token_hex(3)}.mp4" if is_video else f"file_{secrets.token_hex(3)}.bin"
        )
        mime = info.mime_type or mimetypes.guess_type(file_name)[0] or "application/octet-stream"
        enc_name = quote(str(file_name))

        headers = {
            "Content-Type": mime,
            "Content-Disposition": f"attachment; filename=\"{enc_name}\"; filename*=UTF-8''{enc_name}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(req_len),
        }
        if partial:
            headers["Content-Range"] = f"bytes {fb}-{ub}/{file_size}"
        status = 206 if partial else 200
    except Exception as e:
        logger.error(f"Stream setup error: {e}")
        return web.Response(status=500, text="Stream setup failed")

    resp = web.StreamResponse(status=status, headers=headers)
    if request.method == "HEAD":
        await resp.prepare(request)
        await resp.write_eof()
        return resp

    await resp.prepare(request)
    agen = TGCustomYield().yield_file(
        info.file_id_obj, offset, first_cut, last_cut, parts, ncs
    )
    try:
        async for chunk in agen:
            await resp.write(chunk)
        await resp.write_eof()
    except (ConnectionError, asyncio.CancelledError):
        pass                       # the viewer closed the tab or seeked — normal
    except Exception as e:
        logger.error(f"Stream error (mid-body): {e!r}")
        raise
    finally:
        try:
            await agen.aclose()
        except Exception:
            pass
    return resp
