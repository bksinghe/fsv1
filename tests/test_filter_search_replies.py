"""Initial search responses reply to the query; pagination still edits results."""
import ast
import asyncio
import logging
import unittest
from math import ceil
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

SOURCE = (Path(__file__).resolve().parents[1] / 'plugins/filter.py').read_text()


def load():
    tree = ast.parse(SOURCE)
    names = {'_send_search_message', 'send_results'}
    nodes = [n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name in names]
    ns = dict(asyncio=asyncio, logging=logging, ceil=ceil,
              enums=SimpleNamespace(ParseMode=SimpleNamespace(HTML='html')),
              RESULTS_PER_PAGE_PM=12, RESULTS_PER_PAGE_GROUP=10,
              get_search_results=AsyncMock(), suggest_query=Mock(return_value=None),
              build_results_text=Mock(return_value='results'), build_nav=Mock(return_value='nav'),
              check_premium=AsyncMock(return_value=False),
              update_message_activity=Mock(), auto_expire=AsyncMock(), log_error=Mock())
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), '<filter>', 'exec'), ns)
    return ns


class SearchReplyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.ns = load()
        self.sent = SimpleNamespace(id=22)
        self.reply = SimpleNamespace(reply_text=AsyncMock(return_value=self.sent))
        self.client = SimpleNamespace(send_message=AsyncMock(return_value=self.sent))
        self.args = (self.client, 5, 7, 'movie', 0, 5, False)

    async def test_search_result_replies_and_tracks_returned_message(self):
        self.ns['get_search_results'].return_value = ([{'_id':'x'}], '', 1)
        await self.ns['send_results'](*self.args, reply_msg=self.reply, premium=True)
        await asyncio.sleep(0)
        self.reply.reply_text.assert_awaited_once_with('results', quote=True, reply_markup='nav',
                                                      disable_web_page_preview=True, parse_mode='html')
        self.client.send_message.assert_not_awaited()
        self.ns['update_message_activity'].assert_called_once_with(22)
        self.ns['auto_expire'].assert_awaited_once_with(self.sent)

    async def test_no_results_replies_when_query_exists(self):
        self.ns['get_search_results'].return_value = ([], '', 0)
        await self.ns['send_results'](*self.args, reply_msg=self.reply)
        self.assertTrue(self.reply.reply_text.await_args.kwargs['quote'])
        self.assertIn('No results', self.reply.reply_text.await_args.args[0])
        self.client.send_message.assert_not_awaited()

    async def test_reply_cancellation_is_not_swallowed(self):
        self.ns['get_search_results'].return_value = ([], '', 0)
        self.reply.reply_text.side_effect = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await self.ns['send_results'](*self.args, reply_msg=self.reply)
        self.client.send_message.assert_not_awaited()

    async def test_no_results_replies_and_falls_back_if_deleted(self):
        self.ns['get_search_results'].return_value = ([], '', 0)
        self.reply.reply_text.side_effect = RuntimeError('message deleted')
        await self.ns['send_results'](*self.args, reply_msg=self.reply)
        self.assertTrue(self.reply.reply_text.await_args.kwargs['quote'])
        self.client.send_message.assert_awaited_once()
        self.assertIn('No results', self.client.send_message.await_args.args[1])

    async def test_result_reply_failure_still_delivers_and_tracks(self):
        self.ns['get_search_results'].return_value = ([{'_id':'x'}], '', 1)
        self.reply.reply_text.side_effect = RuntimeError('message deleted')
        await self.ns['send_results'](*self.args, reply_msg=self.reply, premium=True)
        await asyncio.sleep(0)
        self.client.send_message.assert_awaited_once_with(5, 'results', reply_markup='nav',
                                                          disable_web_page_preview=True, parse_mode='html')
        self.ns['update_message_activity'].assert_called_once_with(22)
        self.ns['auto_expire'].assert_awaited_once_with(self.sent)

    async def test_suggestion_preserves_reply_and_premium(self):
        self.ns['get_search_results'].side_effect = [([], '', 0), ([{'_id':'x'}], '', 1)]
        self.ns['suggest_query'].return_value = 'alternate'
        await self.ns['send_results'](*self.args, reply_msg=self.reply, premium=True)
        await asyncio.sleep(0)
        self.reply.reply_text.assert_awaited_once()
        self.ns['check_premium'].assert_not_awaited()
        self.assertEqual(self.ns['build_results_text'].call_args.args[-1], '👑 ')

    async def test_pagination_edits_and_no_reply(self):
        self.ns['get_search_results'].return_value = ([{'_id':'x'}], '', 1)
        result = SimpleNamespace(id=55, edit_text=AsyncMock())
        await self.ns['send_results'](*self.args, message=result, reply_msg=self.reply, premium=True)
        result.edit_text.assert_awaited_once()
        self.reply.reply_text.assert_not_awaited()
        self.client.send_message.assert_not_awaited()
        self.ns['update_message_activity'].assert_called_once_with(55)

    async def test_no_reply_argument_uses_existing_send(self):
        self.ns['get_search_results'].return_value = ([], '', 0)
        await self.ns['send_results'](*self.args)
        self.client.send_message.assert_awaited_once()

    def test_filter_passes_the_original_message(self):
        tree = ast.parse(SOURCE)
        handler = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'filter_handler')
        call = next(n for n in ast.walk(handler) if isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Name) and n.func.id == 'send_results')
        self.assertTrue(any(k.arg == 'reply_msg' and isinstance(k.value, ast.Name)
                            and k.value.id == 'message' for k in call.keywords))
