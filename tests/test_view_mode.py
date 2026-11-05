#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🖼️📄 Poster/Text mode — regression test for "change one place, change every place".

Stdlib-only; runs without MongoDB / Telegram / aiohttp:

    python3 -m unittest discover -s tests -v

All Poster/Text behaviour must live in `web/mode_assets.py`. Other files only
add semantic `vm-*` classes and use `window.ViewMode`; this test fails as soon as
another file gets `.mode-text` CSS, its own mode state, a different storage key or
a separate HTML branch for Text mode — preventing the code from splitting into
three places again in the future.
"""
import re
import unittest
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "web"
FILES = {
    name: (WEB / name).read_text(encoding="utf-8")
    for name in (
        "mode_assets.py",
        "web_assets.py",
        "group_assets.py",
        "catalog.py",
    )
}
OTHER_FILES = {k: v for k, v in FILES.items() if k != "mode_assets.py"}


def mode_src():
    return FILES["mode_assets.py"]


def css_block():
    m = re.search(r'^MODE_CSS\s*=\s*r?"""(.*?)"""', mode_src(), re.S | re.M)
    assert m, "MODE_CSS could not be read"
    return m.group(1)


def js_block():
    m = re.search(r'^MODE_JS\s*=\s*r?"""(.*?)"""', mode_src(), re.S | re.M)
    assert m, "MODE_JS could not be read"
    return m.group(1)


class TestSingleSource(unittest.TestCase):

    def test_01_module_defines_everything(self):
        src = mode_src()
        for symbol in ("VIEW_MODE_OPTIONS", "MODE_CSS", "MODE_JS"):
            self.assertTrue(
                re.search(rf"^{symbol}\s*=", src, re.M),
                f"{symbol} is missing from the module",
            )
        self.assertIn("window.ViewMode=", src, "the engine must live in that same module")
        self.assertIn("function imgAttrs(url)", src, "src ⇄ data-src in one place")
        self.assertIn("data-vm-select", src, "select auto-binding in one place")

    def test_02_options_defined_exactly_once_in_all_web_files(self):
        """To change a label, edit one line in mode_assets.py — everything else imports it."""
        occurrences = sum(src.count("🖼️ Poster") for src in FILES.values())
        self.assertEqual(occurrences, 1, "the Poster label is written in more than one place")
        self.assertIn("🖼️ Poster", mode_src())
        self.assertEqual(
            len(re.findall(r"^VIEW_MODE_OPTIONS\s*=", mode_src(), re.M)), 1
        )

    def test_03_shared_module_is_imported_and_appended_last(self):
        wa = FILES["web_assets.py"]
        self.assertRegex(
            wa, r"from web\.mode_assets import VIEW_MODE_OPTIONS, MODE_CSS, MODE_JS"
        )
        self.assertIn("SITE_CSS += MODE_CSS", wa, "MODE_CSS must be included on every page")
        self.assertIn("SITE_JS += MODE_JS", wa, "MODE_JS must be included on every page")
        # cascade: MODE_CSS must be appended last
        css_tail = wa[wa.index("SITE_CSS +="):]
        self.assertIn("GROUP_CSS", css_tail)
        self.assertGreater(
            css_tail.index("SITE_CSS += MODE_CSS"), css_tail.rindex("GROUP_CSS")
        )
        self.assertIn("SITE_JS += MODE_JS", wa[wa.index("SITE_JS += GROUP_JS"):])
        # VIEW_MODE_OPTIONS is the only source for dropdown options
        self.assertRegex(wa, r'"view":\s*VIEW_MODE_OPTIONS')

    def test_04_no_split_mode_logic_anywhere_else(self):
        """Mode code used to be duplicated in /search, group cards and catalog — it must not return."""
        forbidden = {
            ".mode-text{": "mode-text CSS is split",
            "mode-text .": "mode-text CSS is split",
            "state.mode": "a separate mode state in catalog",
            "viewMode": "page-specific mode variable",
            "applyMode(": "page-specific apply function",
            "ff_view_mode'": "storage key hardcoded",
            "ff_cat_mode_": "storage key hardcoded",
        }
        for name, src in OTHER_FILES.items():
            for token, why in forbidden.items():
                self.assertNotIn(token, src, f"{name}: {why}")

    def test_05_no_text_only_markup_branch(self):
        """catalog's cardHTML() gives both modes exactly the same markup."""
        cat = FILES["catalog.py"]
        self.assertNotIn("if(state.mode", cat, "a separate HTML branch for Text mode remains")
        fn = re.search(r"function cardHTML\(it\)[\s\S]*?\n\}", cat)
        self.assertIsNotNone(fn, "cardHTML not found")
        self.assertEqual(
            fn.group(0).count("return `"), 1,
            "cardHTML has more than one markup branch",
        )
        for call in ("ViewMode.imgAttrs(", "ViewMode.init(", "ViewMode.apply()"):
            self.assertIn(call, cat, f"catalog uses a different {call}")
        self.assertRegex(FILES["web_assets.py"], r"ViewMode\.init\(")

    def test_06_every_surface_opts_in_via_vm_classes(self):
        """/search, group/variant cards, /posts, /actors — all from the same contract."""
        wa, gr, cat = (FILES[k] for k in ("web_assets.py", "group_assets.py", "catalog.py"))
        self.assertIn('class="vgrid vm-grid" id="grid"', wa)
        self.assertIn('vm-grid', cat)
        self.assertIn('vm-grid', gr + wa + cat)
        for name, src, required in (
            ("web_assets.py", wa,
             ("vm-card", "vm-poster", "vm-img", "vm-details", "vm-size",
              "vm-actions", "vm-body", "vm-title")),
            ("group_assets.py", gr,
             ("vm-card", "vm-master", "vm-poster", "vm-img", "vm-details",
              "vm-actions", "vm-body", "vm-title")),
            ("catalog.py", cat,
             ("vm-card", "vm-poster", "vm-img", "vm-chip", "vm-actions",
              "vm-always", "vm-body", "vm-title")),
        ):
            for cls in required:
                self.assertIn(cls, src, f"{name}: {cls} contract missing")
        # both mode selects are auto-bound — neither has its own onchange handler
        self.assertEqual(wa.count('"vm": True'), 2)
        self.assertEqual(wa.count('data-vm-select="1"'), 1)
        mode_spec = re.search(r'\{"id": "modeSel"[^\n]*', wa).group(0)
        self.assertNotIn("onchange", mode_spec)
        cat_spec = re.search(r'\{"id": "catMode"[^\n]*', wa).group(0)
        self.assertNotIn("onchange", cat_spec)
        self.assertNotIn('onchange="setMode', wa)

    def test_07_text_mode_hides_only_the_photo(self):
        """CSS hides only the image/placeholder/play-overlay, never the details."""
        block = css_block()
        for cls in (".vm-img", ".vm-ph", ".vm-overlay"):
            self.assertIn(cls, block, f"{cls} hide rule missing")
        for cls in (".vm-details", ".vm-size", ".vm-chip", ".vm-actions", ".vm-body"):
            self.assertIn(cls, block, f"{cls} must remain visible in Text mode")
        hide = re.search(
            r"\.vm-grid\.mode-text\s+\.vm-img,[^{]*\{([^}]*)\}", block, re.S
        )
        self.assertIsNotNone(hide, "the image hide rule was not found")
        self.assertIn("display:none", hide.group(1))
        # apart from the image/placeholder/overlay and image-only pseudo decoration,
        # no element may receive display:none
        for m in re.finditer(r"([^{}]*)\{([^}]*display:none[^}]*)\}", block):
            selector = m.group(1)
            if any(c in selector for c in (".vm-img", ".vm-ph", ".vm-overlay", "::after", "::before")):
                continue
            self.fail("something other than the image is being hidden: " + selector.strip()[:80])

    def test_08_poster_mode_restores_src_without_network_in_text(self):
        js = js_block()
        for token in ("data-src", "data-thumb", "data-retry",
                      "function storageFor(kind)", "window.setMode=",
                      "window.ddSet", "img.dataset.src"):
            self.assertIn(token, js, f"{token} is missing from MODE_JS")
        self.assertIn("'ff_cat_mode_'", js)
        self.assertIn("'ff_view_mode'", js)

    def test_09_text_is_the_default_everywhere(self):
        """An empty localStorage ⇒ Text on every page; the default is one editable line."""
        js = js_block()
        self.assertIn("var DEFAULT='text'", js)
        self.assertIn("cur=DEFAULT", js)
        self.assertIn("function norm(v){return VALID.indexOf(v)>=0?v:DEFAULT;}", js)
        self.assertIn("cur=norm(v||DEFAULT)", js)
        self.assertIn("defaultMode:DEFAULT", js)
        self.assertNotIn("cur='poster'", js, "the old poster default remains")
        self.assertNotIn("v||'poster'", js, "the old poster fallback remains")
        # Existing per-page choices migrate into one shared preference.
        self.assertIn("function resetOnce()", js)
        self.assertIn("'ff_view_mode_shared'", js)
        self.assertIn("localStorage.setItem('ff_view_mode_shared',norm(old))", js)
        self.assertIn("window.addEventListener('storage'", js)
        self.assertIn("function storageFor(kind){return 'ff_view_mode_shared';}", js)
        # no other file may define its own default / initial mode
        for name, src in OTHER_FILES.items():
            self.assertNotIn("modeSel').value", src)
            self.assertNotIn("catMode').value", src)

    def test_10_no_video_type_chip_on_any_thumbnail(self):
        """No 'VIDEO'/'FILE' type chip on thumbnails; quality/res/duration stay."""
        wa = FILES["web_assets.py"]
        spec = re.search(r"^VCARD_CHIP_SPEC\s*=\s*\((.*?)\n\)", wa, re.S | re.M)
        self.assertIsNotNone(spec, "VCARD_CHIP_SPEC not found")
        fields = re.findall(r'^\s*\(\s*"([a-z_]+)"\s*,', spec.group(1), re.M)
        self.assertEqual(fields, ["quality", "res", "duration"])
        self.assertNotIn("type", fields)
        gr = FILES["group_assets.py"]
        self.assertNotIn("g.type", gr, "a VIDEO chip remains on group thumbnails")
        self.assertNotIn("type:'VIDEO'", gr, "type remains in the group demo payload")
        routes = (WEB / "group_routes.py").read_text(encoding="utf-8")
        self.assertNotIn('"type": rep.get("type", "VIDEO")', routes,
                         "VIDEO chip data remains in the group payload")


    def test_11_text_mode_is_a_responsive_grid(self):
        """GitHub reference (v5 `.res-grid`): 📱 1 / 📟 2 / 🖥️ 3 cards per row."""
        css = css_block()
        self.assertIn(".vm-grid.mode-text{display:grid;", css)
        self.assertNotIn(".vm-grid.mode-text{display:block}", css,
                         "Text mode is still a full-width single-column list")
        self.assertIn("grid-template-columns:minmax(0,1fr)", css)
        self.assertIn(
            "@media(min-width:620px){.vm-grid.mode-text{"
            "grid-template-columns:repeat(2,minmax(0,1fr))", css)
        self.assertIn(
            "@media(min-width:1024px){.vm-grid.mode-text{"
            "grid-template-columns:repeat(3,minmax(0,1fr))", css)
        self.assertIn("flex-direction:column", css,
                      "details must stack vertically in 3-column cards")

    def test_12_expanded_group_has_no_giant_master_thumbnail(self):
        """v5 `.grp-card.open .grp-master{display:none}` → fsv1 compact head."""
        gr = FILES["group_assets.py"]
        for token in (
            ".gcard.open .gposter{", "aspect-ratio:auto", "height:auto",
            ".gcard.open .gposter .vm-img", "display:none!important",
            ".gcard.open .gposter .vm-details", ".gcard.open .gposter .vm-actions",
            ".gcard.open .gmaster{display:flex", ".gcard.open .gbody{order:-1",
        ):
            self.assertIn(token, gr, f"compact open-group rule missing: {token}")
        # the variants' 1/2/3 grid stays completely unchanged
        self.assertIn(
            "@media(min-width:1024px){.gcard.open .gvariants{"
            "grid-template-columns:repeat(3,minmax(0,1fr))}}", gr)
        # an open group card still spans the full width (variants 3/row)
        self.assertIn(".gcard.open{grid-column:1/-1", gr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
