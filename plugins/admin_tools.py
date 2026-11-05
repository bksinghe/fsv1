import os
import sys
import time
import asyncio
from datetime import datetime, timedelta
from collections import defaultdict

from hydrogram import Client, filters, enums
from hydrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from hydrogram.errors import MessageNotModified, MessageIdInvalid, BadRequest, ListenerTimeout

from info import ADMINS, LOG_CHANNEL
from database.users_chats_db import db
from database.ia_filterdb import db_count_documents, delete_files, delete_all_files, delete_by_quality
from utils import get_size, get_readable_time, temp


# ======================================================
# 🧠 CONFIG & SAFE INIT
# ======================================================

DASH_LOCKS = defaultdict(asyncio.Lock)

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


def fmt(dt):
    """Format datetime"""
    if isinstance(dt, (int, float)):
        dt = datetime.utcfromtimestamp(dt)
    return dt.strftime("%d %b %Y, %I:%M %p")


def get_expiry_datetime(expire):
    """`expire` is a timestamp in newer plans and a datetime in older ones"""
    if isinstance(expire, (int, float)):
        return datetime.utcfromtimestamp(expire)
    return expire


# ======================================================
# 📊 DASHBOARD BUILDER
# ======================================================

async def build_dashboard():
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
        "📊 <b>ADMIN CONTROL PANEL</b>\n\n"
        f"👤 <b>Users</b>        : <code>{stats['users']}</code>\n"
        f"👥 <b>Groups</b>       : <code>{stats['chats']}</code>\n"
        f"📦 <b>Indexed Files</b>: <code>{stats['files']}</code>\n"
        f"💎 <b>Premium Users</b>: <code>{stats['premium']}</code>\n\n"
        f"⚡ <b>Index Speed</b>  : <code>{idx_text}</code>\n"
        f"🗃 <b>DB Size</b>      : <code>{stats['used_data']}</code>\n\n"
        f"⏱ <b>Uptime</b>       : <code>{stats['uptime']}</code>\n"
        f"🔄 <b>Updated</b>      : <code>{stats['now']}</code>"
    )


# ======================================================
# 🎛 MAIN ADMIN PANEL BUTTONS
# ======================================================

def admin_panel_buttons():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💎 Premium", callback_data="admin_premium"),
            InlineKeyboardButton("🗑 Delete Files", callback_data="admin_delete")
        ],
        [
            InlineKeyboardButton("🔄 Refresh", callback_data="admin_refresh"),
            InlineKeyboardButton("🔄 Restart Bot", callback_data="admin_restart")
        ],
        [
            InlineKeyboardButton("❌ Close", callback_data="close_data")
        ]
    ])


def premium_panel_buttons():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("➕ Add", callback_data="prm_add"),
            InlineKeyboardButton("➖ Remove", callback_data="prm_remove"),
            InlineKeyboardButton("⏳ Extend", callback_data="prm_extend")
        ],
        [
            InlineKeyboardButton("🔍 Check User", callback_data="prm_check")
        ],
        [
            InlineKeyboardButton("⏰ Expiring 3d", callback_data="prm_exp_3"),
            InlineKeyboardButton("⏰ 7d", callback_data="prm_exp_7"),
            InlineKeyboardButton("⏰ 30d", callback_data="prm_exp_30")
        ],
        [
            InlineKeyboardButton("📊 Expiry Chart", callback_data="prm_chart")
        ],
        [
            InlineKeyboardButton("🔙 Back", callback_data="admin_back")
        ]
    ])


def delete_panel_buttons():
    """Delete files management panel"""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔍 Delete by Keyword", callback_data="del_keyword"),
            InlineKeyboardButton("📹 Delete by Quality", callback_data="del_quality")
        ],
        [
            InlineKeyboardButton("🗑 Delete ALL Files", callback_data="del_all_confirm")
        ],
        [
            InlineKeyboardButton("🔙 Back", callback_data="admin_back")
        ]
    ])


def delete_quality_buttons():
    """Quality selection for deletion"""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("360p", callback_data="delq_360p"),
            InlineKeyboardButton("480p", callback_data="delq_480p"),
            InlineKeyboardButton("720p", callback_data="delq_720p")
        ],
        [
            InlineKeyboardButton("1080p", callback_data="delq_1080p"),
            InlineKeyboardButton("1440p", callback_data="delq_1440p"),
            InlineKeyboardButton("2160p", callback_data="delq_2160p")
        ],
        [
            InlineKeyboardButton("🔙 Back", callback_data="admin_delete")
        ]
    ])


