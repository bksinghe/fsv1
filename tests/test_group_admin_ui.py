"""Regression guards for the expanded group toolbar and poster overlay."""
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
                     '.gadmin button:focus-visible', 'class="ga-edit"',
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
