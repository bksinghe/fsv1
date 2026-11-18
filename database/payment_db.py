"""Atomically decide a payment receipt and apply its premium grant once.

The receipt marker, new plan and invoice are committed in the *same* MongoDB
user document, so a crash or an ambiguous write response cannot separate the
idempotency record from the grant. No multi-document transactions are needed.
"""
import asyncio
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from pymongo.errors import DuplicateKeyError
from pymongo.write_concern import WriteConcern
from pymongo.read_concern import ReadConcern
from database.users_chats_db import db


def receipt_key(chat_id, message_id):
    return hashlib.sha256(f'{int(chat_id)}:{int(message_id)}'.encode()).hexdigest()


def _expiry(value):
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, timezone.utc)
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    return None


def _fmt(value):
    return value.strftime('%d %b %Y, %I:%M %p')


def _decide_sync(uid, key, action, plan_text, amount, duration):
    # A majority-acknowledged write survives normal MongoDB primary failover.
    col = db.premium.with_options(write_concern=WriteConcern(w="majority"),
                                  read_concern=ReadConcern("majority"))
    # The existing collection uses `id` rather than `_id` as its user key.
    # Fail closed if uniqueness cannot be enforced (e.g. legacy duplicates).
    col.create_index('id', unique=True)
    try:
        col.update_one({'id': uid}, {'$setOnInsert': {'id': uid}}, upsert=True)
    except DuplicateKeyError:
        # Another concurrent operation created the user first.
        pass

    marker = 'payment_decisions.' + key
    for _ in range(20):
        doc = col.find_one({'id': uid})
        if not doc:
            raise RuntimeError('Premium user record unavailable')
        previous = (doc.get('payment_decisions') or {}).get(key)
        if previous is not None:
            return {'status': 'already_decided', 'decision': previous.get('decision')}
        match = {'id': uid, marker: {'$exists': False}}
        decision = {'decision': action, 'decided_at': datetime.now(timezone.utc).timestamp()}
        updates = {marker: decision}
        if action == 'approved':
            # Compare-and-set the whole old plan: different receipts approved
            # concurrently must both extend the latest version, never overwrite.
            old = doc.get('plan') or {}
            match['plan'] = doc['plan'] if 'plan' in doc else {'$exists': False}
            now = datetime.now(timezone.utc)
            old_expiry = _expiry(old.get('expire'))
            expire = (old_expiry if old_expiry and old_expiry > now else now) + duration
            invoice = {'id': 'PRM-' + secrets.token_hex(3).upper(), 'plan': plan_text,
                       'amount': amount, 'activated': _fmt(now), 'expire': _fmt(expire),
                       'created_at': now.timestamp(), 'by': 'purchase'}
            invoices = list(old.get('invoices') or [])
            invoices.append(invoice)
            updates['plan'] = {'premium': True, 'plan': plan_text, 'expire': expire.timestamp(),
                               'activated_at': now.timestamp(), 'invoices': invoices}
            decision['invoice_id'] = invoice['id']
            decision['expire'] = expire.timestamp()
        result = col.update_one(match, {'$set': updates})
        if result.matched_count:
            result = {'status': 'applied', 'decision': action}
            if action == 'approved':
                result.update(expire=expire, invoice=invoice)
            return result
    raise RuntimeError('Premium plan changed repeatedly; please retry the receipt')


async def decide_payment(uid, chat_id, message_id, action, plan_text='', amount=0, duration=None):
    if action not in ('approved', 'rejected'):
        raise ValueError('Invalid payment decision')
    if action == 'approved' and (not isinstance(duration, timedelta) or duration <= timedelta(0)):
        raise ValueError('Invalid payment duration')
    key = receipt_key(chat_id, message_id)
    return await asyncio.to_thread(_decide_sync, int(uid), key, action, plan_text, amount, duration)
