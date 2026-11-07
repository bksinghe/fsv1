"""Metadata cache for messages in the active BIN_CHANNEL.

Every /download (Range) request used to call Telegram `get_messages` again
(100–300 ms), repeatedly while seeking a video. Now the channel/message pair
is cached for 5 minutes, and simultaneous Range requests share one Telegram call.

The channel is part of the cache key so a live BIN_CHANNEL change cannot return
metadata for a different message with the same Telegram message ID.
"""

import asyncio
import logging
import time
from collections import OrderedDict

from hydrogram.file_id import FileId

from database.runtime_config import runtime_config
from utils import temp

logger = logging.getLogger(__name__)

_TTL = 300
_MAX = 256
_CACHE = OrderedDict()      # (channel_id, message_id) -> (monotonic_ts, MediaInfo)
_INFLIGHT = {}              # (channel_id, message_id) -> asyncio.Task


class MediaInfo:
    __slots__ = ("file_id", "file_id_obj", "file_size", "file_name", "mime_type", "is_video")

    def __init__(self, file_id, file_id_obj, file_size, file_name, mime_type, is_video):
        self.file_id = file_id
        self.file_id_obj = file_id_obj
        self.file_size = file_size
        self.file_name = file_name
        self.mime_type = mime_type
        self.is_video = is_video


async def _fetch(chat_id, message_id, cache_key):
    msg = await temp.BOT.get_messages(chat_id, message_id)
    media = getattr(msg, msg.media.value, None) if msg and msg.media else None
    if not media:
        return None
    info = MediaInfo(
        file_id=media.file_id,
        file_id_obj=FileId.decode(media.file_id),
        file_size=getattr(media, "file_size", None) or 0,
        file_name=getattr(media, "file_name", None),
        mime_type=getattr(media, "mime_type", None),
        is_video=bool(getattr(msg, "video", None)),
    )
    _CACHE[cache_key] = (time.monotonic(), info)
    _CACHE.move_to_end(cache_key)
    while len(_CACHE) > _MAX:
        _CACHE.popitem(last=False)
    return info


async def get_media_info(message_id, chat_id=None):
    """MediaInfo or None (file not found / no media), optionally for a signed chat ID."""
    channel_id = runtime_config.get("BIN_CHANNEL") if chat_id is None else chat_id
    cache_key = (channel_id, int(message_id))
    hit = _CACHE.get(cache_key)
    if hit and time.monotonic() - hit[0] < _TTL:
        _CACHE.move_to_end(cache_key)
        return hit[1]

    task = _INFLIGHT.get(cache_key)
    if task is None:
        task = asyncio.ensure_future(_fetch(channel_id, int(message_id), cache_key))
        _INFLIGHT[cache_key] = task
        task.add_done_callback(lambda _t, _key=cache_key: _INFLIGHT.pop(_key, None))
    return await asyncio.shield(task)
