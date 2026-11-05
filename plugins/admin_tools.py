import asyncio
import time
from datetime import datetime
from hydrogram import Client, filters, enums
from hydrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from hydrogram.errors import MessageNotModified, MessageIdInvalid, BadRequest, ListenerTimeout

from info import ADMINS, LOG_CHANNEL
from database.users_chats_db import db
from database.ia_filterdb import (
    db_count_documents,
    delete_files,
    delete_all_files,
)
from utils import get_size, get_readable_time, fmt, temp


# ======================================================
# 🧠 CONFIG & SAFE INIT
# ======================================================

# Safe init
if not hasattr(temp, "INDEX_STATS"):
    temp.INDEX_STATS = {"running": False, "start": 0, "saved": 0}

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
#    The old admin-panel command used to carry 💎 Premium / 🗑 Files /
#    🔄 Refresh / ♻️ Restart buttons. Every one of them only opened a
#    screen that repeated a command, so that command was replaced by
#    /stats, which is pure text: live stats plus the command list.
# ======================================================

async def build_stats():
    stats = {
        "users": 0,
        "chats": 0,
        "files": 0,
        "premium": 0,
        "used_data": "0 B",
        "uptime": "N/A",
        "now": datetime.fromtimestamp(time.time()).strftime("%d %b %Y, %I:%M %p")
    }

    try:
        stats["users"] = await db.total_users_count()
    except:
        pass

    try:
        stats["chats"] = await asyncio.to_thread(db.groups.count_documents, {})
    except:
        pass

    try:
        stats["files"] = await asyncio.to_thread(db_count_documents)
    except:
        pass

    try:
        stats["premium"] = await asyncio.to_thread(
            db.premium.count_documents, {"plan.premium": True}
        )
    except:
        pass

    try:
        info = await asyncio.to_thread(db.users.database.command, "dbstats")
        stats["used_data"] = get_size(info.get("dataSize", 0))
    except:
        pass

    try:
        stats["uptime"] = get_readable_time(time.time() - temp.START_TIME)
    except:
        pass

    idx_text = "❌ Not running"
    try:
        idx = temp.INDEX_STATS
        if idx.get("running"):
            dur = max(1, time.time() - idx.get("start", time.time()))
            speed = idx.get("saved", 0) / dur
            idx_text = f"🚀 {speed:.2f} files/sec"
    except:
        pass

    return (
        "📊 <b>BOT STATISTICS</b>\n\n"
        f"👤 <b>Users</b>        : <code>{stats['users']}</code>\n"
        f"👥 <b>Groups</b>       : <code>{stats['chats']}</code>\n"
        f"📦 <b>Indexed Files</b>: <code>{stats['files']}</code>\n"
        f"💎 <b>Premium Users</b>: <code>{stats['premium']}</code>\n\n"
        f"⚡ <b>Index Speed</b>  : <code>{idx_text}</code>\n"
        f"🗃 <b>DB Size</b>      : <code>{stats['used_data']}</code>\n\n"
        f"⏱ <b>Uptime</b>       : <code>{stats['uptime']}</code>\n"
        f"🔄 <b>Updated</b>      : <code>{stats['now']}</code>\n\n"
        "⌨️ <b>Commands</b>\n"
        "💎 <code>/addpremium user_id days</code>\n"
        "⏳ <code>/extendpremium user_id days</code>\n"
        "➖ <code>/removepremium user_id</code>\n"
        "🗑 <code>/delete keyword</code>\n"
        "🗑 <code>/deleteall</code>\n"
        "🖼 <code>/warmup_thumbs</code>\n"
        "📁 Indexing – forward a channel post or send a t.me link in PM"
    )


# ======================================================
# 📊 /stats COMMAND — STATS + COMMANDS (NO BUTTONS)
# ======================================================

@Client.on_message(filters.command("stats") & filters.user(ADMINS))
async def stats_cmd(bot, message):
    """Live counters + the admin command list (replaces the old panel)"""
    msg = await message.reply("⏳ Collecting stats...")
    await safe_edit(msg, await build_stats())


# ======================================================
# 🗑 DELETE FILES COMMAND
# ======================================================

@Client.on_message(filters.command("delete") & filters.user(ADMINS))
async def delete_cmd(bot, message):
    if len(message.command) < 2:
        return await message.reply(
            "❌ <b>Usage:</b> <code>/delete keyword</code>\n\n"
            "This will delete all files matching the keyword."
        )

    key = message.text.split(" ", 1)[1].strip()
    msg = await message.reply(f"⏳ Deleting files for `{key}`...")
    
    try:
        count = await delete_files(key)
        await msg.edit(
            f"✅ <b>Files Deleted</b>\n\n"
            f"🗑 Deleted: <code>{count}</code> files\n"
            f"🔍 Keyword: <code>{key}</code>\n"
            f"🕒 Time: <code>{fmt(datetime.utcnow())}</code>"
        )
        
        # Log to channel
        try:
            await bot.send_message(
                LOG_CHANNEL,
                f"🗑 <b>Files Deleted</b>\n\n"
                f"👤 Admin: {message.from_user.mention}\n"
                f"🔍 Keyword: <code>{key}</code>\n"
                f"🗑 Deleted: <code>{count}</code> files\n"
                f"🕒 Time: <code>{fmt(datetime.utcnow())}</code>"
            )
        except:
            pass
            
    except Exception as e:
        await msg.edit(f"❌ Error: {e}")


# ======================================================
# 🗑 DELETE ALL FILES COMMAND (Alternative)
# ======================================================

@Client.on_message(filters.command("deleteall") & filters.user(ADMINS))
async def delete_all_cmd(bot, message):
    file_count = await asyncio.to_thread(db_count_documents)
    
    msg = await message.reply(
        f"⚠️ <b>WARNING: Delete ALL Files</b>\n\n"
        f"📦 Total Files: <code>{file_count}</code>\n\n"
        f"❗ This will permanently delete ALL {file_count} files!\n\n"
        "Reply with 'CONFIRM DELETE ALL' to proceed.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Cancel", callback_data="close_data")]
        ])
    )
    
    try:
        # Wait for confirmation reply
        response = await bot.listen(message.chat.id, filters=filters.text, timeout=30)
        
        if response.text.strip().upper() == "CONFIRM DELETE ALL":
            await response.delete()
            await msg.edit("⏳ Deleting all files...")
            
            count = await delete_all_files()
            
            await msg.edit(
                f"✅ <b>Successfully Deleted ALL Files</b>\n\n"
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
            except:
                pass
        else:
            await msg.edit("❌ Deletion cancelled - incorrect confirmation.")
            
    except ListenerTimeout:
        await msg.edit("❌ Deletion cancelled - timeout (30s).")
    except Exception as e:
        await msg.edit(f"❌ Error: {e}")


# ======================================================
# 🔐 CLOSE CALLBACK
# ======================================================

@Client.on_callback_query(filters.regex("^close_data$"))
async def close_callback(_, query: CallbackQuery):
    await query.message.delete()
    await safe_answer(query, "✅ Closed")
