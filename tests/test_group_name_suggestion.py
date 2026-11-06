#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Group Mode should prefill a clean, editable name for selected files."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GROUP_ASSETS = (ROOT / "web" / "group_assets.py").read_text(encoding="utf-8")


class TestSelectedGroupNameSuggestion(unittest.TestCase):
    def test_selected_group_is_prefilled_but_name_remains_editable(self):
        self.assertIn("name:suggestGroupName(items)", GROUP_ASSETS)
        self.assertIn('id="gmName" value="\'+esc(g.name)+\'"', GROUP_ASSETS)
        self.assertNotIn('id="gmName" value="\'+esc(g.name)+\'" readonly', GROUP_ASSETS)
        self.assertIn("var name=String((q('#gmName')||{}).value||'').trim()", GROUP_ASSETS)

    def test_movie_title_drops_common_quality_and_release_suffixes(self):
        helper = GROUP_ASSETS.split("function cleanSuggestedTitle(name){", 1)[1].split(
            "function seriesNameSuggestion(name){", 1
        )[0]
        for token in ("mp4|mkv", "1080", "web", "x264", "replace(/[._-]+/g,' ')"):
            self.assertIn(token, helper)

    def test_episode_group_suggestion_uses_series_title(self):
        helper = GROUP_ASSETS.split("var EPISODE_MARKERS=[", 1)[1].split(
            "function membersHtml(items,gid){", 1
        )[0]
        for marker in ("S\\d{1,2}", "\\d{1,2}", "Episode", "function seriesNameSuggestion", "return series"):
            self.assertIn(marker, helper)
        self.assertIn("if(episodeMarker(names[i]))", helper)


if __name__ == "__main__":
    unittest.main(verbosity=2)
