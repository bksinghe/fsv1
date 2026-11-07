"""🌐 Routes for the unified Catalog (Posts + Directory profiles).

In v5 this took a separate `post_routes.py` (publish/update/delete/photo/search/single)
and `actor_routes.py` (create/avatar/gallery/social/delete/search/profile) —
~18 endpoints in total, each with its own auth check and response format.

Here there is **one** generic JSON API:

| Method | Path | Purpose |
|---|---|---|
| GET | `/posts`, `/actors` | catalog pages (from the sidebar) |
| GET | `/post/{id}`, `/actor/{id}` | detail page |
| GET | `/api/catalog/{kind}` | list (`q`, `category`, `offset`, `limit`) or `?id=` single |
| POST | `/api/catalog/{kind}/save` | create + edit — **one endpoint** (admin) |
| POST | `/api/catalog/{kind}/delete` | delete (admin) |
| GET | `/api/catalog/{kind}/media` | **Actors only**: Library videos from **Search Tags** (`q` override, `offset`/`limit`) — v5 actor Linked Media. Posts return `source: disabled` (attached videos only) |
| POST | `/api/catalog/{kind}/gallery_upload` | Multiple photos/screenshots straight from the tab (admin, serial Telegram upload) |
| POST | `/api/catalog/{kind}/gallery_delete` | Remove one image without a reload (admin) |
| POST | `/api/catalog/upload` | image → Telegram → `TG_ID:` (admin) |
| GET | `/api/catalog/photo` | `TG_ID:` image bytes (the same serial-safe download engine) |

All writes are admin-only, every input is sanitized by `catalog.normalize()`, and no
server-generated HTML strings are returned (the client renders everything).
"""

import inspect
import io
import logging
import re
import sys as _sys
from urllib.parse import quote

from aiohttp import web

from utils import temp
from database.ia_filterdb import get_search_results
from database.runtime_config import runtime_config
from web.web_assets import get_auth, vcard_meta
from web.catalog import (
    CATALOGS,
    normalize,
    build_listing_page,
    build_detail_page,
)
from web.thumb_engine import get_image_bytes, image_content_type
from database.catalog_db import store

logger = logging.getLogger(__name__)
catalog_routes = web.RouteTableDef()

_MAX_UPLOAD = 5 * 1024 * 1024


def _json(data, status=200):
    return web.json_response(data, status=status)


def _kind(req):
    kind = req.match_info.get("kind", "")
    return kind if kind in CATALOGS else None


def _clean_id(value) -> str:
    """Ids are short hex-ish only — safe for both URLs and Mongo `_id`."""
    return re.sub(r"[^A-Za-z0-9_-]", "", str(value or ""))[:32]


def _media_row(doc: dict) -> dict:
    """🎴 Library doc → Videos tab card payload — the same shared `vcard_meta()`."""
    out = vcard_meta(doc)
    fid = out["file_id"]
    out["thumb"] = "/api/thumb?file_id=" + quote(fid, safe="") + "&v=1"
    out["watch"] = "/setup_stream?file_id=" + quote(fid, safe="") + "&mode=watch"
    return out


async def _file_details(fid: str):
    """Library doc of an attached video — falls back to `collection.find_one` when
    `get_file_details` is missing in a stub/demo (the page never breaks)."""
    ia = _sys.modules.get("database.ia_filterdb")
    if ia is None:
        return None
    try:
        fn = getattr(ia, "get_file_details", None)
        if fn is not None:
            res = fn(fid)
            return await res if inspect.isawaitable(res) else res
        col = getattr(ia, "collection", None)
        return col.find_one({"_id": fid}) if col is not None else None
    except Exception as exc:
        logger.debug("attached video meta skipped (%s): %s", fid, exc)
        return None


async def _enrich_attached_videos(item: dict):
    """📌 Give Post/Actor attached videos the same size/duration/quality/res/type
    chips as `/search` and tag-results — all from `vcard_meta()`."""
    for v in (item.get("videos") or [])[:50]:
        fid = str(v.get("file_id") or "")
        if not fid or str(v.get("quality") or ""):
            continue
        doc = await _file_details(fid)
        if not doc:
            continue
        meta = vcard_meta(doc)
        for key in ("size", "quality", "duration", "res", "type"):
            if meta.get(key):
                v[key] = meta[key]


