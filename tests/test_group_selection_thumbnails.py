#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Selected files must retain their poster URLs through the group modal."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GROUP_ASSETS = (ROOT / "web" / "group_assets.py").read_text(encoding="utf-8")


class TestSelectedGroupThumbnails(unittest.TestCase):
    def test_selected_file_reads_thumbnail_in_poster_and_text_modes(self):
        helper = GROUP_ASSETS.split("function thumbnailFromCard(card){", 1)[1].split(
            "function qualityFromCard(card){", 1
        )[0]
        self.assertIn("getAttribute('data-thumb')", helper)
        self.assertIn("getAttribute('data-src')", helper)
        self.assertIn("getAttribute('src')", helper)
        self.assertIn("thumb:thumbnailFromCard(c)", GROUP_ASSETS)

    def test_thumbnail_is_carried_into_the_group_and_shown_in_picker(self):
        self.assertIn("thumb:v.thumb||''", GROUP_ASSETS)
        self.assertIn("thumb:it.thumb||''", GROUP_ASSETS)
        self.assertIn("v.thumb?'<img src=\"'+esc(v.thumb)+'\"", GROUP_ASSETS)


if __name__ == "__main__":
    unittest.main(verbosity=2)
