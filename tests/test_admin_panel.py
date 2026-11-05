#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""📊 /stats command — it must stay a button-free, text-only report.

Stdlib-only; runs without MongoDB / Telegram / hydrogram:

    python3 -m unittest discover -s tests -v

The dashboard used to be a wall of buttons: 💎 Premium, 🗑 Files, 🔄 Refresh,
♻️ Restart, and inside them ➕ Add, ➖ Remove, ⏳ Extend, 🔍 Check User,
📊 Expiry Chart, ⏰ 3d/7d/30d, 📹 By Quality, 🗑 Delete ALL … every one of
them only opened a screen that repeated a command that already exists.

`/stats` is now **pure text**: live stats + the command list. Every action is
a command (`/addpremium`, `/extendpremium`, `/removepremium`, `/delete`,
`/deleteall`, `/warmup_thumbs`), so a button would be dead weight.

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

# Panel builders that no longer exist
DEAD_BUILDERS = (
    "admin_panel_buttons",
    "premium_panel_buttons",
    "delete_panel_buttons",
    "delete_quality_buttons",
    "confirm_buttons",
)

# Callback handlers that only drove those panels
DEAD_CALLBACKS = ("admin_", "del_", "delq_", "prm_")

# Commands the dashboard must keep documenting (they are the panel now)
DOCUMENTED_COMMANDS = (
    "/addpremium",
    "/extendpremium",
    "/removepremium",
    "/delete",
    "/deleteall",
    "/warmup_thumbs",
)


def function_names():
    return {
        node.name
        for node in TREE.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def callback_regexes():
    """Every callback prefix handled in plugins/admin_tools.py"""
    return re.findall(r'filters\.regex\("\^?([a-z_]+)', ADMIN_TOOLS)


# ----------------------------------------------------------------------
# ✅ TESTS
# ----------------------------------------------------------------------

class TestButtonFreePanel(unittest.TestCase):
    """No panel buttons, no panel callbacks — commands only."""

    def test_panel_builders_are_gone(self):
        names = function_names()
        for name in DEAD_BUILDERS:
            with self.subTest(builder=name):
                self.assertNotIn(name, names, f"{name}() must stay deleted")

    def test_panel_callbacks_are_gone(self):
        for prefix in DEAD_CALLBACKS:
            with self.subTest(prefix=prefix):
                self.assertNotIn(
                    prefix, callback_regexes(),
                    f"'{prefix}' callbacks only drove the old panel buttons",
                )

    def test_no_callback_data_is_emitted(self):
        """Nothing in this file may build a panel keyboard."""
        panel_markers = re.findall(r'callback_data="([^"]+)"', ADMIN_TOOLS)
        self.assertEqual(
            sorted(panel_markers), ["close_data"],
            "only the /deleteall cancel button may carry a callback",
        )

    def test_stats_command_exists(self):
        self.assertIn(
            'filters.command("stats")', ADMIN_TOOLS,
            "/stats must show the statistics",
        )

    def test_admin_panel_command_is_gone(self):
        self.assertNotIn('"admin"', ADMIN_TOOLS, "/admin was replaced by /stats")
        self.assertNotIn('"dashboard"', ADMIN_TOOLS, "/dashboard was replaced by /stats")

    def test_stats_is_sent_without_buttons(self):
        src = ADMIN_TOOLS
        open_idx = src.index("async def stats_cmd")
        open_body = src[open_idx:src.index("async def delete_cmd")]
        self.assertNotIn("reply_markup", open_body, "the stats report takes no keyboard")


class TestDashboardContent(unittest.TestCase):
    """The text replaces the buttons, so it must list what an admin can do."""

    def setUp(self):
        self.dashboard = ADMIN_TOOLS[ADMIN_TOOLS.index("async def build_stats"):]

    def test_stats_are_still_shown(self):
        for stat in ("Users", "Groups", "Indexed Files", "Premium Users",
                     "DB Size", "Uptime"):
            with self.subTest(stat=stat):
                self.assertIn(stat, self.dashboard)

    def test_every_command_is_documented(self):
        for cmd in DOCUMENTED_COMMANDS:
            with self.subTest(command=cmd):
                self.assertIn(
                    cmd, self.dashboard,
                    f"{cmd} must stay listed in the dashboard text",
                )

    def test_indexing_is_explained(self):
        """There is no /index command — the dashboard says how indexing starts."""
        self.assertIn("t.me", self.dashboard)


if __name__ == "__main__":
    unittest.main(verbosity=2)
