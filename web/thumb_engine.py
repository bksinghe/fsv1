"""📸 REAL THUMBNAIL + TRUE METADATA ENGINE — fsv1's serial extraction.

Storage model (Koyeb free / 512 MB RAM) — **unchanged**:
  * MongoDB   → only the Telegram thumbnail **file_id string**
                 `thumb_url: "TG_ID:<file_id>"` (as in v5), or `"NO_THUMB"`.
                 No image bytes are stored.
  * Server RAM → a byte-bounded LRU hot cache (16 MiB default) avoids repeat
                 Telegram downloads; entries evict oldest-first and are never persisted.
                 In-flight buffers remain transient.
  * Browser   → `/api/thumb` uses `ETag` + `Cache-Control` + 304, so the poster
                 lives in the browser's own cache.

Learned from v5 (`JoneySin/v5`), implemented the fsv1 way:

  * **First-time extraction runs one file at a time to avoid rate limits** —
    `_probe_lock` guarantees only **one** `send_cached_media()` call process-wide,
    with a random 1.2–3.0s anti-flood gap between probes (`plugins/warmup.py`).

  * `/api/thumb` does not open 21 parallel probes: a single-worker **queue** plus
    browser `retry=true` (v5's `reloadThumb` pattern).
  * **FLOOD_WAIT / 420** → parse `wait of N seconds` (or `FloodWait.value`),
    `sleep(N + extra)` and retry up to 5 attempts.
  * 🆕 **/warmup_thumbs = thumbnail + real metadata in one probe**: the same
    `send_cached_media` message (and, when needed, the file's bytes) supplies
    duration / width / height / quality / mime / size / type for a DB `$set`.
    `media_probe.py` replaces Telegram's often-wrong `1280×720` attributes with
    the real dimensions from the container header.
  * 🆕 **Never save a fake "NO IMAGE" thumbnail to the DB**: download the candidate
    bytes → check magic/dimensions/variance/markers with `web/image_validate.py`
    → permanently re-upload via Telegram `send_photo` (v5 warmup's approach).
    Anything that fails is rejected and marked `NO_THUMB`; a placeholder never
    becomes a `TG_ID:`. An admin's `thumb_source:"web"` poster is never overwritten.
"""

import asyncio
import io
import logging
import random
from collections import OrderedDict
import re
import zlib

import info as _info
from info import (
    BIN_CHANNEL,
    THUMB_FETCH_CONCURRENCY,
    THUMB_PROBE_GAP_MIN,
    THUMB_PROBE_GAP_MAX,
    THUMB_PROBE_ATTEMPTS,
    THUMB_FLOOD_EXTRA,
)
from utils import temp
from database.ia_filterdb import collection, update_file_meta
from media_probe import META_V, build_media_meta, probe_telegram_media
from web.image_validate import validate_thumb

logger = logging.getLogger(__name__)

# v5's THUMBNAIL_STORAGE_CHANNEL is CATALOG_STORAGE_CHANNEL in fsv1 (defaults to BIN)
_STORAGE_CHANNEL = getattr(_info, "CATALOG_STORAGE_CHANNEL", BIN_CHANNEL)
_MIN_THUMB_BYTES = int(getattr(_info, "THUMB_MIN_BYTES", 512))
_MIN_THUMB_DIM = int(getattr(_info, "THUMB_MIN_DIM", 48))
_MIN_THUMB_STDDEV = float(getattr(_info, "THUMB_MIN_STDDEV", 6.0))

# ── Concurrency control (no thumbnail data is stored here) ─────────────────
# Limited concurrency for downloading files that already have a known TG_ID
_download_sem = asyncio.Semaphore(THUMB_FETCH_CONCURRENCY)
# ⚠️ FIRST-TIME PROBE: only ONE file at a time (v5 warmup "single-bot safe")
_probe_lock = asyncio.Lock()
_probe_queue: asyncio.Queue = asyncio.Queue()
_queued = set()                 # file ids — prevents duplicate enqueues
_MAX_QUEUE = 2000
_worker_task = None
# fid -> asyncio.Task: identical concurrent requests share one download
_INFLIGHT = {}
# Small byte-bounded hot cache: repeatedly requested, already-saved Telegram IDs
# otherwise still incur a Telegram download on every browser/cache miss.
_THUMB_CACHE_MAX_BYTES = max(0, int(getattr(_info, "THUMB_CACHE_BYTES", 16 * 1024 * 1024)))
_THUMB_CACHE = OrderedDict()
_THUMB_CACHE_BYTES = 0
_STATS = {"done": 0, "ok": 0, "no_thumb": 0, "failed": 0,
          "rejected": 0, "meta": 0}


