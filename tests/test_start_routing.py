"""Exercise the plugins' actual Kurigram filters without logging in or opening Mongo."""
import ast
from importlib.util import find_spec
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]


def route_filter(plugin, handler):
    from pyrogram import filters

    tree = ast.parse((ROOT / 'plugins' / plugin).read_text())
    fn = next(n for n in tree.body if getattr(n, 'name', None) == handler)
    expr = ast.Expression(fn.decorator_list[0].args[0])
    return eval(compile(expr, plugin, 'eval'), {'filters': filters})


@unittest.skipUnless(find_spec('pyrogram'), 'requires Kurigram')
class StartRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_one_route_matches_each_private_message(self):
        from pyrogram import enums, types

        routes = {name: route_filter(plugin, name) for name, plugin in [
            ('filter_handler', 'filter.py'), ('start_cmd', 'start.py'),
            ('start_file_delivery', 'file_deliver.py'),
        ]}
        client = SimpleNamespace(me=SimpleNamespace(username='ExampleBot'))
        chat = types.Chat(id=7, type=enums.ChatType.PRIVATE)
        for text, expected in [('/start', ['start_cmd']), ('/start@ExampleBot', ['start_cmd']),
                               ('/start file_-123_abc', ['start_file_delivery']),
                               ('/id', []), ('movie title', ['filter_handler'])]:
            with self.subTest(text=text):
                msg = types.Message(id=1, chat=chat, text=text, outgoing=False)
                self.assertEqual([k for k, f in routes.items() if await f(client, msg)], expected)
