import time
import asyncio

from hydrogram import Client, filters, enums
from hydrogram.errors import FloodWait
from hydrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from info import ADMINS
from database.runtime_config import runtime_config
from database.ia_filterdb import save_file, db as media_db
from utils import get_readable_time, log_error

# =====================================================
# GLOBALS
# =====================================================
LOCK = asyncio.Lock()
CANCEL = False

# 📌 Channels a manual run is indexing right now.
#    plugins/channel.py imports this set and skips live auto-indexing for
#    them, so the manual loop and the live handler never write the same
#    file at the same time.
ACTIVE_INDEXES = set()

# =====================================================
# RESUME DB  (ia_filterdb's client — no second connection)
# =====================================================
resume_col = media_db["index_resume"]


async def get_resume(chat_id):
    doc = await asyncio.to_thread(resume_col.find_one, {"_id": chat_id})
    return doc["last_id"] if doc else None


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
    except:
        pass


async def send_log(bot, text):
    try:
        await bot.send_message(runtime_config.get("INDEX_LOG_CHANNEL"), text)
    except:
        pass


# =====================================================
# ENTRY POINT
# forward / link → DIRECT CONFIRMATION
# =====================================================
@Client.on_message(filters.private & filters.user(ADMINS) & filters.incoming)
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

    except Exception as e:
        return await message.reply(f"❌ Error: `{e}`")

    btn = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "✅ START INDEXING",
            callback_data=f"idx#start#{chat_id}#{last_msg_id}"
        )],
        [InlineKeyboardButton("❌ CANCEL", callback_data="idx#close")]
    ])

    await message.reply(
        f"📢 **Channel:** `{chat.title}`\n"
        f"🆔 **ID:** `{chat_id}`\n"
        f"📊 **Last Message:** `{last_msg_id}`",
        reply_markup=btn
    )


# =====================================================
# CALLBACK
# =====================================================
@Client.on_callback_query(filters.regex("^idx#"))
async def index_callback(bot, query):
    global CANCEL
    data = query.data.split("#")

    # idx#close = ❌ CANCEL of the confirmation, idx#cancel = 🛑 STOP
    # (handled by stop_index below) — neither is a start request.
    if data[1] != "start":
        if data[1] == "close":
            await query.message.edit("❌ Cancelled")
        return

    _, _, chat_id, last_id = data
    chat = await bot.get_chat(int(chat_id))

    await query.message.edit("⚡ Indexing started…")

    async with LOCK:
        CANCEL = False
        await index_worker(
            bot,
            query.message,
            int(chat_id),
            int(last_id),
            chat.title
        )


# =====================================================
# CORE INDEX LOOP
# =====================================================
async def index_worker(bot, status, chat_id, last_msg_id, channel_title):
    start_time = time.time()
    saved = dup = err = nomedia = 0
    processed = 0

    # Resume: continue from the last message the previous run reached
    old_resume_id = await get_resume(chat_id)
    stop_id = old_resume_id or 0

    current_id = last_msg_id

    # 🛑 Live posts of this channel are auto-indexed again once the run ends
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
            except Exception:
                current_id -= 1
                continue

            processed += 1

            # Status Update (Every 50 msgs)
            if processed % 50 == 0:
                elapsed = time.time() - start_time
                speed = processed / elapsed if elapsed else 0
                eta = (current_id - stop_id) / speed if speed else 0

                # A failed status edit must never abort a long run
                try:
                    btn = InlineKeyboardMarkup(
                        [[InlineKeyboardButton("🛑 STOP", callback_data="idx#cancel")]]
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
@Client.on_callback_query(filters.regex("^idx#cancel"))
async def stop_index(bot, query):
    global CANCEL
    CANCEL = True
    await query.answer("Stopping…", show_alert=True)
