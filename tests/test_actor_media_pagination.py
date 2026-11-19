"""Actor single-tag, title and custom searches use full search pagination."""
import ast
import logging
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

ROOT=Path(__file__).resolve().parents[1]


def load(search):
    tree=ast.parse((ROOT/'web/catalog_routes.py').read_text())
    fn=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='_tag_media')
    ns={'get_search_results':search,'logger':logging.getLogger(__name__)}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<catalog>','exec'),ns)
    return ns['_tag_media']


class ActorMediaPaginationTests(unittest.IsolatedAsyncioTestCase):
    async def test_one_tag_uses_full_count_and_correct_offsets(self):
        docs=[{'_id':str(i)} for i in range(313)]
        async def find(q,offset,limit):
            end=min(offset+limit,len(docs))
            return docs[offset:end],str(end) if end<len(docs) else '',len(docs)
        search=AsyncMock(side_effect=find); tag_media=load(search)
        first,nxt,terms,total,source=await tag_media({'tags':['Anissa Kate']},'',0,12)
        self.assertEqual((len(first),nxt,terms,total,source),(12,'12',['Anissa Kate'],313,'tags'))
        last,nxt,_,total,_=await tag_media({'tags':['Anissa Kate']},'',312,12)
        self.assertEqual((last,nxt,total),([{'_id':'312'}],'',313))
        search.assert_any_await('Anissa Kate',312,12)

    async def test_custom_query_and_title_fallback_use_direct_pagination(self):
        search=AsyncMock(return_value=([{'_id':'7'}],'24',50));tag_media=load(search)
        page,nxt,terms,total,source=await tag_media({'tags':['tag']},'custom title',12,12)
        self.assertEqual((page,nxt,terms,total,source),([{'_id':'7'}],'24',['custom title'],50,'custom'))
        search.assert_awaited_with('custom title',12,12)
        _,_,terms,_,source=await tag_media({'title':'Actor Name'},'',12,12)
        self.assertEqual((terms,source),(['Actor Name'],'title'))
        search.assert_awaited_with('Actor Name',12,12)

    async def test_multiple_tags_keep_deduplicated_merge(self):
        async def find(term,offset,limit):
            return ([{'_id':'shared'},{'_id':term}],'',2)
        search=AsyncMock(side_effect=find);tag_media=load(search)
        page,nxt,terms,total,source=await tag_media({'tags':['First','Second']},'',0,2)
        self.assertEqual(([d['_id'] for d in page],nxt,terms,total,source),(['shared','First'],'2',['First','Second'],3,'tags'))
        search.assert_any_await('First',0,60);search.assert_any_await('Second',0,60)

    async def test_no_tags_or_short_term_is_empty(self):
        search=AsyncMock();tag_media=load(search)
        self.assertEqual(await tag_media({'title':'A'},'',0,12),([], '', [], 0, 'title'))
        search.assert_not_awaited()
