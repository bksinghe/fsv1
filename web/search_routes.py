"""🔍 Web file search + 📸 real thumbnails + ▶ signed streaming links.

After login, `/search` provides:
  * `/api/search`  → DB (text + regex) search, including "Recently Added"
  * `/api/thumb`   → real Telegram thumbnails (cache + backfill)
  * `/api/stream`  → cached media in BIN_CHANNEL → signed /watch + /download links
"""

import html
import logging
import time
from urllib.parse import quote

from aiohttp import web

from info import WEB_STREAM_TTL, THUMB_BROWSER_CACHE
from utils import temp, get_size
from database.ia_filterdb import (
    get_search_results,
    get_recent_files,
    get_file_details,
)
from database.runtime_config import runtime_config
from database.group_db import duration_seconds
from web.group_routes import group_cards, filter_group_cards
from stream_security import sign_params
from web.web_assets import get_auth, search_page, vcard_meta
from web.thumb_engine import get_thumb, image_content_type, thumb_version, thumb_state

logger = logging.getLogger(__name__)
search_routes = web.RouteTableDef()

# (BIN_CHANNEL, file_id) -> (message_id, expiry). A channel change gets a fresh
# message while repeat clicks within the same channel reuse its cached message.
_STREAM_CACHE = {}

# ── Group / UnGroup filter ─────────────────────────────────────────
# Groups are now **permanent** (`database/group_db.py`): group_id/num,
# members, auto_keys and excluded live in the DB. The title key also comes from
# that one module, so the search filter, scan-all and new-quality auto-join all
# follow the same rule. Cap the Group/UnGroup page to this many docs on large DBs.
_GROUP_SCAN_LIMIT = 500


async def _group_page(q: str, offset: int, limit: int, mode: str):
    """Group / UnGroup — pages are **cards**, membership covers the whole query set.

    Reads only lightweight metadata such as file_name/_id/quality — no image
    bytes and no server-side thumbnail/RAM cache. `group_cards()` loads every
    member of saved groups from the DB, even when it is outside the scan.
    """
    if q:
        scan, _, _ = await get_search_results(q, 0, _GROUP_SCAN_LIMIT)
    else:
        scan, _, _ = await get_recent_files(0, _GROUP_SCAN_LIMIT)
    cards = await group_cards([_result(d) for d in scan], normalize=_result)
    # A permanent group can contain files with different names → filter using the
    # prepared group/single cards rather than a title count.
    matched = filter_group_cards(cards, mode)
    total = len(matched)
    page = matched[offset:offset + limit]
    next_offset = str(offset + limit) if offset + limit < total else ""
    return page, next_offset, total


def _thumb_url(doc) -> str:
    fid = str(doc.get("_id") or "")
    # Like v5, hash the whole thumb_url ("TG_ID:...") — changing the id changes the URL
    thumb_ref = str(doc.get("thumb_url") or doc.get("thumb_file_id") or "")
    v = thumb_version(fid, thumb_ref)
    return f"/api/thumb?file_id={quote(fid, safe='')}&v={v}"


def _result(doc) -> dict:
    """🎴 card payload = shared `vcard_meta()` + this page's extra fields."""
    out = vcard_meta(doc)
    out["thumb"] = _thumb_url(doc)
    out["caption"] = str(doc.get("caption") or "")[:300]
    out["duration_seconds"] = duration_seconds(doc)
    return out


def _unauthorized():
    return web.json_response(
        {"error": "Login required", "login": "/login"}, status=401
    )


# ───────────────────────── PAGES ─────────────────────────
@search_routes.get("/search")
async def search_page_handler(req):
    role, tg_id = await get_auth(req)
    if not role:
        return web.HTTPFound("/login")
    return search_page(tg_id, role)


# ─────────────────────── SEARCH API ───────────────────────
@search_routes.get("/api/search")
async def api_search(req):
    role, tg_id = await get_auth(req)
    if not role:
        return _unauthorized()

    q = (req.query.get("q") or "").strip()
    try:
        offset = max(0, int(req.query.get("offset", "0")))
    except ValueError:
        offset = 0
    max_web_results = runtime_config.get("MAX_WEB_RESULTS")
    try:
        limit = max(1, min(int(req.query.get("limit", max_web_results)), max_web_results))
    except ValueError:
        limit = max_web_results

    group_mode = (req.query.get("group") or "all").strip().lower()
    if group_mode not in ("all", "group", "ungroup"):
        group_mode = "all"
    try:
        if group_mode != "all":
            # Already grouped cards (offset = card index)
            results, next_offset, total = await _group_page(q, offset, limit, group_mode)
        else:
            if q:
                docs, next_offset, total = await get_search_results(q, offset, limit)
            else:
                docs, next_offset, total = await get_recent_files(offset, limit)
            # 🎴 Permanent groups + same-title buckets → group-first cards.
            # Every member of a saved group comes from the DB; offset stays raw-file based.
            results = await group_cards([_result(d) for d in docs], normalize=_result)
    except Exception as e:
        logger.error(f"Web search failed (q={q!r}, group={group_mode}): {e}")
        return web.json_response({"error": "Search temporarily unavailable"}, status=500)

    return web.json_response({
        "results": results,
        "total": total,
        "next_offset": next_offset,
        "query": q,
        "group": group_mode,
        "is_admin": role == "admin",
    })


