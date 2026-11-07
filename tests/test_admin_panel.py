#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""📊 /stats stays a button-free text report; /admin owns safe runtime settings.

Stdlib-only; runs without MongoDB / Telegram / hydrogram:

    python3 -m unittest discover -s tests -v

The old dashboard in ``admin_tools.py`` was a wall of buttons, many of which
only repeated commands. `/stats` remains pure text with live bot and web
counters. The separate `/admin` private-chat panel is narrowly scoped to live
channel settings, access checks, audit history and rollback.

The implementation is parsed/read from source rather than imported, so this
suite needs neither hydrogram nor a live database.
"""
import ast
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADMIN_TOOLS = (ROOT / "plugins" / "admin_tools.py").read_text(encoding="utf-8")
ADMIN_PANEL = (ROOT / "plugins" / "admin_panel.py").read_text(encoding="utf-8")
RUNTIME_CONFIG = (ROOT / "database" / "runtime_config.py").read_text(encoding="utf-8")
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

class TestStatsAndAdminSettings(unittest.TestCase):
    """Keep /stats simple and gate the separate /admin channel controls."""

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

    def test_admin_command_is_private_and_gated(self):
        self.assertIn('filters.command("admin")', ADMIN_PANEL)
        self.assertIn("filters.private", ADMIN_PANEL)
        self.assertIn("user.id not in ADMINS", ADMIN_PANEL)
        self.assertNotIn('filters.command("dashboard")', ADMIN_PANEL)

    def test_admin_callbacks_recheck_private_chat_and_admin_id(self):
        self.assertIn('filters.regex(r"^admincfg:")', ADMIN_PANEL)
        self.assertIn('group=-1', ADMIN_PANEL)
        self.assertIn("def _is_private_admin(query)", ADMIN_PANEL)
        self.assertIn("if not _is_private_admin(query):", ADMIN_PANEL)
        callbacks = (ROOT / "plugins" / "callbacks.py").read_text(encoding="utf-8")
        self.assertIn('data.startswith("admincfg:")', callbacks)

    def test_panel_exposes_channel_and_safe_feature_settings_not_secrets(self):
        for setting in (
            "BIN_CHANNEL", "LOG_CHANNEL", "INDEX_CHANNELS",
            "INDEX_LOG_CHANNEL", "CATALOG_STORAGE_CHANNEL",
            "USE_CAPTION_FILTER", "PROTECT_CONTENT", "IS_STREAM",
            "PM_FILE_DELETE_TIME", "RESULTS_PER_PAGE_PM",
            "RESULTS_PER_PAGE_GROUP", "MAX_WEB_RESULTS",
        ):
            with self.subTest(setting=setting):
                self.assertIn(setting, ADMIN_PANEL)
        for secret in (
            "BOT_TOKEN", "API_HASH", "STREAM_SECRET", "DATA_DATABASE_URL",
            "ALLOW_UNSIGNED_LINKS", "IS_PREMIUM",
        ):
            with self.subTest(secret=secret):
                self.assertNotIn(secret, ADMIN_PANEL)

    def test_settings_reuse_database_and_have_audit_rollback(self):
        self.assertIn("from database.ia_filterdb import db", RUNTIME_CONFIG)
        self.assertNotIn("MongoClient(", RUNTIME_CONFIG)
        self.assertIn("async def audit_history", RUNTIME_CONFIG)
        self.assertIn("async def rollback_latest", RUNTIME_CONFIG)
        self.assertIn('"$push"', RUNTIME_CONFIG)

    def test_caption_filter_excludes_text_index_hits_when_disabled(self):
        search_db = (ROOT / "database" / "ia_filterdb.py").read_text(encoding="utf-8")
        self.assertIn('use_caption_filter = runtime_config.get("USE_CAPTION_FILTER")', search_db)
        self.assertIn('if use_caption_filter:\n        text_filter =', search_db)
        self.assertIn('cache_key = f"{q_lower}:{offset}:{max_results}:caption=', search_db)
        self.assertIn('rg_filter = {"file_name": regex}', search_db)
        self.assertIn("cache_clear()", ADMIN_PANEL)

    def test_feature_consumers_read_runtime_values(self):
        file_delivery = (ROOT / "plugins" / "file_deliver.py").read_text(encoding="utf-8")
        callbacks = (ROOT / "plugins" / "callbacks.py").read_text(encoding="utf-8")
        filters = (ROOT / "plugins" / "filter.py").read_text(encoding="utf-8")
        web_search = (ROOT / "web" / "search_routes.py").read_text(encoding="utf-8")
        for source, names in (
            (file_delivery, ("IS_STREAM", "PROTECT_CONTENT", "PM_FILE_DELETE_TIME")),
            (callbacks, ("IS_STREAM",)),
            (filters, ("RESULTS_PER_PAGE_PM", "RESULTS_PER_PAGE_GROUP")),
            (web_search, ("MAX_WEB_RESULTS",)),
        ):
            for name in names:
                with self.subTest(name=name, source=source[:20]):
                    self.assertIn(f'runtime_config.get("{name}")', source)

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