# ======================================================
# 🚀 /admin COMMAND - UNIFIED PANEL
# ======================================================

@Client.on_message(filters.command(["admin", "dashboard"]) & filters.user(ADMINS))
async def open_admin_panel(bot, message):
    msg = await message.reply("⏳ Loading admin panel...")
    text = await build_dashboard()
    await safe_edit(msg, text, reply_markup=admin_panel_buttons())


# ======================================================
# 🔁 MAIN ADMIN CALLBACKS
# ======================================================

@Client.on_callback_query(filters.regex("^admin_"))
async def admin_callbacks(bot, query: CallbackQuery):
    if query.from_user.id not in ADMINS:
        return await safe_answer(query, "Admins only", True)

    action = query.data

    # Dashboard refresh
    if action == "admin_refresh":
        async with DASH_LOCKS[query.from_user.id]:
            text = await build_dashboard()
            await safe_edit(query.message, text, reply_markup=admin_panel_buttons())
            await safe_answer(query, "✅ Updated")

    # Premium panel
    elif action == "admin_premium":
        total = db.premium.count_documents({"plan.premium": True})
        await safe_edit(
            query.message,
            (
                "💎 <b>Premium Management Panel</b>\n\n"
                f"👤 Active Premium : <code>{total}</code>\n"
                f"🕒 Time : <code>{fmt(datetime.utcnow())}</code>"
            ),
            reply_markup=premium_panel_buttons()
        )
        await safe_answer(query)

    # Delete files panel
    elif action == "admin_delete":
        file_count = await asyncio.to_thread(db_count_documents)
        await safe_edit(
            query.message,
            "🗑 <b>Delete Files Management</b>\n\n"
            f"📦 Total Files: <code>{file_count}</code>\n\n"
            "Choose deletion method:",
            reply_markup=delete_panel_buttons()
        )
        await safe_answer(query)

    # Restart bot
    elif action == "admin_restart":
        await safe_answer(query, "🔄 Restarting bot...", True)
        await safe_edit(query.message, "⏳ Restarting...")
        try:
            os.execl(sys.executable, sys.executable, "bot.py")
        except Exception as e:
            await safe_edit(query.message, f"❌ Restart failed: {e}")

    # Back to main panel
    elif action == "admin_back":
        text = await build_dashboard()
        await safe_edit(query.message, text, reply_markup=admin_panel_buttons())
        await safe_answer(query)


# ======================================================
# 🗑 DELETE CALLBACKS
# ======================================================

@Client.on_callback_query(filters.regex("^del_"))
async def delete_callbacks(bot, query: CallbackQuery):
    if query.from_user.id not in ADMINS:
        return await safe_answer(query, "Admins only", True)

    action = query.data

    # Delete by keyword
    if action == "del_keyword":
        await safe_edit(
            query.message,
            "🔍 <b>Delete Files by Keyword</b>\n\n"
            "Use command:\n<code>/delete keyword</code>\n\n"
            "Example: <code>/delete movie_name</code>\n\n"
            "This will delete all files matching the keyword.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Back", callback_data="admin_delete")]]
            )
        )
        await safe_answer(query)

    # Delete by quality
    elif action == "del_quality":
        await safe_edit(
            query.message,
            "📹 <b>Delete Files by Quality</b>\n\n"
            "Select quality to delete all files of that quality:",
            reply_markup=delete_quality_buttons()
        )
        await safe_answer(query)

    # Delete ALL confirmation
    elif action == "del_all_confirm":
        file_count = await asyncio.to_thread(db_count_documents)
        await safe_edit(
            query.message,
            f"⚠️ <b>WARNING: Delete ALL Files</b>\n\n"
            f"📦 Total Files: <code>{file_count}</code>\n\n"
            f"❗ This will permanently delete ALL {file_count} files from the database!\n\n"
            "Are you absolutely sure?",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ Yes, Delete ALL", callback_data="del_all_execute"),
                    InlineKeyboardButton("❌ Cancel", callback_data="admin_delete")
                ]
            ])
        )
        await safe_answer(query)

    # Execute delete ALL
    elif action == "del_all_execute":
        await safe_answer(query, "🗑 Deleting all files...", True)
        msg = await query.message.edit("⏳ Deleting all files from database...")
        
        try:
            count = await delete_all_files()
            await msg.edit(
                f"✅ <b>Successfully Deleted ALL Files</b>\n\n"
                f"🗑 Deleted: <code>{count}</code> files\n"
                f"🕒 Time: <code>{fmt(datetime.utcnow())}</code>",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🔙 Back to Dashboard", callback_data="admin_back")]]
                )
            )
            
            # Log to channel
            try:
                await bot.send_message(
                    LOG_CHANNEL,
                    f"🗑 <b>ALL FILES DELETED</b>\n\n"
                    f"👤 Admin: {query.from_user.mention}\n"
                    f"🗑 Deleted: <code>{count}</code> files\n"
                    f"🕒 Time: <code>{fmt(datetime.utcnow())}</code>"
                )
            except:
                pass
                
        except Exception as e:
            await msg.edit(f"❌ Error deleting files: {e}")


