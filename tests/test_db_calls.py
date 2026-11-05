#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🔌 plugins → database call signatures.

Stdlib-only; runs without MongoDB / Telegram / hydrogram:

    python3 -m unittest discover -s tests -v

`plugins/channel.py` used to call three `database.ia_filterdb` helpers with
arguments they do not accept:

    save_file(media, quality=quality)        → save_file(media)
    detect_quality(media.file_name, caption) → detect_quality(name)
    update_file_caption(fid, caption, qual)  → update_file_caption(fid, caption)

Every one of them raises `TypeError` at runtime, and because the handler
swallows exceptions the channel posts were silently never indexed — the
suite could not see it (hydrogram cannot be imported here).

These tests parse both sides with `ast` and compare every call made from
`plugins/` against the real signature in `database/`, so a mismatch now
fails before it reaches production.
"""

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "database"
PLUGINS = sorted((ROOT / "plugins").glob("*.py"))

# Names that exist in more than one database module with a different shape
# (`db` is a handle in one module and a DataBase object in another, …)
AMBIGUOUS = {"db", "store", "collection", "client", "mongo"}


class Signature:
    """Positional/keyword shape of one `def`."""

    def __init__(self, node, module):
        args = node.args
        params = [a.arg for a in (*args.posonlyargs, *args.args)]
        # a method called as `obj.method(...)` already has `self` bound
        if params and params[0] in ("self", "cls"):
            params = params[1:]

        self.module = module
        self.names = set(params)
        self.required = len(params) - len(args.defaults)
        self.total = len(params)
        self.vararg = args.vararg is not None
        self.kwarg = args.kwarg is not None

    def check(self, node):
        """(problems) for one ast.Call against this signature"""
        problems = []

        if len(node.args) > self.total and not self.vararg:
            problems.append(
                f"takes {self.total} positional argument(s) "
                f"({', '.join(sorted(self.names))}) but {len(node.args)} were passed"
            )

        supplied = len(node.args)
        for kw in node.keywords:
            if kw.arg is None:                      # **kwargs splat — skip
                supplied += 1
                continue
            if kw.arg not in self.names:
                problems.append(
                    f"got an unexpected keyword argument '{kw.arg}' "
                    f"— {self.module}.{node.func.id}() accepts "
                    f"{', '.join(sorted(self.names)) or 'nothing'}"
                )
            else:
                supplied += 1

        if not self.vararg and supplied < self.required and not node.keywords:
            problems.append(
                f"missing {self.required - supplied} required positional "
                f"argument(s) — {self.module}.{node.func.id}() needs "
                f"{self.required}"
            )
        return problems


def database_signatures():
    """name -> Signature, for every function defined under database/"""
    table = {}
    for path in sorted(DATABASE.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name.startswith("_"):
                    continue
                sig = Signature(node, f"database/{path.stem}")
                if node.name in AMBIGUOUS:
                    continue
                # first definition wins (a re-definition is a shadow bug anyway)
                table.setdefault(node.name, sig)
    return table


def database_imports(tree):
    """{'save_file': 'database.ia_filterdb'} for `from database.x import y`"""
    imports = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("database"):
            for alias in node.names:
                imports[alias.asname or alias.name] = node.module
    return imports


# ----------------------------------------------------------------------
# ✅ TESTS
# ----------------------------------------------------------------------

class TestDatabaseCalls(unittest.TestCase):
    """Every plugins → database call must match the real signature."""

    def setUp(self):
        self.signatures = database_signatures()

    def calls(self):
        for path in PLUGINS:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            imports = database_imports(tree)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                if not isinstance(node.func, ast.Name):
                    continue
                name = node.func.id
                if name in imports and name in self.signatures:
                    yield path.name, node, self.signatures[name]

    def test_every_call_matches_the_signature(self):
        checked = 0
        for filename, node, sig in self.calls():
            checked += 1
            with self.subTest(plugin=filename, call=node.func.id, line=node.lineno):
                self.assertEqual(
                    sig.check(node), [],
                    f"{filename}:{node.lineno} → {node.func.id}()",
                )
        self.assertGreaterEqual(checked, 10, "the scan should find the real call sites")

    def test_scanner_catches_the_mistakes_it_was_written_for(self):
        """Self-check: the three broken calls must be flagged."""
        cases = {
            "save_file(media, quality=quality)":
                "unexpected keyword argument 'quality'",
            "detect_quality(media.file_name, caption)":
                "takes 1 positional argument",
            "update_file_caption(media.file_id, new_caption, quality)":
                "takes 2 positional argument",
        }
        for expr, expected in cases.items():
            call = ast.parse(expr, mode="eval").body
            problems = self.signatures[call.func.id].check(call)
            with self.subTest(call=expr):
                self.assertTrue(
                    any(expected in problem for problem in problems),
                    f"{expr} was not flagged: {problems}",
                )

    def test_known_broken_calls_are_gone(self):
        """The three calls that silently broke channel auto-indexing."""
        src = (ROOT / "plugins" / "channel.py").read_text(encoding="utf-8")
        self.assertNotIn("save_file(media, quality", src)
        self.assertNotIn("detect_quality(media.file_name, ", src)
        self.assertIn("update_file_caption(\n            media.file_id,\n            message.caption or \"\"\n        )", src)


class TestIndexAndChannel(unittest.TestCase):
    """plugins/index.py ↔ plugins/channel.py must stay in sync."""

    def setUp(self):
        self.index = (ROOT / "plugins" / "index.py").read_text(encoding="utf-8")
        self.channel = (ROOT / "plugins" / "channel.py").read_text(encoding="utf-8")

    def test_active_indexes_is_shared(self):
        """channel.py must read the set index.py actually owns."""
        self.assertIn("ACTIVE_INDEXES = set()", self.index)
        self.assertIn("from plugins.index import ACTIVE_INDEXES", self.channel)
        self.assertIn("ACTIVE_INDEXES.add(chat_id)", self.index)
        self.assertIn("ACTIVE_INDEXES.discard(chat_id)", self.index)
        self.assertIn("message.chat.id in ACTIVE_INDEXES", self.channel)

    def test_no_dead_cancel_index_import(self):
        """`CANCEL_INDEX` never existed in index.py — the import was dead."""
        self.assertNotIn("CANCEL_INDEX", self.channel)
        self.assertNotIn("CANCEL_INDEX", self.index)

    def test_stop_callback_does_not_crash_the_start_handler(self):
        """idx#cancel also matches `^idx#` — the start handler must ignore it."""
        self.assertIn("if data[1] != \"start\":", self.index)

    def test_no_second_mongo_client(self):
        """index.py shares ia_filterdb's connection instead of opening its own."""
        self.assertNotIn("MongoClient", self.index)
        self.assertIn("db as media_db", self.index)
        self.assertIn("resume_col = media_db[\"index_resume\"]", self.index)

    def test_channel_has_no_private_size_helper(self):
        """format_file_size() duplicated utils.get_size()."""
        self.assertNotIn("def format_file_size", self.channel)
        self.assertIn("from utils import get_size", self.channel)


if __name__ == "__main__":
    unittest.main(verbosity=2)
