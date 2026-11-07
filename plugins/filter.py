import asyncio
import hashlib
from math import ceil
from time import time
from collections import defaultdict

from hydrogram import Client, filters, enums
from hydrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from info import ADMINS
from database.users_chats_db import db
from database.ia_filterdb import get_search_results
from database.runtime_config import runtime_config
from utils import (
    get_size,
    is_premium,
    temp,
    learn_keywords,
    suggest_query,
    premium_required_text,
    premium_buy_markup,
    log_error
)

# Configuration
RESULT_EXPIRE_TIME = 300      # 5 minutes
EXPIRE_DELETE_DELAY = 60      # delete after 1 min
RATE_LIMIT = 5                # searches per minute
RATE_LIMIT_WINDOW = 60        # seconds

# Rate limiting storage
user_search_times = defaultdict(list)

# Callback data storage (to avoid 64-byte limit)
if not hasattr(temp, 'callback_data'):
    temp.callback_data = {}

# Track message activity for auto-expire
if not hasattr(temp, 'message_activity'):
    temp.message_activity = {}


# =====================================================
# 🔧 ADMIN CHECK HELPER
# =====================================================
async def is_group_admin(client, chat_id, user_id):
    """Check if user is admin in the group"""
    try:
        member = await client.get_chat_member(chat_id, user_id)
        return member.status in (
            enums.ChatMemberStatus.ADMINISTRATOR,
            enums.ChatMemberStatus.OWNER
        )
    except:
        return False


# =====================================================
# 🔄 SEARCH TOGGLE COMMANDS (ADMIN ONLY)
# =====================================================
@Client.on_message(filters.group & filters.command("search"))
async def search_toggle(client, message):
    """Toggle search on/off in group - Admin only"""
    try:
        # Check if user is admin
        if not await is_group_admin(client, message.chat.id, message.from_user.id):
            return await message.reply_text(
                "❌ Only group admins can use this command.",
                quote=True
            )
        
        # Get current settings
        settings = await db.get_settings(message.chat.id) or {}
        
        # Check for on/off parameter
        args = message.text.split()
        
        if len(args) < 2:
            # Show current status
            current = settings.get("search", True)
            status = "✅ Enabled" if current else "❌ Disabled"
            
            return await message.reply_text(
                f"🔍 <b>Search Status:</b> {status}\n\n"
                "💡 <b>Usage:</b>\n"
                "• <code>/search on</code> - Enable search\n"
                "• <code>/search off</code> - Disable search",
                quote=True
            )
        
        action = args[1].lower()
        
        if action == "on":
            settings["search"] = True
            await db.update_settings(message.chat.id, settings)
            
            return await message.reply_text(
                "✅ <b>Search Enabled!</b>\n\n"
                "Members can now search for files in this group.",
                quote=True
            )
        
        elif action == "off":
            settings["search"] = False
            await db.update_settings(message.chat.id, settings)
            
            return await message.reply_text(
                "❌ <b>Search Disabled!</b>\n\n"
                "File search has been turned off for this group.\n"
                "Use <code>/search on</code> to enable again.",
                quote=True
            )
        
        else:
            return await message.reply_text(
                "❌ Invalid option. Use:\n"
                "• <code>/search on</code>\n"
                "• <code>/search off</code>",
                quote=True
            )
    
    except Exception as e:
        print(f"Search toggle error: {e}")
        await message.reply_text(
            "❌ An error occurred. Please try again.",
            quote=True
        )


# =====================================================
# 🤖 GROUP PROTECTION (MOVED FROM plugins/group_mgmt.py)
# =====================================================
@Client.on_message(filters.new_chat_members)
async def anti_bot(client, message):
    """Ban any bot a non-admin tries to add to the group"""
    for user in message.new_chat_members:
        if user.is_bot and not await is_group_admin(
            client, message.chat.id, message.from_user.id
        ):
            await client.ban_chat_member(message.chat.id, user.id)


