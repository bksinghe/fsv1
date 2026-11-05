#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🌐 Guest pages — regression test for the landing page and sign-in forms.

Stdlib-only; runs without MongoDB / Telegram / aiohttp:

    python3 -m unittest discover -s tests -v

The GitHub reference (`JoneySin/v5`) uses a cinematic `login-bg` hero and a
`login-card`. fsv1 rebuilds that idea in `web/welcome_assets.py`: CSS-only gradients,
one shared topbar and one shared split auth layout. This test guards the single
source, the light/reduced-motion variants, the fact that logged-in pages are
untouched, and every auth form/route contract that must not change.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
FILES = {
    name: (WEB / name).read_text(encoding="utf-8")
    for name in ("welcome_assets.py", "web_assets.py", "stream_routes.py",
                 "auth_routes.py", "mode_assets.py", "catalog.py")
}
WELCOME = FILES["welcome_assets.py"]


def block(name):
    m = re.search(rf"^{name}\s*=\s*r?\"\"\"(.*?)\"\"\"", WELCOME, re.S | re.M)
    assert m, f"{name} could not be read"
    return m.group(1)


class TestGuestSingleSource(unittest.TestCase):

    def test_01_module_defines_everything(self):
        for symbol in ("GUEST_BODY_CLASS", "GUEST_TOPBAR", "GUEST_AMBIENT",
                       "WELCOME_CSS", "WELCOME_JS", "def landing_body("):
            self.assertRegex(WELCOME, rf"(?m)^{re.escape(symbol)}" if symbol.startswith("def ")
                             else rf"(?m)^{re.escape(symbol)}\s*=",
                             f"{symbol} is missing from welcome_assets.py")
        self.assertEqual(GUEST_BODY_CLASS_VALUE(), "guest")

    def test_02_css_is_scoped_and_self_contained(self):
        css = block("WELCOME_CSS")
        for frag in ("body.guest{", ".wc-top{", ".wc-hero{", ".wc-feature-grid{",
                     "html.light .wc-top", "html.light body.guest .auth-card",
                     "@media(prefers-reduced-motion:reduce)",
                     "@media(max-width:980px)", "@media(max-width:560px)",
                     "@keyframes wcRise", "@keyframes wcDrift"):
            self.assertIn(frag, css, f"WELCOME_CSS is missing {frag}")
        # No external imagery / CDN: the v5 reference used an nflxext.com JPEG.
        for bad in ("nflxext.com", "url(http", "url('http", 'url("http',
                    ".login-bg{", ".hero-bg{", ".card-enter{"):
            self.assertNotIn(bad, css, f"guest CSS must not contain {bad}")
        # The shimmer keyframe is reused from VIDEO_CARD_CSS, not duplicated.
        self.assertNotIn("@keyframes sh{", css)
        self.assertNotIn("animation:sh 1.6s", css, "landing preview should not shimmer continuously")

    def test_03_js_is_defensive_and_keeps_form_markup(self):
        js = block("WELCOME_JS")
        for frag in ("body.classList.contains('guest')", "DOMContentLoaded",
                     "input[type=password]", "b.type='button'", "wc-eye",
                     ".wc-sign-txt", "window.RevealCards"):
            self.assertIn(frag, js, f"WELCOME_JS is missing {frag}")
        # No inline handlers or markup changes to the form fields themselves.
        self.assertNotIn("innerHTML=", js)
        self.assertNotIn("name='password'", js.split("function init()")[0])

    def test_04_shared_shell_is_shipped_on_every_page(self):
        main = FILES["web_assets.py"]
        self.assertRegex(main, r"(?m)^from web\.welcome_assets import \(")
        self.assertIn("SITE_CSS += WELCOME_CSS", main)
        self.assertIn("SITE_JS += WELCOME_JS", main)
        # Poster/Text rules must remain last in both chains.
        self.assertLess(main.index("SITE_CSS += WELCOME_CSS"),
                        main.index("SITE_CSS += MODE_CSS"))
        self.assertLess(main.index("SITE_JS += WELCOME_JS"),
                        main.index("SITE_JS += MODE_JS"))
        # page() injects the ambient backdrop only for guest bodies.
        self.assertIn('ambient = GUEST_AMBIENT if GUEST_BODY_CLASS in body_class else ""', main)
        self.assertIn("nav = topbar or GUEST_TOPBAR", main)
        self.assertIn("DEFAULT_TOPBAR = GUEST_TOPBAR", main)
        self.assertIn("return page(title, body, GUEST_BODY_CLASS)", main)
        # Logged-in shell is a separate function and must stay untouched.
        self.assertIn("def app_page(", main)

    def test_05_landing_and_split_auth_markup(self):
        topbar = re.search(r"^GUEST_TOPBAR\s*=\s*\((.*?)\n\)", WELCOME, re.S | re.M).group(1)
        for frag in ('class="wc-top"', 'class="wc-brand"', 'onclick="toggleTheme()"',
                     'class="wc-sign"', 'href="/#features"'):
            self.assertIn(frag, topbar, f"GUEST_TOPBAR is missing {frag}")
        ambient = re.search(r"^GUEST_AMBIENT\s*=\s*\((.*?)\n\)", WELCOME, re.S | re.M).group(1)
        self.assertIn('class="wc-ambient"', ambient)
        for frag in ("<main class=\"wc-hero\">", "class=\"wc-preview\"",
                     "class=\"wc-feature rv-enter\"", "id=\"features\"",
                     "class=\"wc-foot\"", "Sign In to Search"):
            self.assertIn(frag, WELCOME, f"landing_body() is missing {frag}")
        self.assertNotIn("https://t.me/", WELCOME, "Telegram link should be removed from landing page")
        mini = re.search(r"\.wc-mini-poster\{([^}]+)\}", WELCOME)
        self.assertIsNotNone(mini)
        self.assertNotIn("animation:", mini.group(1), "preview poster shimmer should stay static")
        main = FILES["web_assets.py"]
        for frag in ("<div class='wc-auth'>", "<div class='wc-story'>",
                     "<span class='wc-kicker-card'>", "<div class='auth-wrap'>",
                     "f\"<h2>{html.escape(heading or title)}</h2>{e}{m}{inner}\""):
            self.assertIn(frag, main, f"form_page() is missing {frag}")

    def test_06_routes_and_form_contracts_unchanged(self):
        root = FILES["stream_routes.py"]
        self.assertIn("landing_body(bot_username)", root)
        self.assertIn("GUEST_BODY_CLASS", root)
        self.assertIn("return web.HTTPFound(\"/search\")", root)
        self.assertIn('"FAST FINDER — Web File Search"', root)
        login = FILES["auth_routes.py"]
        for frag in ("action='/api/login' method='post'", "name='email'",
                     "name='password'", "autocomplete='username'",
                     "autocomplete='current-password'", "href='/forgot_password'",
                     "href='/register'", "return web.HTTPFound(\"/search\")"):
            self.assertIn(frag, login, f"login contract changed: {frag}")

    def test_07_english_and_existing_contracts(self):
        for name, src in FILES.items():
            self.assertNotRegex(src, r"[\u0900-\u097f]", f"{name} contains Devanagari")
        cat = FILES["catalog.py"]
        self.assertIn('CATEGORY_ALL_LABEL = "📂 All"', cat)
        self.assertNotIn("All Categories", cat)


def GUEST_BODY_CLASS_VALUE():
    m = re.search(r'^GUEST_BODY_CLASS\s*=\s*"([^"]+)"', WELCOME, re.M)
    return m.group(1) if m else ""


if __name__ == "__main__":
    unittest.main()