def image_content_type(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


def thumb_version(fid: str, thumb_ref: str = "") -> str:
    """Like v5, hash the whole thumb_url — a new thumbnail changes the URL/ETag."""
    raw = f"{fid}:{thumb_ref}"
    return f"{zlib.crc32(raw.encode('utf-8')):08x}"


def thumb_id_from_doc(doc) -> str:
    """Read the Telegram thumbnail file_id from a DB doc (v5 `TG_ID:` + legacy alias).

    `NO_THUMB` = permanently without a poster ⇒ there is no id.
    """
    doc = doc or {}
    raw = str(doc.get("thumb_url") or "")
    if raw.startswith("TG_ID:"):
        return raw[len("TG_ID:"):]
    if raw == "NO_THUMB":
        return ""
    return str(doc.get("thumb_file_id") or "")


def is_no_thumb(doc) -> bool:
    return str((doc or {}).get("thumb_url") or "") == "NO_THUMB"


def _cache_get(key: str):
    data = _THUMB_CACHE.pop(key, None)
    if data is not None:
        _THUMB_CACHE[key] = data
    return data


def _cache_put(key: str, data: bytes) -> None:
    global _THUMB_CACHE_BYTES
    if not _THUMB_CACHE_MAX_BYTES or len(data) > _THUMB_CACHE_MAX_BYTES:
        return
    previous = _THUMB_CACHE.pop(key, None)
    if previous is not None:
        _THUMB_CACHE_BYTES -= len(previous)
    while _THUMB_CACHE and _THUMB_CACHE_BYTES + len(data) > _THUMB_CACHE_MAX_BYTES:
        _, evicted = _THUMB_CACHE.popitem(last=False)
        _THUMB_CACHE_BYTES -= len(evicted)
    _THUMB_CACHE[key] = data
    _THUMB_CACHE_BYTES += len(data)


def invalidate_thumb(fid: str) -> None:
    """✏️ An admin changed the custom poster → an in-flight download must not restore the old one."""
    global _THUMB_CACHE_BYTES
    if not fid:
        return
    _INFLIGHT.pop(f"dl:{fid}", None)
    _queued.discard(fid)
    cached = _THUMB_CACHE.pop(fid, None)
    if cached is not None:
        _THUMB_CACHE_BYTES -= len(cached)


def thumb_queue_state() -> dict:
    """Lightweight snapshot for /stats, /api/db_stats and the `/warmup_thumbs` report."""
    return {
        "queued": len(_queued),
        "done": _STATS["done"],
        "ok": _STATS["ok"],
        "no_thumb": _STATS["no_thumb"],
        "failed": _STATS["failed"],
        "rejected": _STATS["rejected"],
        "meta": _STATS["meta"],
    }


async def thumb_state(fid: str) -> str:
    """Lightweight status for a 404 from /api/thumb ('queued' ⇒ the browser should retry)."""
    doc = await _read_doc(fid)
    if doc is None:
        return "missing"                 # not in the DB ⇒ skip a pointless Telegram call
    if is_no_thumb(doc):
        return "no-thumb"
    if fid in _queued:
        return "queued"
    if thumb_id_from_doc(doc):
        # an unverified lock is an index-time id that still needs validation
        if not doc.get("thumb_verified"):
            enqueue_probe(fid, force=True)
            return "queued"
        return "ready"
    return "queued" if enqueue_probe(fid) else "missing"


# ─────────────────────────────────────────────────────────────
# 🛡️ v5-style FLOOD_WAIT handling
# ─────────────────────────────────────────────────────────────
def flood_wait_seconds(err) -> int:
    """Extract the wait seconds from a FloodWait exception (`e.value`) or its message."""
    value = getattr(err, "value", None)
    if isinstance(value, (int, float)) and value > 0:
        return int(value)
    text = str(err)
    upper = text.upper()
    if "FLOOD_WAIT" not in upper and "420" not in text and "FLOOD" not in upper:
        return 0
    m = re.search(r"wait of (\d+) seconds?", text)
    return int(m.group(1)) if m else 20


async def _backoff(err, default: float = 2.0):
    wait = flood_wait_seconds(err)
    await asyncio.sleep((wait + THUMB_FLOOD_EXTRA) if wait else default)


async def _delete_later(message_id: int, delay: int = 5):
    """Like v5's delete queue — remove the probe message from BIN_CHANNEL (non-blocking)."""
    await asyncio.sleep(delay)
    try:
        await temp.BOT.delete_messages(BIN_CHANNEL, message_id)
    except Exception:
        pass


def _valid_thumb_ref(tid) -> bool:
    """v5 warmup's strict id validation: a string, >20 chars, no NO_THUMB marker."""
    return (
        isinstance(tid, str)
        and len(tid.strip()) > 20
        and "NO_THUMB" not in tid.upper()
    )


def _extract_media(msg):
    """Media object plus **all** thumbnail file_ids from the message (largest first).

    Telegram sometimes returns a placeholder first and the real frame second,
    so we never rely on `thumbs[0]` alone.
    """
    media = getattr(msg, msg.media.value, None) if msg and getattr(msg, "media", None) else None
    ids, seen = [], set()
    for obj in (media, getattr(msg, "video", None),
                getattr(msg, "document", None), getattr(msg, "animation", None)):
        for thumb in (getattr(obj, "thumbs", None) or []):
            tid = getattr(thumb, "file_id", None)
            if tid and tid not in seen:
                seen.add(tid)
                ids.append(tid)
    photo = getattr(msg, "photo", None)
    if photo:
        for size in reversed(getattr(photo, "sizes", None) or []):
            tid = getattr(size, "file_id", None)
            if tid and tid not in seen:
                seen.add(tid)
                ids.append(tid)
        tid = getattr(photo, "file_id", None)
        if tid and tid not in seen:
            seen.add(tid)
            ids.append(tid)
    ids.reverse()                    # Telegram returns thumbs small→large; real large ones first
    return media, ids


async def _download_thumb(thumb_file_id: str):
    """Download thumbnail bytes from Telegram — never stored, returned directly."""
    bot = getattr(temp, "BOT", None)
    if not bot or not thumb_file_id:
        return None
    for attempt in range(3):
        try:
            async with _download_sem:
                buf = await bot.download_media(thumb_file_id, in_memory=True)
            if not buf:
                return None
            data = buf.getvalue() if hasattr(buf, "getvalue") else bytes(buf)
            return data or None
        except Exception as e:
            if attempt == 2:
                logger.debug(f"thumb download failed for {thumb_file_id[:16]}: {e}")
                return None
            await _backoff(e, default=1.5)
    return None


async def _upload_thumb(data: bytes) -> str:
    """✅ v5 warmup: fresh-upload the validated image to the storage channel.

    Telegram's `send_photo` only accepts a genuine image ⇒ this id is permanent
    (a transient thumb file_reference cannot expire). Fail-soft: if the bot lacks
    the method, the validated original id is used instead.
    """
    bot = getattr(temp, "BOT", None)
    if not bot or not data:
        return ""
    try:
        buf = io.BytesIO(data)
        buf.name = "poster.png" if data.startswith(b"\x89PNG") else "poster.jpg"
        msg = await bot.send_photo(chat_id=_STORAGE_CHANNEL, photo=buf)
        photo = getattr(msg, "photo", None)
        sizes = getattr(photo, "sizes", None) if photo else None
        tid = sizes[-1].file_id if sizes else getattr(photo, "file_id", "")
        return str(tid or "")
    except Exception as e:
        logger.debug(f"[thumb] permanent re-upload skipped: {str(e)[:80]}")
        return ""


async def _real_thumb_bytes(thumb_ids):
    """Download + validate every candidate → `(bytes, info)` or `(None, {})`.

    Anything fake / "NO IMAGE" / blank / tiny is rejected;
    `_STATS['rejected']` counts it so it appears in the `/warmup_thumbs` report.
    """
    for tid in thumb_ids:
        if not _valid_thumb_ref(tid):
            _STATS["rejected"] += 1
            continue
        data = await _download_thumb(tid)
        if not data:
            continue
        ok, info = validate_thumb(
            data,
            min_bytes=_MIN_THUMB_BYTES,
            min_dim=_MIN_THUMB_DIM,
            min_stddev=_MIN_THUMB_STDDEV,
        )
        if not ok:
            _STATS["rejected"] += 1
            logger.info(f"[thumb] rejected fake poster ({info['reason']}): {tid[:16]}")
            continue
        return data, {"ref": tid, **info}
    return None, {}


async def get_image_bytes(telegram_file_id: str):
    """📷 Public wrapper — used for Posts/Actors `TG_ID:` images."""
    return await _download_thumb(telegram_file_id)


async def _read_doc(fid: str):
    return await asyncio.to_thread(
        collection.find_one, {"_id": fid},
        {"thumb_url": 1, "thumb_file_id": 1, "thumb_verified": 1,
         "thumb_source": 1, "meta_v": 1, "quality": 1, "file_name": 1},
    )


def _meta_version(doc) -> int:
    try:
        return int(doc.get("meta_v") or 0)
    except (TypeError, ValueError):
        return 0


async def probe_file(fid: str, force: bool = False):
    """🖼️ ONE file: **real thumbnail + true metadata** — serial, like v5 warmup.

    `_probe_lock` allows only one `send_cached_media` at a time process-wide,
    with an anti-flood gap between probes. The DB receives only the id
    (`TG_ID:` / `NO_THUMB`) and metadata (`duration/quality/...`).
    A fake placeholder is never saved — the file is marked `NO_THUMB` instead.
    """
    if not fid or len(fid) > 512:
        return None

    async with _probe_lock:
        probed = False
        try:
            doc = await _read_doc(fid) or {}
            raw = str(doc.get("thumb_url") or "")
            custom = str(doc.get("thumb_source") or "") == "web"   # protect the admin poster
            verified = bool(doc.get("thumb_verified"))

            need_meta = force or _meta_version(doc) < META_V
            need_thumb = force or (
                (not raw.startswith("TG_ID:") and raw != "NO_THUMB")
                or (raw.startswith("TG_ID:") and not verified)
            )
            if custom:
                need_thumb = False        # never overwrite a custom poster

            if not need_meta and not need_thumb:
                if raw.startswith("TG_ID:"):
                    return await _download_thumb(raw[len("TG_ID:"):])
                return None

            bot = getattr(temp, "BOT", None)
            if bot is None:
                return None

            for attempt in range(THUMB_PROBE_ATTEMPTS):
                msg = None
                try:
                    msg = await bot.send_cached_media(chat_id=BIN_CHANNEL, file_id=fid)
                    probed = True
                except Exception as e:
                    wait = flood_wait_seconds(e)
                    logger.warning(
                        f"[thumb probe] {fid[:16]} attempt {attempt + 1}: "
                        f"{str(e)[:90]}" + (f" → sleeping {wait + THUMB_FLOOD_EXTRA}s" if wait else "")
                    )
                    await _backoff(e)
                    continue

                media, thumb_ids = _extract_media(msg)
                file_name = str(doc.get("file_name") or "")
                meta = {}

                # 1️⃣ True metadata — from the same message + a file-bytes probe (free backfill)
                if need_meta and media:
                    try:
                        probed_meta = await probe_telegram_media(
                            bot, media, file_name=file_name,
                            file_size=int(doc.get("file_size") or 0),
                        )
                    except Exception as e:
                        logger.debug(f"[probe] {fid[:16]} media probe skipped: {e}")
                        probed_meta = {}
                    meta.update(build_media_meta(media, probed_meta, file_name, doc))
                    need_meta = False       # do not repeat the range fetch on the next attempt

                # 2️⃣ Real thumbnail — validate + permanent re-upload
                #    no candidate / all fake ⇒ mark NO_THUMB immediately
                #    (downloading the same placeholder 5 times is pointless).
                data, info = (None, {})
                if need_thumb:
                    data, info = await _real_thumb_bytes(thumb_ids)
                    if data:
                        permanent = await _upload_thumb(data)
                        chosen = permanent or info["ref"]
                        meta.update({
                            "thumb_url": f"TG_ID:{chosen}",
                            "thumb_file_id": chosen,
                            "thumb_verified": True,
                            "thumb_source": "probe",
                            "is_thumb_permanent": bool(permanent),
                            "thumb_width": info["width"],
                            "thumb_height": info["height"],
                        })
                    else:
                        meta.update({
                            "thumb_url": "NO_THUMB", "thumb_file_id": "",
                            "thumb_verified": False, "thumb_source": "",
                            "is_thumb_permanent": False,
                        })

                if meta:
                    await update_file_meta(fid, meta)
                    if "meta_v" in meta:
                        _STATS["meta"] += 1

                asyncio.create_task(_delete_later(getattr(msg, "id", 0)))

                if not need_thumb:
                    return None                    # this was a metadata-only backfill
                if data:
                    _STATS["ok"] += 1
                    return data
                # Telegram only had a fake/placeholder ⇒ save nothing to the DB
                _STATS["no_thumb"] += 1
                return None

            # Every `send_cached_media` attempt failed ⇒ network/flood issue,
            # do not mark NO_THUMB (it will be retried next time).
            _STATS["failed"] += 1
            return None
        finally:
            _STATS["done"] += 1
            # ⏱️ v5-warmup-style 1.2–3.0s random anti-flood gap (after a probe only)
            if probed:
                await asyncio.sleep(random.uniform(THUMB_PROBE_GAP_MIN, THUMB_PROBE_GAP_MAX))


# ─────────────────────────────────────────────────────────────
# 🔄 SINGLE-WORKER QUEUE — "thumbnails are extracted one at a time"
# ─────────────────────────────────────────────────────────────
def _ensure_worker():
    global _worker_task
    if _worker_task is None or _worker_task.done():
        _worker_task = asyncio.create_task(_queue_worker())


async def _queue_worker():
    """One file at a time from the queue; the rest wait (no parallel burst)."""
    while True:
        fid, force = await _probe_queue.get()
        try:
            await probe_file(fid, force=force)
        except Exception as e:
            logger.warning(f"[thumb queue] {fid[:16]} failed: {e}")
        finally:
            _queued.discard(fid)
            _probe_queue.task_done()


def enqueue_probe(fid: str, force: bool = False) -> bool:
    """Enqueue a first-time / stale-id file without blocking."""
    if not fid or len(fid) > 512:
        return False
    if fid in _queued or len(_queued) >= _MAX_QUEUE:
        return False
    _queued.add(fid)
    _probe_queue.put_nowait((fid, force))
    _ensure_worker()
    return True


async def get_thumb(fid: str, retry: bool = False):
    """Poster bytes or None. There is no persistent RAM cache.

    * `TG_ID:` present → download directly (identical requests share one task)
    * `NO_THUMB`       → return None immediately, no Telegram call (as in v5)
    * no id            → enqueue it and return 404 for now; the browser's `retry=true`
                         picks up the poster shortly (one file at a time)
    * 🆕 a stored id turns out fake/blank → do not serve it, force a re-probe
    """
    if not fid or len(fid) > 512:
        return None

    doc = await _read_doc(fid)
    if doc is None:
        return None                      # unknown file_id ⇒ no probe / no queue
    if is_no_thumb(doc):
        return None
    # Telegram already validated an intentional custom poster (`thumb_source:"web"`)
    # when it was uploaded with `send_photo` — do not block it by size/variance.
    custom = str(doc.get("thumb_source") or "") == "web"
    thumb_file_id = thumb_id_from_doc(doc)

    if thumb_file_id:
        cached = _cache_get(fid)
        if cached is not None:
            return cached
        key = f"dl:{fid}"
        task = None if retry else _INFLIGHT.get(key)
        if task is None or task.done():
            task = asyncio.ensure_future(_download_thumb(thumb_file_id))
            _INFLIGHT[key] = task

            def _cleanup(_t, k=key, t=task):
                if _INFLIGHT.get(k) is t:
                    _INFLIGHT.pop(k, None)

            task.add_done_callback(_cleanup)
        data = await asyncio.shield(task)
        if data:
            ok = True if custom else validate_thumb(
                data, min_bytes=_MIN_THUMB_BYTES,
                min_dim=_MIN_THUMB_DIM, min_stddev=_MIN_THUMB_STDDEV,
            )[0]
            if ok:
                _cache_put(fid, data)
                return data
            # 💾 A fake poster was found in the DB → remove it and fetch a real one
            _STATS["rejected"] += 1
            await update_file_meta(fid, {
                "thumb_url": "", "thumb_file_id": "",
                "thumb_verified": False,
            })
            enqueue_probe(fid, force=True)
            return None
        # stale / expired file_reference → fresh probe (still one at a time)
        enqueue_probe(fid, force=True)
        return None

    # 🆕 FIRST TIME: one serial queue instead of 21 parallel Telegram calls
    enqueue_probe(fid)
    return None
