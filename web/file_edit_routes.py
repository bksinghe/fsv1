"""✏️ Web **File Editor** — fsv1's take on `JoneySin/v5`'s "Edit Title Metadata".

v5's `/api/edit_name` + `/api/upload_thumb` + `/api/delete` made these editable:

* `file_name` — the title
* `caption` — Search Tags (feeds the text index)
* `target_collection` — v5's 3 separate collections (absent in fsv1, so not ported)
* Poster thumbnail — 16:9 crop via Cropper.js → Telegram storage channel → `TG_ID:`
* Delete file

fsv1 has a single MongoDB collection and no primary/cloud/archive `section`
concept, so this is **not a verbatim copy** — v5's collection-move control is not
ported. The editor does show the file's permanent group ID and lets an admin move
it to another existing group (or ungroup it):

* no `section` field, no collection-move dropdown, no `/api/search?section=`.
* Cropper.js CDN → a **fully dependency-free** built-in 16:9 canvas crop (in the UI).
* Uploads go to `CATALOG_STORAGE_CHANNEL`; bytes never enter the DB/RAM — only a `TG_ID:`
  string, and `thumb_version()` hashes it to bust the browser cache.
* Extra fsv1 chips are editable too: `quality`, `duration`, `width`×`height`.
* No `window.location.reload()` — the card updates in place from the JSON response.

Every endpoint is **admin-only** and each `$set` key passes through a whitelist.
"""

import io
import logging
import re
from urllib.parse import quote

from aiohttp import web

from utils import temp, get_size
from database.runtime_config import runtime_config
from database import ia_filterdb as ia
from database.group_db import (
    store as group_store, title_key, series_key, normal_kind, KIND_EPISODES,
)
from web.web_assets import get_auth, vcard_is_video
from web.thumb_engine import thumb_version, invalidate_thumb, enqueue_probe

logger = logging.getLogger(__name__)
file_edit_routes = web.RouteTableDef()

_MAX_UPLOAD = 5 * 1024 * 1024
_QUALITY_RE = re.compile(r"^[A-Za-z0-9 +.\-]{0,16}$")
_RES_RE = re.compile(r"^(\d{1,5})[x×](\d{1,5})$", re.I)


def _json(data, status=200):
    return web.json_response(data, status=status)


def _clean(value, limit=300) -> str:
    """Strip control chars / NUL — safe for both UI `textContent` and the DB."""
    text = str(value or "").strip()
    text = "".join(c for c in text if c in "\n\t" or ord(c) >= 32)
    return text[:limit]


def _fmt_duration(seconds) -> str:
    try:
        s = int(seconds or 0)
    except (TypeError, ValueError):
        return ""
    if s <= 0:
        return ""
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def _parse_duration(value):
    """`1:36:22`, `14:48`, `600` (seconds) → int; invalid input → None."""
    t = str(value or "").strip()
    if not t:
        return 0
    if t.isdigit():
        return min(int(t), 10_000_000)
    parts = t.replace("：", ":").split(":")
    if len(parts) not in (2, 3) or any(not p.strip().isdigit() for p in parts):
        return None
    n = [int(p) for p in parts]
    secs = n[-1] + n[-2] * 60 + (n[-3] * 3600 if len(n) == 3 else 0)
    return min(secs, 10_000_000)


def _parse_res(value):
    """`1920×1080` / `1280x720` → (w, h); empty → (0, 0); invalid → None."""
    t = str(value or "").strip().replace(" ", "")
    if not t:
        return 0, 0
    m = _RES_RE.match(t)
    if not m:
        return None
    w, h = int(m.group(1)), int(m.group(2))
    return (w, h) if w <= 8192 and h <= 8192 else None


def _is_image(raw: bytes) -> bool:
    return bool(raw) and (
        raw.startswith(b"\xff\xd8\xff")
        or raw.startswith(b"\x89PNG\r\n\x1a\n")
        or (raw[:4] == b"RIFF" and raw[8:12] == b"WEBP")
    )


