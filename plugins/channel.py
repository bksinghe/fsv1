import asyncio
from hydrogram import Client, filters
from hydrogram.errors import (
    FloodWait,
    ReactionInvalid
)

from database.runtime_config import runtime_config
from database.ia_filterdb import (
    save_file,
    update_file_caption,
    detect_quality
)
from utils import get_size

# 🔥 Channels the manual indexer is working on right now (plugins/index.py
#    owns that set). Live posts of such a channel are skipped, so the manual
#    loop and this handler never write the same file at the same time.
try:
    from plugins.index import ACTIVE_INDEXES
except ImportError:
    ACTIVE_INDEXES = set()

# ─────────────────────────────────────────────
# MEDIA FILTER
# ─────────────────────────────────────────────
media_filter = (filters.video | filters.document)


def _is_index_channel(chat):
    """Check the live INDEX_CHANNELS setting (including legacy @usernames)."""
    chat_id = getattr(chat, "id", None)
    username = (getattr(chat, "username", None) or "").lstrip("@").casefold()
    for configured in runtime_config.get("INDEX_CHANNELS"):
        if isinstance(configured, int) and configured == chat_id:
            return True
        raw = str(configured).strip()
        if raw.lstrip("-").isdigit():
            try:
                if int(raw) == chat_id:
                    return True
            except ValueError:
                pass
        elif username and raw.lstrip("@").casefold() == username:
            return True
    return False


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

async def safe_react(message, emoji: str):
    try:
        await message.react(emoji)
        return True
    except ReactionInvalid:
        return False
    except FloodWait as e:
        await asyncio.sleep(e.value)
        try:
            await message.react(emoji)
            return True
        except:
            return False
    except Exception:
        return False


async def safe_log(client, text: str):
    log_channel = runtime_config.get("LOG_CHANNEL")
    if not log_channel:
        return False
    try:
        await client.send_message(log_channel, text)
        return True
    except FloodWait as e:
        await asyncio.sleep(e.value)
        try:
            await client.send_message(log_channel, text)
            return True
        except:
            return False
    except Exception:
        return False


def get_media_info(message):
    try:
        media = message.document or message.video
        if not media or not getattr(media, "file_id", None):
            return None
        return media
    except:
        return None

# ─────────────────────────────────────────────
# 📥 AUTO INDEX (LIVE POSTS ONLY)
# ─────────────────────────────────────────────

@Client.on_message(filters.channel & media_filter, group=10)
async def index_new_file(bot, message):
    if not _is_index_channel(message.chat):
        return

    # 🛑 Skip while the manual indexer is running for this channel
    if message.chat.id in ACTIVE_INDEXES:
        return

    media = get_media_info(message)
    if not media:
        return

    try:
        # NOTE: save_file() reads the caption straight off the media object
        #       (see database/ia_filterdb.py) — `caption` is part of the
        #       search text index, so a live post must carry it too. A manual
        #       run (plugins/index.py) does exactly the same.
        media.caption = message.caption or ""
        status = await save_file(media)

        emoji_map = {
            "suc": "✅",
            "dup": "♻️",
            "err": "❌",
            "skip": "⏭",
        }

        await safe_react(message, emoji_map.get(status, "❓"))

        await safe_log(
            bot,
            f"📥 **Auto Index**\n\n"
            f"📄 `{media.file_name}`\n"
            f"📊 `{get_size(getattr(media, 'file_size', 0))}`\n"
            f"🎞 `{detect_quality(getattr(media, 'file_name', None))}`\n"
            f"✅ `{status}`\n"
            f"💬 `{message.chat.title}`"
        )

    except FloodWait as e:
        await asyncio.sleep(e.value)
    except Exception:
        await safe_react(message, "❌")

# ─────────────────────────────────────────────
# ✏️ CAPTION EDIT
# ─────────────────────────────────────────────

@Client.on_edited_message(filters.channel & media_filter, group=11)
async def update_caption(bot, message):
    if not _is_index_channel(message.chat):
        return
    if message.chat.id in ACTIVE_INDEXES:
        return

    media = get_media_info(message)
    if not media:
        return

    try:
        updated = await update_file_caption(
            media.file_id,
            message.caption or ""
        )

        await safe_react(message, "✏️" if updated else "⚠️")

    except FloodWait as e:
        await asyncio.sleep(e.value)
    except Exception:
        await safe_react(message, "❌")

# ─────────────────────────────────────────────
# 🗑️ DELETE LOG
# ─────────────────────────────────────────────

@Client.on_deleted_messages(filters.channel, group=12)
async def handle_deleted_files(bot, messages):
    if not messages or not _is_index_channel(messages[0].chat):
        return
    try:
        await safe_log(
            bot,
            f"🗑️ **Deleted Messages**\nCount: `{len(messages)}`"
        )
    except:
        pass
