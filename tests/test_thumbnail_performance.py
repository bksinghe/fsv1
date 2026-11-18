"""Responsiveness and bounded-memory thumbnail regression tests."""
import ast
import asyncio
import threading
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'web/thumb_engine.py').read_text()


def load(names, env):
    tree = ast.parse(SOURCE)
    funcs = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names]
    assert {n.name for n in funcs} == set(names)
    exec(compile(ast.fix_missing_locations(ast.Module(body=funcs, type_ignores=[])), '<thumb>', 'exec'), env)


class ThreadedValidationTests(unittest.IsolatedAsyncioTestCase):
    async def test_validation_does_not_block_loop_and_is_serial(self):
        started = threading.Event()
        release = threading.Event()
        lock = threading.Lock()
        running = 0
        peak = 0
        def validate(data, **kwargs):
            nonlocal running, peak
            with lock:
                running += 1
                peak = max(peak, running)
            started.set()
            if not release.wait(3):
                raise RuntimeError('test timed out')
            with lock:
                running -= 1
            return True, {'reason': 'ok'}
        env = {'asyncio': asyncio, '_validation_sem': asyncio.Semaphore(1), 'validate_thumb': validate,
               '_MIN_THUMB_BYTES': 1, '_MIN_THUMB_DIM': 1, '_MIN_THUMB_STDDEV': 1}
        load({'_validate_thumb_async'}, env)
        first = asyncio.create_task(env['_validate_thumb_async'](b'a'))
        try:
            self.assertTrue(await asyncio.to_thread(started.wait, 1))
            second = asyncio.create_task(env['_validate_thumb_async'](b'b'))
            await asyncio.sleep(.02)  # loop stays responsive while Pillow is working
            self.assertFalse(first.done())
            self.assertFalse(second.done())
            self.assertEqual(peak, 1)
        finally:
            release.set()
        self.assertEqual((await first)[0], True)
        self.assertEqual((await second)[0], True)
        self.assertEqual(peak, 1)

    async def test_cancelled_validation_holds_limit_until_worker_finishes(self):
        started, release = threading.Event(), threading.Event()
        def validate(data, **kwargs):
            started.set()
            if not release.wait(3):
                raise RuntimeError('test timed out')
            return True, {}
        sem = asyncio.Semaphore(1)
        env = {'asyncio': asyncio, '_validation_sem': sem, 'validate_thumb': validate,
               '_MIN_THUMB_BYTES': 1, '_MIN_THUMB_DIM': 1, '_MIN_THUMB_STDDEV': 1}
        load({'_validate_thumb_async'}, env)
        first = asyncio.create_task(env['_validate_thumb_async'](b'a'))
        try:
            self.assertTrue(await asyncio.to_thread(started.wait, 1))
            first.cancel()
            await asyncio.sleep(.02)
            self.assertTrue(sem.locked())
            self.assertFalse(first.done())
        finally:
            release.set()
        with self.assertRaises(asyncio.CancelledError):
            await first
        self.assertFalse(sem.locked())

    async def test_concurrent_and_retry_requests_share_one_download_and_validation(self):
        doc = {'thumb_url': 'TG_ID:poster', 'thumb_verified': True, 'is_thumb_permanent': True}
        started = asyncio.Event()
        release = asyncio.Event()
        async def download(fid):
            started.set()
            await release.wait()
            return b'image'
        validator = AsyncMock(return_value=(True, {}))
        env = {'asyncio': asyncio, '_read_doc': AsyncMock(return_value=doc),
               '_cache_get': lambda key: None, '_cache_put': MagicMock(),
               '_INFLIGHT': {}, '_download_thumb': AsyncMock(side_effect=download),
               '_validate_thumb_async': validator, '_STATS': {'rejected': 0},
               'enqueue_probe': MagicMock(), 'update_file_meta': AsyncMock()}
        load({'get_thumb', 'is_no_thumb', 'thumb_id_from_doc', '_download_checked_thumb'}, env)
        first = asyncio.create_task(env['get_thumb']('file'))
        await started.wait()
        second = asyncio.create_task(env['get_thumb']('file', retry=True))
        await asyncio.sleep(.01)
        release.set()
        self.assertEqual(await asyncio.gather(first, second), [b'image', b'image'])
        self.assertEqual(env['_download_thumb'].await_count, 1)
        self.assertEqual(validator.await_count, 1)
        env['enqueue_probe'].assert_not_called()


class CacheLimitTests(unittest.TestCase):
    def test_default_and_config_are_capped_at_16_mib(self):
        source = ast.parse((ROOT / 'info.py').read_text())
        node = next(n for n in source.body if isinstance(n, ast.Assign) and
                    any(isinstance(t, ast.Name) and t.id == 'THUMB_CACHE_BYTES' for t in n.targets))
        def limit(env):
            ns = {'environ': env}
            exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), '<info>', 'exec'), ns)
            return ns['THUMB_CACHE_BYTES']
        self.assertEqual(limit({}), 16 * 1024 * 1024)
        self.assertEqual(limit({'THUMB_CACHE_BYTES': '33554432'}), 16 * 1024 * 1024)
        self.assertEqual(limit({'THUMB_CACHE_BYTES': '0'}), 0)
        self.assertEqual(limit({'THUMB_CACHE_BYTES': '8388608'}), 8 * 1024 * 1024)
