#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""✨ Staggered result entrance — regression test for "change one place, change every place".

Stdlib-only; runs without MongoDB / Telegram / aiohttp:

    python3 -m unittest discover -s tests -v

The v5-style spring pop-in (`staggerCards()` / `cardEnter` in the GitHub reference)
is rebuilt in `web/reveal_assets.py`. This test fails if a page grows its own copy of
the keyframes, the observer or the stagger timing, or if one of the three result
surfaces (main /search, /posts, /actors) stops opting in. It also guards nested group
variants: they must never be hidden waiting for an off-screen intersection.
"""
import re
import unittest
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "web"
FILES = {
    name: (WEB / name).read_text(encoding="utf-8")
    for name in (
        "reveal_assets.py", "web_assets.py", "group_assets.py", "catalog.py",
    )
}
OTHER_FILES = {k: v for k, v in FILES.items() if k != "reveal_assets.py"}


def reveal_css():
    m = re.search(r'^REVEAL_CSS\s*=\s*r?"""(.*?)"""', FILES["reveal_assets.py"], re.S | re.M)
    assert m, "REVEAL_CSS could not be read"
    return m.group(1)


def reveal_js():
    m = re.search(r'^REVEAL_JS\s*=\s*r?"""(.*?)"""', FILES["reveal_assets.py"], re.S | re.M)
    assert m, "REVEAL_JS could not be read"
    return m.group(1)


class TestSingleSource(unittest.TestCase):

    def test_01_module_owns_the_whole_animation(self):
        css, js = reveal_css(), reveal_js()
        for frag in ("@keyframes rvEnter", ".rv-enter{opacity:0}",
                     ".rv-enter.in{animation:rvEnter .22s ease-out", "from{opacity:0}to{opacity:1}",
                     ".vcard:active,.gcard:active{transform:scale(.97)",
                     "prefers-reduced-motion:reduce"):
            self.assertIn(frag, css, f"REVEAL_CSS is missing {frag}")
        for frag in ("var DUR=0.22, STEP=0.03, MAX=4;", "IntersectionObserver", "threshold:.08", "animationDelay",
                     "window.RevealCards=", "function reveal(", "function stagger("):
            self.assertIn(frag, js, f"REVEAL_JS is missing {frag}")
        # The engine cleans the classes up so hover/press transforms keep working.
        self.assertIn("classList.remove('rv-enter','in')", js)

    def test_02_engine_is_shipped_on_every_page(self):
        main = FILES["web_assets.py"]
        self.assertRegex(main, r"(?m)^from web\.reveal_assets import REVEAL_CSS, REVEAL_JS$")
        self.assertIn("SITE_CSS += REVEAL_CSS", main)
        self.assertIn("SITE_JS += REVEAL_JS", main)
        # Poster/Text rules must stay last, as before this change.
        self.assertLess(main.index("SITE_CSS += REVEAL_CSS"),
                        main.index("SITE_CSS += MODE_CSS"))
        self.assertLess(main.index("SITE_JS += REVEAL_JS"),
                        main.index("SITE_JS += MODE_JS"))

    def test_03_no_page_owns_a_second_animation(self):
        forbidden = ("@keyframes catIn", "@keyframes vIn", "animation:catIn",
                     "animation:vIn", "card-enter", "card-visible", "staggerCards",
                     "function reveal(grid)", "function stagger(sel)")
        for name, src in OTHER_FILES.items():
            for frag in forbidden:
                self.assertNotIn(frag, src, f"{name} still owns {frag}")

    def test_04_main_search_opts_in_on_every_batch(self):
        src = FILES["web_assets.py"]
        self.assertIn("CARD_CLASS:topLevel?' rv-enter':''", src)
        self.assertIn("RevealCards.reveal($('#grid'))", src)
        self.assertIn("function card(f){return cardHTML(f,true)}", src)
        self.assertIn("class=\"vcard rv-skel vm-card\"", src)
        # Show more appends to the same grid; the reveal runs after both branches.
        self.assertIn("insertAdjacentHTML('beforeend',html)", src)

    def test_05_catalog_pages_and_detail_tabs_use_it(self):
        src = FILES["catalog.py"]
        self.assertIn('class="cat-card rv-enter vm-card"', src)
        self.assertIn("RevealCards.reveal(grid)", src)
        self.assertIn("RevealCards.stagger('#catVideos .vcard')", src)
        self.assertIn("RevealCards.stagger('#catMediaResults .vcard')", src)
        self.assertIn("RevealCards.stagger('#catGallery .cat-galitem')", src)
        self.assertIn('CARD_CLASS=" rv-enter"', src)   # attached video cards
        self.assertIn("CARD_CLASS:' rv-enter'", src)    # tag-driven results

    def test_06_group_cards_only_at_top_level(self):
        src = FILES["group_assets.py"]
        self.assertIn("CARD_CLASS:topLevel?' rv-enter':''", src)
        self.assertIn("function html(g,imgAttrs,imgError,topLevel)", src)
        # Variants call the shared builder without the flag ⇒ they stay visible.
        self.assertRegex(src, r"window\.cardHTML\?window\.cardHTML\(v\):''")

    def test_07_english_ui_contract_untouched(self):
        src = FILES["catalog.py"]
        self.assertIn('CATEGORY_ALL_LABEL = "📂 All"', src)
        self.assertNotIn("All Categories", src)


if __name__ == "__main__":
    unittest.main()
