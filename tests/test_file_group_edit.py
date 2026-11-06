#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🗂️ Admin file editor ↔ permanent group transfer contract.

Stdlib-only so the checks run without MongoDB or Telegram:

    python3 -m unittest discover -s tests -v
"""
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = (ROOT / "web" / "web_assets.py").read_text(encoding="utf-8")
ROUTES = (ROOT / "web" / "file_edit_routes.py").read_text(encoding="utf-8")
GROUP_DB = (ROOT / "database" / "group_db.py").read_text(encoding="utf-8")


def function_source(source, name):
    tree = ast.parse(source)
    node = next(
        (n for n in ast.walk(tree)
         if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name),
        None,
    )
    if node is None:
        raise AssertionError(f"function {name} not found")
    return ast.get_source_segment(source, node)


class TestFileEditorGroupControl(unittest.TestCase):
    def test_editor_shows_current_group_and_sends_the_target_id(self):
        self.assertIn('id="feGroupId"', ASSETS)
        self.assertIn('id="feGroupHint"', ASSETS)
        self.assertIn("setGroupInfo(f)", ASSETS)
        self.assertIn("f.group_id", ASSETS)
        self.assertIn("group_id:q('#feGroupId').value.trim()", ASSETS)
        self.assertIn("leave blank to remove it from the group", ASSETS)

    def test_edit_meta_returns_canonical_group_details(self):
        meta = function_source(ROUTES, "api_file_meta")
        self.assertIn("await _file_group(fid, doc)", meta)
        self.assertIn("group_loaded=True", meta)
        self.assertIn('"group_id": group_id', ROUTES)
        self.assertIn('"group_name": group_name', ROUTES)

    def test_transfer_is_admin_only_validated_and_moves_group_membership(self):
        edit = function_source(ROUTES, "api_file_edit")
        transfer = function_source(ROUTES, "_move_file_group")
        self.assertIn("if not await _admin(req)", edit)
        self.assertIn('has_group_update = "group_id" in data', edit)
        self.assertIn('await group_store.get(target_gid)', edit)
        self.assertIn('"Group not found"', edit)
        self.assertIn("await _move_file_group(fid, name, target_gid, existing)", edit)
        self.assertIn("await group_store.pull_files([fid], exclude=True)", transfer)
        self.assertIn("group_store.add_members(", transfer)
        self.assertIn("target_gid, [(fid, name)], auto_keys=[key] if key else []", transfer)
        self.assertIn("await group_store.mark_files([fid], target_gid)", transfer)
        self.assertIn("await group_store.mark_files([fid], \"\")", transfer)
        self.assertIn("await group_store.cleanup_empty()", transfer)
        self.assertIn('"group_changed": group_changed', edit)

    def test_search_rebuilds_group_cards_after_a_transfer(self):
        self.assertIn("if(moved && typeof window.load==='function') window.load(true)", ASSETS)

    def test_group_cleanup_clears_stale_file_markers_and_master_thumbnail(self):
        pull_files = function_source(GROUP_DB, "pull_files")
        cleanup_empty = function_source(GROUP_DB, "cleanup_empty")
        self.assertIn('if str(g.get("thumb_fid") or "") in s:', pull_files)
        self.assertIn('g["thumb_fid"] = ""', pull_files)
        self.assertIn('await self.mark_files(members, "", only_if=gid)', cleanup_empty)


if __name__ == "__main__":
    unittest.main(verbosity=2)
