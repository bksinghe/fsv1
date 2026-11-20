import asyncio
import html
import logging
import re
from dataclasses import dataclass

from pyrogram import Client, filters, enums
from telegram_buttons import styled_button, styled_keyboard
from pyrogram.types import CallbackQuery
from pyrogram.errors import FloodWait

from info import ADMINS, IS_STREAM, PM_FILE_DELETE_TIME, PROTECT_CONTENT
from database.ia_filterdb import get_file_details
from database.group_db import store, episode_label, KIND_EPISODES
from database import search_expiry
from database.users_chats_db import db
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

    if not (await db.get_settings(msg.chat.id)).get("group_mode", False):
        return await query.answer("Group delivery is off. Search again for a PM link.", show_alert=True)

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
        await send_delivery(client, msg.chat.id, query.from_user.id, file_id, file,
                            group=True, topic=msg.message_thread_id)
    except Exception:
        logging.exception("Could not deliver group search result")
        await msg.reply_text("❌ Couldn't send the file here. Check the bot's media permissions.")
        return


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
    def cleanup(_):
        active_tasks.pop(key, None)
        batch_offers.pop(key, None)
    task.add_done_callback(cleanup)


@dataclass(frozen=True)
class BatchOffer:
    owner: int
    seed: str
    gid: str
    label: str


# Offers are scoped to the original delivered message, not to callback data
# supplied by a client. Restart/expiry invalidates them just like stream buttons.
batch_offers = {}
batch_jobs = {}


def discard_batch_offer(chat_id, message_id):
    batch_offers.pop((chat_id, message_id), None)


@Client.on_message(filters.command("sendall") & filters.user(ADMINS))
async def send_all_setting(client, message):
    args = message.command[1:]
    if args and (len(args) != 1 or args[0].lower() not in ("on", "off")):
        return await message.reply_text("Usage: /sendall on or /sendall off")
    try:
        if args:
            enabled = args[0].lower() == "on"
            await db.set_send_all_enabled(enabled)
        else:
            enabled = await db.send_all_enabled()
    except Exception:
        logging.exception("Could not access the Send All setting")
        return await message.reply_text("Could not access the Send All setting. Please retry.")
    await message.reply_text(f"Send All is {'ON' if enabled else 'OFF'} for all PMs and groups.")


async def lookup_offer(owner, fid):
    try:
        if not await db.send_all_enabled():
            return None
        groups = await store.by_members([fid])
        if groups:
            g = groups[0]
            count = len(set(g['members']) - {fid})
            if count:
                label = (f'⚡Send All {count} Episode' if g.get('kind') == KIND_EPISODES
                         else f'♻️Send All {count} Quality')
                return BatchOffer(owner, fid, g['_id'], label)
    except Exception:
        logging.exception("Optional delivery group lookup failed")
    return None


async def send_delivery(client, chat, owner, fid, doc, *, group=False, topic=None, offer_batch=True):
    offer = await lookup_offer(owner, fid) if offer_batch else None
    rows = []
    if not group and IS_STREAM:
        rows.append([styled_button("▶️ Watch / Download", callback_data=f"stream#{fid}")])
    if offer:
        rows.append([styled_button(offer.label, callback_data="send_all")])
    if not group:
        rows.append([styled_button("❌ Close", callback_data="close_data")])
    sent = await client.send_cached_media(
        chat_id=chat, message_thread_id=topic, file_id=fid, caption=file_caption(doc),
        parse_mode=enums.ParseMode.HTML, protect_content=PROTECT_CONTENT,
        reply_markup=styled_keyboard(rows) if rows else None,
    )
    if offer:
        batch_offers[(chat, sent.id)] = offer
    track_expiry(client, sent, chat, fid, group=group)


async def remaining_files(offer):
    g = await store.get(offer.gid)
    if not g or offer.seed not in g['members']:
        return []
    ids = list(dict.fromkeys(i for i in g['members'] if i != offer.seed))
    docs = {doc['_id']: doc for doc in await store.files_by_ids(ids)}
    ordered = [docs[i] for i in ids if i in docs]
    if g.get('kind') == KIND_EPISODES:
        labels = g.get('episode_map') or {}
        def episode_order(pair):
            idx, doc = pair
            label, ep = episode_label(labels.get(doc['_id']) or doc.get('file_name'), idx)
            season = re.match(r'S(\d+)E', label)
            return (int(season[1]) if season else 1, ep)
        ordered = [doc for _, doc in sorted(enumerate(ordered), key=episode_order)]
    return ordered


async def send_batch(client, msg, offer, group):
    sent_count = 0
    try:
        files = await remaining_files(offer)
        if not files:
            await msg.reply_text("No remaining files in this group.")
            return
        for doc in files:
            if sent_count:
                await asyncio.sleep(3 if group else 1)
            for attempt in range(2):
                # Recheck after pacing or a FloodWait: the admin may switch to PM-only mode.
                if not await db.send_all_enabled() or not await has_premium_or_grace(offer.owner) or (
                    group and not (await db.get_settings(msg.chat.id)).get('group_mode', False)
                ):
                    await msg.reply_text("Batch stopped: delivery is no longer enabled.")
                    return
                try:
                    await send_delivery(client, msg.chat.id, offer.owner, doc['_id'], doc,
                                        group=group, topic=msg.message_thread_id, offer_batch=False)
                    break
                except FloodWait as wait:
                    if attempt:
                        raise
                    await asyncio.sleep(wait.value + 1)
            sent_count += 1
    except Exception:
        logging.exception("Batch delivery stopped after %s files", sent_count)
        try:
            await msg.reply_text(f"Batch stopped after {sent_count} files. Search again to request missing files.")
        except Exception:
            logging.exception("Could not report batch failure")


@Client.on_callback_query(filters.regex(r"^send_all$"))
async def send_all(client, query):
    msg = query.message
    key = (msg.chat.id, msg.id) if msg else None
    offer = batch_offers.get(key)
    if not offer:
        return await query.answer("Already requested or expired.", show_alert=True)
    if query.from_user.id != offer.owner:
        return await query.answer("Only the original requester can send this group.", show_alert=True)
    if not await db.send_all_enabled():
        return await query.answer("Send All is disabled by the bot admin.", show_alert=True)
    group = msg.chat.type in (enums.ChatType.GROUP, enums.ChatType.SUPERGROUP)
    if not await has_premium_or_grace(offer.owner):
        return await query.answer("Premium access required.", show_alert=True)
    if group and not (await db.get_settings(msg.chat.id)).get('group_mode', False):
        return await query.answer("Group delivery is off.", show_alert=True)
    job_key = (msg.chat.id, offer.owner)
    # Claim after all awaits: competing taps cannot both schedule this offer.
    if job_key in batch_jobs:
        return await query.answer("Already sending files here.")
    if batch_offers.pop(key, None) is not offer:
        return await query.answer("Already requested or expired.")
    task = asyncio.create_task(send_batch(client, msg, offer, group))
    batch_jobs[job_key] = task
    task.add_done_callback(lambda _: batch_jobs.pop(job_key, None))
    await query.answer("Sending the remaining files here…")


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

        await send_delivery(client, uid, uid, file_id, file)

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
