"""Regression guards for the expanded group toolbar and poster overlay."""
import re
import unittest
from pathlib import Path

GROUP = (Path(__file__).resolve().parents[1] / 'web' / 'group_assets.py').read_text()


class GroupAdminUITests(unittest.TestCase):
    def test_no_dark_click_blocking_overlay_on_expanded_group(self):
        self.assertIn('.gcard.open.gactive .gposter::after{display:none}', GROUP)
        self.assertNotIn('.gcard.gactive .gposter::after{content:', GROUP)
        self.assertIn('.gcard.gactive:not(.open) .gbottom{display:none}', GROUP)

    def test_toolbar_remains_responsive_and_accessible(self):
        for part in ('.gcard.open .gposter .gadmin{flex:1 1 100%',
                     '.gcard.open .gadmin button{flex:1 1 calc(50% - 6px)}',
                     'class="ga-edit"',
                     'class="ga-merge"', 'class="ga-del"',
                     'gSelectGroup(', 'gUngroup('):
            self.assertIn(part, GROUP)
        self.assertNotIn('.gadmin button{flex:1 1 100%}', GROUP)


if __name__ == '__main__':
    unittest.main()

class GroupEditorTests(unittest.TestCase):
    def test_editor_is_structured_without_old_explanation(self):
        self.assertNotIn('Saving a changed <b>GROUP NAME</b>', GROUP)
        editor = GROUP.split('window.gEdit=function(k)', 1)[1].split('window.gFind=function', 1)[0]
        for part in ('class="gmedit"', 'class="gmedit-section"',
                     'class="gmedit-actions"', 'for="gmName"',
                     'kindHtml(g)+episodesHtml(g)', 'thumbsHtml(g)',
                     'membersHtml(items', 'id="gmSave"', 'gUngroup(',
                     '<summary>Add to an existing group</summary>'):
            self.assertIn(part, editor)
        self.assertIn('.gmcard.is-edit', GROUP)
        self.assertIn('.gmedit-actions{position:sticky', GROUP)
        self.assertIn('.gmedit .gmlist{max-height:210px', GROUP)
        self.assertIn("b.setAttribute('aria-pressed'", GROUP)


class GroupLightThemeTests(unittest.TestCase):
    def test_group_editor_uses_light_theme_surfaces_and_readable_controls(self):
        self.assertIn('html.light .gmcard.is-edit{--gm-surface:#fff', GROUP)
        for part in ('--gm-section:#f7f8fb', '--gm-input:#fff', '--gm-label:#50596a',
                     'background:var(--gm-surface);border-bottom',
                     'background:var(--gm-surface);border-top',
                     '.gmedit .gminput{background:var(--gm-input)',
                     'html.light .gmodal{background:rgba(28,34,47,.46)}'):
            self.assertIn(part, GROUP)
        self.assertNotIn('background:rgba(30,31,42,.97)', GROUP)

    def test_group_toolbar_and_chips_have_light_styles(self):
        for part in ('html.light .gadmin{background:rgba(255,255,255,.96)',
                     'html.light .gcard.open .gposter .vtag',
                     'html.light .gcard.open .gposter .gqchip.ep'):
            self.assertIn(part, GROUP)
        mode = (Path(__file__).resolve().parents[1] / 'web' / 'mode_assets.py').read_text()
        self.assertIn('html.light .vm-grid.mode-text .gcard .gposter .gqchip', mode)


class AdminActionContrastTests(unittest.TestCase):
    def test_shared_action_colors_remain_readable_on_base_and_hover(self):
        css = (Path(__file__).resolve().parents[1] / 'web/web_assets.py').read_text()
        palette = css.split('ADMIN_ACTION_CSS = """', 1)[1].split('"""', 1)[0]

        def luminance(hexcolor):
            rgb = [int(hexcolor[i:i+2], 16) / 255 for i in (1, 3, 5)]
            return sum(w * (v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4)
                       for v, w in zip(rgb, (.2126, .7152, .0722)))

        for selector in ('.gadmin button', '.ga-edit', '.ga-merge', '.ga-del',
                         '.va-edit', '.va-del', '.gmbtn.alt', '.gmbtn.danger', '.febtn.danger'):
            with self.subTest(selector=selector):
                props = re.search(re.escape(selector) + r'[^{}]*\{(--action-bg:[^}]+)\}', palette)[1]
                colors = dict(re.findall(r'--action-(\w+):(#[a-f0-9]{6})', props))
                for state in ('bg', 'hover'):
                    # Bright, opaque surface with dark text, even in dark mode.
                    self.assertGreater(luminance(colors[state]), .45)
                    self.assertGreaterEqual((luminance(colors[state]) + .05) /
                                            (luminance(colors['ink']) + .05), 4.5)
        self.assertIn('.gadmin button:focus-visible', palette)