async def _tag_media(item: dict, custom_q: str, offset: int, limit: int):
    """🏷️ v5's `get_actor_search_results(name|tags)` — Library videos from tags.

    v5 ran one raw regex-OR (`(tag1|tag2|...)`) and forgot the actor name.
    Here fsv1's **own** search pipeline (`$text` + regex fallback) runs for each
    term and the results are merged/deduped — the index is used, with no new query
    layer. Typing a custom `q` ignores tags (exactly like v5).
    """
    tags = [str(t).strip() for t in (item.get("tags") or []) if str(t).strip()][:12]
    custom = str(custom_q or "").strip()
    if custom:
        terms, source = [custom], "custom"
    elif tags:
        terms, source = tags, "tags"
    else:
        title = str(item.get("title") or "").strip()
        terms, source = ([title] if len(title) >= 2 else []), "title"
    terms = [t[:80] for t in terms if len(t) >= 2][:12]
    if not terms:
        return [], "", [], 0, source

    merged, seen = [], set()
    for term in terms:
        try:
            docs = (await get_search_results(term, 0, 60))[0] or []
        except Exception as e:
            logger.debug(f"tag media search skipped ({term!r}): {e}")
            docs = []
        for d in docs:
            fid = str(d.get("_id") or "")
            if fid and fid not in seen:
                seen.add(fid)
                merged.append(d)
    total = len(merged)
    page = merged[offset:offset + limit]
    nxt = str(offset + limit) if offset + limit < total else ""
    return page, nxt, terms, total, source


def _safe_item(kind, item):
    """Even a stale/raw DB document is returned in the sanitized schema."""
    clean = normalize(kind, item)
    clean.update({
        "id": item.get("id", ""),
        "created_at": item.get("created_at", 0),
        "updated_at": item.get("updated_at", 0),
    })
    return clean


# ─────────────────────────────────────────────────────────────
# 🖼️ Register the specific endpoints first (before /{kind}, which would swallow them)
# ─────────────────────────────────────────────────────────────
@catalog_routes.get("/api/catalog/photo")
async def api_photo(req):
    """`TG_ID:<file_id>` → image bytes, via the same throttle/FloodWait-safe engine."""
    role, _ = await get_auth(req)
    if not role:
        return web.Response(status=401)
    fid = (req.query.get("id") or "").strip()
    if not fid or len(fid) > 512:
        return web.Response(status=400)
    data = await get_image_bytes(fid)
    if not data:
        return web.Response(status=404, headers={"Cache-Control": "no-store"})
    return web.Response(
        body=data,
        content_type=image_content_type(data),
        headers={"Cache-Control": "public, max-age=86400"},
    )


@catalog_routes.post("/api/catalog/upload")
async def api_upload(req):
    """Cover/avatar upload → Telegram → permanent `TG_ID:` (like v5, without a reload).

    If the bot is not ready the client shows a clear error and offers a URL paste option.
    """
    role, _ = await get_auth(req)
    if role != "admin":
        return _json({"ok": False, "error": "Admins only"}, 403)
    try:
        data = await req.post()
        field = data.get("image")
        if not field or not hasattr(field, "file"):
            return _json({"ok": False, "error": "No image"}, 400)
        raw = field.file.read()
    except Exception as e:
        return _json({"ok": False, "error": f"Bad upload: {e}"}, 400)
    if not raw or len(raw) > _MAX_UPLOAD:
        return _json({"ok": False, "error": "Image is empty or larger than 5 MB"}, 400)

    bot = getattr(temp, "BOT", None)
    if bot is None:
        return _json({"ok": False, "error": "The bot is not ready yet — paste an image URL instead"}, 503)
    try:
        buf = io.BytesIO(raw)
        buf.name = "cover.jpg"
        msg = await bot.send_photo(chat_id=runtime_config.get("CATALOG_STORAGE_CHANNEL"), photo=buf)
        photo = getattr(msg, "photo", None)
        if not photo:
            raise RuntimeError("Telegram did not return a photo")
        sizes = getattr(photo, "sizes", None)
        fid = sizes[-1].file_id if sizes else photo.file_id
        if not fid:
            raise RuntimeError("No file_id returned")
        return _json({"ok": True, "value": f"TG_ID:{fid}"})
    except Exception as e:
        logger.warning(f"catalog upload failed: {e}")
        return _json({"ok": False, "error": str(e)[:120]}, 502)


# ─────────────────────────────────────────────────────────────
# 📄 Pages
# ─────────────────────────────────────────────────────────────
async def _listing(req, kind):
    role, tg_id = await get_auth(req)
    if not role:
        return web.HTTPFound("/login")
    return build_listing_page(kind, role, tg_id)


