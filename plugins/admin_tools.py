import asyncio
import time
from datetime import datetime
from hydrogram import Client, filters, enums
from hydrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from hydrogram.errors import MessageNotModified, MessageIdInvalid, BadRequest, ListenerTimeout

from info import ADMINS, LOG_CHANNEL
from database.ia_filterdb import (
    db_count_documents,
    delete_files,
    delete_all_files,
)
from database.stats_db import snapshot
from utils import fmt, temp


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

def _row(emoji, label, value):
    return f"{emoji} <b>{label}</b>: <code>{value}</code>\n"


async def build_stats():
    s = await snapshot()
    queue = s["thumb_queue"]
    groups = (
        f"{s['groups']} (🎞️ {s['quality_groups']} · "
        f"📺 {s['episode_groups']} · 🎬 {s['episodes_total']} eps)"
    )

    return (
        "📊 <b>BOT STATISTICS</b>\n\n"
        + _row("👤", "Users", s["users"])
        + _row("👥", "Groups", s["chats"])
        + _row("📦", "Indexed Files", s["files"])
        + _row("💎", "Premium Users", s["premium"])
        + _row("🗃", "DB Size", s["db_size"])
        + _row("⏱", "Uptime", s["uptime"])
        + "\n🌐 <b>WEB STATISTICS</b>\n\n"
        + _row("🖥", "Server", s["web_state"])
        + _row("🔗", "URL", s["url"])
        + _row("🔌", "Port", s["port"])
        + _row("⏱", "Web Uptime", s["web_uptime"])
        + _row("🧑‍💻", "Web Accounts", s["web_accounts"])
        + _row("🔓", "Live Sessions", s["live_sessions"])
        + _row("📝", "Posts", s["posts"])
        + _row("🎭", "Profiles", s["actors"])
        + _row("🗂", "Catalog Groups", groups)
        + _row("🖼", "Posters", s["thumbnails"])
        + _row("⏳", "Thumb Queue", queue.get("queued", 0))
        + "\n" + _row("🔄", "Updated", s["now"])
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
