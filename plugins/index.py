import logging
import time
import asyncio

from pyrogram import Client, filters, enums
from pyrogram.errors import FloodWait
from telegram_buttons import styled_button
from pyrogram.types import InlineKeyboardMarkup

from info import ADMINS, INDEX_LOG_CHANNEL
from database.ia_filterdb import save_file, db as media_db
from utils import get_readable_time, log_error

# =====================================================
# GLOBALS
# =====================================================
LOCK = asyncio.Lock()
CANCEL = False

# 📌 Channels currently being manually indexed.
ACTIVE_INDEXES = set()

# =====================================================
# RESUME DB  (ia_filterdb's client — no second connection)
# =====================================================
resume_col = media_db["index_resume"]


async def set_resume(chat_id, msg_id):
    await asyncio.to_thread(
        resume_col.update_one,
        {"_id": chat_id},
        {"$set": {"last_id": msg_id}},
        upsert=True
    )


# =====================================================
# HELPERS
# =====================================================
async def auto_delete(bot, chat_id, msg_id, delay=120):
    await asyncio.sleep(delay)
    try:
        await bot.delete_messages(chat_id, msg_id)
    except Exception:
        logging.getLogger(__name__).debug("auto_delete: optional operation failed", exc_info=True)
        pass


async def send_log(bot, text):
    if not INDEX_LOG_CHANNEL:
        return
    try:
        await bot.send_message(INDEX_LOG_CHANNEL, text)
    except Exception:
        logging.getLogger(__name__).debug("send_log: optional operation failed", exc_info=True)
        pass


# =====================================================
# ENTRY POINT
# forward / link → DIRECT CONFIRMATION
# =====================================================
def is_index_request(_, __, message):
    return bool(
        (message.text and message.text.startswith("https://t.me"))
        or (message.forward_from_chat and message.forward_from_chat.type == enums.ChatType.CHANNEL)
    )


@Client.on_message(filters.private & filters.user(ADMINS) & filters.incoming & filters.create(is_index_request), group=-1)
async def start_index(bot, message):
    if LOCK.locked():
        return await message.reply("⏳ Indexing already running")

    try:
        # ---- LINK ----
        if message.text and message.text.startswith("https://t.me"):
            parts = message.text.split("/")
            last_msg_id = int(parts[-1])
            raw = parts[-2]
            chat_id = int("-100" + raw) if raw.isdigit() else raw

        # ---- FORWARD ----
        elif message.forward_from_chat and message.forward_from_chat.type == enums.ChatType.CHANNEL:
            last_msg_id = message.forward_from_message_id
            chat_id = message.forward_from_chat.id

        else:
            return

        chat = await bot.get_chat(chat_id)
        if chat.type != enums.ChatType.CHANNEL:
            return await message.reply("❌ Only channels supported")
        chat_id = chat.id  # Resolve public usernames before building callback data.

    except Exception as e:
        return await message.reply(f"❌ Error: `{e}`")

    btn = InlineKeyboardMarkup([
        [styled_button(
            "✅ START INDEXING",
            callback_data=f"idx#start#{chat_id}#{last_msg_id}"
        )],
        [styled_button("❌ CANCEL", callback_data="idx#close")]
    ])

    await message.reply(
        f"📢 **Channel:** `{chat.title}`\n"
        f"🆔 **ID:** `{chat_id}`\n"
        f"📊 **Last Message:** `{last_msg_id}`",
        reply_markup=btn
    )
    message.stop_propagation()


# =====================================================
# CALLBACK
# =====================================================
@Client.on_callback_query(filters.regex("^idx#"))
async def index_callback(bot, query):
    global CANCEL
    if not query.from_user or query.from_user.id not in ADMINS:
        return await query.answer("Admins only", show_alert=True)
    data = query.data.split("#")

    # idx#close = ❌ CANCEL of the confirmation, idx#cancel = 🛑 STOP
    # (handled by stop_index below) — neither is a start request.
    if data[1] != "start":
        if data[1] == "close":
            await query.answer("Cancelled")
            await query.message.edit("❌ Cancelled")
        return

    if LOCK.locked():
        return await query.answer("Indexing already running", show_alert=True)
    try:
        _, _, chat_id, last_id = data
        chat_id, last_id = int(chat_id), int(last_id)
        if last_id <= 0:
            raise ValueError("invalid message ID")
    except (TypeError, ValueError):
        return await query.answer("Invalid index request", show_alert=True)

    # Reserve before yielding so two rapid clicks cannot start duplicate scans.
    await LOCK.acquire()
    CANCEL = False
    try:
        await query.answer("Indexing started")
    except Exception:
        LOCK.release()
        raise
    asyncio.create_task(_run_index(bot, query.message, chat_id, last_id))


