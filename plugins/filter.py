import logging
import html
import asyncio
import hashlib
from math import ceil
from time import time
from collections import defaultdict

from pyrogram import Client, filters, enums
from telegram_buttons import styled_button
from pyrogram.types import LinkPreviewOptions, InlineKeyboardMarkup

from info import ADMINS
from database.users_chats_db import db
from database.ia_filterdb import get_search_results
from database import search_expiry
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
RESULTS_PER_PAGE_PM = 12      # 12 results in private messages
RESULTS_PER_PAGE_GROUP = 10   # 10 results in groups
RATE_LIMIT = 5                # searches per minute
RATE_LIMIT_WINDOW = 60        # seconds

# Rate limiting storage
user_search_times = defaultdict(list)

# Callback data storage (to avoid 64-byte limit)
if not hasattr(temp, 'callback_data'):
    temp.callback_data = {}

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
    except Exception:
        logging.getLogger(__name__).debug("is_group_admin: optional operation failed", exc_info=True)
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
            )
        
        action = args[1].lower()
        
        if action == "on":
            settings["search"] = True
            await db.update_settings(message.chat.id, settings)
            
            return await message.reply_text(
                "✅ <b>Search Enabled!</b>\n\n"
                "Members can now search for files in this group.",
            )
        
        elif action == "off":
            settings["search"] = False
            await db.update_settings(message.chat.id, settings)
            
            return await message.reply_text(
                "❌ <b>Search Disabled!</b>\n\n"
                "File search has been turned off for this group.\n"
                "Use <code>/search on</code> to enable again.",
            )
        
        else:
            return await message.reply_text(
                "❌ Invalid option. Use:\n"
                "• <code>/search on</code>\n"
                "• <code>/search off</code>",
            )
    
    except Exception as e:
        print(f"Search toggle error: {e}")
        await message.reply_text(
            "❌ An error occurred. Please try again.",
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
        if is_group_chat and user_id not in ADMINS:
            user_is_premium, stg = await asyncio.gather(
                check_premium(user_id, client), db.get_settings(message.chat.id)
            )
        else:
            user_is_premium = (
                True if user_id in ADMINS else await check_premium(user_id, client)
            )
            stg = await db.get_settings(message.chat.id) if is_group_chat else None

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
                        parse_mode=enums.ParseMode.HTML,
                    )
                except Exception as e:
                    print(f"Failed to send premium message: {e}")
                    await message.reply_text(
                        "🔒 PM search requires premium subscription.",
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
            stg = stg or {}
            
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
                    return await message.reply_text(text)

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
            premium=user_is_premium,
            reply_msg=message
        )
    
    except Exception as e:
        log_error("Filter handler", e)
        try:
            await message.reply_text(
                "❌ An error occurred. Please try again.",
            )
        except Exception:
            logging.getLogger(__name__).debug("filter_handler: optional operation failed", exc_info=True)
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
    """Compact quoted page information followed by clickable file names."""
    text = (
        f"<blockquote><b><i>{html.escape(str(crown))}🎬 Total Files: {total}\n"
        f"📄 Page: {page} / {total_pages}</i></b></blockquote>\n\n"
    )

    for f in files:
        try:
            size = html.escape(str(get_size(f.get("file_size", 0))))
            file_id = f.get('_id', '')
            file_name = html.escape(str(f.get('file_name', 'Unknown')))
            link = f"https://t.me/{temp.U_NAME}?start=file_{source_chat_id}_{file_id}"
            text += f'📁 <a href="{html.escape(link, quote=True)}"><b><i>[{size}] {file_name}</i></b></a>\n\n'
        except Exception as e:
            print(f"File list error: {e}")
            continue

    return text


def build_nav(search, offset, next_offset, results_per_page, source_chat_id, owner, is_pm):
    """◀️ Prev / Next ▶️ row — None when the page stands alone"""
    nav = []

    if offset > 0:
        callback_key = make_callback_key(
            search, offset - results_per_page, source_chat_id, owner, is_pm
        )
        nav.append(styled_button("◀️ Prev", callback_data=f"page#{callback_key}"))

    if next_offset:
        callback_key = make_callback_key(
            search, offset + results_per_page, source_chat_id, owner, is_pm
        )
        nav.append(styled_button("Next ▶️", callback_data=f"page#{callback_key}"))

    return InlineKeyboardMarkup([nav]) if nav else None


async def _send_new(client, chat_id, reply_msg, text, fallback_prefix="", **kwargs):
    """Send a NEW message; quote-reply to the user's message when we have it."""
    if reply_msg is not None:
        try:
            return await reply_msg.reply_text(text, **kwargs)
        except Exception as e:
            # e.g. the user already deleted their message → fall back to a plain send
            logging.getLogger(__name__).debug("quote reply failed, sending plain: %s", e)
    return await client.send_message(chat_id, fallback_prefix + text, **kwargs)


async def _register_expiry(message):
    """Avoid leaving an untracked result visible if MongoDB is unavailable."""
    try:
        await search_expiry.register(message.chat.id, message.id)
    except Exception:
        logging.getLogger(__name__).exception("Could not persist search result expiry")
        try:
            await message.delete()
        except Exception:
            logging.getLogger(__name__).exception("Could not delete untracked search result")


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
    premium=None,
    reply_msg=None
):
    try:
        # Determine results per page based on PM or Group
        results_per_page = RESULTS_PER_PAGE_PM if is_pm else RESULTS_PER_PAGE_GROUP
        
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
                        True,
                        premium=premium,
                        reply_msg=reply_msg
                    )
            except Exception as e:
                print(f"Fallback suggestion error: {e}")

        if not files:
            text = f"❌ <b>No results found for:</b>\n<code>{html.escape(str(search))}</code>"
            if message:
                return await message.edit_text(text, parse_mode=enums.ParseMode.HTML)
            msg = await _send_new(
                client, chat_id, reply_msg, text, parse_mode=enums.ParseMode.HTML
            )
            await _register_expiry(msg)
            return msg

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
                link_preview_options=LinkPreviewOptions(is_disabled=True),
                parse_mode=enums.ParseMode.HTML
            )
        else:
            # Send new message
            msg = await _send_new(
                client,
                chat_id,
                reply_msg,
                text,
                fallback_prefix=f"🔎 <b>Search:</b> <code>{html.escape(str(search))}</code>\n\n",
                reply_markup=markup,
                link_preview_options=LinkPreviewOptions(is_disabled=True),
                parse_mode=enums.ParseMode.HTML
            )
            await _register_expiry(msg)
    
    except Exception as e:
        log_error("Send results", e)
        error_text = "❌ An error occurred while fetching results."
        try:
            if message:
                await message.edit_text(error_text)
            else:
                await client.send_message(chat_id, error_text)
        except Exception:
            logging.getLogger(__name__).debug("send_results: optional operation failed", exc_info=True)
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

        # The atomic touch wins only before expiry is claimed by the worker.
        if not await search_expiry.touch(query.message.chat.id, query.message.id):
            return await query.answer("⌛ This result has expired. Please search again.", show_alert=True)
        await query.answer()

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
        except Exception:
            logging.getLogger(__name__).debug("pagination_handler: optional operation failed", exc_info=True)
            pass