# =====================================================
# 🛠️ GROUP HELP (ADMIN ONLY · MOVED FROM group_mgmt.py)
# =====================================================
@Client.on_message(filters.group & filters.command("help"))
async def help_command(client, message):
    if not await is_group_admin(client, message.chat.id, message.from_user.id):
        return

    help_text = (
        "🛠️ **Admin Help Menu**\n"
        "━━━━━━━━━━━━━━━━━━\n\n"

        "🔍 **File Search:**\n"
        "• `/search` – Show the current status\n"
        "• `/search on` – Enable file search here\n"
        "• `/search off` – Disable file search here\n\n"

        "🤖 **Auto Protection:**\n"
        "• Anti-bot system is enabled\n"
        "• Only admins can add bots\n\n"

        "⚠️ **Note:** `/help` is admin-only"
    )

    await message.reply(help_text)


# =====================================================
# 🛡️ RATE LIMITER
# =====================================================
def is_rate_limited(user_id):
    """Check if user has exceeded search rate limit"""
    now = time()
    # Clean old timestamps
    user_search_times[user_id] = [
        t for t in user_search_times[user_id] 
        if now - t < RATE_LIMIT_WINDOW
    ]
    
    if len(user_search_times[user_id]) >= RATE_LIMIT:
        return True
    
    user_search_times[user_id].append(now)
    return False


# =====================================================
# 🔑 CALLBACK KEY GENERATOR
# =====================================================
def make_callback_key(search, offset, source_chat_id, owner, is_pm):
    """Generate short callback key and store full data"""
    # Create unique hash
    data_str = f"{search}:{offset}:{source_chat_id}:{owner}:{time()}"
    key = hashlib.md5(data_str.encode()).hexdigest()[:12]
    
    # Store full data
    temp.callback_data[key] = {
        'search': search,
        'offset': offset,
        'source_chat_id': source_chat_id,
        'owner': owner,
        'is_pm': is_pm,
        'created_at': time()
    }
    
    # Clean old keys (older than 10 minutes)
    current_time = time()
    temp.callback_data = {
        k: v for k, v in temp.callback_data.items()
        if current_time - v.get('created_at', 0) < 600
    }
    
    return key


# =====================================================
# 🔓 CALLBACK KEY RETRIEVER
# =====================================================
def get_callback_data(key):
    """Retrieve stored callback data"""
    return temp.callback_data.get(key)


# =====================================================
# 🧹 INPUT SANITIZER
# =====================================================
def sanitize_search(text):
    """Sanitize search input"""
    # Remove excessive whitespace
    text = " ".join(text.split())
    
    # Remove potentially problematic characters
    forbidden = ['<', '>', '&', '"', "'"]
    for char in forbidden:
        text = text.replace(char, '')
    
    return text.strip()


# =====================================================
# ⏱️ UPDATE MESSAGE ACTIVITY
# =====================================================
def update_message_activity(message_id):
    """Update last activity time for a message"""
    temp.message_activity[message_id] = time()


# =====================================================
# 📩 MESSAGE HANDLER (✅ FULLY FIXED)
# =====================================================
@Client.on_message(filters.text & filters.incoming & (filters.group | filters.private))
async def filter_handler(client, message):
    try:
        # Ignore commands
        if message.text.startswith("/"):
            return

        user_id = message.from_user.id
        raw_search = message.text.strip().lower()

        # Minimum length check
        if len(raw_search) < 2:
            return

        # ==============================
        # ✅ CHECK: GROUP or PM
        # ==============================
        is_group_chat = message.chat.type in (enums.ChatType.GROUP, enums.ChatType.SUPERGROUP)

        # Admins have every premium right; everyone else is looked up once here
        # (the result is handed to send_results() so the 👑 crown is free)
        user_is_premium = (
            True if user_id in ADMINS else await check_premium(user_id, client)
        )

        # ==============================
        # 📩 PM SEARCH - CHECK PREMIUM FIRST
        # ==============================
        if not is_group_chat:
            if not user_is_premium:
                try:
                    await message.reply_text(
                        premium_required_text(
                            "PM search is only available for premium users."
                        ),
                        reply_markup=premium_buy_markup(),
                        quote=True,
                        parse_mode=enums.ParseMode.HTML,
                    )
                except Exception as e:
                    print(f"Failed to send premium message: {e}")
                    await message.reply_text(
                        "🔒 PM search requires premium subscription.",
                        quote=True
                    )
                return

            # If we reach here, user is premium or admin
            chat_id = user_id
            source_chat_id = 0
            is_pm = True

        # ==============================
        # 🚫 GROUP SEARCH - CHECK IF ENABLED
        # ==============================
        else:
            stg = await db.get_settings(message.chat.id) or {}
            
            # ✅ NEW: Check if search is disabled
            if stg.get("search") is False:
                return

            chat_id = message.chat.id
            source_chat_id = message.chat.id
            is_pm = False

            # Rate limit check for groups (non-premium users only)
            if not user_is_premium:
                if is_rate_limited(user_id):
                    text = (
                        "⚠️ <b>Too many searches!</b>\n\n"
                        "Please wait a moment before searching again.\n\n"
                        "💡 <b>Tip:</b> Premium users get unlimited searches!"
                    )
                    return await message.reply_text(text, quote=True)

        # 🔥 auto-learn keywords (RAM only, ultra fast)
        try:
            learn_keywords(raw_search)
        except Exception as e:
            print(f"Keyword learning error: {e}")

        # 🧹 Sanitize and normalize search
        search = sanitize_search(raw_search)
        
        if not search:
            return

        await send_results(
            client=client,
            chat_id=chat_id,
            owner=user_id,
            search=search,
            offset=0,
            source_chat_id=source_chat_id,
            is_pm=is_pm,
            premium=user_is_premium
        )
    
    except Exception as e:
        log_error("Filter handler", e)
        try:
            await message.reply_text(
                "❌ An error occurred. Please try again.",
                quote=True
            )
        except:
            pass


