import asyncio
import html
import logging

from pyrogram import Client, filters, enums
from telegram_buttons import styled_button, styled_keyboard
from pyrogram.types import CallbackQuery

from info import IS_STREAM, PM_FILE_DELETE_TIME, PROTECT_CONTENT
from database.ia_filterdb import get_file_details
from database import search_expiry
from utils import temp, is_premium, premium_required_text, premium_buy_markup


# ======================================================
# CONFIG
# ======================================================
RESEND_EXPIRE_TIME = 60  # seconds

# Track active deletion tasks
active_tasks = {}


# ======================================================
# PREMIUM CHECK WITH GRACE PERIOD
# ======================================================
async def has_premium_or_grace(user_id: int) -> bool:
    """Admin, or premium inside the grace period.

    utils.is_premium() owns that rule (and its 10-minute cache) — this is
    only a thin wrapper so a DB hiccup can never block file delivery.
    """
    try:
        return await is_premium(user_id)
    except Exception as e:
        print(f"Premium check error for {user_id}: {e}")
        return False


# ======================================================
# FILE BUTTON HANDLER (GROUP)
# ======================================================
@Client.on_callback_query(filters.regex(r"^file#"))
async def file_button_handler(client: Client, query: CallbackQuery):
    """A group selection is delivered only to the chat containing the result."""
    msg = query.message
    if not msg or msg.chat.type not in (enums.ChatType.GROUP, enums.ChatType.SUPERGROUP):
        return await query.answer("Open the original group result.", show_alert=True)
    if not await has_premium_or_grace(query.from_user.id):
        return await query.answer("🔒 Premium required to request files. See /plan in PM.", show_alert=True)

    # Do not accept a stale/forged payload or a copy forwarded to another chat.
    rows = getattr(msg.reply_markup, 'inline_keyboard', [])
    if not any(b.callback_data == query.data for row in rows for b in row) or not await search_expiry.touch(msg.chat.id, msg.id):
        return await query.answer("⌛ Result expired. Search again.", show_alert=True)
    file_id = query.data.split("#", 1)[1]
    file = await get_file_details(file_id)
    if not file:
        return await query.answer("❌ File not found", show_alert=True)

    await query.answer()
    try:
        sent = await client.send_cached_media(
            chat_id=msg.chat.id, message_thread_id=msg.message_thread_id,
            reply_to_message_id=msg.id, file_id=file_id, caption=file_caption(file),
            parse_mode=enums.ParseMode.HTML, protect_content=PROTECT_CONTENT,
        )
    except Exception:
        logging.exception("Could not deliver group search result")
        await msg.reply_text("❌ Couldn't send the file here. Check the bot's media permissions.")
        return
    track_expiry(client, sent, msg.chat.id, file_id, group=True)


# ======================================================
# START FILE DELIVERY (PM)
# ======================================================
@Client.on_message(
    filters.private &
    filters.command("start") &
    filters.regex(r"file_"),
    group=1  # Higher priority
)
async def start_file_delivery(client: Client, message):
    """Handle /start file_ commands in PM"""
    try:
        # Parse file command
        _, grp_id, file_id = message.text.split("_", 2)
        grp_id = int(grp_id)
    except Exception:
        return

    uid = message.from_user.id
    
    # ========================================
    # PREMIUM CHECK (Bot Admin or Premium)
    # ========================================
    is_user_premium = await has_premium_or_grace(uid)
    
    if not is_user_premium:
        # Non-premium user tried to access file directly
        text = premium_required_text(
            "Direct file access is only available for premium users."
        )
        btn = premium_buy_markup(close=True)
        
        await message.reply_text(
            text,
            reply_markup=btn,
            parse_mode=enums.ParseMode.HTML
        )
        
        # Delete /start command
        try:
            await message.delete()
        except Exception:
            logging.getLogger(__name__).debug("start_file_delivery: optional operation failed", exc_info=True)
            pass
        return
    
    # ========================================
    # DELIVER FILE TO PREMIUM USER
    # ========================================
    # Cancel previous file task for this user
    user_task_key = f"user_{uid}"
    if user_task_key in active_tasks:
        active_tasks[user_task_key].cancel()

    # Create new delivery task
    task = asyncio.create_task(
        deliver_file(client, uid, grp_id, file_id)
    )
    active_tasks[user_task_key] = task

    # Cleanup callback
    def cleanup_task(t):
        if active_tasks.get(user_task_key) is t:
            active_tasks.pop(user_task_key, None)
    
    task.add_done_callback(cleanup_task)

    # Delete /start command
    try:
        await message.delete()
    except Exception:
        logging.getLogger(__name__).debug("start_file_delivery: optional operation failed", exc_info=True)
        pass


