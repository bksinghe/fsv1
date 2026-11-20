"""Offline menu registration using Kurigram's real command/scope objects."""
import importlib.util
import unittest
from unittest.mock import AsyncMock

from test_commands import registered_commands


@unittest.skipUnless(importlib.util.find_spec('pyrogram'), 'requires Kurigram')
class CommandMenuTests(unittest.IsolatedAsyncioTestCase):
    async def test_scopes_cover_all_handlers_without_leaking_admin_commands(self):
        from telegram_commands import sync_command_menus
        from pyrogram import types
        bot = AsyncMock()
        await sync_command_menus(bot, [42, 42])
        menus = {}
        for call in bot.set_bot_commands.await_args_list:
            scope = call.kwargs['scope']
            commands = call.args[0]
            menus[type(scope)] = {c.command for c in commands}
            self.assertEqual(len(commands), len(menus[type(scope)]))
            self.assertTrue(all(1 <= len(c.description) <= 256 for c in commands))
            if isinstance(scope, types.BotCommandScopeChat):
                self.assertEqual(scope.chat_id, 42)
        self.assertEqual(bot.set_bot_commands.await_count, 4)
        private = menus[types.BotCommandScopeAllPrivateChats]
        self.assertEqual(private, {'start','id','link','upload','cancel_upload','plan','invoice','myplan'})
        self.assertEqual(menus[types.BotCommandScopeAllGroupChats], {'id','link'})
        self.assertEqual(menus[types.BotCommandScopeAllChatAdministrators], {'id','link','search','group_mode','help'})
        self.assertTrue(private < menus[types.BotCommandScopeChat])
        self.assertEqual(set.union(*menus.values()), set(registered_commands()))

    async def test_one_failed_scope_does_not_block_the_rest(self):
        from telegram_commands import sync_command_menus
        bot = AsyncMock()
        bot.set_bot_commands.side_effect = [True, True, True, RuntimeError('unknown peer'), True]
        with self.assertLogs('telegram_commands', 'WARNING'):
            await sync_command_menus(bot, [42, 43])
        self.assertEqual(bot.set_bot_commands.await_count, 5)
