"""Group filtering scans beyond 500 without caching the entire file result."""
import ast
import asyncio
import logging
import re
import unittest
from pathlib import Path
from typing import Dict, List, Tuple
from unittest.mock import AsyncMock

ROOT=Path(__file__).resolve().parents[1]


def function(path,name):
    tree=ast.parse((ROOT/path).read_text())
    return next(n for n in tree.body if isinstance(n,(ast.AsyncFunctionDef,ast.FunctionDef)) and n.name==name)


def install(fn,ns):
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<isolated>','exec'),ns)
    return ns[fn.name]


class GroupUnlimitedTests(unittest.IsolatedAsyncioTestCase):
    async def test_full_database_search_bypasses_cache_and_ignores_count_cap(self):
        docs=[{'_id':str(i)} for i in range(12005)]
        class Cursor:
            def sort(self,*args): return self
            def skip(self,n): self.offset=n;return self
            def limit(self,n): self.n=n;return self
            def __iter__(self):return iter(docs[self.offset:] if self.n==0 else docs[self.offset:self.offset+self.n])
        class Collection:
            def find(self,*args):return Cursor()
            def count_documents(self,filter,limit):return min(limit,len(docs))
        cache_set=unittest.mock.Mock(); cache_get=unittest.mock.Mock(return_value=None)
        ns={'List':List,'Tuple':Tuple,'Dict':Dict,'MAX_BTN':10,'USE_CAPTION_FILTER':False,'WEB_EXTRA_FIELDS':{},
            'collection':Collection(),'asyncio':asyncio,'re':re,'logger':logging.getLogger(__name__),
            'CACHE_GENERATION':0,'cache_get':cache_get,'cache_set':cache_set}
        search=install(function('database/ia_filterdb.py','get_search_results'),ns)
        found,nxt,total=await search('common',0,0)
        self.assertEqual((len(found),nxt,total),(12005,'',10000))
        cache_get.assert_not_called();cache_set.assert_not_called()
        class NoTextCollection(Collection):
            def find(self,filter,*args):
                if '$text' in filter: raise RuntimeError('missing index')
                return Cursor()
        ns['collection']=NoTextCollection()
        with self.assertLogs(level='ERROR'):
            fallback,nxt,count=await search('common',0,0)
        self.assertEqual((len(fallback),nxt,count),(12005,'',5000))
        cache_set.assert_not_called()

    async def test_main_group_scans_past_500_and_paginates_all_group_cards(self):
        docs=[{'_id':str(i)} for i in range(12005)]
        search=AsyncMock(return_value=(docs,'',10000));recent=AsyncMock(return_value=(docs,'',12005))
        async def group(cards,normalize):return [{'group':True,'id':c['id']} for c in cards]
        ns={'GROUP_FILTER_LOCK':asyncio.Lock(),'get_search_results':search,'get_recent_files':recent,
            '_result':lambda d:{'id':d['_id']},'group_cards':group,'filter_group_cards':lambda cards,mode:cards}
        run=install(function('web/search_routes.py','_group_page'),ns)
        page,nxt,total=await run('keyword',12000,10,'group')
        self.assertEqual((page[-1]['id'],nxt,total),('12004','',12005))
        search.assert_awaited_once_with('keyword',0,0)
        await run('',0,10,'group');recent.assert_awaited_once_with(0,0)

    async def test_full_group_scans_are_serialized(self):
        active=0;max_active=0
        async def find(*args):
            nonlocal active,max_active
            active+=1;max_active=max(active,max_active);await asyncio.sleep(.01);active-=1
            return [],'',0
        ns={'GROUP_FILTER_LOCK':asyncio.Lock(),'get_search_results':find,'get_recent_files':find,
            '_result':lambda d:d,'group_cards':AsyncMock(return_value=[]),'filter_group_cards':lambda c,m:c}
        run=install(function('web/search_routes.py','_group_page'),ns)
        await asyncio.gather(run('one',0,10,'group'),run('two',0,10,'group'))
        self.assertEqual(max_active,1)

    async def test_actor_group_scan_fetches_all_tags_deduplicated(self):
        async def search(term,offset,limit):
            self.assertEqual((offset,limit),(0,0))
            ids=range(0,650) if term=='first' else range(600,1250)
            return [{'_id':str(i)} for i in ids],'',650
        ns={'get_search_results':search,'logger':logging.getLogger(__name__)}
        tag_media=install(function('web/catalog_routes.py','_tag_media'),ns)
        docs,nxt,terms,total,source=await tag_media({'tags':['first','second']},'',0,0)
        self.assertEqual((len(docs),nxt,terms,total,source),(1250,'',['first','second'],1250,'tags'))
        self.assertEqual(len({d['_id'] for d in docs}),1250)
