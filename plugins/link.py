"""Create time-limited links for a file the user replied to in Telegram."""
import logging

from pyrogram import Client, filters

from info import BIN_CHANNEL, IS_STREAM, URL
from stream_security import REPLY_LINK_TTL, sign_params
from telegram_buttons import styled_button, styled_keyboard
from database.ia_filterdb import media_is_recycled
from utils import is_premium


@Client.on_message(filters.command("link") & (filters.private | filters.group) & filters.incoming)
async def file_link(client, message):
    if not IS_STREAM:
        return await message.reply_text("Streaming links are disabled.")
    source = message.reply_to_message
    media = getattr(source, source.media.value, None) if source and source.media else None
    fid = getattr(media, 'file_id', None)
    if not fid or source.chat.id != message.chat.id:
        return await message.reply_text("Reply to a file with /link to create 5-hour links.")
    if source.has_protected_content or source.chat.has_protected_content or getattr(media, 'ttl_seconds', None):
        return await message.reply_text("Links cannot be created for protected or disappearing files.")
    if not message.from_user or not await is_premium(message.from_user.id, client):
        return await message.reply_text("🔒 Premium access is required to generate file links.")

    try:
        if await media_is_recycled(fid):
            return await message.reply_text("File unavailable.")
        # Telegram reuses its existing copy; never download the file to the bot.
        stored = await client.send_cached_media(chat_id=BIN_CHANNEL, file_id=fid)
        signed = sign_params(stored.id, REPLY_LINK_TTL)
        buttons = styled_keyboard([[
            styled_button("▶️ Watch Online", url=f"{URL}watch/{stored.id}?{signed}"),
            styled_button("⬇️ Download", url=f"{URL}download/{stored.id}?{signed}"),
        ]])
    except Exception:
        logging.getLogger(__name__).exception("Could not prepare file links")
        return await message.reply_text("Couldn't generate links for this file. Please try again later.")

    await message.reply_text("🔗 File links · valid for 5 hours from now.", reply_markup=buttons)