# =====================================================
# 🔎 SEND / EDIT RESULTS
# =====================================================

async def check_premium(user_id, client):
    """Premium lookup that never raises (DB / network hiccups are not fatal)"""
    try:
        return await is_premium(user_id, client)
    except Exception as e:
        print(f"Premium check error for {user_id}: {e}")
        return False


def build_results_text(files, search, total, page, total_pages, source_chat_id, crown=""):
    """Header + file list of one result page"""
    text = (
        f"{crown}🔎 <b>Search:</b> <code>{search}</code>\n"
        f"🎬 <b>Total Files:</b> <code>{total}</code>\n"
        f"📄 <b>Page:</b> <code>{page} / {total_pages}</code>\n\n"
    )

    for f in files:
        try:
            size = get_size(f.get("file_size", 0))
            file_id = f.get('_id', '')
            file_name = f.get('file_name', 'Unknown')

            link = f"https://t.me/{temp.U_NAME}?start=file_{source_chat_id}_{file_id}"
            text += f"📁 <a href='{link}'>[{size}] {file_name}</a>\n\n"
        except Exception as e:
            print(f"File list error: {e}")
            continue

    return text


def build_nav(search, offset, next_offset, results_per_page, source_chat_id, owner, is_pm):
    """◀️ Prev / Next ▶️ row — None when the page stands alone"""
    nav = []

    if offset > 0:
        previous_offset = max(0, offset - results_per_page)
        callback_key = make_callback_key(
            search, previous_offset, source_chat_id, owner, is_pm
        )
        nav.append(InlineKeyboardButton("◀️ Prev", callback_data=f"page#{callback_key}"))

    if next_offset:
        callback_key = make_callback_key(
            search, offset + results_per_page, source_chat_id, owner, is_pm
        )
        nav.append(InlineKeyboardButton("Next ▶️", callback_data=f"page#{callback_key}"))

    return InlineKeyboardMarkup([nav]) if nav else None


