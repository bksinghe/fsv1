"""The bot report follows the compact Telegram blockquote layout."""
import ast
import html
import unittest
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import AsyncMock

SOURCE = (Path(__file__).resolve().parents[1] / 'plugins/admin_tools.py').read_text()


class StatsLayoutTests(unittest.IsolatedAsyncioTestCase):
    async def test_snapshot_values_layout_and_escaping(self):
        tree = ast.parse(SOURCE)
        nodes = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and n.name in ('_stat_value', 'build_stats')]
        values = {'users': 1, 'chats': 2, 'files': 3, 'premium': 4, 'db_size': '8.32 MB',
                  'uptime': '7m', 'web_accounts': 5, 'posts': 6, 'actors': 7, 'groups': 8,
                  'quality_groups': 9, 'episode_groups': 10, 'episodes_total': 11,
                  'thumbnails': 12, 'now': '<bad & date>'}
        ns = {'html': html, 'snapshot': AsyncMock(return_value=values)}
        exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), '<stats>', 'exec'), ns)
        result = await ns['build_stats']()
        ns['snapshot'].assert_awaited_once()
        for fragment in ('<blockquote>📊 <b>BOT STATISTICS</b></blockquote>',
                         '👤 <b>Users:</b> <code>1</code>', '👥 <b>Groups:</b> <code>2</code>',
                         'Total Files:</i></b> <code>3</code>', 'Premium:</b> <code>4</code>',
                         'WEB STATISTICS', 'Web Accounts:</b> <code>5</code>',
                         'Posts:</b> <code>6</code>', 'Profiles:</b> <code>7</code>',
                         'Groups:</b> <b><i>8</i></b>', '🎞️ 9 · 📺 10 · 🎬 11 eps',
                         'Posters:</b> <code>12</code>', '&lt;bad &amp; date&gt;'):
            self.assertIn(fragment, result)
        for removed in ('Server:', 'Live Sessions:', 'Thumb Queue:', 'Web Uptime:', 'Port:', 'URL:'):
            self.assertNotIn(removed, result)
        class Tags(HTMLParser):
            def __init__(self): super().__init__(); self.stack = []; self.quotes = 0
            def handle_starttag(self, tag, attrs):
                self.stack.append(tag)
                if tag == 'blockquote': self.quotes += 1
            def handle_endtag(self, tag): self.assert_close(tag)
            def assert_close(self, tag):
                if not self.stack or self.stack.pop() != tag: raise AssertionError('unbalanced ' + tag)
        parser = Tags(); parser.feed(result)
        self.assertEqual(parser.stack, [])
        self.assertEqual(parser.quotes, 11)
