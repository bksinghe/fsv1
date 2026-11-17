import ast
import html
import unittest
from pathlib import Path

SOURCE = (Path(__file__).resolve().parents[1] / 'web/catalog.py').read_text()


class CatalogDetailPosterTests(unittest.TestCase):
    def test_shared_detail_poster_responsive_and_preview_accessible(self):
        self.assertIn('@media(max-width:600px){\n  .cat-hero{padding:16px;gap:18px}', SOURCE)
        self.assertIn('.cat-hero-cover,.cat-hero > .cat-hero-img{flex:0 1 100%;width:100%;max-width:360px;margin:0 auto}', SOURCE)
        self.assertIn('aria-label="Enlarge poster"', SOURCE)
        self.assertIn('openLight(this.firstElementChild.currentSrc || this.firstElementChild.src)', SOURCE)
        self.assertIn('aria-label="Close image preview"', SOURCE)
        self.assertIn("if(e.key==='Escape'){ closeLight()", SOURCE)
        self.assertIn('lightReturnFocus.focus()', SOURCE)
        self.assertIn('if src else', SOURCE)

    def test_cover_markup_escapes_source_and_placeholder_has_no_zoom(self):
        tree = ast.parse(SOURCE)
        func = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_detail_body')
        # Exercise the shared renderer with representative post and actor configs.
        from urllib.parse import quote
        cfg = {'categories': [], 'galleryTab': 'Gallery', 'videosHeading': 'Videos',
               'videoEmptyHint': 'None', 'galleryEmpty': 'None', 'uploadLabel': 'Upload',
               'galleryHint': 'Hint', 'tagMedia': False, 'base': '/catalog', 'kind': 'posts'}
        env = {'html': html, 'quote': quote, 'CATALOGS': {'posts': cfg, 'actors': cfg},
               'image_src': lambda v: v or ''}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[func], type_ignores=[])), '<catalog>', 'exec'), env)
        for kind in ('posts', 'actors'):
            with self.subTest(kind=kind):
                out = env['_detail_body'](kind, 'user', {'title': 'Test', 'image': 'https://x.test/?a="b"'})
                self.assertIn('class="cat-hero-cover"', out)
                self.assertIn('https://x.test/?a=&quot;b&quot;', out)
                self.assertIn('class="cat-lightbox-close"', out)
                empty = env['_detail_body'](kind, 'user', {'title': 'Test'})
                self.assertNotIn('class="cat-hero-cover"', empty)
