import random
import asyncio

from hydrogram import Client, enums
from hydrogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
    InputMediaPhoto
)
from hydrogram.errors import (
    MessageNotModified,
    MessageIdInvalid,
    MessageDeleteForbidden,
    QueryIdInvalid,
    BadRequest
)

from info import ADMINS, PICS, URL, BIN_CHANNEL
from Script import script

from utils import is_premium, temp  # ✅ REMOVED: get_wish
from stream_security import sign_params, USER_LINK_TTL


# ======================================================
# 🛡 SAFE EDIT HELPERS (IMPROVED)
# ======================================================

def has_media(msg) -> bool:
    """True when `msg` carries media (photo / video / ...), i.e. it has a caption.

    /start replies with a photo, but its fallback (and /help) sends plain text,
    so the same help menu must be able to edit both kinds of message.
    """
    if getattr(msg, "media", None):
        return True
    return any(
        getattr(msg, key, None)
        for key in ("photo", "video", "animation", "audio", "document")
    )


async def safe_edit_media(msg, media, reply_markup=None, max_retries=3):
    """Safely edit message media with retry logic"""
    for attempt in range(max_retries):
        try:
            await msg.edit_media(media=media, reply_markup=reply_markup)
            return True
        except MessageNotModified:
            return True  # Already in desired state
        except (MessageIdInvalid, BadRequest) as e:
            print(f"Edit media error (attempt {attempt + 1}): {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(0.5)
            else:
                return False
        except Exception as e:
            print(f"Unexpected edit media error: {e}")
            return False
    return False


async def safe_edit_caption(
    msg,
    caption,
    reply_markup=None,
    parse_mode=enums.ParseMode.HTML,
    max_retries=3,
):
    """Safely edit message caption with retry logic"""
    for attempt in range(max_retries):
        try:
            await msg.edit_caption(caption, parse_mode=parse_mode, reply_markup=reply_markup)
            return True
        except MessageNotModified:
            return True  # Already in desired state
        except (MessageIdInvalid, BadRequest) as e:
            print(f"Edit caption error (attempt {attempt + 1}): {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(0.5)
            else:
                return False
        except Exception as e:
            print(f"Unexpected edit caption error: {e}")
            return False
    return False


async def safe_edit_text(
    msg,
    text,
    reply_markup=None,
    parse_mode=enums.ParseMode.HTML,
    max_retries=3,
):
    """Safely edit a plain (non-media) message with retry logic"""
    for attempt in range(max_retries):
        try:
            await msg.edit_text(text, parse_mode=parse_mode, reply_markup=reply_markup)
            return True
        except MessageNotModified:
            return True  # Already in desired state
        except (MessageIdInvalid, BadRequest) as e:
            print(f"Edit text error (attempt {attempt + 1}): {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(0.5)
            else:
                return False
        except Exception as e:
            print(f"Unexpected edit text error: {e}")
            return False
    return False


CAPTION_LIMIT = 1024  # Telegram's limit for photo / video captions


async def safe_edit_body(
    msg,
    text,
    reply_markup=None,
    parse_mode=enums.ParseMode.HTML,
    max_retries=3,
):
    """Edit a message in place — its caption when it has media, its text otherwise.

    A caption holds only 1024 characters, so a longer list is sent as a new
    message instead of failing with a silent BadRequest.
    """
    if has_media(msg):
        if len(text.encode("utf-16-le")) // 2 > CAPTION_LIMIT:
            try:
                await msg.reply_text(text, parse_mode=parse_mode, reply_markup=reply_markup)
                return True
            except Exception as e:
                print(f"Long text fallback error: {e}")
                return False
        return await safe_edit_caption(
            msg, text, reply_markup=reply_markup,
            parse_mode=parse_mode, max_retries=max_retries,
        )
    return await safe_edit_text(
        msg, text, reply_markup=reply_markup,
        parse_mode=parse_mode, max_retries=max_retries,
    )


# ======================================================
# 🔘 HELP MENU BUTTONS
# ======================================================

def help_buttons(is_admin: bool = False):
    """Buttons of the help menu — 🛡️ Admin Commands only for bot admins."""
    rows = [[InlineKeyboardButton("👤 User Commands", callback_data="user_cmds")]]
    if is_admin:
        rows[0].append(
            InlineKeyboardButton("🛡️ Admin Commands", callback_data="admin_cmds")
        )
    rows.append([InlineKeyboardButton("❌ Close", callback_data="close_data")])
    return InlineKeyboardMarkup(rows)


def back_buttons():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🔙 Back", callback_data="help")],
            [InlineKeyboardButton("❌ Close", callback_data="close_data")],
        ]
    )


async def safe_edit_markup(msg, reply_markup, max_retries=3):
    """Safely edit reply markup with retry logic"""
    for attempt in range(max_retries):
        try:
            await msg.edit_reply_markup(reply_markup)
            return True
        except MessageNotModified:
            return True  # Already in desired state
        except (MessageIdInvalid, BadRequest) as e:
            print(f"Edit markup error (attempt {attempt + 1}): {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(0.5)
            else:
                return False
        except Exception as e:
            print(f"Unexpected edit markup error: {e}")
            return False
    return False


async def safe_delete_message(msg, delay=0):
    """Safely delete a message with optional delay"""
    try:
        if delay > 0:
            await asyncio.sleep(delay)
        await msg.delete()
        return True
    except (MessageIdInvalid, MessageDeleteForbidden) as e:
        print(f"Delete message error: {e}")
        return False
    except Exception as e:
        print(f"Unexpected delete error: {e}")
        return False


async def safe_answer_query(query, text="", show_alert=False, max_retries=2):
    """Safely answer callback query"""
    for attempt in range(max_retries):
        try:
            await query.answer(text, show_alert=show_alert)
            return True
        except QueryIdInvalid:
            print("Query already answered or expired")
            return False
        except Exception as e:
            print(f"Answer query error (attempt {attempt + 1}): {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(0.3)
            else:
                return False
    return False


# ======================================================
# 🔁 CALLBACK HANDLER (OPTIMIZED)
# ======================================================

@Client.on_callback_query()
async def cb_handler(client: Client, query: CallbackQuery):
    """Main callback query handler with comprehensive error handling"""
    
    try:
        data = query.data
        uid = query.from_user.id

        # --------------------------------------------------
        # ❗ PAGINATION (filter.py handles)
        # --------------------------------------------------
        if data.startswith("page#") or data == "pages":
            await safe_answer_query(query)
            return

        # ==================================================
        # ❌ CLOSE FILE (OWNER ONLY)
        # ==================================================
        if data == "close_data":
            await safe_answer_query(query, "Closed")

            # Find and cleanup user's file entry
            target_key = None
            for k, v in temp.FILES.items():
                if v.get("owner") == uid:
                    target_key = k
                    break

            if target_key:
                mem = temp.FILES.pop(target_key, None)
                
                if mem:
                    # Cancel any pending tasks
                    if "task" in mem:
                        try:
                            if not mem["task"].done():
                                mem["task"].cancel()
                        except Exception as e:
                            print(f"Task cancel error: {e}")

                    # Delete file message
                    if "file" in mem:
                        await safe_delete_message(mem["file"])

                    # Delete notice message
                    if "notice" in mem:
                        await safe_delete_message(mem["notice"])

            # Delete callback message and its reply
            await safe_delete_message(query.message)
            
            if query.message.reply_to_message:
                await safe_delete_message(query.message.reply_to_message)
            
            return

        # ==================================================
        # ▶️ STREAM (OWNER + PREMIUM)
        # ==================================================
        if data.startswith("stream#"):
            try:
                file_id = data.split("#", 1)[1]
            except IndexError:
                await safe_answer_query(query, "❌ Invalid data", show_alert=True)
                return

            # Check ownership
            owned = False
            for v in temp.FILES.values():
                if v.get("owner") == uid and v.get("file_id") == file_id:
                    owned = True
                    break

            if not owned:
                await safe_answer_query(
                    query,
                    "❌ This file is not for you",
                    show_alert=True
                )
                return

            # Check premium status
            try:
                user_is_premium = await is_premium(uid, client)
            except Exception as e:
                print(f"Premium check error: {e}")
                user_is_premium = False

            if not user_is_premium:
                await safe_answer_query(
                    query,
                    "🔒 Premium only feature.\nUse /plan to upgrade.",
                    show_alert=True
                )
                return

            # Generate stream links
            try:
                msg = await client.send_cached_media(
                    chat_id=BIN_CHANNEL,
                    file_id=file_id
                )

                # 🔐 Signed stream links (the same links the web search page creates)
                signed = sign_params(msg.id, USER_LINK_TTL)
                watch = f"{URL}watch/{msg.id}?{signed}"
                download = f"{URL}download/{msg.id}?{signed}"

                success = await safe_edit_markup(
                    query.message,
                    InlineKeyboardMarkup(
                        [
                            [
                                InlineKeyboardButton("▶️ Watch Online", url=watch),
                                InlineKeyboardButton("⬇️ Fast Download", url=download)
                            ],
                            [InlineKeyboardButton("❌ Close", callback_data="close_data")]
                        ]
                    )
                )
                
                if success:
                    await safe_answer_query(query, "✅ Links ready")
                else:
                    await safe_answer_query(query, "⚠️ Failed to update message", show_alert=True)
                
            except Exception as e:
                print(f"Stream generation error: {e}")
                await safe_answer_query(
                    query,
                    "❌ Failed to generate stream links",
                    show_alert=True
                )
            
            return

        # ==================================================
        # 🆘 HELP (USER / ADMIN COMMANDS)
        # ==================================================
        if data == "help":
            try:
                caption = script.HELP_TXT.format(query.from_user.mention)
                buttons = help_buttons(uid in ADMINS)
                pic = random.choice(PICS) if PICS else None

                if pic and has_media(query.message):
                    success = await safe_edit_media(
                        query.message,
                        InputMediaPhoto(
                            pic,
                            caption=caption,
                            parse_mode=enums.ParseMode.HTML
                        ),
                        reply_markup=buttons
                    )
                else:
                    success = await safe_edit_body(
                        query.message,
                        caption,
                        reply_markup=buttons
                    )
                
                if success:
                    await safe_answer_query(query)
                else:
                    await safe_answer_query(query, "⚠️ Failed to load help", show_alert=True)
                    
            except Exception as e:
                print(f"Help callback error: {e}")
                await safe_answer_query(query, "❌ Error loading help", show_alert=True)
            
            return

        # ==================================================
        # 👤 USER COMMANDS
        # ==================================================
        if data == "user_cmds":
            try:
                success = await safe_edit_body(
                    query.message,
                    script.USER_COMMAND_TXT,
                    reply_markup=back_buttons()
                )
                
                if success:
                    await safe_answer_query(query)
                else:
                    await safe_answer_query(query, "⚠️ Failed to load commands", show_alert=True)
                    
            except Exception as e:
                print(f"User commands error: {e}")
                await safe_answer_query(query, "❌ Error loading commands", show_alert=True)
            
            return

        # ==================================================
        # 🛡️ ADMIN COMMANDS
        # ==================================================
        if data == "admin_cmds":
            if uid not in ADMINS:
                await safe_answer_query(query, "⚠️ Admins only", show_alert=True)
                return

            try:
                success = await safe_edit_body(
                    query.message,
                    script.ADMIN_COMMAND_TXT,
                    reply_markup=back_buttons()
                )
                
                if success:
                    await safe_answer_query(query)
                else:
                    await safe_answer_query(query, "⚠️ Failed to load commands", show_alert=True)
                    
            except Exception as e:
                print(f"Admin commands error: {e}")
                await safe_answer_query(query, "❌ Error loading commands", show_alert=True)
            
            return

        # ==================================================
        # ❓ UNKNOWN ACTION
        # ==================================================
        await safe_answer_query(query, "⚠️ Unknown action")
    
    except Exception as e:
        print(f"Callback handler main error: {e}")
        try:
            await safe_answer_query(query, "❌ An error occurred", show_alert=True)
        except:
            pass
