#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🎛 /admin panel — the dashboard and its sub-panels must stay lean.

Stdlib-only; runs without MongoDB / Telegram / hydrogram:

    python3 -m unittest discover -s tests -v

The panel used to be a wall of buttons: 💎 Premium alone showed ➕ Add,
➖ Remove and ⏳ Extend, which only printed the usage of the very commands
that exist for them, and 🗑 Files had a 🔍 Delete by Keyword button that did
nothing but echo `/delete keyword`. Those are gone — the panels now show the
commands as text and keep only real actions, and every destructive action
asks for a confirmation first.

The source of `plugins/admin_tools.py` is parsed with `ast` (never imported),
so this suite needs neither hydrogram nor a database.
"""
import ast
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADMIN_TOOLS = (ROOT / "plugins" / "admin_tools.py").read_text(encoding="utf-8")
TREE = ast.parse(ADMIN_TOOLS)

# Buttons that only printed usage text — they must never come back
INSTRUCTION_ONLY = {"prm_add", "prm_remove", "prm_extend", "del_keyword"}

# Maximum number of buttons a panel may show (keyboard clutter guard)
MAX_BUTTONS = {
    "admin_panel_buttons": 5,     # 💎 · 🗑 · 🔄 · ♻️ · ❌
    "premium_panel_buttons": 6,   # 🔍 · 📊 · ⏰×3 · 🔙
    "delete_panel_buttons": 3,    # 📹 · 🗑 · 🔙
    "delete_quality_buttons": 7,  # 6 qualities · 🔙
}


def panel_source(name):
    """Source of a `def name(): …` panel builder in plugins/admin_tools.py"""
    for node in TREE.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(ADMIN_TOOLS, node)
    raise AssertionError(f"{name}() not found in plugins/admin_tools.py")


def callback_data(name):
    """Every callback_data used by a panel"""
    return re.findall(r'callback_data="([^"]+)"', panel_source(name))


def button_count(name):
    return panel_source(name).count("InlineKeyboardButton(")


# ----------------------------------------------------------------------
# ✅ TESTS
# ----------------------------------------------------------------------

class TestPanelLayout(unittest.TestCase):
    """Panels stay small: only real actions, no instruction-only buttons."""

    def test_panels_stay_compact(self):
        for name, limit in MAX_BUTTONS.items():
            with self.subTest(panel=name):
                self.assertLessEqual(
                    button_count(name), limit,
                    f"{name} has too many buttons — keep the panel lean",
                )

    def test_no_instruction_only_buttons(self):
        """➕ Add / ➖ Remove / ⏳ Extend / 🔍 Keyword only echoed usage text."""
        used = set()
        for name in MAX_BUTTONS:
            used |= set(callback_data(name))
        for cb in sorted(INSTRUCTION_ONLY):
            with self.subTest(callback=cb):
                self.assertNotIn(
                    cb, used,
                    f"{cb} is an instruction-only button — show the command as text",
                )

    def test_commands_are_shown_as_text(self):
        """The premium / files panels document the commands in their body."""
        for cmd in ("/addpremium", "/extendpremium", "/removepremium", "/delete"):
            with self.subTest(command=cmd):
                self.assertIn(
                    cmd, ADMIN_TOOLS,
                    f"{cmd} must stay documented in the panel text",
                )

    def test_every_sub_panel_can_go_back(self):
        for name, back in (
            ("premium_panel_buttons", "admin_back"),
            ("delete_panel_buttons", "admin_back"),
            ("delete_quality_buttons", "admin_delete"),
        ):
            with self.subTest(panel=name):
                self.assertIn(back, callback_data(name), f"{name} has no way back")


class TestDestructiveActions(unittest.TestCase):
    """Bulk deletes must never run on a single tap."""

    def test_confirm_helper_exists(self):
        self.assertIn("def confirm_buttons(", ADMIN_TOOLS)

    def test_confirm_helper_is_used(self):
        self.assertGreaterEqual(
            ADMIN_TOOLS.count("confirm_buttons("), 3,
            "delete-ALL and delete-by-quality must both confirm first",
        )

    def test_quality_delete_asks_first(self):
        """delq_720p only shows a confirmation; delq_go_720p does the delete."""
        self.assertIn('quality.startswith("go_")', ADMIN_TOOLS)
        self.assertIn('f"delq_go_{quality}"', ADMIN_TOOLS)
        self.assertIn("count_by_quality", ADMIN_TOOLS)

    def test_quality_delete_shows_the_file_count(self):
        """The confirmation tells how many files will be deleted."""
        self.assertIn("files will be permanently deleted", ADMIN_TOOLS)

    def test_delete_all_asks_first(self):
        self.assertIn("del_all_confirm", ADMIN_TOOLS)
        self.assertIn("del_all_execute", ADMIN_TOOLS)

    def test_count_by_quality_exists_in_the_db_layer(self):
        src = (ROOT / "database" / "ia_filterdb.py").read_text(encoding="utf-8")
        self.assertIn("async def count_by_quality(", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
