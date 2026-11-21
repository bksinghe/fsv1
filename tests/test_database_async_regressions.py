"""Regression tests for nonblocking media operations and re-index poster safety."""
import ast
import asyncio
import logging
import re
import threading
import time
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock


class DuplicateKeyError(Exception):
    pass


def load_functions(*names, **extra):
    tree = ast.parse((Path(__file__).resolve().parents[1] / 'database/ia_filterdb.py').read_text())
    nodes = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names]
    module = ast.Module(body=nodes, type_ignores=[])
    ns = dict(asyncio=asyncio, re=re, time=time, datetime=datetime, logger=logging.getLogger(__name__),
              List=list, Dict=dict, Tuple=tuple, Optional=__import__('typing').Optional,
              Any=object, MAX_BTN=10, WEB_EXTRA_FIELDS={}, USE_CAPTION_FILTER=False,
              SEARCH_CACHE={}, CACHE_GENERATION=0, CACHE_TTL=30, MAX_CACHE_SIZE=1000,
              DuplicateKeyError=DuplicateKeyError)
    ns.update(extra)
    exec(compile(ast.fix_missing_locations(module), '<database>', 'exec'), ns)
    return ns


class DatabaseAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_iteration_and_count_run_off_loop_and_stale_results_not_cached(self):
        started, release = threading.Event(), threading.Event()
        loop_thread = threading.get_ident()
        threads = []
        class Cursor:
            def sort(self, *a): return self
            def skip(self, *a): return self
            def limit(self, *a): return self
            def __iter__(self):
                threads.append(threading.get_ident()); started.set(); release.wait(3)
                return iter([{'_id': 'x'}])
        class Collection:
            def revision(self): return 0
            def find(self, *a): threads.append(threading.get_ident()); return Cursor()
            def count_documents(self, *a, **kw): threads.append(threading.get_ident()); return 1
        ns = load_functions('get_search_results', 'cache_get', 'cache_set', 'cache_clear', collection=Collection())
        task = asyncio.create_task(ns['get_search_results']('movie'))
        self.assertTrue(await asyncio.to_thread(started.wait, 2))
        ns['cache_clear']()
        release.set()
        self.assertEqual((await task)[2], 1)
        self.assertTrue(threads and all(t != loop_thread for t in threads))
        self.assertEqual(ns['SEARCH_CACHE'], {})

    async def test_duplicate_preserves_custom_poster_and_conditional_fill(self):
        class Collection:
            def __init__(self): self.calls = []
            def insert_one(self, doc): raise DuplicateKeyError()
            def update_one(self, query, update):
                self.calls.append((query, update, threading.get_ident()))
                return SimpleNamespace(matched_count=1)
        col = Collection()
        ns = load_functions('save_file', collection=col, cache_clear=lambda: None,
                            unpack_new_file_id=lambda x: 'id', clean_text=lambda x: x,
                            detect_quality=lambda x: '720p', _auto_join_group=AsyncMock())
        media = SimpleNamespace(file_id='raw', file_name='movie', file_size=12, caption='new',
                                thumbs=[SimpleNamespace(file_id='new-thumb')])
        self.assertEqual(await ns['save_file'](media), 'dup')
        metadata, poster = col.calls
        self.assertNotIn('thumb_url', metadata[1]['$set'])
        self.assertEqual(poster[0]['thumb_source'], {'$ne': 'web'})
        self.assertEqual(poster[0]['thumb_verified'], {'$ne': True})
        self.assertIn({'thumb_url': ''}, poster[0]['$and'][0]['$or'])
        self.assertIn({'thumb_file_id': ''}, poster[0]['$and'][1]['$or'])
        self.assertEqual(poster[0]['is_thumb_permanent'], {'$ne': True})
        self.assertEqual(poster[1]['$set']['thumb_url'], 'TG_ID:new-thumb')
        self.assertTrue(all(c[2] != threading.get_ident() for c in col.calls))

    async def test_cancellation_propagates(self):
        started, release = threading.Event(), threading.Event()
        def find_one(*args): started.set(); release.wait(3); return {}
        ns = load_functions('get_file_details', collection=SimpleNamespace(find_one=find_one))
        task = asyncio.create_task(ns['get_file_details']('id'))
        self.assertTrue(await asyncio.to_thread(started.wait, 2))
        task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        release.set()
