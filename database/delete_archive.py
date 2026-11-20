"""Archive an indexed file to Telegram before removing it from the library."""
import asyncio
import html
import logging

from pyrogram import enums
from info import DELETE_ARCHIVE_CHANNEL, INDEX_CHANNELS
from database import ia_filterdb as ia
from database.group_db import store as group_store

logger = logging.getLogger(__name__)
# Serialise delete operations within this process so simultaneous web/PM requests
# cannot both archive and delete the same document.
_delete_lock = asyncio.Lock()


class ArchiveDeleteError(Exception):
    pass


async def archive_and_delete(bot, fid):
    """Return False for a missing file; never delete if archival fails."""
    if not DELETE_ARCHIVE_CHANNEL:
        raise ArchiveDeleteError('Set DELETE_ARCHIVE_CHANNEL before deleting files.')
    if DELETE_ARCHIVE_CHANNEL in INDEX_CHANNELS:
        raise ArchiveDeleteError('DELETE_ARCHIVE_CHANNEL must not be in INDEX_CHANNELS.')
    if bot is None:
        raise ArchiveDeleteError('Bot is not ready; file was not deleted.')
    async with _delete_lock:
        doc = await ia.get_file_meta(fid)
        if not doc:
            return False
        # The database stores Telegram's reusable media identifier, not the source
        # channel/message ID. Send a copy of the media instead of forwarding a post.
        try:
            sent = await bot.send_cached_media(
                chat_id=DELETE_ARCHIVE_CHANNEL, file_id=fid,
                caption=html.escape(str(doc.get('caption') or '')[:900]),
                parse_mode=enums.ParseMode.HTML,
            )
            if not getattr(sent, 'id', None):
                raise RuntimeError('Telegram did not confirm the archive message')
        except Exception as exc:
            logger.exception('Could not archive file before deletion')
            raise ArchiveDeleteError('Archive failed; file was not deleted. Check the archive channel and bot permissions.') from exc
        if not await ia.delete_file_by_id(fid):
            raise ArchiveDeleteError('File was archived, but database deletion failed. Check the database before retrying.')
        try:
            await group_store.pull_files([fid])
            await group_store.cleanup_empty()
        except Exception:
            logger.exception('Group cleanup failed after archived deletion')
        return True
