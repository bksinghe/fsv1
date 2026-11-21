import logging
import asyncio
import time
import html
from datetime import datetime
from pyrogram import Client, filters, enums
from telegram_buttons import styled_button, styled_keyboard
from pyrogram.types import CallbackQuery
from pyrogram.errors import MessageNotModified, MessageIdInvalid, BadRequest

from info import ADMINS, LOG_CHANNEL
from database.ia_filterdb import (
    db_count_documents,
    find_delete_batch,
    unpack_new_file_id,
    delete_all_files,
)
from database.stats_db import snapshot
from database.delete_archive import archive_and_delete, ArchiveDeleteError
from utils import fmt, temp
from plugins.file_deliver import discard_batch_offer


# ======================================================
# 🧠 CONFIG & SAFE INIT
# ======================================================

if not hasattr(temp, "START_TIME"):
    temp.START_TIME = time.time()


# ======================================================
# 🛡 SAFE HELPERS
# ======================================================

async def safe_edit(msg, text, parse_mode=enums.ParseMode.HTML, **kwargs):
    try:
        if msg.text == text:
            return True
        await msg.edit(text, parse_mode=parse_mode, **kwargs)
        return True
    except (MessageNotModified, MessageIdInvalid, BadRequest):
        return False
    except Exception:
        return False


async def safe_answer(query, text="", alert=False):
    try:
        await query.answer(text, show_alert=alert)
    except Exception:
        pass


# ======================================================
# 📊 STATS TEXT (BUTTON-FREE)
#    Pure numbers — no command list (the 👨‍🚒 Help button of /start
#    documents the commands) and no index-speed counter (it only meant
#    something while an indexing run was in flight).
#
#    The counters come from database.stats_db.snapshot(), the same call
#    the web "Database Stats" page uses.
# ======================================================

def _stat_value(value):
    """Escape database-derived values before inserting them into Telegram HTML."""
    return html.escape(str(value))


async def build_stats():
    s = await snapshot()
    value = _stat_value
    return (
        "<blockquote>📊 <b>BOT STATISTICS</b></blockquote>\n"
        f"<blockquote>👤 <b>Users:</b> <code>{value(s['users'])}</code>  "
        f"👥 <b>Groups:</b> <code>{value(s['chats'])}</code>\n"
        f"📦 <b><i>Total Files:</i></b> <code>{value(s['files'])}</code></blockquote>\n"
        f"<blockquote>💎 <b>Premium:</b> <code>{value(s['premium'])}</code>\n"
        f"🗃 <b>DB Size:</b> <code>{value(s['db_size'])}</code></blockquote>\n"
        f"<blockquote>⏱ <b>Uptime:</b> <code>{value(s['uptime'])}</code></blockquote>\n\n"
        "<blockquote>🌐 <b>WEB STATISTICS</b></blockquote>\n\n"
        f"<blockquote>🧑‍💻 <b>Web Accounts:</b> <code>{value(s['web_accounts'])}</code></blockquote>\n"
        f"<blockquote>📝 <b>Posts:</b> <code>{value(s['posts'])}</code></blockquote>\n"
        f"<blockquote>🎭 <b>Profiles:</b> <code>{value(s['actors'])}</code></blockquote>\n"
        f"<blockquote>🗂 <b>Groups:</b> <b><i>{value(s['groups'])}</i></b></blockquote>\n"
        f"<b><i>(🎞️ {value(s['quality_groups'])} · 📺 {value(s['episode_groups'])} · "
        f"🎬 {value(s['episodes_total'])} eps)</i></b>\n"
        f"<blockquote>🖼 <b>Posters:</b> <code>{value(s['thumbnails'])}</code></blockquote>\n\n"
        f"<blockquote>🔄 <b>Updated:</b> <code>{value(s['now'])}</code></blockquote>"
    )


# ======================================================
# 📊 /stats COMMAND — BOT + WEB COUNTERS (NO BUTTONS)
# ======================================================

@Client.on_message(filters.command("stats") & filters.user(ADMINS))
async def stats_cmd(bot, message):
    """Live bot + web counters (replaces the old panel)"""
    msg = await message.reply("⏳ Collecting stats...")
    await safe_edit(msg, await build_stats())


# ======================================================
# 🗑 DELETE FILES COMMAND
# ======================================================

_delete_task = None


@Client.on_message(filters.private & filters.command("delete") & filters.user(ADMINS))
async def delete_cmd(bot, message):
    """Archive/delete in a single bounded background job."""
    global _delete_task
    if _delete_task and not _delete_task.done():
        return await message.reply("⏳ A delete operation is already running.")
    _delete_task = asyncio.create_task(_run_delete(bot, message))
    def done(task):
        if not task.cancelled() and task.exception():
            logging.getLogger(__name__).error("Delete operation failed", exc_info=task.exception())
    _delete_task.add_done_callback(done)


async def _run_delete(bot, message):
    """Reply to one media file, or archive matching files one at a time."""
    reply = getattr(message, "reply_to_message", None)
    media = (getattr(reply, "document", None) or getattr(reply, "video", None)) if reply else None
    key = message.text.split(" ", 1)[1].strip() if len(message.command) >= 2 else ""
    if not media and len(key) < 2:
        return await message.reply(
            "Reply to a video/document with /delete, or use /delete keyword to archive and delete matching files."
        )
    msg = await message.reply("⏳ Archiving before deleting…")
    count = 0
    try:
        if media:
            fid = unpack_new_file_id(media.file_id)
            if not fid or not await archive_and_delete(bot, fid):
                return await msg.edit("❌ File not found in the database.")
            count = 1
        else:
            after = ""
            while True:
                page = await find_delete_batch(key, after)
                if not page:
                    break
                for doc in page:
                    fid = str(doc["_id"])
                    if await archive_and_delete(bot, fid):
                        count += 1
                after = str(page[-1]["_id"])
        await msg.edit(f"✅ Archived and moved <code>{count}</code> file(s) to the Recycle Bin.")
    except Exception as exc:
        # Stop on the first error. Files already archived/deleted stay deleted;
        # the failed file and all later files are left in the database.
        text = str(exc) if isinstance(exc, ArchiveDeleteError) else "Database or network error; operation stopped."
        await msg.edit(f"❌ Stopped after <code>{count}</code> file(s). {html.escape(text)}")


