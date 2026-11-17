import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = (ROOT / 'web/catalog.py').read_text()
MODE = (ROOT / 'web/mode_assets.py').read_text()


class CatalogCardsTests(unittest.TestCase):
    def test_listing_has_no_admin_buttons_and_opens_detail(self):
        section = CATALOG.split('function cardHTML(it){', 1)[1].split('function skeletons()', 1)[0]
        self.assertNotIn('cat-actions', section)
        self.assertNotIn('openEditor(', section)
        self.assertNotIn('removeItem(', section)
        self.assertIn('onclick="openDetail(this.dataset.id)"', section)
        self.assertIn('role="link" tabindex="0"', section)
        self.assertIn('ViewMode.imgAttrs(esc(src),true)', section)
        self.assertIn('.cat-meta-main{display:none', CATALOG)
        self.assertIn('.vm-grid.mode-text .cat-meta-main{display:block}', MODE)
        self.assertIn("e.target===card && (e.key==='Enter'||e.key===' ')", CATALOG)

    def test_detail_actions_admin_only_and_available_above_tabs(self):
        tree = ast.parse(CATALOG)
        func = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_detail_body')
        src = ast.get_source_segment(CATALOG, func)
        self.assertIn('if admin:', src)
        self.assertIn('<div class="cat-detail-actions">', src)
        self.assertIn('?edit={item_id}', src)
        self.assertIn('deleteDetail(this.dataset.id)', src)
        self.assertLess(src.index('{admin_bar}'), src.index('<div class="cat-tabs"'))
        self.assertEqual(src.count('{admin_bar}'), 1)
