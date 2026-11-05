"""🖼️ `/warmup_thumbs` — sequential engine for thumbnails + **real metadata**.

Learned from `plugins/warmup.py` in JoneySin/v5: `send_cached_media` one file at a
time, a random 3.0–5.0s anti-flood gap between files (wider after a FloodWait),
`e.value + 10` sleep on FloodWait, strict thumbnail validation and a `NO_THUMB`
mark for files without one.

In fsv1 all of that lives in `web/thumb_engine.py::probe_file()` + `_probe_lock` (web
requests go through the same single lock/queue). This command additionally:

  * **writes more than thumbnails to the DB**: duration, quality, width/height,
    mime, size and type. `media_probe.py` reads the file's real bytes to get
    accurate dimensions/duration (Telegram's default 1280×720 can be wrong).

  * **never saves a fake "NO IMAGE" poster**: candidate bytes are validated,
    only genuine images become `TG_ID:`; fake/blank ones are marked `NO_THUMB`.
    Like v5, a validated image is permanently re-uploaded to the storage channel.

  * The query only selects documents whose thumbnail is not yet **verified** or
    whose metadata probe (`meta_v`) is pending — so unverified `TG_ID:` ids from
    earlier indexing are validated in this run as well.
"""

import asyncio
import logging
import re
import time

from hydrogram import Client, filters, enums
from hydrogram.errors import MessageNotModified

from info import ADMINS
from database.ia_filterdb import collection
from media_probe import META_V

logger = logging.getLogger(__name__)

# v5's smart filter plus fsv1's verification/metadata gate:
#   * NO_THUMB = already confirmed to have no real poster ⇒ do not pick it up again
#   * everything else: missing id / unverified / metadata probe pending
_PENDING_QUERY = {
    "thumb_url": {"$ne": "NO_THUMB"},
    "$or": [
        {"thumb_url": {"$not": re.compile(r"^TG_ID:")}},
        {"thumb_verified": {"$ne": True}},
        {"meta_v": {"$ne": META_V}},
    ],
}


def _progress(col_name, done, total, ok, meta, fake, elapsed):
    pct = int((done / max(total, 1)) * 100)
    speed = (done / max(elapsed, 1)) * 60
    eta = int((total - done) / max(speed / 60, 0.001))
    dot = "🔴" if pct < 30 else "🟡" if pct < 70 else "🟢"
    return (
        "<b>🎬 THUMBNAIL + META WARMUP</b>\n"
        "────────────────────\n"
        f"📁 Collection: <code>{col_name}</code>\n"
        f"📈 Progress: <code>{done:,} / {total:,}</code> ({pct}%)\n"
        f"🖼️ Real posters: <code>{ok:,}</code> · 🚫 Fake rejected: <code>{fake:,}</code>\n"
        f"💾 Meta saved: <code>{meta:,}</code>\n"
        f"⚡ Speed: <code>{speed:.1f} files/min</code> · ETA <code>~{eta}s</code>\n"
        "────────────────────\n"
        f"{dot} <i>One file at a time with an anti-flood gap — no parallel bursts.</i>"
    )


@Client.on_message(filters.command("warmup_thumbs") & filters.user(ADMINS))
async def warmup_thumbs_cmd(client, message):
    # Lazy import: the `web` package is already loaded by bot.py; this avoids a cycle.
    from web.thumb_engine import probe_file, thumb_queue_state

    status = await message.reply(
        "⚙️ <b>Thumbnail + Metadata Warmup</b>\n\nCounting pending files…",
        parse_mode=enums.ParseMode.HTML,
    )

    docs = await asyncio.to_thread(
        lambda: list(collection.find(_PENDING_QUERY, {"_id": 1, "file_name": 1}))
    )
    total = len(docs)
    if not total:
        return await status.edit_text(
            "✨ <b>Everything is up-to-date!</b>\n\n"
            "Every file has a <b>verified</b> <code>TG_ID:</code> thumbnail lock, "
            "accurate <code>meta_v</code> metadata or a <code>NO_THUMB</code> mark.",
            parse_mode=enums.ParseMode.HTML,
        )

    skipped = 0
    start = time.time()
    base = thumb_queue_state()
    for i, doc in enumerate(docs, 1):
        fid = str(doc.get("_id") or "")
        if not fid:
            skipped += 1
            continue
        try:
            # ⚠️ This is the serial point: global _probe_lock + 3.0–5.0s anti-flood gap
            #    (wider after a FloodWait) + FloodWait retry. The same probe writes true
            #    metadata and the verified thumbnail to the DB.
            await probe_file(fid)
        except Exception as e:
            logger.warning(f"[warmup] {fid[:16]} skipped: {e}")
            skipped += 1

        # Like v5, refresh the UI every 10 files
        if i % 10 == 0 or i == total:
            q = thumb_queue_state()
            try:
                await status.edit_text(
                    _progress("files", i, total,
                              q["ok"] - base["ok"], q["meta"] - base["meta"],
                              q["rejected"] - base["rejected"], time.time() - start),
                    parse_mode=enums.ParseMode.HTML,
                )
            except MessageNotModified:
                pass
            except Exception:
                pass

    q = thumb_queue_state()
    ok = q["ok"] - base["ok"]
    meta = q["meta"] - base["meta"]
    fake = q["rejected"] - base["rejected"]
    no_thumb = q["no_thumb"] - base["no_thumb"]
    failed = q["failed"] - base["failed"]
    await status.edit_text(
        "🎉 <b>WARMUP COMPLETE</b>\n"
        "────────────────────\n"
        f"🎯 Scanned: <code>{total:,}</code>\n"
        f"🖼️ Real posters saved: <code>{ok:,}</code>\n"
        f"💾 Duration/quality/meta saved: <code>{meta:,}</code>\n"
        f"🚫 Fake \"NO IMAGE\" rejected: <code>{fake:,}</code>\n"
        f"⚪ No real poster (NO_THUMB): <code>{no_thumb:,}</code>\n"
        f"⏳ Remaining in queue: <code>{q['queued']}</code> · Errors: <code>{failed + skipped}</code>\n"
        f"🕐 Time: <code>{int(time.time() - start)}s</code>\n\n"
        "<i>The web UI now shows only verified posters and accurate duration/quality, "
        "with no extra probing.</i>",
        parse_mode=enums.ParseMode.HTML,
    )
