"""Search requires every query term even when Mongo text search uses OR."""
import ast
import asyncio
import logging
import re
import unittest
from pathlib import Path
from typing import Dict, List, Tuple

SOURCE = (Path(__file__).resolve().parents[1] / 'database/ia_filterdb.py').read_text()


class Cursor:
    def __init__(self, docs): self.docs, self.offset, self.size = docs, 0, len(docs)
    def sort(self, *args): return self
    def skip(self, value): self.offset = value; return self
    def limit(self, value): self.size = value; return self
    def __iter__(self): return iter(self.docs[self.offset:self.offset+self.size])


class Collection:
    def __init__(self, docs, text_broken=False):
        self.docs, self.text_broken, self.calls = docs, text_broken, []
    def matches(self, doc, filt):
        def condition(node):
            if '$or' in node: return any(condition(x) for x in node['$or'])
            if '$and' in node: return all(condition(x) for x in node['$and'])
            return all(regex.search(doc.get(field, '')) for field, regex in node.items())
        if '$text' in filt:
            # MongoDB's unquoted multiword text search uses OR.
            terms = filt['$text']['$search'].lower().split()
            text = (doc.get('file_name','')+' '+doc.get('caption','')).lower()
            if not any(term in text for term in terms): return False
        return condition({'$and':filt['$and']})
    def find(self, filt, projection):
        self.calls.append(filt)
        if '$text' in filt and self.text_broken: raise RuntimeError('missing text index')
        return Cursor([d for d in self.docs if self.matches(d, filt)])
    def count_documents(self, filt, limit=None):
        total = sum(self.matches(d, filt) for d in self.docs)
        return min(total, limit) if limit else total


def handler(col, captions=True):
    tree=ast.parse(SOURCE)
    fn=next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name=='get_search_results')
    cache={}
    ns={'List':List,'Tuple':Tuple,'Dict':Dict,'MAX_BTN':10,'USE_CAPTION_FILTER':captions,
        'WEB_EXTRA_FIELDS':{},'collection':col,'asyncio':asyncio,'re':re,
        'logger':logging.getLogger(__name__),'CACHE_GENERATION':0,
        'cache_get':cache.get,'cache_set':lambda key, value:cache.update({key:value})}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])), '<search>', 'exec'),ns)
    return ns['get_search_results']


class SearchAllTermsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.docs=[
            {'_id':'correct', 'file_name':'Anissa.Kate.720p.mp4', 'caption':''},
            {'_id':'wrong', 'file_name':'Joney Kate video', 'caption':''},
            {'_id':'caption', 'file_name':'Joney Kate video', 'caption':'with Anissa'},
            {'_id':'reverse', 'file_name':'kate - anissa film', 'caption':''},
            {'_id':'only-first', 'file_name':'Anissa film', 'caption':''},
        ]

    async def test_text_search_requires_both_case_insensitive_terms(self):
        col=Collection(self.docs);search=handler(col)
        docs,nxt,total=await search('ANISSA   kate',0,10)
        self.assertEqual([d['_id'] for d in docs],['correct','caption','reverse'])
        self.assertEqual((nxt,total),('',3))
        self.assertIn('$text',col.calls[0])

    async def test_disabled_caption_requires_both_terms_in_name(self):
        docs,_,_=await handler(Collection(self.docs),False)('Anissa Kate')
        self.assertEqual([d['_id'] for d in docs],['correct','reverse'])

    async def test_fallback_applies_identical_rules_and_escapes_regex(self):
        col=Collection(self.docs+[{'_id':'literal','file_name':'A+B Kate','caption':''}],text_broken=True)
        search=handler(col)
        with self.assertLogs(level='ERROR'):
            docs,_,_=await search('A+B Kate')
        self.assertEqual([d['_id'] for d in docs],['literal'])
        with self.assertLogs(level='ERROR'):
            docs,_,_=await search('Anissa Kate')
        self.assertEqual([d['_id'] for d in docs],['correct','caption','reverse'])

    async def test_pagination_uses_filtered_count_and_no_fallback_on_empty_late_page(self):
        col=Collection(self.docs);search=handler(col)
        first,nxt,total=await search('Anissa Kate',0,2)
        second,last,total2=await search('Anissa Kate',2,2)
        empty,_,total3=await search('Anissa Kate',4,2)
        self.assertEqual([d['_id'] for d in first+second],['correct','caption','reverse'])
        self.assertEqual((nxt,last,total,total2,total3,empty),('2','',3,3,3,[]))
        self.assertTrue(all('$text' in query for query in col.calls))


    async def test_actor_exact_phrase_case_boundaries_and_separators(self):
        docs=[
            {'_id':'space','file_name':'Anissa Kate 1080p','caption':''},
            {'_id':'dot','file_name':'prefix_Anissa.Kate-720p','caption':''},
            {'_id':'case','file_name':'ANISSA-kAtE video','caption':''},
            {'_id':'extra','file_name':'Anissa and Kate video','caption':''},
            {'_id':'reverse','file_name':'Kate Anissa video','caption':''},
            {'_id':'partial','file_name':'Anissab Kate','caption':''},
            {'_id':'other','file_name':'Joney Kate','caption':''},
            {'_id':'caption','file_name':'other','caption':'featuring Anissa Kate'},
            {'_id':'split','file_name':'Anissa','caption':'Kate'},
            {'_id':'second','file_name':'Anisss kutaa video','caption':''},
        ]
        col=Collection(docs);search=handler(col)
        found,nxt,total=await search('Anissa Kate',0,2,exact_phrase=True)
        more,_,_=await search('Anissa Kate',2,2,exact_phrase=True)
        self.assertEqual([d['_id'] for d in found+more],['space','dot','case','caption'])
        self.assertEqual((nxt,total),('2',4))
        self.assertTrue(all('$text' not in c for c in col.calls))
        second,_,count=await search('Anisss kutaa',0,10,exact_phrase=True)
        self.assertEqual(([d['_id'] for d in second],count),(['second'],1))
        normal,_,_=await search('Anissa Kate',0,10)
        self.assertIn('extra',[d['_id'] for d in normal]) # distinct cache entry
        disabled,_,_=await handler(Collection(docs),False)('Anissa Kate',0,10,exact_phrase=True)
        self.assertNotIn('caption',[d['_id'] for d in disabled])

    async def test_one_word_search_is_still_supported(self):
        docs,_,_=await handler(Collection(self.docs))('Kate')
        self.assertEqual([d['_id'] for d in docs],['correct','wrong','caption','reverse'])