# ======================================================
# 📹 DELETE BY QUALITY CALLBACKS
# ======================================================

@Client.on_callback_query(filters.regex("^delq_"))
async def delete_quality_callbacks(bot, query: CallbackQuery):
    if query.from_user.id not in ADMINS:
        return await safe_answer(query, "Admins only", True)

    quality = query.data.replace("delq_", "")
    
    await safe_answer(query, f"🗑 Deleting {quality} files...", True)
    msg = await query.message.edit(f"⏳ Deleting all {quality} files...")
    
    try:
        count = await delete_by_quality(quality)
        await msg.edit(
            f"✅ <b>Deleted {quality} Files</b>\n\n"
            f"🗑 Deleted: <code>{count}</code> files\n"
            f"📹 Quality: <code>{quality}</code>\n"
            f"🕒 Time: <code>{fmt(datetime.utcnow())}</code>",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Back", callback_data="admin_delete")]]
            )
        )
        
        # Log to channel
        try:
            await bot.send_message(
                LOG_CHANNEL,
                f"🗑 <b>Files Deleted by Quality</b>\n\n"
                f"👤 Admin: {query.from_user.mention}\n"
                f"📹 Quality: <code>{quality}</code>\n"
                f"🗑 Deleted: <code>{count}</code> files\n"
                f"🕒 Time: <code>{fmt(datetime.utcnow())}</code>"
            )
        except:
            pass
            
    except Exception as e:
        await msg.edit(f"❌ Error: {e}")


# ======================================================
# 💎 PREMIUM CALLBACKS
# ======================================================

