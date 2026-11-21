"""Private, bounded per-account playback progress for the shared web player."""
import asyncio
import logging
import math
import time

from aiohttp import web
from database.users_chats_db import dbase
from database.ia_filterdb import get_file_details, recycled_ids
from web.web_assets import get_auth

logger = logging.getLogger(__name__)
progress_routes = web.RouteTableDef()
MAX_ITEMS = 30
MAX_SECONDS = 7 * 24 * 60 * 60


def _file_id(value):
    return value.strip() if isinstance(value, str) and 0 < len(value.strip()) <= 512 else ''


def _position(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError('invalid time')
    result = float(value)
    if not math.isfinite(result) or result < 0 or result > MAX_SECONDS:
        raise ValueError('invalid time')
    return result


def _collection():
    if dbase is None:
        raise RuntimeError('Database unavailable')
    return dbase['web_playback_progress']


@progress_routes.get('/api/progress')
async def get_progress(req):
    role, user_id = await get_auth(req)
    if not role:
        return web.json_response({'error': 'Sign in required'}, status=401)
    fid = _file_id(req.query.get('file_id', ''))
    if 'file_id' in req.query and not fid:
        return web.json_response({'error': 'Invalid file ID'}, status=400)
    try:
        doc = await asyncio.to_thread(_collection().find_one, {'_id': user_id}, {'items': 1})
        items = (doc or {}).get('items') or []
        hidden = await recycled_ids([x["file_id"] for x in items])
        items = [x for x in items if x["file_id"] not in hidden]
        if fid:
            return web.json_response({'item': next((x for x in items if x.get('file_id') == fid), None)}, headers={'Cache-Control': 'no-store'})
        return web.json_response({'items': items[:MAX_ITEMS]}, headers={'Cache-Control': 'no-store'})
    except Exception:
        logger.exception('Could not read playback progress')
        return web.json_response({'error': 'Progress unavailable'}, status=503)


@progress_routes.post('/api/progress')
async def save_progress(req):
    role, user_id = await get_auth(req)
    if not role:
        return web.json_response({'error': 'Sign in required'}, status=401)
    try:
        data = await req.json()
        if not isinstance(data, dict):
            raise ValueError('invalid payload')
        fid = _file_id(data.get('file_id'))
        position, duration = _position(data.get('position')), _position(data.get('duration'))
        if not fid or duration <= 0 or position > duration + 1:
            raise ValueError('invalid progress')
    except (ValueError, TypeError):
        return web.json_response({'error': 'Invalid progress'}, status=400)
    try:
        files = _collection()
        # Completion removes the entry instead of keeping a near-finished video.
        if position >= duration * .95:
            await asyncio.to_thread(files.update_one, {'_id': user_id}, {'$pull': {'items': {'file_id': fid}}})
            return web.json_response({'ok': True, 'completed': True})
        if position < 5:
            return web.json_response({'ok': True, 'ignored': True})
        doc = await get_file_details(fid)
        if not doc:
            return web.json_response({'error': 'File not found'}, status=404)
        item = {'file_id': fid, 'name': str(doc.get('file_name') or 'Video')[:500],
                'position': round(position, 1), 'duration': round(duration, 1), 'updated_at': int(time.time())}
        # One atomic write per user: replace the same file and bound history size.
        pipeline = [{'$set': {'items': {'$slice': [{'$concatArrays': [
            {'$literal': [item]},
            {'$filter': {'input': {'$ifNull': ['$items', []]}, 'as': 'entry',
                         'cond': {'$ne': ['$$entry.file_id', {'$literal': fid}]}}}
        ]}, MAX_ITEMS]}}}]
        await asyncio.to_thread(files.update_one, {'_id': user_id}, pipeline, upsert=True)
        return web.json_response({'ok': True})
    except Exception:
        logger.exception('Could not save playback progress')
        return web.json_response({'error': 'Progress unavailable'}, status=503)


@progress_routes.delete('/api/progress')
async def delete_progress(req):
    role, user_id = await get_auth(req)
    if not role:
        return web.json_response({'error': 'Sign in required'}, status=401)
    fid = _file_id(req.query.get('file_id', ''))
    if not fid:
        return web.json_response({'error': 'Invalid file ID'}, status=400)
    try:
        await asyncio.to_thread(_collection().update_one, {'_id': user_id}, {'$pull': {'items': {'file_id': fid}}})
        return web.json_response({'ok': True})
    except Exception:
        logger.exception('Could not delete playback progress')
        return web.json_response({'error': 'Progress unavailable'}, status=503)
