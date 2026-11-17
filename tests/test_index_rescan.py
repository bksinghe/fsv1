import ast
import asyncio
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock


class IndexRescanTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tree = ast.parse((Path(__file__).resolve().parents[1] / 'plugins/index.py').read_text())
        nodes = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and n.name in ('index_worker', 'is_index_request')]
        module = ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[]))
        self.ns = dict(asyncio=asyncio, time=time, CANCEL=False, ACTIVE_INDEXES=set(),
                       enums=SimpleNamespace(MessageMediaType=SimpleNamespace(VIDEO='video', DOCUMENT='document'),
                                             ChatType=SimpleNamespace(CHANNEL='channel')),
                       FloodWait=type('FloodWait', (Exception,), {}),
                       get_readable_time=lambda x: 'time', log_error=lambda *args: None,
                       save_file=AsyncMock(return_value='suc'), set_resume=AsyncMock(),
                       send_log=AsyncMock(), auto_delete=AsyncMock())
        exec(compile(module, '<index>', 'exec'), self.ns)

    async def test_rescan_repairs_older_holes(self):
        media = SimpleNamespace(value='document')
        self.ns['enums'].MessageMediaType.DOCUMENT = media
        message = SimpleNamespace(media=media, document=SimpleNamespace(), caption='caption')
        bot = SimpleNamespace(get_messages=AsyncMock(return_value=message))
        status = SimpleNamespace(edit=AsyncMock(return_value=SimpleNamespace(chat=SimpleNamespace(id=1), id=2)))
        await self.ns['index_worker'](bot, status, 7, 3, 'channel')
        self.assertEqual([c.args[1] for c in bot.get_messages.await_args_list], [3, 2, 1])
        self.ns['set_resume'].assert_awaited_once_with(7, 3)
        await asyncio.sleep(0)

    async def test_fetch_or_save_failure_does_not_advance_checkpoint(self):
        for failure in ('fetch', 'save'):
            with self.subTest(failure=failure):
                self.ns['set_resume'].reset_mock()
                media = SimpleNamespace(value='document')
                self.ns['enums'].MessageMediaType.DOCUMENT = media
                msg = SimpleNamespace(media=media, document=SimpleNamespace(), caption='')
                bot = SimpleNamespace(get_messages=AsyncMock(return_value=msg))
                if failure == 'fetch':
                    bot.get_messages.side_effect = RuntimeError('offline')
                self.ns['save_file'].return_value = 'err' if failure == 'save' else 'suc'
                status = SimpleNamespace(edit=AsyncMock())
                await self.ns['index_worker'](bot, status, 7, 3, 'channel')
                self.ns['set_resume'].assert_not_awaited()
                self.assertIn('Failed', status.edit.await_args.args[0])
                self.assertNotIn(7, self.ns['ACTIVE_INDEXES'])

    def test_request_filter_does_not_capture_commands(self):
        f = self.ns['is_index_request']
        self.assertFalse(f(None, None, SimpleNamespace(text='/stats', forward_from_chat=None)))
        self.assertTrue(f(None, None, SimpleNamespace(text='https://t.me/channel/42', forward_from_chat=None)))
        self.assertTrue(f(None, None, SimpleNamespace(text=None, forward_from_chat=SimpleNamespace(type='channel'))))


if __name__ == '__main__':
    unittest.main()
