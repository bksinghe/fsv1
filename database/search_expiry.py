"""Durable, bounded cleanup of bot search replies.

One MongoDB document per message; no message objects or sleeping task per result.
The worker atomically leases due records so a pagination click and expiry cannot
both win, and an interrupted worker can be recovered after its lease expires.
"""
import asyncio
import logging
import time
import uuid

from pyrogram import enums
from pyrogram.errors import FloodWait, MessageIdInvalid
from pymongo import ReturnDocument

from database.ia_filterdb import db

logger = logging.getLogger(__name__)
collection = db['search_result_expiry']
INACTIVITY_SECONDS = 300
DELETE_DELAY_SECONDS = 60
POLL_SECONDS = 5
LEASE_SECONDS = 120
BATCH_SIZE = 25


def _key(chat_id, message_id):
    return f'{int(chat_id)}:{int(message_id)}'


async def ensure_indexes():
    await asyncio.to_thread(collection.create_index, [('due', 1)], name='search_expiry_due')


async def register(chat_id, message_id):
    now = time.time()
    await asyncio.to_thread(collection.update_one,
        {'_id': _key(chat_id, message_id)},
        {'$set': {'chat_id': int(chat_id), 'message_id': int(message_id),
                  'stage': 'active', 'due': now + INACTIVITY_SECONDS,
                  'lease_until': 0, 'attempts': 0}, '$unset': {'lease_token': ''}},
        upsert=True)


async def touch(chat_id, message_id):
    """Extend only an unexpired, unclaimed result; never resurrect a deleted one."""
    now = time.time()
    result = await asyncio.to_thread(collection.update_one,
        {'_id': _key(chat_id, message_id), 'stage': 'active',
         'due': {'$gt': now}, 'lease_until': {'$lte': now}},
        {'$set': {'due': now + INACTIVITY_SECONDS}})
    return bool(result.matched_count)


async def _claim(now):
    token = uuid.uuid4().hex
    return await asyncio.to_thread(collection.find_one_and_update,
        {'due': {'$lte': now}, 'lease_until': {'$lte': now}},
        {'$set': {'lease_until': now + LEASE_SECONDS, 'lease_token': token}},
        sort=[('due', 1)], return_document=ReturnDocument.AFTER)


async def _advance(record, fields):
    return await asyncio.to_thread(collection.update_one,
        {'_id': record['_id'], 'lease_token': record['lease_token']},
        {'$set': {**fields, 'lease_until': 0}, '$unset': {'lease_token': ''}})


async def _process(client, record):
    chat_id, message_id = record['chat_id'], record['message_id']
    if record['stage'] == 'active':
        try:
            # Editing text removes the buttons in the same Telegram request.
            await client.edit_message_text(chat_id, message_id,
                '⌛ <i>This result has expired.</i>', reply_markup=None,
                parse_mode=enums.ParseMode.HTML)
        except Exception:
            # Even if edit fails, attempt deletion after the normal grace period.
            logger.warning('Could not mark search result %s expired; deletion still scheduled',
                           record['_id'], exc_info=True)
        await _advance(record, {'stage': 'delete', 'due': time.time() + DELETE_DELAY_SECONDS,
                                'attempts': 0})
        return

    try:
        await client.delete_messages(chat_id, message_id)
    except MessageIdInvalid:
        # Already deleted or otherwise no longer exists.
        pass
    except Exception as exc:
        attempts = int(record.get('attempts', 0)) + 1
        delay = min(30 * (2 ** min(attempts - 1, 5)), 900)
        if isinstance(exc, FloodWait):
            delay = max(delay, int(exc.value or 0))
        logger.warning('Search result deletion failed for %s; retrying in %ss',
                       record['_id'], delay, exc_info=True)
        await _advance(record, {'due': time.time() + delay, 'attempts': attempts})
        return
    await asyncio.to_thread(collection.delete_one,
                            {'_id': record['_id'], 'lease_token': record['lease_token']})


async def run_worker(client):
    """Process a bounded number per pass, including records left by a restart."""
    indexed = False
    while True:
        try:
            if not indexed:
                await ensure_indexes()
                indexed = True
            processed = 0
            for _ in range(BATCH_SIZE):
                record = await _claim(time.time())
                if record is None:
                    break
                await _process(client, record)
                processed += 1
            # Yield between full batches; otherwise poll at a low, fixed rate.
            await asyncio.sleep(0.1 if processed == BATCH_SIZE else POLL_SECONDS)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception('Search expiry worker failed; retrying')
            await asyncio.sleep(POLL_SECONDS)
