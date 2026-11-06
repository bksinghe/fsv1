#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Admin scan-all action placement, matching the v5 group-filter dropdown."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB_ASSETS = (ROOT / "web" / "web_assets.py").read_text(encoding="utf-8")
GROUP_ASSETS = (ROOT / "web" / "group_assets.py").read_text(encoding="utf-8")


class TestAdminGroupScanButton(unittest.TestCase):
    def test_scan_action_is_only_added_to_admin_search_filter(self):
        self.assertIn('"group_admin":', WEB_ASSETS)
        self.assertIn('("scan_all", "⚙️ Scan all & build groups")', WEB_ASSETS)
        self.assertIn(
            'dict(sp, options="group_admin") if admin and sp["id"] == "groupSel"',
            WEB_ASSETS,
        )
        self.assertIn("filter_buttons(search_filters)", WEB_ASSETS)

    def test_scan_option_runs_scan_and_restores_the_previous_filter(self):
        handler = WEB_ASSETS.split("function setGroup(v){", 1)[1].split(
            "function doSearch()", 1
        )[0]
        self.assertIn("if(v==='scan_all')", handler)
        self.assertIn("$('#groupSel').value=groupMode", handler)
        self.assertIn("window.gScanAll()", handler)
        self.assertIn("localStorage.setItem('ff_group_mode',groupMode)", handler)

    def test_scan_action_is_available_without_entering_group_mode(self):
        self.assertIn("window.gScanAll=function()", GROUP_ASSETS)
        self.assertIn("/api/group/scan_all", GROUP_ASSETS)
        self.assertIn("/api/group/scan_status", GROUP_ASSETS)
        self.assertNotIn('onclick="gScanAll()">⚙️ Scan all</button>', GROUP_ASSETS)


if __name__ == "__main__":
    unittest.main(verbosity=2)
