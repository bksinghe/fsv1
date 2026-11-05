#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""📊 /stats command — it must stay a button-free, text-only report.

Stdlib-only; runs without MongoDB / Telegram / hydrogram:

    python3 -m unittest discover -s tests -v

The dashboard used to be a wall of buttons: 💎 Premium, 🗑 Files, 🔄 Refresh,
♻️ Restart, and inside them ➕ Add, ➖ Remove, ⏳ Extend, 🔍 Check User,
📊 Expiry Chart, ⏰ 3d/7d/30d, 📹 By Quality, 🗑 Delete ALL … every one of
them only opened a screen that repeated a command that already exists.

`/stats` is now **pure text**: live bot counters + live web counters. Every
action is a command (`/addpremium`, `/extendpremium`, `/removepremium`,
`/delete`, `/deleteall`, `/warmup_thumbs`), so a button would be dead weight —
and the command list itself was dropped on request: the 👨‍🚒 Help button of
`/start` already documents every command, and the ⚡ index-speed counter only
meant something while an indexing run was in flight.

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

# The /stats report is numbers only — these must NOT be listed in it again
# (the 👨‍🚒 Help button of /start is the one place commands are documented)
UNDOCUMENTED_ON_PURPOSE = (
    "/addpremium",
    "/extendpremium",
    "/removepremium",
    "/delete",
    "/deleteall",
    "/warmup_thumbs",
)

# Counters the 🌐 WEB section must keep showing
EXPECTED_WEB_STATS = (
    "WEB STATISTICS", "Server", "URL", "Port", "Web Uptime",
    "Web Accounts", "Live Sessions", "Posts", "Profiles",
    "Catalog Groups", "Posters", "Thumb Queue",
)


def stats_source():
    """Source of build_stats() only — not the commands below it in the file."""
    for node in TREE.body:
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "build_stats":
            return ast.get_source_segment(ADMIN_TOOLS, node) or ""
    return ""


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
        self.dashboard = stats_source()

    def test_stats_are_still_shown(self):
        for stat in ("Users", "Groups", "Indexed Files", "Premium Users",
                     "DB Size", "Uptime"):
            with self.subTest(stat=stat):
                self.assertIn(stat, self.dashboard)

    def test_web_stats_are_shown(self):
        """/stats also reports the web app (site state, accounts, catalog)."""
        for stat in EXPECTED_WEB_STATS:
            with self.subTest(stat=stat):
                self.assertIn(stat, self.dashboard)

    def test_no_command_list_in_the_report(self):
        for cmd in UNDOCUMENTED_ON_PURPOSE:
            with self.subTest(command=cmd):
                self.assertNotIn(
                    cmd, self.dashboard,
                    f"{cmd} is documented by /start → 👨‍🚒 Help, not by /stats",
                )

    def test_index_speed_is_gone(self):
        """The ⚡ index-speed counter only meant something mid-indexing."""
        self.assertNotIn("Index Speed", ADMIN_TOOLS)
        self.assertNotIn("INDEX_STATS", ADMIN_TOOLS)

    def test_counters_come_from_the_shared_module(self):
        """The web page and /stats must read the same snapshot()."""
        self.assertIn("from database.stats_db import snapshot", ADMIN_TOOLS)
        self.assertIn("await snapshot()", self.dashboard)


if __name__ == "__main__":
    unittest.main(verbosity=2)