# ─────────────────────── THUMBNAIL API ───────────────────────
@search_routes.get("/api/thumb")
async def api_thumb(req):
    role, _ = await get_auth(req)
    if not role:
        return web.Response(status=401)

    fid = req.query.get("file_id", "")
    if not fid:
        return web.Response(status=400)
    retry = req.query.get("retry", "false").lower() == "true"

    # 🧠 Browser cache: there is no RAM/DB cache on the server. The poster lives
    # in the browser's own memory/disk cache; changing `v` changes the ETag.
    etag = f'"{req.query.get("v") or thumb_version(fid)}"'
    cache_headers = {
        "Cache-Control": f"private, max-age={THUMB_BROWSER_CACHE}",
        "ETag": etag,
    }
    if req.headers.get("If-None-Match") == etag and not retry:
        return web.Response(status=304, headers=cache_headers)

    data = await get_thumb(fid, retry=retry)
    if not data:
        # 🆕 v5-style serial warmup: a first-time id is being fetched (one at a time).
        # Do not cache the 404 — the browser should know to retry shortly.
        state = await thumb_state(fid)
        headers = {"Cache-Control": "no-store", "X-Thumb-State": state}
        if state in ("queued", "missing"):
            headers["Retry-After"] = "2"
        return web.Response(status=404, headers=headers)

    return web.Response(
        body=data,
        content_type=image_content_type(data),
        headers={
            "Content-Disposition": 'inline; filename="poster.jpg"',
            **cache_headers,
        },
    )


# ──────────────────── STREAM LINK PIPELINE ────────────────────
def _prune_stream_cache():
    if len(_STREAM_CACHE) <= 500:
        return
    now = time.time()
    for k in [k for k, v in _STREAM_CACHE.items() if v[1] <= now]:
        _STREAM_CACHE.pop(k, None)
    while len(_STREAM_CACHE) > 500:
        _STREAM_CACHE.pop(next(iter(_STREAM_CACHE)), None)


async def _tunnel_stream(fid: str, doc: dict) -> dict:
    """Send the file to the active BIN channel and build signed stream URLs."""
    now = time.time()
    bin_channel = runtime_config.get("BIN_CHANNEL")
    cache_key = (bin_channel, fid)
    hit = _STREAM_CACHE.get(cache_key)
    if hit and hit[1] > now + 60:
        msg_id, expiry = hit
    else:
        bot = getattr(temp, "BOT", None)
        if bot is None:
            raise RuntimeError("Bot is still starting, please retry in a moment")
        msg = await bot.send_cached_media(chat_id=bin_channel, file_id=fid)
        msg_id = int(msg.id)
        expiry = now + WEB_STREAM_TTL
        _STREAM_CACHE[cache_key] = (msg_id, expiry)
        _prune_stream_cache()

    ttl = max(60, int(expiry - now))
    signed = sign_params(msg_id, ttl, chat_id=bin_channel)
    poster = _thumb_url(doc)
    watch = f"/watch/{msg_id}?{signed}&poster={quote(poster, safe='')}"
    download = f"/download/{msg_id}?{signed}"
    return {
        "file_id": fid,
        "name": str(doc.get("file_name") or "Untitled"),
        "watch": watch,
        "download": download,
        "stream": download,          # this is the Range-enabled URL for <video src>
        "poster": poster,
        "expires_in": ttl,
    }


@search_routes.post("/api/stream")
async def api_stream(req):
    role, _ = await get_auth(req)
    if not role:
        return _unauthorized()
    try:
        data = await req.json()
    except Exception:
        data = dict(req.query)
    fid = str(data.get("file_id") or "").strip()
    if not fid:
        return web.json_response({"error": "Missing file_id"}, status=400)

    doc = await get_file_details(fid)
    if not doc:
        return web.json_response({"error": "File not found in database"}, status=404)

    try:
        return web.json_response(await _tunnel_stream(fid, doc))
    except Exception as e:
        logger.error(f"Stream setup failed for {fid[:16]}: {e}")
        return web.json_response(
            {"error": "Could not create a stream link. Please try again shortly."},
            status=503,
        )


@search_routes.get("/setup_stream")
async def setup_stream(req):
    """/setup_stream?file_id=... — GET shortcut (v5-style shareable links)."""
    role, _ = await get_auth(req)
    if not role:
        return web.HTTPFound("/login")
    fid = str(req.query.get("file_id") or "").strip()
    doc = await get_file_details(fid) if fid else None
    if not doc:
        return web.Response(text="❌ File not found", status=404)
    try:
        urls = await _tunnel_stream(fid, doc)
    except Exception as e:
        return web.Response(text=f"❌ {html.escape(str(e))}", status=503)
    target = urls["download"] if req.query.get("mode") == "download" else urls["watch"]
    return web.HTTPFound(target)
