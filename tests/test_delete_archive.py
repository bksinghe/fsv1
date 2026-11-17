import ast
import asyncio
import html
import logging
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

ROOT = Path(__file__).resolve().parents[1]


def load_service():
    tree = ast.parse((ROOT / 'database/delete_archive.py').read_text())
    nodes = [n for n in tree.body if isinstance(n, (ast.ClassDef, ast.AsyncFunctionDef))]
    env = {'asyncio': asyncio, 'html': html, 'logger': logging.getLogger('test'),
           'enums': SimpleNamespace(ParseMode=SimpleNamespace(HTML='html')),
           'DELETE_ARCHIVE_CHANNEL': -1009, 'INDEX_CHANNELS': [],
           '_delete_lock': asyncio.Lock(),
           'ia': SimpleNamespace(get_file_meta=AsyncMock(return_value={'caption': 'a < b'}),
                                 delete_file_by_id=AsyncMock(return_value=True)),
           'group_store': SimpleNamespace(pull_files=AsyncMock(), cleanup_empty=AsyncMock())}
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), '<archive>', 'exec'), env)
    return env


class ArchiveTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.env = load_service()
        self.bot = SimpleNamespace(send_cached_media=AsyncMock(return_value=SimpleNamespace(id=10)))

    async def test_archive_completes_before_delete(self):
        events = []
        async def send(**kwargs):
            events.append('archived')
            self.assertEqual(kwargs['chat_id'], -1009)
            self.assertEqual(kwargs['caption'], 'a &lt; b')
            return SimpleNamespace(id=10)
        async def delete(fid):
            events.append('deleted')
            return True
        self.bot.send_cached_media.side_effect = send
        self.env['ia'].delete_file_by_id.side_effect = delete
        self.assertTrue(await self.env['archive_and_delete'](self.bot, 'abc'))
        self.assertEqual(events, ['archived', 'deleted'])
        self.env['group_store'].pull_files.assert_awaited_once_with(['abc'])

    async def test_fail_closed_on_missing_config_or_archive_failure(self):
        for variant in ('unset', 'indexed', 'offline', 'bad_message'):
            with self.subTest(variant=variant):
                env = load_service()
                bot = SimpleNamespace(send_cached_media=AsyncMock(return_value=SimpleNamespace(id=10)))
                if variant == 'unset': env['DELETE_ARCHIVE_CHANNEL'] = None
                if variant == 'indexed': env['INDEX_CHANNELS'] = [-1009]
                if variant == 'offline': bot.send_cached_media.side_effect = RuntimeError('bad')
                if variant == 'bad_message': bot.send_cached_media.return_value = None
                with self.assertRaises(env['ArchiveDeleteError']):
                    await env['archive_and_delete'](bot, 'abc')
                env['ia'].delete_file_by_id.assert_not_awaited()
                env['group_store'].pull_files.assert_not_awaited()

    async def test_db_failure_is_reported_after_archive(self):
        self.env['ia'].delete_file_by_id.return_value = False
        with self.assertRaisesRegex(self.env['ArchiveDeleteError'], 'archived.*database deletion failed'):
            await self.env['archive_and_delete'](self.bot, 'abc')
        self.bot.send_cached_media.assert_awaited_once()
        self.env['group_store'].pull_files.assert_not_awaited()

    async def test_missing_file_not_archived(self):
        self.env['ia'].get_file_meta.return_value = None
        self.assertFalse(await self.env['archive_and_delete'](self.bot, 'abc'))
        self.bot.send_cached_media.assert_not_awaited()

    async def test_concurrent_same_file_does_not_archive_twice(self):
        self.env['ia'].get_file_meta.side_effect = [{'caption': ''}, None]
        results = await asyncio.gather(*(self.env['archive_and_delete'](self.bot, 'abc') for _ in range(2)))
        self.assertEqual(results, [True, False])
        self.bot.send_cached_media.assert_awaited_once()


class IntegrationTests(unittest.TestCase):
    def test_web_and_pm_use_shared_safe_path(self):
        web = (ROOT / 'web/file_edit_routes.py').read_text()
        bot = (ROOT / 'plugins/admin_tools.py').read_text()
        channel = (ROOT / 'plugins/channel.py').read_text()
        self.assertIn('await archive_and_delete(getattr(temp, "BOT", None), fid)', web)
        self.assertIn('await archive_and_delete(bot, fid)', bot)
        self.assertIn('filters.private & filters.command("delete")', bot)
        self.assertIn('await find_delete_batch(key, after)', bot)
        self.assertIn('if message.chat.id == DELETE_ARCHIVE_CHANNEL:', channel)
