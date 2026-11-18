"""Search filter labels and separation from the scan-all admin action."""
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB_ASSETS = (ROOT / 'web/web_assets.py').read_text(encoding='utf-8')
GROUP_ASSETS = (ROOT / 'web/group_assets.py').read_text(encoding='utf-8')


class TestGroupFilter(unittest.TestCase):
    def test_filter_options_have_icons_and_no_scan_for_any_role(self):
        tree = ast.parse(WEB_ASSETS)
        node = next(n for n in tree.body if isinstance(n, ast.Assign) and
                    any(isinstance(t, ast.Name) and t.id == 'FILTER_OPTIONS' for t in n.targets))
        group = next(value for key, value in zip(node.value.keys, node.value.values)
                     if ast.literal_eval(key) == 'group')
        self.assertEqual(ast.literal_eval(group), (
            ('all', '📂 All'), ('group', '🗂️ Group'), ('ungroup', '📄 UnGroup')))
        self.assertNotIn('"group_admin"', WEB_ASSETS)
        self.assertIn('filter_buttons(SEARCH_FILTERS)', WEB_ASSETS)
        handler = WEB_ASSETS.split('function setGroup(v){', 1)[1].split('function doSearch()', 1)[0]
        self.assertNotIn('scan_all', handler)
        self.assertIn("localStorage.setItem('ff_group_mode',groupMode)", handler)

    def test_scan_endpoint_and_implementation_remain_available(self):
        self.assertIn('window.gScanAll=function()', GROUP_ASSETS)
        self.assertIn('/api/group/scan_all', GROUP_ASSETS)
        self.assertIn('/api/group/scan_status', GROUP_ASSETS)


if __name__ == '__main__':
    unittest.main()
