import ast
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
GROUP = (ROOT / 'web/group_assets.py').read_text()
ASSETS = (ROOT / 'web/web_assets.py').read_text()


def load_preview(ns):
    tree = ast.parse((ROOT / 'web/group_routes.py').read_text())
    fn = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'api_group_preview')
    fn.decorator_list = []
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), '<preview>', 'exec'), ns)
    return ns['api_group_preview']


class PreviewEndpointTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.store = SimpleNamespace(get=AsyncMock(), files_by_ids=AsyncMock())
        self.auth = AsyncMock(return_value=True)
        self.ns = dict(_admin=self.auth, _denied=lambda: ('denied', 403),
            _json=lambda data, status=200: (data, status),
            _fid=lambda v: v if v.isdigit() else '', store=self.store, quote=quote,
            quality_label=lambda h, n, q: (q, int(h.split('×')[-1]) if h else 0), thumb_version=lambda fid, ref: 'v',
            _group_thumb_url=lambda g, variants: variants[-1]['thumb'] if variants else '',
            logger=SimpleNamespace(exception=lambda *a: None))
        self.handler = load_preview(self.ns)

    async def test_exact_id_returns_group_and_highest_quality_poster(self):
        self.store.get.return_value = {'_id': '12', 'num': 12, 'name': 'Show', 'members': ['a', 'b']}
        self.store.files_by_ids.return_value = [{'_id': 'b', 'width': 1920, 'height': 1080}, {'_id': 'a', 'width': 1280, 'height': 720}]
        data, status = await self.handler(SimpleNamespace(query={'id': '#12'}))
        self.assertEqual(status, 200)
        self.assertEqual(data['group']['name'], 'Show')
        self.assertEqual(data['group']['count'], 2)
        self.assertIn('file_id=b', data['group']['thumb'])
        self.store.get.assert_awaited_once_with('12')

    async def test_denied_invalid_missing_and_failure(self):
        req = SimpleNamespace(query={'id': '12'})
        self.auth.return_value = False
        self.assertEqual(await self.handler(req), ('denied', 403))
        self.store.get.assert_not_awaited()
        self.auth.return_value = True
        self.assertEqual((await self.handler(SimpleNamespace(query={'id': '12/3'})))[1], 400)
        self.store.get.return_value = None
        self.assertEqual((await self.handler(req))[1], 404)
        self.store.get.side_effect = RuntimeError('offline')
        self.assertEqual((await self.handler(req))[1], 503)


class PreviewUITests(unittest.TestCase):
    def test_file_merge_prefills_current_group_and_previews_entered_destination(self):
        merge = GROUP.split('window.gMergeFile=async function', 1)[1].split('document.addEventListener(\'click\'', 1)[0]
        for part in ('/api/file/meta?id=', 'file.group_id', 'input.value=sourceId',
                     'id="gmTarget"', 'GroupPreview(input,preview',
                     "'/api/group/save'", 'group_id:dest.id',
                     'id="gmCreateGroup"', 'window.gClose();openSingleGroupEditor(item)'):
            self.assertIn(part, merge)
        self.assertIn("'/api/group/preview?id='+encodeURIComponent(id)", GROUP)

    def test_all_transfers_use_safe_previews_and_confirmation(self):
        for part in ('window.GroupPreview=function', "if(request!==seq)return", "name.textContent=g.name",
                     "GroupPreview(q('#gmFind'),q('#gmChosen')", "GroupPreview(q('#gmTarget'),q('#gmMergePreview')",
                     'if(!dest||dest.id!==targetGid)', "if(dest.id===String(current.gid))",
                     'if(transferring)return d;', 'confirm(\'Merge group #'):
            self.assertIn(part, GROUP)
        for part in ("GroupPreview(q('#feGroupId'),q('#feGroupPreview'))",
                     'dest.id!==target', "confirm('Move this file to group #"):
            self.assertIn(part, ASSETS)

class MergeModalTests(unittest.TestCase):
    def test_merge_does_not_load_or_search_group_lists(self):
        merge = GROUP.split('window.gMerge=function(k)', 1)[1].split('/* ── ☑️ Group Mode', 1)[0]
        self.assertNotIn('/api/group/list', merge)
        self.assertNotIn('gmMergeResults', merge)
        self.assertNotIn('gFindMerge', GROUP)
        self.assertNotIn('gPickMerge', GROUP)
        self.assertIn("GroupPreview(q('#gmTarget'),q('#gmMergePreview'))", merge)
        self.assertIn("confirm('Merge group #", merge)
        self.assertIn("post('/api/group/merge'", merge)
