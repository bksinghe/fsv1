"""Reply command: validate actual signed targets and lifetime without Telegram or Mongo."""
import ast
import importlib.util
import logging
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qsl, urlsplit

ROOT = Path(__file__).resolve().parents[1]


class ReplyLinkTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('reply_link_signer', ROOT / 'stream_security.py')
        self.signer = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, info=SimpleNamespace(BOT_TOKEN='test-only')):
            spec.loader.exec_module(self.signer)
        self.ns = dict(logging=logging, IS_STREAM=True, BIN_CHANNEL=-123, URL='https://example.test/',
                       is_premium=AsyncMock(return_value=True), sign_params=self.signer.sign_params,
                       REPLY_LINK_TTL=self.signer.REPLY_LINK_TTL, styled_keyboard=lambda rows: rows,
                       styled_button=lambda text, url: url)
        node = next(n for n in ast.parse((ROOT / 'plugins/link.py').read_text()).body if isinstance(n, ast.AsyncFunctionDef))
        node.decorator_list = []
        exec(compile(ast.Module([node], type_ignores=[]), 'link.py', 'exec'), self.ns)
        self.client = SimpleNamespace(send_cached_media=AsyncMock(return_value=SimpleNamespace(id=72)))
        self.chat = SimpleNamespace(id=-44, has_protected_content=False)
        self.source = SimpleNamespace(chat=self.chat, media=SimpleNamespace(value='document'),
                                      document=SimpleNamespace(file_id='cached'), has_protected_content=False)
        self.message = SimpleNamespace(chat=self.chat, from_user=SimpleNamespace(id=7),
                                       reply_to_message=self.source, reply_text=AsyncMock())

    async def test_links_use_bin_message_and_expire_in_five_hours(self):
        with patch.object(self.signer.time, 'time', return_value=1000):
            await self.ns['file_link'](self.client, self.message)
            self.client.send_cached_media.assert_awaited_once_with(chat_id=-123, file_id='cached')
            row, = self.message.reply_text.await_args.kwargs['reply_markup']
            urls = list(map(urlsplit, row))
            self.assertEqual([u.path for u in urls], ['/watch/72', '/download/72'])
            self.assertEqual(urls[0].query, urls[1].query)
            params = dict(parse_qsl(urls[0].query))
            self.assertEqual(int(params['e']), 19000)
            self.assertTrue(self.signer.verify(72, params['e'], params['s']))
        with patch.object(self.signer.time, 'time', return_value=19001):
            self.assertFalse(self.signer.verify(72, params['e'], params['s']))

    async def test_invalid_requests_never_copy_files(self):
        for case in ('no reply', 'text', 'protected', 'not premium', 'disabled'):
            with self.subTest(case=case):
                self.message.reply_to_message = None if case == 'no reply' else self.source
                self.source.media = None if case == 'text' else SimpleNamespace(value='document')
                self.source.has_protected_content = case == 'protected'
                self.ns['is_premium'].return_value = case != 'not premium'
                self.ns['IS_STREAM'] = case != 'disabled'
                self.message.reply_text.reset_mock()
                await self.ns['file_link'](self.client, self.message)
                self.message.reply_text.assert_awaited_once()
                self.client.send_cached_media.assert_not_awaited()
