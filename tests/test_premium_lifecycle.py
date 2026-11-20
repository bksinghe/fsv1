"""Exercise premium workers against Mongo-shaped records without a Telegram login."""
import ast
import asyncio
import logging
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

try:
    import mongomock
    from pymongo.errors import DuplicateKeyError
except ImportError:
    mongomock = None

ROOT = Path(__file__).resolve().parents[1]


def load_defs(path, names, ns):
    tree = ast.parse((ROOT / path).read_text())
    tree.body = [node for node in tree.body if getattr(node, 'name', None) in names
                 or (isinstance(node, ast.Assign) and getattr(node.targets[0], 'id', None) in names)]
    exec(compile(tree, path, 'exec'), ns)


@unittest.skipIf(mongomock is None, 'requires mongomock and pymongo')
class PremiumLifecycleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.ns = ns = dict(datetime=datetime, timezone=timezone, timedelta=timedelta,
                            ADMINS=[], asyncio=asyncio, DuplicateKeyError=DuplicateKeyError,
                            logger=logging.getLogger(__name__), temp=SimpleNamespace(PREMIUM={}))
        load_defs('database/users_chats_db.py', {'Database'}, ns)
        db = ns['Database'].__new__(ns['Database'])
        db.premium = mongomock.MongoClient().db.premium
        db.premium.create_index('id', unique=True)
        self.db = ns['db'] = db
        load_defs('utils.py', {'premium_expiry_reminder', 'get_expiry_datetime', 'REMINDER_STEPS',
                              'GRACE_PERIOD', 'fmt'}, ns)
        load_defs('bot.py', {'check_and_remove_expired_premium'}, ns)
        load_defs('plugins/premium.py', {'get_plan_data', 'myplan_text', 'apply_premium', 'revoke_premium'}, ns)
        ns['gen_invoice_id'] = lambda: 'invoice'
        self.client = SimpleNamespace(send_message=AsyncMock())

    def insert(self, uid, minutes):
        expiry = (datetime.now(timezone.utc) + timedelta(minutes=minutes)).timestamp()
        self.db.premium.insert_one({'id': uid, 'plan': {'premium': True, 'expire': expiry,
                                                       'invoices': ['old']}})
        return expiry

    async def run_cycle(self, name):
        async def sleep(seconds):
            if seconds >= 600:
                raise asyncio.CancelledError
        self.ns['asyncio'] = SimpleNamespace(sleep=sleep, to_thread=asyncio.to_thread)
        with self.assertRaises(asyncio.CancelledError):
            await self.ns[name](self.client)

    async def test_expiry_notifies_telegram_id_and_preserves_grace_and_history(self):
        self.insert(101, -31)
        self.insert(102, -10)
        await self.run_cycle('check_and_remove_expired_premium')
        self.assertEqual(self.client.send_message.await_args.args[0], 101)
        self.client.send_message.assert_awaited_once()
        plan = await self.db.get_plan(101)
        self.assertFalse(plan['premium'])
        self.assertEqual(plan['invoices'], ['old'])
        data, _ = await self.ns['get_plan_data'](102)
        self.assertIn('grace period', self.ns['myplan_text'](data))
        self.assertTrue((await self.db.get_plan(102))['premium'])
        self.assertEqual(self.db.premium.count_documents({}), 2)

    async def test_delayed_worker_or_admin_write_cannot_undo_renewal(self):
        old = self.insert(101, -40)
        snapshot = await self.db.get_plan(101)
        renewed = dict(snapshot, expire=old+86400, invoices=['old', 'new'])
        self.assertTrue(await self.db.update_plan(101, renewed, expected=snapshot))
        self.assertFalse(await self.db.expire_plan(101, old))
        self.assertFalse(await self.db.update_plan(101, snapshot, expected=snapshot))
        await self.db.mark_reminder(101, old, None, '1 day')
        self.assertEqual(await self.db.get_plan(101), renewed)

    async def test_reminder_sends_nearest_window_only_once(self):
        self.insert(101, 50)
        await self.run_cycle('premium_expiry_reminder')
        self.assertEqual(self.client.send_message.await_args.args[0], 101)
        self.assertIn('1 hour', self.client.send_message.await_args.args[1])
        await self.run_cycle('premium_expiry_reminder')
        self.client.send_message.assert_awaited_once()

    async def test_only_one_worker_claims_the_same_reminder(self):
        expire = self.insert(101, 50)
        claims = await asyncio.gather(*(self.db.mark_reminder(101, expire, None, '1 hour')
                                        for _ in range(3)))
        self.assertEqual(sum(claims), 1)

    async def test_first_grant_and_revoke_refresh_cache_and_keep_invoice(self):
        cache = self.ns['temp'].PREMIUM
        cache[101] = {'expire': None}
        _, invoice = await self.ns['apply_premium'](101, '7 days', 0, days=7)
        self.assertNotIn(101, cache)
        cache[101] = {'expire': datetime.utcnow()}
        await self.ns['revoke_premium'](101)
        self.assertNotIn(101, cache)
        self.assertEqual((await self.db.get_plan(101))['invoices'], [invoice])