def _public_file(doc, group=None, group_loaded=False) -> dict:
    """Safe projection like `/search`'s `_result()` plus editor-only fields.

    Group membership is normally copied onto the file document for fast searches;
    the editor passes `group_loaded=True` to use the canonical group document instead.
    """
    doc = doc or {}
    fid = str(doc.get("_id") or "")
    w = int(doc.get("width") or 0)
    h = int(doc.get("height") or 0)
    thumb_ref = str(doc.get("thumb_url") or doc.get("thumb_file_id") or "")
    v = thumb_version(fid, thumb_ref)
    if group_loaded:
        group = group or {}
        group_id = str(group.get("_id") or "")
        group_num = str(group.get("num") or "")
        group_name = str(group.get("name") or "")
    else:
        group_id = str(doc.get("group_id") or "")
        group_num = group_id
        group_name = ""
    return {
        "file_id": fid,
        "name": str(doc.get("file_name") or "Untitled"),
        "caption": str(doc.get("caption") or "")[:1000],
        "quality": str(doc.get("quality") or ""),
        "type": "VIDEO" if vcard_is_video(doc) else "FILE",
        "duration": _fmt_duration(doc.get("duration")),
        "duration_seconds": int(doc.get("duration") or 0),
        "res": f"{w}×{h}" if w and h else "",
        "width": w,
        "height": h,
        "size": get_size(doc.get("file_size") or 0),
        "group_id": group_id,
        "group_num": group_num,
        "group_name": group_name,
        "thumb": f"/api/thumb?file_id={quote(fid, safe='')}&v={v}",
        "v": v,
        "custom_thumb": (
            str(doc.get("thumb_url") or "").startswith("TG_ID:")
            and str(doc.get("thumb_source") or "") == "web"
        ),
    }


async def _admin(req):
    role, _ = await get_auth(req)
    return role == "admin"


def _denied():
    return _json({"ok": False, "error": "Admins only"}, 403)


def _file_id(value) -> str:
    fid = str(value or "").strip()
    # Telegram file_ids + fsv1 short ids; URL/control chars reject
    return fid[:512] if re.fullmatch(r"[A-Za-z0-9_\-=]{1,512}", fid) else ""


async def _file_group(fid, doc=None):
    """Resolve a file's canonical permanent group, preferring its indexed marker."""
    marker = str((doc or {}).get("group_id") or "")
    try:
        if marker:
            group = await group_store.get(marker)
            if group and fid in {str(m) for m in (group.get("members") or [])}:
                return group
        groups = await group_store.by_members([fid])
        if not groups:
            return None
        return next((g for g in groups if str(g.get("_id") or "") == marker), groups[0])
    except Exception as e:
        logger.warning(f"group lookup for file {fid} skipped: {e}")
        # Preserve the visible marker during a temporary group-store outage so a
        # routine metadata save cannot accidentally ungroup the file.
        return {"_id": marker, "num": marker, "name": ""} if marker else None


# ───────────────────────── READ ─────────────────────────
@file_edit_routes.get("/api/file/meta")
async def api_file_meta(req):
    if not await _admin(req):
        return _denied()
    fid = _file_id(req.query.get("id"))
    if not fid:
        return _json({"ok": False, "error": "Invalid file id"}, 400)
    doc = await ia.get_file_meta(fid)
    if not doc:
        return _json({"ok": False, "error": "File not found"}, 404)
    group = await _file_group(fid, doc)
    return _json({"ok": True, "file": _public_file(doc, group, group_loaded=True)})


# ── 🗂️ Sync with permanent groups (file delete / rename) ───────────────

async def _group_cleanup(fid):
    """Remove a deleted file from all groups; drop empty groups (v5 `_group_cleanup`)."""
    try:
        await group_store.pull_files([fid])
        await group_store.cleanup_empty()
    except Exception as e:
        logger.warning(f"group cleanup after delete skipped: {e}")


async def _sync_group_name(fid, name):
    """A new name from the editor refreshes the group's member list + auto_keys."""
    try:
        for g in await group_store.by_members([fid]):
            gid = str(g.get("_id") or "")
            await group_store.rename_member(gid, fid, name)
            key = (series_key(name) if normal_kind(g.get("kind")) == KIND_EPISODES
                   else title_key(name))
            if key:
                await group_store.add_members(gid, [], auto_keys=[key])
    except Exception as e:
        logger.warning(f"group name sync skipped: {e}")