async def _run_index(bot, status, chat_id, last_id):
    try:
        chat = await bot.get_chat(chat_id)
        await status.edit("⚡ Indexing started…")
        await index_worker(bot, status, chat_id, last_id, chat.title)
    except Exception as exc:
        log_error("Index startup", exc)
        try:
            await status.edit("❌ Could not start indexing. Please try again.")
        except Exception:
            pass
    finally:
        LOCK.release()


# =====================================================
# CORE INDEX LOOP
# =====================================================
async def index_worker(bot, status, chat_id, last_msg_id, channel_title):
    start_time = time.time()
    saved = dup = err = nomedia = 0
    processed = 0

    # Older runs could advance the checkpoint despite fetch/save errors (or
    # skip live posts). Re-scan the full range so those holes can be repaired.
    # save_file is idempotent and updates already indexed files.
    stop_id = 0

    current_id = last_msg_id

    # Track the active run for diagnostics.
    ACTIVE_INDEXES.add(chat_id)

    try:
        while current_id > stop_id:
            if CANCEL:
                break

            try:
                msg = await bot.get_messages(chat_id, current_id)
            except FloodWait as e:
                await asyncio.sleep(e.value)
                continue
            except Exception as e:
                raise RuntimeError(f"Could not fetch message {current_id}: {e}") from e

            processed += 1

            # Status Update (Every 50 msgs)
            if processed % 50 == 0:
                elapsed = time.time() - start_time
                speed = processed / elapsed if elapsed else 0
                eta = (current_id - stop_id) / speed if speed else 0

                # A failed status edit must never abort a long run
                try:
                    btn = InlineKeyboardMarkup(
                        [[styled_button("🛑 STOP", callback_data="idx#cancel")]]
                    )
                    await status.edit(
                        f"📊 `{processed}` scanned\n"
                        f"✅ `{saved}` | ♻️ `{dup}` | ❌ `{err}`\n"
                        f"⚡ `{speed:.2f}/s`\n"
                        f"⏳ `{get_readable_time(eta)}`",
                        reply_markup=btn
                    )
                except Exception:
                    pass

            # Validate Media
            if not msg or not msg.media:
                nomedia += 1
                current_id -= 1
                continue

            if msg.media not in (
                enums.MessageMediaType.VIDEO,
                enums.MessageMediaType.DOCUMENT
            ):
                nomedia += 1
                current_id -= 1
                continue

            media = getattr(msg, msg.media.value, None)
            if not media:
                current_id -= 1
                continue

            # save_file() reads the caption straight off the media object
            media.caption = msg.caption
            res = await save_file(media)

            if res == "suc":
                saved += 1
            elif res == "dup":
                dup += 1
            else:
                err += 1
                raise RuntimeError(f"Could not save message {current_id}; retry indexing")

            current_id -= 1

        if not CANCEL:
            await set_resume(chat_id, last_msg_id)

    except Exception as e:
        log_error("Index worker", e)
        await status.edit(f"❌ Failed: `{e}`")
        return

    finally:
        ACTIVE_INDEXES.discard(chat_id)

    total_time = get_readable_time(time.time() - start_time)
    headline = "⏹ **Indexing Stopped**" if CANCEL else "✅ **Index Completed**"

    final_msg = await status.edit(
        f"{headline}\n\n"
        f"📢 `{channel_title}`\n"
        f"🆔 `{chat_id}`\n\n"
        f"✅ `{saved}` | ♻️ `{dup}` | ❌ `{err}` | 🚫 `{nomedia}`\n"
        f"⏱ `{total_time}`"
    )
    asyncio.create_task(auto_delete(bot, final_msg.chat.id, final_msg.id, 120))

    await send_log(
        bot,
        f"{'⏹ **Index Stopped**' if CANCEL else '📊 **Index Report**'}\n\n"
        f"📢 **Channel:** `{channel_title}`\n"
        f"🆔 **Channel ID:** `{chat_id}`\n\n"
        f"✅ **Saved:** `{saved}`\n"
        f"♻️ **Duplicate:** `{dup}`\n"
        f"❌ **Errors:** `{err}`\n"
        f"🚫 **Non-media:** `{nomedia}`\n"
        f"⏱ **Time:** `{total_time}`"
    )


# =====================================================
# STOP
# =====================================================
@Client.on_callback_query(filters.regex("^idx#cancel"), group=1)
async def stop_index(bot, query):
    global CANCEL
    if not query.from_user or query.from_user.id not in ADMINS:
        return await query.answer("Admins only", show_alert=True)
    CANCEL = True
    await query.answer("Stopping…", show_alert=True)