# ======================================================
# SCHEDULE FILE DELETION
# ======================================================
async def schedule_file_deletion(client, sent_msg, uid, file_id, *, group=False):
    """Schedule auto-deletion of file message"""
    message_key = (uid, sent_msg.id)
    
    if not group:
        temp.FILES[message_key] = file_id

    try:
        # Wait for expiry
        await asyncio.sleep(PM_FILE_DELETE_TIME)
        
        # Remove from tracking
        if not group and temp.FILES.pop(message_key, None) is None:
            return  # Closed manually: do not send a resend prompt.
        
        # Delete the file message
        try:
            await sent_msg.delete()
        except Exception:
            logging.getLogger(__name__).debug("schedule_file_deletion: optional operation failed", exc_info=True)
            pass
        
        if group:
            return  # No private stream/resend controls in a shared chat.

        # Send resend button
        resend = await client.send_message(
            uid,
            "⌛ <b>File expired</b>",
            reply_markup=styled_keyboard([
                [styled_button(
                    "🔁 Resend File",
                    callback_data=f"resend#{file_id}"
                )]
            ])
        )
        
        # Auto-delete resend button
        await asyncio.sleep(RESEND_EXPIRE_TIME)
        try:
            await resend.delete()
        except Exception:
            logging.getLogger(__name__).debug("schedule_file_deletion: optional operation failed", exc_info=True)
            pass
            
    except asyncio.CancelledError:
        # Task cancelled, cleanup
        temp.FILES.pop(message_key, None)
        raise


# ======================================================
# CORE FILE DELIVERY
# ======================================================
def file_caption(file):
    name = (file.get("file_name") or "").strip()
    return f"<b>{html.escape(name)}</b>" if name else ""


def track_expiry(client, sent, chat_id, file_id, *, group=False):
    key = (chat_id, sent.id)
    task = asyncio.create_task(schedule_file_deletion(client, sent, chat_id, file_id, group=group))
    active_tasks[key] = task
    task.add_done_callback(lambda _: active_tasks.pop(key, None))


async def deliver_file(client, uid, grp_id, file_id):
    """Deliver file to premium user in PM"""
    try:
        # Get file details
        file = await get_file_details(file_id)
        if not file:
            return

        # Verify premium status again (security check)
        if not await has_premium_or_grace(uid):
            text = premium_required_text(
                "This file is only accessible to premium users."
            )
            btn = premium_buy_markup(close=False)
            
            await client.send_message(
                uid,
                text,
                reply_markup=btn,
                parse_mode=enums.ParseMode.HTML
            )
            return

        # Build buttons
        buttons = []
        if IS_STREAM:
            buttons.append([
                styled_button(
                    "▶️ Watch / Download",
                    callback_data=f"stream#{file_id}"
                )
            ])
        buttons.append([
            styled_button("❌ Close", callback_data="close_data")
        ])

        markup = styled_keyboard(buttons)

        # Send file
        sent = await client.send_cached_media(
            chat_id=uid,
            file_id=file_id,
            caption=file_caption(file),
            parse_mode=enums.ParseMode.HTML,
            protect_content=PROTECT_CONTENT,
            reply_markup=markup
        )

        track_expiry(client, sent, uid, file_id)

    except Exception as e:
        logging.error(f"Error delivering file: {e}")


# ======================================================
# RESEND HANDLER
# ======================================================
@Client.on_callback_query(filters.regex(r"^resend#"))
async def resend_handler(client, query: CallbackQuery):
    """Handle resend file button"""
    file_id = query.data.split("#", 1)[1]
    uid = query.from_user.id

    # Verify premium status
    if not await has_premium_or_grace(uid):
        return await query.answer(
            "🔒 Premium required to resend files",
            show_alert=True
        )

    await query.answer()
    
    # Delete resend message
    try:
        await query.message.delete()
    except Exception:
        logging.getLogger(__name__).debug("resend_handler: optional operation failed", exc_info=True)
        pass

    # Resend file
    asyncio.create_task(deliver_file(client, uid, 0, file_id))
