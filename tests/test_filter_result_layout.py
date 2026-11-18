"""Search messages use a compact quote block and preserve reply/pagination behavior."""
import ast
import asyncio
import html
import logging
import unittest
from html.parser import HTMLParser
from math import ceil
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

SOURCE = (Path(__file__).resolve().parents[1] / 'plugins/filter.py').read_text()


def load():
    tree = ast.parse(SOURCE)
    names = {'build_results_text', '_send_new', 'send_results'}
    nodes = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names]
    ns = dict(html=html, logging=logging, asyncio=asyncio, ceil=ceil,
              enums=SimpleNamespace(ParseMode=SimpleNamespace(HTML='html')),
              temp=SimpleNamespace(U_NAME='ExampleBot'), get_size=lambda n: f'{n} MB',
              RESULTS_PER_PAGE_PM=12, RESULTS_PER_PAGE_GROUP=10,
              get_search_results=AsyncMock(), suggest_query=Mock(return_value=None),
              build_nav=Mock(return_value='buttons'), check_premium=AsyncMock(return_value=False),
              _register_expiry=AsyncMock(), log_error=Mock())
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), '<filter>', 'exec'), ns)
    return ns


class FilterResultLayoutTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.ns = load()
        self.sent = SimpleNamespace(id=10)
        self.reply = SimpleNamespace(reply_text=AsyncMock(return_value=self.sent))
        self.client = SimpleNamespace(send_message=AsyncMock(return_value=self.sent))
        self.args = (self.client, -100, 123, 'search', 0, -100, False)

    def test_layout_escaping_and_deep_links(self):
        text = self.ns['build_results_text']([{'_id':'abc_1', 'file_size':196,
                                              'file_name':'Rock & <Roll> "movie"'}],
                                              'search', 5, 1, 2, -100, '👑 ')
        self.assertIn('<blockquote><b><i>👑 🎬 Total Files: 5\n📄 Page: 1 / 2</i></b></blockquote>', text)
        self.assertIn('https://t.me/ExampleBot?start=file_-100_abc_1', text)
        self.assertIn('📁 <a href=', text)
        self.assertIn('[196 MB] Rock &amp; &lt;Roll&gt; &quot;movie&quot;', text)
        class Reader(HTMLParser):
            def __init__(self): super().__init__(); self.stack=[]; self.links=[]
            def handle_starttag(self, tag, attrs):
                self.stack.append(tag)
                if tag == 'a': self.links.append(dict(attrs)['href'])
            def handle_endtag(self, tag):
                if not self.stack or self.stack.pop() != tag: raise AssertionError(tag)
        parser = Reader(); parser.feed(text)
        self.assertEqual(parser.stack, [])
        self.assertEqual(parser.links, ['https://t.me/ExampleBot?start=file_-100_abc_1'])

    async def test_initial_reply_and_pagination(self):
        self.ns['get_search_results'].return_value = ([{'_id':'a','file_name':'Name'}], '10', 20)
        await self.ns['send_results'](*self.args, reply_msg=self.reply, premium=True)
        await asyncio.sleep(0)
        text = self.reply.reply_text.await_args.args[0]
        self.assertIn('<blockquote>', text)
        self.assertNotIn('Search:', text)
        self.assertTrue(self.reply.reply_text.await_args.kwargs['quote'])
        self.ns['_register_expiry'].assert_awaited_once_with(self.sent)
        result = SimpleNamespace(id=55, edit_text=AsyncMock())
        await self.ns['send_results'](*self.args, message=result, premium=True)
        self.assertIn('<blockquote>', result.edit_text.await_args.args[0])
        self.assertEqual(result.edit_text.await_args.kwargs['reply_markup'], 'buttons')
        self.client.send_message.assert_not_awaited()

    async def test_reply_failure_preserves_search_context_and_links(self):
        self.ns['get_search_results'].return_value = ([{'_id':'a','file_name':'Movie'}], '', 1)
        self.reply.reply_text.side_effect = RuntimeError('deleted')
        await self.ns['send_results'](*self.args, reply_msg=self.reply, premium=False)
        await asyncio.sleep(0)
        text = self.client.send_message.await_args.args[1]
        self.assertIn('<code>search</code>', text)
        self.assertIn('<blockquote>', text)
        self.assertIn('start=file_-100_a', text)

    async def test_suggestion_retains_reply_and_crown(self):
        self.ns['get_search_results'].side_effect = [([], '', 0), ([{'_id':'a'}], '', 1)]
        self.ns['suggest_query'].return_value = 'alternate'
        await self.ns['send_results'](*self.args, reply_msg=self.reply, premium=True)
        await asyncio.sleep(0)
        self.assertIn('👑', self.reply.reply_text.await_args.args[0])
        self.ns['check_premium'].assert_not_awaited()

    async def test_no_results_and_cancelled_reply(self):
        self.ns['get_search_results'].return_value = ([], '', 0)
        await self.ns['send_results'](*self.args, reply_msg=self.reply)
        self.assertIn('No results found', self.reply.reply_text.await_args.args[0])
        self.ns['_register_expiry'].assert_awaited_once_with(self.sent)
        self.reply.reply_text.side_effect = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await self.ns['send_results'](*self.args, reply_msg=self.reply)
        self.client.send_message.assert_not_awaited()
