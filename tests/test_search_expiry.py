"""Persistent search message expiry, recovery, concurrency and retry behavior."""
import ast
import asyncio
import importlib.util
import logging
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

try:
    import mongomock
    import pymongo
    import hydrogram
except ImportError:
    mongomock = None

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipIf(mongomock is None, 'requires mongomock and application dependencies')
class ExpiryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db = mongomock.MongoClient().db
        spec = importlib.util.spec_from_file_location('isolated_search_expiry', ROOT / 'database/search_expiry.py')
        self.mod = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'database.ia_filterdb': SimpleNamespace(db=self.db)}):
            spec.loader.exec_module(self.mod)
        self.now = 1000.0
        self.clock = patch.object(self.mod.time, 'time', lambda: self.now)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.client = SimpleNamespace(edit_message_text=AsyncMock(), delete_messages=AsyncMock())

    async def test_index_and_independent_chat_ids(self):
        await self.mod.ensure_indexes()
        await self.mod.register(1, 42)
        await self.mod.register(2, 42)
        self.now += 100
        self.assertTrue(await self.mod.touch(1, 42))
        self.assertEqual(self.mod.collection.find_one({'_id':'1:42'})['due'], 1400)
        self.assertEqual(self.mod.collection.find_one({'_id':'2:42'})['due'], 1300)
        self.assertIn('search_expiry_due', self.mod.collection.index_information())

    async def test_expire_grace_delete_and_restart_recovery(self):
        await self.mod.register(-99, 42)
        self.now = 1300
        record = await self.mod._claim(self.now)
        self.assertFalse(await self.mod.touch(-99, 42))
        await self.mod._process(self.client, record)
        self.client.edit_message_text.assert_awaited_once()
        self.assertEqual(self.mod.collection.find_one({'_id':'-99:42'})['due'], 1360)
        self.assertIsNone(await self.mod._claim(1359))
        # A fresh worker sees the same durable collection after a restart.
        self.now = 1360
        record = await self.mod._claim(self.now)
        await self.mod._process(self.client, record)
        self.client.delete_messages.assert_awaited_once_with(-99, 42)
        self.assertIsNone(self.mod.collection.find_one({'_id':'-99:42'}))

    async def test_claim_lease_recovery_and_atomic_activity(self):
        await self.mod.register(1, 7)
        self.now = 1300
        first = await self.mod._claim(self.now)
        self.assertIsNone(await self.mod._claim(self.now))
        self.assertFalse(await self.mod.touch(1, 7))
        self.now += self.mod.LEASE_SECONDS
        second = await self.mod._claim(self.now)
        self.assertNotEqual(first['lease_token'], second['lease_token'])
        result = await self.mod._advance(first, {'stage':'delete', 'due': 0})
        self.assertEqual(result.matched_count, 0)
        await self.mod._process(self.client, second)
        self.assertEqual(self.mod.collection.find_one({'_id':'1:7'})['stage'], 'delete')

    async def test_edit_failure_still_schedules_delete_and_retries_failed_delete(self):
        await self.mod.register(1, 7)
        self.now = 1300
        self.client.edit_message_text.side_effect = RuntimeError('edit failed')
        with self.assertLogs(self.mod.logger, level='WARNING'):
            await self.mod._process(self.client, await self.mod._claim(self.now))
        self.now = 1360
        self.client.delete_messages.side_effect = RuntimeError('network')
        with self.assertLogs(self.mod.logger, level='WARNING'):
            await self.mod._process(self.client, await self.mod._claim(self.now))
        doc = self.mod.collection.find_one({'_id':'1:7'})
        self.assertEqual(doc['attempts'], 1)
        self.assertEqual(doc['due'], 1390)
        self.client.delete_messages.side_effect = None
        self.now = 1390
        await self.mod._process(self.client, await self.mod._claim(self.now))
        self.assertEqual(self.mod.collection.count_documents({}), 0)

    async def test_missing_message_is_removed_from_db(self):
        await self.mod.register(1, 7)
        self.now = 1300
        await self.mod._process(self.client, await self.mod._claim(self.now))
        self.now = 1360
        self.client.delete_messages.side_effect = self.mod.MessageIdInvalid()
        await self.mod._process(self.client, await self.mod._claim(self.now))
        self.assertEqual(self.mod.collection.count_documents({}), 0)


class RegistrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_registration_deletes_untracked_message(self):
        tree = ast.parse((ROOT / 'plugins/filter.py').read_text())
        node = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == '_register_expiry')
        store = SimpleNamespace(register=AsyncMock(side_effect=RuntimeError('offline')))
        ns = {'search_expiry':store, 'logging':logging, '__name__':'test_expiry'}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), '<filter>', 'exec'), ns)
        msg = SimpleNamespace(id=2, chat=SimpleNamespace(id=1), delete=AsyncMock())
        with self.assertLogs('test_expiry', level='ERROR'):
            await ns['_register_expiry'](msg)
        msg.delete.assert_awaited_once()

class PaginationIntegrationTests(unittest.IsolatedAsyncioTestCase):
    def handler(self, store):
        source = (ROOT / 'plugins/filter.py').read_text()
        tree = ast.parse(source)
        node = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'pagination_handler')
        node.decorator_list = []
        ns = {'search_expiry':store, 'get_callback_data':lambda key: {
                  'search':'movie', 'offset':10, 'source_chat_id': 9, 'owner': 7, 'is_pm':False},
              'ADMINS':[], 'send_results':AsyncMock(), 'log_error':lambda *a:None, 'logging':logging,
              '__name__':'test_pagination'}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), '<filter>', 'exec'), ns)
        return ns

    async def test_valid_pagination_extends_before_editing(self):
        store = SimpleNamespace(touch=AsyncMock(return_value=True))
        ns = self.handler(store)
        query = SimpleNamespace(data='page#key', from_user=SimpleNamespace(id=7),
                                message=SimpleNamespace(id=4, chat=SimpleNamespace(id=9)), answer=AsyncMock())
        await ns['pagination_handler'](None, query)
        store.touch.assert_awaited_once_with(9, 4)
        ns['send_results'].assert_awaited_once()
        query.answer.assert_awaited_once_with()

    async def test_expired_result_cannot_be_resurrected(self):
        store = SimpleNamespace(touch=AsyncMock(return_value=False))
        ns = self.handler(store)
        query = SimpleNamespace(data='page#key', from_user=SimpleNamespace(id=7),
                                message=SimpleNamespace(id=4, chat=SimpleNamespace(id=9)), answer=AsyncMock())
        await ns['pagination_handler'](None, query)
        self.assertTrue(query.answer.await_args.kwargs['show_alert'])
        ns['send_results'].assert_not_awaited()

    async def test_other_user_cannot_extend(self):
        store = SimpleNamespace(touch=AsyncMock(return_value=True))
        ns = self.handler(store)
        query = SimpleNamespace(data='page#key', from_user=SimpleNamespace(id=8),
                                message=SimpleNamespace(id=4, chat=SimpleNamespace(id=9)), answer=AsyncMock())
        await ns['pagination_handler'](None, query)
        store.touch.assert_not_awaited()