async def _move_file_group(fid, name, target_gid, existing):
    """Move one file into an existing permanent group, or ungroup it when blank."""
    marker = str((existing or {}).get("group_id") or "")
    memberships = await group_store.by_members([fid])
    member_gids = {str(g.get("_id") or "") for g in memberships}

    # Avoid touching group metadata when the file is already consistently placed.
    if target_gid:
        if len(memberships) == 1 and target_gid in member_gids and marker == target_gid:
            return False
    elif not memberships and not marker:
        return False

    # Match the group UI's move behavior: remove from old memberships and blacklist
    # there, then add to the selected target so an old auto_key cannot pull it back.
    await group_store.pull_files([fid], exclude=True)
    if target_gid:
        target_meta = await group_store.get(target_gid)
        if not target_meta:
            raise LookupError("Group not found")
        key = (series_key(name) if normal_kind(target_meta.get("kind")) == KIND_EPISODES
               else title_key(name))
        target = await group_store.add_members(
            target_gid, [(fid, name)], auto_keys=[key] if key else []
        )
        if not target:
            raise LookupError("Group not found")
        await group_store.mark_files([fid], target_gid)
    else:
        await group_store.mark_files([fid], "")
    await group_store.cleanup_empty()
    return True


# ───────────────────────── EDIT ─────────────────────────
@file_edit_routes.post("/api/file/edit")
async def api_file_edit(req):
    if not await _admin(req):
        return _denied()
    try:
        data = await req.json()
        if not isinstance(data, dict):
            raise ValueError("expected an object")
    except Exception:
        return _json({"ok": False, "error": "Bad JSON"}, 400)
    fid = _file_id(data.get("file_id"))
    if not fid:
        return _json({"ok": False, "error": "Invalid file id"}, 400)

    name = _clean(data.get("name"), 300)
    if not name:
        return _json({"ok": False, "error": "File name cannot be empty"}, 400)
    quality = _clean(data.get("quality"), 16)
    if quality and not _QUALITY_RE.match(quality):
        return _json({"ok": False, "error": "Invalid quality value"}, 400)
    duration = _parse_duration(data.get("duration"))
    if duration is None:
        return _json({"ok": False, "error": "Enter duration as H:MM:SS"}, 400)
    res = _parse_res(data.get("res"))
    if res is None:
        return _json({"ok": False, "error": "Enter resolution as 1920×1080"}, 400)

    existing = await ia.get_file_meta(fid)
    if not existing:
        return _json({"ok": False, "error": "File not found"}, 404)

    # Older callers may omit group_id entirely. The editor always sends it; an empty
    # value means ungroup, while a non-empty value must identify an existing group.
    has_group_update = "group_id" in data
    target_gid = ""
    if has_group_update:
        raw_gid = str(data.get("group_id") or "").strip()
        if raw_gid:
            if raw_gid.startswith("#"):
                raw_gid = raw_gid[1:].strip()
            target_gid = _file_id(raw_gid)
            if not target_gid:
                return _json({"ok": False, "error": "Invalid group ID"}, 400)
            if not await group_store.get(target_gid):
                return _json({"ok": False, "error": "Group not found"}, 404)

    fields = {
        "file_name": name,
        "caption": _clean(data.get("caption"), 1000),
        "quality": quality,
        "duration": duration,
        "width": res[0],
        "height": res[1],
    }
    doc = await ia.update_file_fields(fid, fields)
    if not doc:
        return _json({"ok": False, "error": "Could not save changes"}, 500)

    group_changed = False
    if has_group_update:
        try:
            group_changed = await _move_file_group(fid, name, target_gid, existing)
        except LookupError:
            return _json({"ok": False, "error": "Group not found"}, 404)
        except Exception as e:
            logger.exception(f"file group transfer failed for {fid}: {e}")
            return _json({"ok": False, "error": "Could not update group membership"}, 500)

    await _sync_group_name(fid, name)
    # `group_id` is marked by GroupStore after the file fields are saved; re-read it
    # so the editor gets the new membership and can refresh grouped search cards.
    doc = await ia.get_file_meta(fid) or doc
    group = await _file_group(fid, doc)
    return _json({"ok": True, "file": _public_file(doc, group, group_loaded=True),
                  "group_changed": group_changed})


