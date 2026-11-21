"""Metadata cache for BIN_CHANNEL messages.

Every /download (Range) request used to call Telegram `get_messages` again
(100–300 ms), repeatedly while seeking a video. Now file_id / size / name / mime
stay cached for 5 minutes, and several simultaneous Range requests share
a single Telegram call.

* The TTL is short (5 min) so file_reference values never go stale.
"""

import asyncio
import logging
import time
from collections import OrderedDict

from pyrogram.file_id import FileId

from database.ia_filterdb import media_is_recycled
from info import BIN_CHANNEL
from utils import temp

logger = logging.getLogger(__name__)

_TTL = 300
_MAX = 256
_CACHE = OrderedDict()      # message_id -> (monotonic_ts, MediaInfo)
_INFLIGHT = {}              # message_id -> asyncio.Task


class MediaInfo:
    __slots__ = ("file_id", "file_id_obj", "file_size", "file_name", "mime_type", "is_video")

    def __init__(self, file_id, file_id_obj, file_size, file_name, mime_type, is_video):
        self.file_id = file_id
        self.file_id_obj = file_id_obj
        self.file_size = file_size
        self.file_name = file_name
        self.mime_type = mime_type
        self.is_video = is_video


async def _fetch(message_id):
    msg = await temp.BOT.get_messages(BIN_CHANNEL, message_id)
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
    _CACHE[message_id] = (time.monotonic(), info)
    _CACHE.move_to_end(message_id)
    while len(_CACHE) > _MAX:
        _CACHE.popitem(last=False)
    return info


async def get_media_info(message_id):
    """MediaInfo or None (file not found / no media)."""
    info = await _cached_media(message_id)
    # Never cache visibility. Use Telegram's actual media, not URL parameters:
    # this covers old links, /link, HEAD and every Range request.
    if info and not await media_is_recycled(info.file_id):
        return info
    return None


async def _cached_media(message_id):
    hit = _CACHE.get(message_id)
    if hit and time.monotonic() - hit[0] < _TTL:
        _CACHE.move_to_end(message_id)
        return hit[1]

    task = _INFLIGHT.get(message_id)
    if task is None:
        task = asyncio.ensure_future(_fetch(message_id))
        _INFLIGHT[message_id] = task
        task.add_done_callback(lambda _t, _m=message_id: _INFLIGHT.pop(_m, None))
    return await asyncio.shield(task)
