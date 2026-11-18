"""UnGroup is a flat view of matching files, not a membership filter."""
import ast
import logging
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

ROOT = Path(__file__).resolve().parents[1]


def load_handler(namespace):
    tree = ast.parse((ROOT / 'web/search_routes.py').read_text())
    fn = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'api_search')
    fn.decorator_list = []
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), '<search>', 'exec'), namespace)
    return namespace['api_search']


class UngroupSearchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.docs = [{'_id': str(i), 'group_id': 'saved' if i in (0, 1, 520) else None} for i in range(550)]
        async def fetch(*args):
            offset, limit = args[-2:]
            end = min(offset + limit, len(self.docs))
            return self.docs[offset:end], str(end) if end < len(self.docs) else '', len(self.docs)
        self.search = AsyncMock(side_effect=fetch)
        self.recent = AsyncMock(side_effect=fetch)
        self.group_cards = AsyncMock(return_value=[{'group': True}])
        self.group_page = AsyncMock(return_value=([{'group': True}], '', 1))
        self.namespace = {
            'get_auth': AsyncMock(return_value=('user', 123)),
            '_unauthorized': lambda: {'error': 'unauthorized'},
            'MAX_WEB_RESULTS': 21,
            'get_search_results': self.search, 'get_recent_files': self.recent,
            '_result': lambda doc: {'file_id': doc['_id'], 'name': 'file ' + doc['_id']},
            'group_cards': self.group_cards, '_group_page': self.group_page,
            'web': SimpleNamespace(json_response=lambda obj, **kwargs: obj),
            'logger': logging.getLogger(__name__),
        }
        self.handler = load_handler(self.namespace)

    async def request(self, **query):
        return await self.handler(SimpleNamespace(query=query))

    async def test_flat_search_keeps_group_members_and_paginates_beyond_scan_limit(self):
        first = await self.request(q='film', group='ungroup', limit='21')
        self.assertEqual([r['file_id'] for r in first['results']], [str(i) for i in range(21)])
        self.assertEqual(first['next_offset'], '21')
        self.assertEqual(first['total'], 550)
        self.search.assert_awaited_with('film', 0, 21)
        later = await self.request(q='film', group='ungroup', offset='520', limit='21')
        self.assertEqual(later['results'][0]['file_id'], '520')
        self.assertEqual(later['next_offset'], '541')
        self.group_cards.assert_not_awaited()
        self.group_page.assert_not_awaited()

    async def test_recent_results_are_flat_and_final_page_has_no_next(self):
        result = await self.request(group='ungroup', offset='546', limit='21')
        self.assertEqual([r['file_id'] for r in result['results']], ['546', '547', '548', '549'])
        self.assertEqual(result['next_offset'], '')
        self.recent.assert_awaited_once_with(546, 21)
        self.group_cards.assert_not_awaited()

    async def test_all_and_group_still_use_existing_group_logic(self):
        all_results = await self.request(q='film', group='all')
        self.assertTrue(all_results['results'][0]['group'])
        self.group_cards.assert_awaited_once()
        grouped = await self.request(q='film', group='group', offset='21')
        self.assertTrue(grouped['results'][0]['group'])
        self.group_page.assert_awaited_once_with('film', 21, 21, 'group')

    async def test_unauthorized_never_reads_data(self):
        self.namespace['get_auth'].return_value = (None, None)
        self.assertIn('error', await self.request(group='ungroup'))
        self.recent.assert_not_awaited()
        self.search.assert_not_awaited()