# ─────────────────── CUSTOM POSTER THUMBNAIL ───────────────
@file_edit_routes.post("/api/file/thumb")
async def api_file_thumb(req):
    if not await _admin(req):
        return _denied()
    try:
        data = await req.post()
        fid = _file_id(data.get("file_id"))
        part = data.get("image")
        raw = part.file.read() if part is not None and hasattr(part, "file") else b""
    except Exception as e:
        return _json({"ok": False, "error": f"Bad upload: {e}"}, 400)
    if not fid or not raw:
        return _json({"ok": False, "error": "Missing file_id or image"}, 400)
    if len(raw) > _MAX_UPLOAD or not _is_image(raw):
        return _json({"ok": False, "error": "JPG/PNG/WEBP only, up to 5 MB"}, 400)

    doc = await ia.get_file_meta(fid)
    if not doc:
        return _json({"ok": False, "error": "File not found"}, 404)
    bot = getattr(temp, "BOT", None)
    if bot is None:
        return _json({"ok": False, "error": "The bot is not ready yet"}, 503)

    try:
        buf = io.BytesIO(raw)
        buf.name = "poster.jpg"
        msg = await bot.send_photo(chat_id=runtime_config.get("CATALOG_STORAGE_CHANNEL"), photo=buf)
        photo = getattr(msg, "photo", None)
        sizes = getattr(photo, "sizes", None) if photo else None
        thumb_fid = sizes[-1].file_id if sizes else getattr(photo, "file_id", "")
    except Exception as e:
        logger.warning(f"file thumb upload failed: {e}")
        return _json({"ok": False, "error": "Telegram upload failed"}, 502)
    if not thumb_fid:
        return _json({"ok": False, "error": "No thumbnail file_id returned"}, 502)

    thumb_ref = "TG_ID:" + str(thumb_fid)
    updated = await ia.update_file_fields(fid, {
        "thumb_url": thumb_ref,
        "thumb_file_id": str(thumb_fid),
        "thumb_source": "web",
        "is_thumb_permanent": True,
        # An admin uploaded a real image ⇒ warmup must not overwrite / re-verify it
        "thumb_verified": True,
    })
    if not updated:
        return _json({"ok": False, "error": "Could not save changes"}, 500)
    invalidate_thumb(fid)     # an old in-flight download must not restore it
    out = _public_file(updated)
    return _json({"ok": True, "file": out, "thumb": out["thumb"], "v": out["v"]})


@file_edit_routes.post("/api/file/thumb_reset")
async def api_file_thumb_reset(req):
    """🔄 Remove the custom poster and fetch Telegram's original thumbnail again."""
    if not await _admin(req):
        return _denied()
    try:
        data = await req.json()
    except Exception:
        return _json({"ok": False, "error": "Bad JSON"}, 400)
    fid = _file_id(data.get("file_id"))
    if not fid or not await ia.get_file_meta(fid):
        return _json({"ok": False, "error": "File not found"}, 404)
    updated = await ia.update_file_fields(fid, {
        "thumb_url": "", "thumb_file_id": "", "thumb_source": "",
        "is_thumb_permanent": False,
        "thumb_verified": False,     # the serial probe will fetch a real thumbnail again
    })
    if not updated:
        return _json({"ok": False, "error": "Could not reset the thumbnail"}, 500)
    invalidate_thumb(fid)
    enqueue_probe(fid, force=True)     # serial queue — one at a time, rate-limit safe
    out = _public_file(updated)
    return _json({"ok": True, "file": out, "thumb": out["thumb"],
                  "v": out["v"], "queued": True})


# ───────────────────────── DELETE ─────────────────────────
@file_edit_routes.post("/api/file/delete")
async def api_file_delete(req):
    if not await _admin(req):
        return _denied()
    try:
        data = await req.json()
    except Exception:
        return _json({"ok": False, "error": "Bad JSON"}, 400)
    fid = _file_id(data.get("file_id"))
    if not fid:
        return _json({"ok": False, "error": "Invalid file id"}, 400)
    if not await ia.delete_file_by_id(fid):
        return _json({"ok": False, "error": "File not found"}, 404)
    invalidate_thumb(fid)
    await _group_cleanup(fid)
    return _json({"ok": True, "deleted": fid})