async def send_results(
    client,
    chat_id,
    owner,
    search,
    offset,
    source_chat_id,
    is_pm,
    message=None,
    tried_fallback=False,
    premium=None
):
    try:
        offset = max(0, int(offset))
        # Admin changes apply to the next search/page fetch without restart.
        if is_pm:
            results_per_page = runtime_config.get("RESULTS_PER_PAGE_PM")
        else:
            results_per_page = runtime_config.get("RESULTS_PER_PAGE_GROUP")
        
        files, next_offset, total = await get_search_results(
            search,
            offset=offset,
            max_results=results_per_page
        )

        # ==============================
        # 🧠 SMART FALLBACK (AI-LIKE)
        # ==============================
        if not files and not tried_fallback:
            try:
                alt = suggest_query(search)
                if alt and alt != search:
                    return await send_results(
                        client,
                        chat_id,
                        owner,
                        alt,
                        0,
                        source_chat_id,
                        is_pm,
                        message,
                        True
                    )
            except Exception as e:
                print(f"Fallback suggestion error: {e}")

        if not files:
            text = f"❌ <b>No results found for:</b>\n<code>{search}</code>"
            if message:
                return await message.edit_text(text, parse_mode=enums.ParseMode.HTML)
            return await client.send_message(chat_id, text, parse_mode=enums.ParseMode.HTML)

        # ==============================
        # 📄 PAGE INFO
        # ==============================
        page = (offset // results_per_page) + 1
        total_pages = ceil(total / results_per_page)

        # The crown was decided by the caller; otherwise look it up (pagination)
        if premium is None:
            premium = await check_premium(owner, client)
        crown = "👑 " if premium else ""

        text = build_results_text(
            files, search, total, page, total_pages, source_chat_id, crown
        )

        # -------- PAGINATION --------
        markup = build_nav(
            search, offset, next_offset, results_per_page, source_chat_id, owner, is_pm
        )

        if message:
            # Update existing message
            await message.edit_text(
                text,
                reply_markup=markup,
                disable_web_page_preview=True,
                parse_mode=enums.ParseMode.HTML
            )
            # Update activity time
            update_message_activity(message.id)
        else:
            # Send new message
            msg = await client.send_message(
                chat_id,
                text,
                reply_markup=markup,
                disable_web_page_preview=True,
                parse_mode=enums.ParseMode.HTML
            )
            # Track for auto-expire
            update_message_activity(msg.id)
            asyncio.create_task(auto_expire(msg))
    
    except Exception as e:
        log_error("Send results", e)
        error_text = "❌ An error occurred while fetching results."
        try:
            if message:
                await message.edit_text(error_text)
            else:
                await client.send_message(chat_id, error_text)
        except:
            pass


# =====================================================
# 🔁 PAGINATION CALLBACK (OWNER ONLY)
# =====================================================
@Client.on_callback_query(filters.regex("^page#"))
async def pagination_handler(client, query):
    try:
        _, callback_key = query.data.split("#", 1)
        
        # Retrieve stored data
        callback_data = get_callback_data(callback_key)
        
        if not callback_data:
            return await query.answer(
                "⌛ This result has expired. Please search again.",
                show_alert=True
            )
        
        search = callback_data['search']
        offset = callback_data['offset']
        source_chat_id = callback_data['source_chat_id']
        owner = callback_data['owner']
        is_pm = callback_data.get('is_pm', False)

        # Owner verification
        if query.from_user.id != owner and query.from_user.id not in ADMINS:
            return await query.answer("❌ Not your result", show_alert=True)

        await query.answer()

        # Update activity - user is interacting
        update_message_activity(query.message.id)

        await send_results(
            client,
            query.message.chat.id,
            owner,
            search,
            offset,
            source_chat_id,
            is_pm,
            query.message
        )
    
    except Exception as e:
        log_error("Pagination handler", e)
        try:
            await query.answer("❌ An error occurred", show_alert=True)
        except:
            pass


# =====================================================
# ⏱ AUTO EXPIRE (SMART DELETE)
# =====================================================
async def auto_expire(message):
    """
    Auto-expire message after RESULT_EXPIRE_TIME of inactivity
    If user clicks Next/Prev, timer resets
    """
    try:
        message_id = message.id
        
        while True:
            await asyncio.sleep(RESULT_EXPIRE_TIME)
            
            # Check if there was recent activity
            last_activity = temp.message_activity.get(message_id, time())
            time_since_activity = time() - last_activity
            
            # If activity within expire time, reset timer
            if time_since_activity < RESULT_EXPIRE_TIME:
                continue
            
            # No activity for RESULT_EXPIRE_TIME, expire now
            break
        
        # Remove buttons and show expired message
        try:
            await message.edit_reply_markup(None)
            await message.edit_text("⌛ <i>This result has expired.</i>")
        except Exception as e:
            print(f"Expire edit error: {e}")
            # Clean up tracking
            temp.message_activity.pop(message_id, None)
            return

        # Wait before deletion
        await asyncio.sleep(EXPIRE_DELETE_DELAY)
        
        # Delete message
        try:
            await message.delete()
        except Exception as e:
            print(f"Expire delete error: {e}")
        
        # Clean up tracking
        temp.message_activity.pop(message_id, None)
    
    except Exception as e:
        print(f"Auto expire error: {e}")
        # Clean up on error
        temp.message_activity.pop(message.id, None)
