"""Offline regression tests for thumbnail retries, DB writes and admin races."""
import ast
import asyncio
import logging
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

ROOT = Path(__file__).resolve().parents[1]


def load_functions(path, names, env):
    tree = ast.parse((ROOT / path).read_text())
    nodes = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names]
    assert {n.name for n in nodes} == set(names)
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), str(path), 'exec'), env)


def stats():
    return {k: 0 for k in ('done', 'ok', 'no_thumb', 'failed', 'rejected', 'meta')}


class CandidateTests(unittest.IsolatedAsyncioTestCase):
    async def test_transient_failure_does_not_mean_no_thumbnail(self):
        env = {'_valid_thumb_ref': lambda x: x != 'invalid', '_STATS': stats(),
               '_download_thumb': AsyncMock(side_effect=[None, b'bad']),
               '_validate_thumb_async': AsyncMock(return_value=(False, {'reason': 'blank'})),
               '_MIN_THUMB_BYTES': 1, '_MIN_THUMB_DIM': 1, '_MIN_THUMB_STDDEV': 1,
               'logger': logging.getLogger(__name__)}
        load_functions('web/thumb_engine.py', {'_real_thumb_bytes'}, env)
        data, _, failed = await env['_real_thumb_bytes'](['invalid', 'failed', 'blank'])
        self.assertIsNone(data)
        self.assertTrue(failed)
        self.assertEqual(env['_STATS']['rejected'], 2)
        self.assertEqual(await env['_real_thumb_bytes']([]), (None, {}, False))

    async def test_later_valid_candidate_wins_over_earlier_failure(self):
        env = {'_valid_thumb_ref': lambda x: True, '_STATS': stats(),
               '_download_thumb': AsyncMock(side_effect=[None, b'valid']),
               '_validate_thumb_async': AsyncMock(return_value=(True, {'width': 100, 'height': 150})),
               '_MIN_THUMB_BYTES': 1, '_MIN_THUMB_DIM': 1, '_MIN_THUMB_STDDEV': 1,
               'logger': logging.getLogger(__name__)}
        load_functions('web/thumb_engine.py', {'_real_thumb_bytes'}, env)
        data, info, failed = await env['_real_thumb_bytes'](['failed', 'valid'])
        self.assertEqual((data, info['ref'], failed), (b'valid', 'valid', False))


class ProbeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.doc = {'thumb_url': '', 'file_name': 'file', 'meta_v': 2}
        self.update = AsyncMock(return_value=True)
        self.candidates = AsyncMock(return_value=(None, {}, False))
        self.upload = AsyncMock(return_value='P' * 30)
        self.cleanup = AsyncMock()
        self.bot = SimpleNamespace(send_cached_media=AsyncMock(return_value=SimpleNamespace(id=7)))
        fake_asyncio = SimpleNamespace(create_task=asyncio.create_task, sleep=AsyncMock())
        self.env = {'asyncio': fake_asyncio, '_probe_lock': asyncio.Lock(), '_STATS': stats(),
                    '_read_doc': AsyncMock(side_effect=lambda fid: dict(self.doc)), '_meta_version': lambda d: d['meta_v'],
                    'META_V': 2, 'temp': SimpleNamespace(BOT=self.bot), 'BIN_CHANNEL': 1,
                    'THUMB_PROBE_ATTEMPTS': 2, 'THUMB_FLOOD_EXTRA': 10,
                    'flood_wait_seconds': lambda e: 0, '_backoff': AsyncMock(), '_add_flood_penalty': MagicMock(),
                    '_clear_flood_penalty': MagicMock(), '_GAP_PENALTY': 0,
                    'THUMB_PROBE_GAP_MIN': 3, 'THUMB_PROBE_GAP_MAX': 5,
                    'random': SimpleNamespace(uniform=lambda a, b: 3),
                    '_extract_media': lambda msg: (None, ['candidate']), '_real_thumb_bytes': self.candidates,
                    '_upload_thumb': self.upload, '_valid_thumb_ref': lambda x: bool(x) and len(x) > 20,
                    'update_file_meta': self.update, '_delete_later': self.cleanup,
                    '_download_thumb': AsyncMock(), 'logger': logging.getLogger(__name__)}
        load_functions('web/thumb_engine.py', {'probe_file'}, self.env)

    async def run_probe(self, force=False):
        result = await self.env['probe_file']('file', force=force)
        await asyncio.sleep(0)  # allow the scheduled probe-message cleanup to run
        return result

    async def test_download_failure_is_retryable_and_counted_as_failure(self):
        self.candidates.return_value = (None, {}, True)
        self.assertIsNone(await self.run_probe())
        self.update.assert_not_awaited()
        self.assertEqual((self.env['_STATS']['failed'], self.env['_STATS']['no_thumb']), (1, 0))
        self.cleanup.assert_awaited_once_with(7)

    async def test_missing_or_rejected_candidates_can_be_marked_no_thumb(self):
        await self.run_probe()
        meta = self.update.await_args.args[1]
        self.assertEqual(meta['thumb_url'], 'NO_THUMB')
        self.assertEqual(self.update.await_args.kwargs['expected_thumb'], self.doc)
        self.assertEqual((self.env['_STATS']['no_thumb'], self.env['_STATS']['failed']), (1, 0))

    async def test_permanent_upload_failure_never_stores_ephemeral_reference(self):
        self.candidates.return_value = (b'valid', {'ref': 'T' * 30, 'width': 100, 'height': 150}, False)
        self.upload.return_value = ''
        self.assertIsNone(await self.run_probe())
        self.update.assert_not_awaited()
        self.assertEqual((self.env['_STATS']['failed'], self.env['_STATS']['ok']), (1, 0))

    async def test_db_failure_or_admin_race_cannot_be_reported_as_success(self):
        self.candidates.return_value = (b'valid', {'ref': 'T' * 30, 'width': 100, 'height': 150}, False)
        self.update.return_value = False
        self.assertIsNone(await self.run_probe())
        self.assertEqual((self.env['_STATS']['failed'], self.env['_STATS']['ok']), (1, 0))
        self.assertEqual(self.update.await_args.kwargs['expected_thumb'], self.doc)
        self.cleanup.assert_awaited_once()

    async def test_success_only_saves_permanent_id_and_respects_existing_custom(self):
        self.candidates.return_value = (b'valid', {'ref': 'T' * 30, 'width': 100, 'height': 150}, False)
        self.assertEqual(await self.run_probe(), b'valid')
        meta = self.update.await_args.args[1]
        self.assertEqual(meta['thumb_url'], 'TG_ID:' + 'P' * 30)
        self.assertTrue(meta['is_thumb_permanent'])
        self.assertEqual(self.env['_STATS']['ok'], 1)
        self.doc.update(thumb_source='web', thumb_url='TG_ID:custom')
        self.update.reset_mock();self.bot.send_cached_media.reset_mock()
        await self.run_probe()
        self.update.assert_not_awaited();self.bot.send_cached_media.assert_not_awaited()

    async def test_explicit_retry_and_legacy_nonpermanent_are_probed(self):
        self.doc.update(thumb_url='NO_THUMB')
        self.candidates.return_value = (None, {}, True)
        await self.run_probe(force=True)
        self.update.assert_not_awaited()
        self.doc.update(thumb_url='TG_ID:old', thumb_verified=True, is_thumb_permanent=False)
        await self.run_probe()
        self.assertEqual(self.bot.send_cached_media.await_count, 2)

    async def test_unexpected_processing_error_still_cleans_up(self):
        self.candidates.side_effect = RuntimeError('network')
        await self.run_probe()
        self.assertEqual(self.env['_STATS']['failed'], 1)
        self.cleanup.assert_awaited_once_with(7)


class UpdateTests(unittest.IsolatedAsyncioTestCase):
    async def test_compare_and_set_blocks_admin_overwrite_and_detects_missing(self):
        doc = {'_id': 'file', 'thumb_url': '', 'thumb_source': ''}
        class Collection:
            def update_one(self, query, update):
                if doc.get('_id') != query['_id'] or any(doc.get(k) != v for k, v in query.items() if k != '_id'):
                    return SimpleNamespace(matched_count=0)
                doc.update(update['$set'])
                return SimpleNamespace(matched_count=1)
        clear = MagicMock()
        env = {'asyncio': asyncio, 'collection': Collection(), 'cache_clear': clear, 'logger': logging.getLogger(__name__)}
        load_functions('database/ia_filterdb.py', {'update_file_meta'}, env)
        snapshot = dict(doc)
        doc.update(thumb_url='TG_ID:admin', thumb_source='web')
        self.assertFalse(await env['update_file_meta']('file', {'thumb_url': 'NO_THUMB'}, expected_thumb=snapshot))
        self.assertEqual(doc['thumb_url'], 'TG_ID:admin')
        self.assertFalse(await env['update_file_meta']('missing', {'duration': 1}))
        self.assertTrue(await env['update_file_meta']('file', {'duration': 1}))
        clear.assert_called_once()

    def test_recovery_is_opt_in_and_does_not_bulk_reset(self):
        src = (ROOT / 'plugins/warmup.py').read_text()
        self.assertIn('retry_no_thumb', src)
        self.assertIn('{"thumb_url": "NO_THUMB", "thumb_source": {"$ne": "web"}}', src)
        self.assertIn('probe_file(fid, force=retry_no_thumb)', src)
        self.assertNotIn('update_many', src)