# ======================================================
# 🗑 DELETE ALL FILES COMMAND (Alternative)
# ======================================================

DELETE_ALL_PENDING = {}
DELETE_ALL_OWNERS = set()

@Client.on_message(filters.command("deleteall") & filters.user(ADMINS))
async def delete_all_cmd(bot, message):
    owner_key = (message.chat.id, message.from_user.id)
    if owner_key in DELETE_ALL_OWNERS:
        return await message.reply("⚠️ A delete-all confirmation is already pending.")
    DELETE_ALL_OWNERS.add(owner_key)
    try:
        file_count = await asyncio.to_thread(db_count_documents)
    
        msg = await message.reply(
            f"⚠️ <b>WARNING: Delete ALL Files</b>\n\n"
            f"📦 Total Files: <code>{file_count}</code>\n\n"
            f"❗ Move all {file_count} files to the Recycle Bin?\n\n"
            "Reply with 'CONFIRM DELETE ALL' to proceed.",
            reply_markup=styled_keyboard([
                [styled_button("❌ Cancel", callback_data="deleteall_cancel")]
            ])
        )

    except BaseException:
        DELETE_ALL_OWNERS.discard(owner_key)
        raise
    key = (message.chat.id, msg.id)
    cancel = asyncio.Event()
    DELETE_ALL_PENDING[key] = (message.from_user.id, cancel)
    asyncio.create_task(_wait_delete_all(bot, message, msg, key, owner_key, cancel))


async def _wait_delete_all(bot, message, msg, key, owner_key, cancel):
    listener = asyncio.create_task(bot.listen(
        chat_id=message.chat.id, user_id=message.from_user.id, filters=filters.text, timeout=30
    ))
    cancelled = asyncio.create_task(cancel.wait())
    try:
        done, _ = await asyncio.wait((listener, cancelled), return_when=asyncio.FIRST_COMPLETED)
        if cancelled in done or cancel.is_set():
            return
        response = await listener
        # Once confirmation wins, the cancel button must no longer claim success.
        DELETE_ALL_PENDING.pop(key, None)
        if response.text.strip().upper() == "CONFIRM DELETE ALL":
            await response.delete()
            await msg.edit("⏳ Deleting all files...")
            
            count = await delete_all_files()
            
            await msg.edit(
                f"✅ <b>Moved all indexed files to the Recycle Bin</b>\n\n"
                f"🗑 Deleted: <code>{count}</code> files\n"
                f"🕒 Time: <code>{fmt(datetime.utcnow())}</code>"
            )
            
            # Log to channel
            try:
                await bot.send_message(
                    LOG_CHANNEL,
                    f"🗑 <b>ALL FILES DELETED</b>\n\n"
                    f"👤 Admin: {message.from_user.mention}\n"
                    f"🗑 Deleted: <code>{count}</code> files\n"
                    f"🕒 Time: <code>{fmt(datetime.utcnow())}</code>"
                )
            except Exception:
                logging.getLogger(__name__).debug("delete_all_cmd: optional operation failed", exc_info=True)
                pass
        else:
            await msg.edit("❌ Deletion cancelled - incorrect confirmation.")
            
    except asyncio.TimeoutError:
        await msg.edit("❌ Deletion cancelled - timeout (30s).")
    except Exception as e:
        await msg.edit(f"❌ Error: {html.escape(str(e))}")
    finally:
        DELETE_ALL_PENDING.pop(key, None)
        DELETE_ALL_OWNERS.discard(owner_key)
        for task in (listener, cancelled):
            if not task.done():
                task.cancel()
        await asyncio.gather(listener, cancelled, return_exceptions=True)


@Client.on_callback_query(filters.regex("^deleteall_cancel$"))
async def cancel_delete_all(_, query: CallbackQuery):
    key = (query.message.chat.id, query.message.id)
    pending = DELETE_ALL_PENDING.get(key)
    if not pending:
        return await query.answer("Confirmation expired or deletion already started", show_alert=True)
    if query.from_user.id != pending[0]:
        return await query.answer("Only the requesting admin can cancel", show_alert=True)
    pending[1].set()
    await query.answer("Cancelled")
    await query.message.edit("❌ Deletion cancelled.")


# ======================================================
# 🔐 CLOSE CALLBACK
# ======================================================

@Client.on_callback_query(filters.regex("^(?:close_data|close_file)$"))
async def close_callback(_, query: CallbackQuery):
    msg = query.message
    key = (msg.chat.id, msg.id)
    if msg.chat.id != query.from_user.id:
        # Reject copied, stale or substituted callbacks on shared messages.
        rows = getattr(msg.reply_markup, "inline_keyboard", ())
        if not any(b.callback_data == query.data for row in rows for b in row):
            return await safe_answer(query, "Button unavailable.", alert=True)
        if query.data == "close_file":
            delivery = temp.FILES.get(key)
            if not delivery or delivery[0] != query.from_user.id:
                return await safe_answer(query, "Only the original requester can close this file.", alert=True)
    await msg.delete()
    temp.FILES.pop(key, None)
    discard_batch_offer(*key)
    await safe_answer(query, "✅ Closed")
