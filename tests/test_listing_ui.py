#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🧭 Listing UI guards — group name label + New Post/Profile button placement.

Stdlib-only:

    python3 -m unittest discover -s tests -v

1. The "▾ Files" label next to the group name must not come back;
   the expand/collapse toggle (`.gopenbtn`) must remain.
2. The ✨ New Post / ✨ New Profile button on `/posts` / `/actors` moved out of
   `.cat-head` into `.cat-toolbar`, after the filters — 🖥️ on desktop it shares
   the search line (`flex-wrap:nowrap`), 📱 on mobile it takes a full-width row
   below the filters (`flex:1 1 100%`).
3. The Category filter button's default label is just **All** (not "All Categories")
   — the listing filter and the inline editor both use the same
   `CATEGORY_ALL_LABEL` source, so one change updates every surface.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
GROUP = (WEB / "group_assets.py").read_text(encoding="utf-8")
CATALOG = (WEB / "catalog.py").read_text(encoding="utf-8")
WEB_ASSETS = (WEB / "web_assets.py").read_text(encoding="utf-8")


class TestGroupNameLabel(unittest.TestCase):

    def test_01_no_files_label_next_to_group_name(self):
        tpl = re.search(
            r"^GROUP_CARD_TEMPLATE\s*=\s*\((.*?)\n\)", GROUP, re.S | re.M)
        self.assertIsNotNone(tpl, "GROUP_CARD_TEMPLATE not found")
        self.assertNotIn("Files", tpl.group(1),
                         "the 'Files' label returned next to the name")
        self.assertNotIn(">▾ Files<", GROUP)

    def test_02_group_name_is_the_only_toggle_and_expansion_is_animated(self):
        self.assertIn('class="gtitle vm-title" onclick="event.stopPropagation();gToggle(this)"', GROUP)
        self.assertNotIn('class="gopenbtn"', GROUP, "redundant chevron toggle returned")
        self.assertNotIn(">▾</button>", GROUP)
        self.assertIn("window.gToggle=function(node)", GROUP)
        self.assertIn("transition:max-height .24s ease", GROUP)
        self.assertIn(".gcard.open .gvariants{max-height:5000px", GROUP)
        self.assertIn('<div class="gvariants-inner">{VARIANTS}</div>', GROUP)


class TestCreateButtonPlacement(unittest.TestCase):

    def test_03_button_is_in_the_single_box(self):
        body = re.search(r"def _listing_body\([\s\S]*?\n\"\"\"", CATALOG)
        self.assertIsNotNone(body)
        html = body.group(0)
        self.assertIn('class="cat-btn cat-create"', html)
        self.assertIn("openEditor(", html)
        self.assertIn("✨ New ", html)
        self.assertNotIn('<div class="cat-head">', html,
                         "the page heading returned")
        self.assertIn('<div class="cat-toolbar cat-box"', html)
        toolbar = html.split('<div class="cat-toolbar cat-box"')[1].split(
            "\n  </div>")[0]
        for token in ("cat-search", "{filters_html}", "{create_btn}", 'id="catCount"'):
            self.assertIn(token, toolbar, f"{token} is missing from the box")
        # DOM order: search → filters → create → count
        self.assertLess(toolbar.index("{filters_html}"), toolbar.index("{create_btn}"))
        self.assertLess(toolbar.index("{create_btn}"), toolbar.index('id="catCount"'))

    def test_06_no_page_heading_one_search_box(self):
        """Like v5 `.search-box`: no title, everything inside one card-box."""
        self.assertNotIn(".cat-head{", CATALOG)
        self.assertNotIn(".cat-title{", CATALOG)
        self.assertNotIn('"page": "Content Posts"', CATALOG)
        self.assertNotIn('"page": "Directory Profiles"', CATALOG)
        self.assertIn(".cat-toolbar.cat-box{", CATALOG)
        self.assertIn("background:var(--card)", CATALOG)
        self.assertIn("box-shadow:0 4px 15px rgba(0,0,0,.10)", CATALOG)
        self.assertIn("padding:16px;margin-bottom:25px", CATALOG)
        # the old "remove the chrome" mobile override must not return
        self.assertNotIn("background:transparent;border:0;border-radius:0;padding:0",
                         WEB_ASSETS, "the box disappeared again on mobile")
        self.assertIn(".cat-toolbar.cat-toolbar .cat-count{", WEB_ASSETS,
                      "the count must stay inside the same box")

    def test_04_desktop_same_line_as_search(self):
        self.assertIn(".cat-toolbar .cat-create{flex:0 0 auto;white-space:nowrap}", CATALOG)
        self.assertIn(
            "@media(min-width:761px){.cat-toolbar.cat-toolbar{flex-wrap:nowrap}}", CATALOG)
        self.assertIn(".cat-search{position:relative;flex:1 1 240px;min-width:0}", CATALOG,
                      "the search input must be allowed to shrink (no overflow)")

    def test_05_mobile_below_filter_buttons(self):
        mobile = re.search(
            r"@media\(max-width:760px\)\{(.*?)\n\}", WEB_ASSETS, re.S)
        self.assertIsNotNone(mobile, "the shared mobile filter-row block was not found")
        block = mobile.group(1)
        self.assertIn(".filters{flex:1 1 100%}", block)
        self.assertIn(".qwrap,.cat-toolbar .cat-search{flex:1 1 100%}", block)
        self.assertIn(
            ".cat-toolbar.cat-toolbar .cat-create{flex:1 1 100%;width:100%}", block,
            "the create button does not take a full line below the filters on mobile")
        # (0,3,0) specificity — the later CATALOG_CSS in the body must not win
        self.assertIn(".cat-toolbar.cat-toolbar", block)


class TestCategoryAllLabel(unittest.TestCase):
    """The /posts + /actors Category button must always read "All"."""

    def test_07_single_source_and_no_all_categories(self):
        self.assertIn('CATEGORY_ALL_LABEL = "📂 All"', CATALOG)
        self.assertNotIn("All Categories", CATALOG,
                         "'All Categories' returned on the Category button")
        # the `<option value="all">` label comes from the constant, not a literal
        opts = re.search(r"def _category_options\([\s\S]*?\n\s*out \+=", CATALOG)
        self.assertIsNotNone(opts, "_category_options not found")
        self.assertIn("CATEGORY_ALL_LABEL", opts.group(0))
        self.assertIn('<option value="all">', opts.group(0))
        self.assertIn('"catCategory": _category_options(kind)', CATALOG)

    def test_08_inline_editor_uses_the_same_injected_label(self):
        # the label is not duplicated in JS — build_listing_page injects it
        self.assertIn("'<option value=\"all\">' + __ALL_CAT__ + '</option>'", CATALOG)
        self.assertIn('.replace("__ALL_CAT__", json.dumps(CATEGORY_ALL_LABEL,',
                      CATALOG)
        self.assertNotIn("'<option value=\"all\">📂 All</option>'", CATALOG,
                         "the label is hardcoded in the editor again")
        # the /search Group/UnGroup filter also keeps "All"
        self.assertIn('"group": (("all", "All")', WEB_ASSETS)

    def test_09_category_options_are_unchanged_after_the_all_option(self):
        body = re.search(r"def _category_options\([\s\S]*?return \"\"\.join\(out\)",
                         CATALOG)
        self.assertIsNotNone(body)
        self.assertIn('f\'<option value="{html.escape(c["value"])}">', body.group(0))
        self.assertIn('include_all', body.group(0))
        self.assertIn('value="all"', body.group(0))


if __name__ == "__main__":
    unittest.main(verbosity=2)
