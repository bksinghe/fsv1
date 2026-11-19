"""Actor tags are ORed as complete, ordered phrases before pagination."""
import ast
import asyncio
import logging
import re
import unittest
from pathlib import Path
from types import SimpleNamespace

try:
    import mongomock
except ImportError:
    mongomock=None

ROOT=Path(__file__).resolve().parents[1]


def load(path,name,ns):
    tree=ast.parse((ROOT/path).read_text())
    node=next(n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==name)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'<test>','exec'),ns)
    return ns[name]


class ActorTagMemberTests(unittest.TestCase):
    def test_extra_group_members_obey_identical_tag_rules(self):
        ns={'re':re,'_info':SimpleNamespace(USE_CAPTION_FILTER=True)}
        member=load('web/catalog_routes.py','_tag_member_filter',ns)(['Anissa Kate','Anisss kutaa'])
        self.assertTrue(member({'file_name':'_Anissa.Kate_1080p'}))
        self.assertTrue(member({'file_name':'other','caption':'Anisss kutaa'}))
        for d in ({'file_name':'Joney Kate'}, {'file_name':'Anissa and Kate'},
                  {'file_name':'Kate Anissa'}, {'file_name':'Anissax Kate'},
                  {'file_name':'Anissa','caption':'Kate'}):
            self.assertFalse(member(d),d)
        ns['_info'].USE_CAPTION_FILTER=False
        self.assertFalse(member({'file_name':'other','caption':'Anisss kutaa'}))


@unittest.skipIf(mongomock is None,'mongomock required')
class ActorMultiTagDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_results_are_paginated_and_deduplicated_before_count(self):
        col=mongomock.MongoClient().db.files
        col.insert_many([{'_id':f'{i:04}', 'file_name':f'Anissa_Kate scene {i}', 'caption':''} for i in range(313)]+[
            {'_id':'x','file_name':'Anisss kutaa scene','caption':''},
            {'_id':'y','file_name':'Anissa Kate and Anisss kutaa','caption':''},
            {'_id':'z','file_name':'Joney Kate','caption':''},
            {'_id':'zz','file_name':'Anissa and Kate','caption':''},
        ])
        ns={'re':re,'asyncio':asyncio,'MAX_BTN':12,'USE_CAPTION_FILTER':True,
            'collection':col,'WEB_EXTRA_FIELDS':{}}
        search=load('database/ia_filterdb.py','get_search_results_for_phrases',ns)
        first,nxt,total=await search(['Anissa Kate','Anisss kutaa'],0,12)
        self.assertEqual((len(first),nxt,total),(12,'12',315))
        last,nxt,total=await search(['Anissa Kate','Anisss kutaa'],312,12)
        self.assertEqual((len(last),nxt,total),(3,'',315))
        self.assertEqual({x['_id'] for x in last},{'0312','x','y'})
        all_docs,nxt,total=await search(['Anissa Kate','Anisss kutaa'],0,0)
        self.assertEqual((len(all_docs),nxt,total),(315,'',315))