async def _detail(req, kind, item_id):
    role, tg_id = await get_auth(req)
    if not role:
        return web.HTTPFound("/login")
    item = await store.get_item(kind, _clean_id(item_id))
    if not item:
        return web.Response(text="❌ Entry not found", status=404)
    item = _safe_item(kind, item)
    await _enrich_attached_videos(item)   # 🎴 every video card gets the same chips
    return build_detail_page(kind, role, tg_id, item)


@catalog_routes.get("/posts")
async def posts_page(req):
    return await _listing(req, "posts")


@catalog_routes.get("/actors")
async def actors_page(req):
    return await _listing(req, "actors")


@catalog_routes.get("/post/{id}")
async def post_detail(req):
    return await _detail(req, "posts", req.match_info["id"])


@catalog_routes.get("/actor/{id}")
async def actor_detail(req):
    return await _detail(req, "actors", req.match_info["id"])


# ─────────────────────────────────────────────────────────────
# 🔌 Generic JSON API
# ─────────────────────────────────────────────────────────────
@catalog_routes.get("/api/catalog/{kind}")
async def api_list(req):
    role, _ = await get_auth(req)
    if not role:
        return _json({"error": "Login required", "login": "/login"}, 401)
    kind = _kind(req)
    if not kind:
        return _json({"error": "Unknown catalog"}, 404)

    # ?id= → a single item for deep-link editing
    single = _clean_id(req.query.get("id"))
    if single:
        item = await store.get_item(kind, single)
        return _json({
            "items": [_safe_item(kind, item)] if item else [],
            "total": 1 if item else 0,
            "has_next": False,
        })

    q = (req.query.get("q") or "").strip()
    category = (req.query.get("category") or "all").strip()
    try:
        offset = max(0, int(req.query.get("offset", "0")))
        limit = max(1, min(int(req.query.get("limit", "20")), 60))
    except ValueError:
        offset, limit = 0, 20

    items, has_next = await store.list_items(kind, q, category, offset, limit)
    total = await store.count(kind, q, category)
    return _json({
        "items": [_safe_item(kind, it) for it in items],
        "total": total,
        "has_next": has_next,
        "offset": offset,
        "limit": limit,
    })


async def _read_payload(req):
    try:
        return await req.json()
    except Exception:
        try:
            return dict(await req.post())
        except Exception:
            return {}


@catalog_routes.post("/api/catalog/{kind}/save")
async def api_save(req):
    """✨ Create + Edit in one endpoint (v5 had 2 wizards + 2 APIs)."""
    role, _ = await get_auth(req)
    if role != "admin":
        return _json({"ok": False, "error": "Admins only"}, 403)
    kind = _kind(req)
    if not kind:
        return _json({"ok": False, "error": "Unknown catalog"}, 404)

    payload = await _read_payload(req)
    clean = normalize(kind, payload)
    if not clean["title"]:
        return _json({"ok": False, "error": "A title is required"}, 400)
    item = await store.save_item(
        kind, clean, _clean_id(payload.get("id")),
        allow_create=bool(payload.get("restore")),
    )
    if not item:
        return _json({"ok": False, "error": "Entry not found"}, 404)
    return _json({"ok": True, "item": _safe_item(kind, item)})


@catalog_routes.get("/api/catalog/{kind}/media")
async def api_media(req):
    """🎬 Videos tab — Library videos from **Search Tags** (like v5's actor page).

    Passing `q=` runs that query (tags ignored); when empty it uses the item's tags,
    or the title when there are no tags. `offset` / `limit` provide pagination.
    """
    role, _ = await get_auth(req)
    if not role:
        return _json({"error": "Login required", "login": "/login"}, 401)
    kind = _kind(req)
    if not kind:
        return _json({"results": [], "terms": [], "total": 0}, 404)
    # 📝 Posts must not show search-text results — attached videos only.
    if not CATALOGS[kind].get("tagMedia"):
        return _json({"results": [], "terms": [], "total": 0,
                      "source": "disabled", "offset": 0, "next_offset": ""})
    item = await store.get_item(kind, _clean_id(req.query.get("id")))
    if not item:
        return _json({"results": [], "terms": [], "total": 0}, 404)
    try:
        offset = max(0, int(req.query.get("offset", "0")))
        limit = max(1, min(int(req.query.get("limit", "12")), 30))
    except ValueError:
        offset, limit = 0, 12
    page, nxt, terms, total, source = await _tag_media(
        item, req.query.get("q", ""), offset, limit
    )
    return _json({
        "results": [_media_row(d) for d in page],
        "terms": terms, "source": source, "total": total,
        "offset": offset, "next_offset": nxt,
    })