@Client.on_callback_query(filters.regex("^prm_"))
async def premium_callbacks(bot, query: CallbackQuery):
    if query.from_user.id not in ADMINS:
        return await safe_answer(query, "Admins only", True)

    action = query.data
    now = datetime.utcnow()

    await safe_answer(query)

    # Expiring soon (3/7/30 days)
    if action.startswith("prm_exp_"):
        days = int(action.split("_")[-1])
        limit = now + timedelta(days=days)

        users = await db.get_premium_users()
        result = []

        for u in users:
            uid = u.get("id")
            if uid in ADMINS:
                continue

            plan = u.get("plan", {})
            expire = plan.get("expire")
            if not expire:
                continue

            if isinstance(expire, (int, float)):
                expire = datetime.utcfromtimestamp(expire)

            if now <= expire <= limit:
                left = int((expire - now).total_seconds())
                result.append(f"👤 <code>{uid}</code> → ⏳ {get_readable_time(left)}")

            if len(result) >= 20:
                break

        if not result:
            await safe_edit(
                query.message,
                f"✅ No premium users expiring in next {days} days.\n\n"
                "Use /admin to return to panel.",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🔙 Back", callback_data="admin_premium")]]
                )
            )
        else:
            await safe_edit(
                query.message,
                f"⏰ <b>Premium Expiring in {days} Days</b>\n\n" + "\n".join(result),
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🔙 Back", callback_data="admin_premium")]]
                )
            )

    # Expiry chart
    elif action == "prm_chart":
        users = await db.get_premium_users()
        c_3 = c_7 = c_30 = c_30p = 0

        for u in users:
            uid = u.get("id")
            if uid in ADMINS:
                continue

            plan = u.get("plan", {})
            expire = plan.get("expire")
            if not expire:
                continue

            if isinstance(expire, (int, float)):
                expire = datetime.utcfromtimestamp(expire)

            days_left = (expire - now).days

            if days_left <= 3:
                c_3 += 1
            elif days_left <= 7:
                c_7 += 1
            elif days_left <= 30:
                c_30 += 1
            else:
                c_30p += 1

        await safe_edit(
            query.message,
            "📊 <b>Premium Expiry Chart</b>\n\n"
            f"🟥 0–3 days   : <code>{c_3}</code>\n"
            f"🟧 4–7 days   : <code>{c_7}</code>\n"
            f"🟨 8–30 days  : <code>{c_30}</code>\n"
            f"🟩 30+ days   : <code>{c_30p}</code>",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Back", callback_data="admin_premium")]]
            )
        )

    # Check user (asks for the ID and listens for it, like /deleteall does)
    elif action == "prm_check":
        back = InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 Back", callback_data="admin_premium")]]
        )

        await safe_edit(
            query.message,
            "🔍 <b>Check Premium Status</b>\n\n"
            "Send the user ID now (60s timeout).",
            reply_markup=back
        )

        try:
            reply = await bot.listen(query.message.chat.id, filters=filters.text, timeout=60)
        except (ListenerTimeout, asyncio.TimeoutError):
            return await safe_edit(
                query.message,
                "⌛ <b>Timed out</b> — no user ID received.",
                reply_markup=back
            )

        if reply is None or not (reply.text or "").strip():
            return await safe_edit(
                query.message,
                "❌ No user ID received.",
                reply_markup=back
            )

        # Remove the ID message so the chat stays clean
        try:
            await reply.delete()
        except Exception:
            pass

        await safe_answer(query)

        raw = (reply.text or "").split()[0] if reply.text else ""
        try:
            target = int(raw)
        except (ValueError, TypeError):
            return await safe_edit(
                query.message,
                f"❌ <code>{raw or 'empty'}</code> is not a valid user ID.",
                reply_markup=back
            )

        if target in ADMINS:
            body = "👑 <b>Bot admin</b> — lifetime premium access."
        else:
            plan = await db.get_plan(target) or {}
            if not plan.get("premium"):
                body = "🆓 <b>No active premium plan.</b>"
            else:
                expire = plan.get("expire")
                exp_dt = get_expiry_datetime(expire) if expire else None
                if exp_dt and exp_dt > datetime.utcnow():
                    left = get_readable_time(
                        int((exp_dt - datetime.utcnow()).total_seconds())
                    )
                    body = (
                        "💎 <b>Premium Active</b>\n\n"
                        f"📦 Plan: <code>{plan.get('plan')}</code>\n"
                        f"⏰ Expires: <code>{fmt(exp_dt)}</code>\n"
                        f"⏳ Remaining: <code>{left}</code>"
                    )
                else:
                    body = "⌛ <b>Premium expired.</b>"

        await safe_edit(
            query.message,
            f"🔍 <b>Premium Status</b>\n\n"
            f"👤 User: <code>{target}</code>\n\n"
            f"{body}",
            reply_markup=back
        )

    # Add premium
    elif action == "prm_add":
        await safe_edit(
            query.message,
            "➕ <b>Add Premium</b>\n\n"
            "Use command:\n<code>/addpremium user_id days</code>\n\n"
            "Example: <code>/addpremium 123456789 30</code>",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Back", callback_data="admin_premium")]]
            )
        )

    # Remove premium
    elif action == "prm_remove":
        await safe_edit(
            query.message,
            "➖ <b>Remove Premium</b>\n\n"
            "Use command:\n<code>/removepremium user_id</code>\n\n"
            "Example: <code>/removepremium 123456789</code>",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Back", callback_data="admin_premium")]]
            )
        )

    # Extend premium
    elif action == "prm_extend":
        await safe_edit(
            query.message,
            "⏳ <b>Extend Premium</b>\n\n"
            "Use command:\n<code>/extendpremium user_id days</code>\n\n"
            "Example: <code>/extendpremium 123456789 15</code>",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Back", callback_data="admin_premium")]]
            )
        )


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
