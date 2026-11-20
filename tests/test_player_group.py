import ast
import json
import html
from urllib.parse import quote
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

ROOT = Path(__file__).resolve().parents[1]


def load_function(path, name, namespace):
    tree = ast.parse(path.read_text())
    node = next(n for n in tree.body if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) and n.name == name)
    node.decorator_list = []
    module = ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[]))
    exec(compile(module, str(path), 'exec'), namespace)
    return namespace[name]


class PlayerGroupTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.store = SimpleNamespace(by_members=AsyncMock(), files_by_ids=AsyncMock())
        self.auth = AsyncMock(return_value=('user', 1))
        self.ns = {'get_auth': self.auth, 'store': self.store,
                   '_unauthorized': lambda: ('unauthorized', 401),
                   'web': SimpleNamespace(json_response=lambda data, status=200: (data, status)),
                   'logger': SimpleNamespace(exception=lambda *args: None),
                   'clean_episode_map': lambda x: x or {},
                   'normal_kind': lambda x: x or 'qualities', 'KIND_EPISODES': 'episodes',
                   'episode_identity': lambda n: 'E02' if 'E02' in n else '',
                   'episode_label': lambda n, i: (f'E{i+1:02}', i+1),
                   'quality_label': lambda h, n, q: (q or '?', 0),
                   'vcard_meta': lambda doc: {'duration': doc.get('formatted_duration', ''), 'size': doc.get('formatted_size', '0.00 B')}}
        self.handler = load_function(ROOT / 'web/search_routes.py', 'api_player_group', self.ns)

    async def test_members_preserve_custom_episode_and_quality_and_ignore_deleted(self):
        self.store.by_members.return_value = [{'members': ['a', 'b', 'missing'], 'kind': 'episodes', 'episode_map': {'a': 'Special'}}]
        self.store.files_by_ids.return_value = [{'_id': 'b', 'file_name': 'Show E02', 'quality': '720p'}, {'_id': 'a', 'file_name': 'Show', 'quality': '1080p', 'file_size': 1024, 'formatted_size': '1.00 KB', 'formatted_duration': '23:10'}]
        data, status = await self.handler(SimpleNamespace(query={'file_id': 'a'}))
        self.assertEqual(status, 200)
        self.assertEqual([(i['file_id'], i['episode'], i['quality']) for i in data['items']], [('a', 'Special', '1080p'), ('b', 'E02', '720p')])

        self.assertEqual((data['items'][0]['duration'], data['items'][0]['size']), ('23:10', '1.00 KB'))
        self.assertEqual((data['items'][1]['duration'], data['items'][1]['size']), ('', ''))

    async def test_unauthorized_and_ungrouped(self):
        self.auth.return_value = (None, None)
        self.assertEqual(await self.handler(SimpleNamespace(query={'file_id': 'a'})), ('unauthorized', 401))
        self.store.by_members.assert_not_awaited()
        self.auth.return_value = ('user', 1)
        self.store.by_members.return_value = []
        self.assertEqual(await self.handler(SimpleNamespace(query={'file_id': 'a'})), ({'items': []}, 200))

    def test_modal_actions_share_one_row_and_keep_signed_copy_link(self):
        tree = ast.parse((ROOT / 'web/web_assets.py').read_text())
        values = {n.targets[0].id: ast.literal_eval(n.value) for n in tree.body
                  if isinstance(n, ast.Assign) and len(n.targets) == 1
                  and isinstance(n.targets[0], ast.Name)
                  and n.targets[0].id in ('PLAYER_MODAL_HTML', 'PLAYER_JS', 'SITE_CSS')}
        modal, js, css = values['PLAYER_MODAL_HTML'], values['PLAYER_JS'], values['SITE_CSS']
        self.assertNotIn('pWatch', modal + js)
        self.assertNotIn('Copy stream link', modal)
        self.assertIn('Copy link', modal)
        self.assertIn('id="pDl"', modal)
        self.assertIn('closePlayer()', modal)
        self.assertIn('grid-template-columns:repeat(3,minmax(0,1fr))', css)
        self.assertIn('currentWatch=location.origin+d.watch', js)
        self.assertIn('clip.writeText(currentWatch)', js)

    def test_choice_cards_show_current_item_and_metadata_accessibly(self):
        assets = (ROOT / 'web/web_assets.py').read_text()
        for part in ('choice-label', 'choice-name', 'choice-meta', 'choice-state',
                     "state.textContent='Selected'", "setAttribute('aria-pressed'",
                     'focus-visible', 'grid-template-columns:repeat(2,minmax(0,1fr))',
                     'name.textContent=item.name', 'item.duration', 'item.size'):
            self.assertIn(part, assets)

    def test_player_race_guards(self):
        assets = (ROOT / 'web/web_assets.py').read_text()
        for part in ('duration:v.duration', 'size:v.size', 'request!==seq', 'playerGroupContext(el)'):
            self.assertIn(part, assets)

    async def test_signed_page_reuses_search_player_and_signed_download(self):
        info = SimpleNamespace(file_name='Title <HD>.mp4', file_id='tg', mime_type=None, is_video=False)
        ns = dict(html=html, quote=quote, get_media_info=AsyncMock(return_value=info),
                  unpack_new_file_id=lambda _: 'group-id', PLAYER_JS='PLAYER SCRIPT',
                  PLAYER_MODAL_HTML='SHARED MODAL', page=lambda title, body, **kwargs: body)
        watch = load_function(ROOT / 'web/utils/render_template.py', 'media_watch', ns)
        guest = await watch(42, 'e=123&s=abc')
        for part in ('SHARED MODAL', 'PLAYER SCRIPT', 'data-stream="/download/42?e=123&amp;s=abc"',
                     'data-name="Title &lt;HD&gt;.mp4"', 'data-file-id="group-id"', 'data-account="0"',
                     'data-poster=""'):
            self.assertIn(part, guest)
        signed_in = await watch(42, signed_in=True, poster='https://example.org/untrusted')
        self.assertIn('data-poster="/api/thumb?file_id=group-id"', signed_in)
        self.assertIn('data-account="1"', signed_in)