@catalog_routes.post("/api/catalog/{kind}/gallery_upload")
async def api_gallery_upload(req):
    """🖼️ Multiple photos straight from the Gallery/Screenshots tab (like v5, no reload).

    v5's `/api/actor/gallery_upload` submitted a form and reloaded the page; here a
    JSON response is rendered in place. Uploads go to Telegram **one at a time**
    (the same anti-flood behaviour as thumbnails); one failure does not stop the rest.
    """
    role, _ = await get_auth(req)
    if role != "admin":
        return _json({"ok": False, "error": "Admins only"}, 403)
    kind = _kind(req)
    if not kind:
        return _json({"ok": False, "error": "Unknown catalog"}, 404)
    try:
        data = await req.post()
        item_id = _clean_id(data.get("id"))
        parts = list(data.getall("image")) if hasattr(data, "getall") else [data.get("image")]
        blobs = []
        for f in parts:
            if f is None or not hasattr(f, "file"):
                continue
            raw = f.file.read()
            if raw and len(raw) <= _MAX_UPLOAD:
                blobs.append(raw)
    except Exception as e:
        return _json({"ok": False, "error": f"Bad upload: {e}"}, 400)
    if not item_id or not blobs:
        return _json({"ok": False, "error": "Missing id or images"}, 400)

    item = await store.get_item(kind, item_id)
    if not item:
        return _json({"ok": False, "error": "Entry not found"}, 404)
    bot = getattr(temp, "BOT", None)
    if bot is None:
        return _json({"ok": False, "error": "The bot is not ready yet"}, 503)

    added = []
    for i, raw in enumerate(blobs[:12], 1):
        try:
            buf = io.BytesIO(raw)
            buf.name = f"gallery_{item_id}_{i}.jpg"
            msg = await bot.send_photo(chat_id=runtime_config.get("CATALOG_STORAGE_CHANNEL"), photo=buf)
            photo = getattr(msg, "photo", None)
            sizes = getattr(photo, "sizes", None) if photo else None
            fid = sizes[-1].file_id if sizes else getattr(photo, "file_id", "")
            if not fid:
                raise RuntimeError("No file_id returned")
            added.append("TG_ID:" + fid)
        except Exception as e:
            logger.warning(f"gallery upload {i}/{len(blobs)} failed: {e}")
            continue
    if not added:
        return _json({"ok": False, "error": "No images were saved to Telegram"}, 502)

    clean = normalize(kind, item)
    clean["gallery"] = (list(item.get("gallery") or []) + added)[:12]
    updated = await store.save_item(kind, clean, item_id)
    return _json({"ok": True, "added": added, "item": _safe_item(kind, updated)})


@catalog_routes.post("/api/catalog/{kind}/gallery_delete")
async def api_gallery_delete(req):
    """🖼️ Remove one image from the detail Gallery tab without a page reload (admin).

    v5 called `window.location.reload()` after `/api/actor/gallery_delete`;
    here only the gallery array is updated and the client removes the card from the DOM.
    """
    role, _ = await get_auth(req)
    if role != "admin":
        return _json({"ok": False, "error": "Admins only"}, 403)
    kind = _kind(req)
    if not kind:
        return _json({"ok": False, "error": "Unknown catalog"}, 404)
    payload = await _read_payload(req)
    item_id = _clean_id(payload.get("id"))
    try:
        idx = int(payload.get("index"))
    except (TypeError, ValueError):
        return _json({"ok": False, "error": "Bad index"}, 400)
    item = await store.get_item(kind, item_id)
    if not item:
        return _json({"ok": False, "error": "Entry not found"}, 404)
    gallery = list(item.get("gallery") or [])
    if idx < 0 or idx >= len(gallery):
        return _json({"ok": False, "error": "Index out of range"}, 400)
    gallery.pop(idx)
    clean = normalize(kind, item)
    clean["gallery"] = gallery
    updated = await store.save_item(kind, clean, item_id)
    return _json({"ok": True, "item": _safe_item(kind, updated)})


@catalog_routes.post("/api/catalog/{kind}/delete")
async def api_delete(req):
    role, _ = await get_auth(req)
    if role != "admin":
        return _json({"ok": False, "error": "Admins only"}, 403)
    kind = _kind(req)
    if not kind:
        return _json({"ok": False, "error": "Unknown catalog"}, 404)
    payload = await _read_payload(req)
    item_id = _clean_id(payload.get("id"))
    if not item_id:
        return _json({"ok": False, "error": "Missing id"}, 400)
    return _json({"ok": await store.delete_item(kind, item_id)})