class ThumbReadRaceTests(unittest.IsolatedAsyncioTestCase):
    def make_env(self, docs, image=b'image'):
        cache = {}
        env = {'asyncio': asyncio, '_read_doc': AsyncMock(side_effect=docs),
               '_cache_get': lambda key: cache.get(key), '_cache_put': lambda key, data: cache.__setitem__(key, data),
               '_INFLIGHT': {}, '_download_thumb': AsyncMock(return_value=image), '_STATS': stats(),
               'enqueue_probe': MagicMock(return_value=True), 'update_file_meta': AsyncMock(return_value=False),
               '_validate_thumb_async': AsyncMock(return_value=(False, {})),
               '_MIN_THUMB_BYTES': 1, '_MIN_THUMB_DIM': 1, '_MIN_THUMB_STDDEV': 1}
        load_functions('web/thumb_engine.py', {'get_thumb', 'is_no_thumb', 'thumb_id_from_doc', '_download_checked_thumb'}, env)
        return env, cache

    async def test_old_inflight_download_not_cached_after_admin_changes_poster(self):
        old = {'thumb_url': 'TG_ID:old', 'thumb_verified': True}
        new = {'thumb_url': 'TG_ID:new', 'thumb_verified': True, 'thumb_source': 'web'}
        env, cache = self.make_env([old, new])
        self.assertIsNone(await env['get_thumb']('file'))
        self.assertEqual(cache, {})
        env['update_file_meta'].assert_not_awaited()

    async def test_failed_compare_and_set_never_clears_new_admin_poster(self):
        old = {'thumb_url': 'TG_ID:old', 'thumb_verified': True}
        env, cache = self.make_env([old, old])
        self.assertIsNone(await env['get_thumb']('file'))
        self.assertEqual(env['update_file_meta'].await_args.kwargs['expected_thumb'], old)
        env['enqueue_probe'].assert_not_called()

    async def test_legacy_or_unverified_thumb_is_queued_for_repair(self):
        doc = {'thumb_url': 'TG_ID:old', 'thumb_verified': True, 'is_thumb_permanent': False}
        env, _ = self.make_env([doc, doc])
        await env['get_thumb']('file')
        env['enqueue_probe'].assert_called_once_with('file', force=True)


class MongoCompatibilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_conditional_update_and_warmup_query_in_mongomock(self):
        try:
            import mongomock
        except ImportError:
            self.skipTest('optional mongomock not installed')
        import re
        collection = mongomock.MongoClient().db.files
        collection.insert_many([
            {'_id': 'race', 'thumb_url': '', 'thumb_source': ''},
            {'_id': 'weak', 'thumb_url': 'TG_ID:old', 'thumb_source': 'probe', 'thumb_verified': True, 'is_thumb_permanent': False, 'meta_v': 2},
            {'_id': 'custom', 'thumb_url': 'TG_ID:custom', 'thumb_source': 'web', 'thumb_verified': True, 'is_thumb_permanent': False, 'meta_v': 2},
            {'_id': 'none', 'thumb_url': 'NO_THUMB'},
        ])
        env = {'asyncio': asyncio, 'collection': collection, 'cache_clear': lambda: None,
               'logger': logging.getLogger(__name__)}
        load_functions('database/ia_filterdb.py', {'update_file_meta'}, env)
        snapshot = collection.find_one({'_id': 'race'})
        collection.update_one({'_id': 'race'}, {'$set': {'thumb_url': 'TG_ID:new', 'thumb_source': 'web'}})
        self.assertFalse(await env['update_file_meta']('race', {'thumb_url': 'NO_THUMB'}, expected_thumb=snapshot))
        self.assertEqual(collection.find_one({'_id': 'race'})['thumb_url'], 'TG_ID:new')
        source = ast.parse((ROOT / 'plugins/warmup.py').read_text())
        query_node = next(n for n in source.body if isinstance(n, ast.Assign) and
                          any(isinstance(t, ast.Name) and t.id == '_PENDING_QUERY' for t in n.targets))
        ns = {'re': re, 'META_V': 2}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[query_node], type_ignores=[])), '<query>', 'exec'), ns)
        ids = {d['_id'] for d in collection.find(ns['_PENDING_QUERY'])}
        self.assertIn('weak', ids)
        self.assertNotIn('custom', ids)
        self.assertNotIn('none', ids)
