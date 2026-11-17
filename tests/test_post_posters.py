import ast
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = (ROOT / 'web/catalog.py').read_text()
MODE = (ROOT / 'web/mode_assets.py').read_text()


def constant(path, name):
    tree = ast.parse(path.read_text())
    node = next(n for n in tree.body if isinstance(n, ast.Assign) and
                any(isinstance(t, ast.Name) and t.id == name for t in n.targets))
    return ast.literal_eval(node.value)


class PostPosterTests(unittest.TestCase):
    def test_posts_load_cover_in_text_and_poster_modes(self):
        self.assertIn("ViewMode.imgAttrs(esc(src),CFG.kind==='posts')", CATALOG)
        self.assertIn("CFG.kind==='posts'?'vm-show-cover':''", CATALOG)
        self.assertIn('.vm-grid.mode-text .vm-show-cover .vm-img{display:block!important', MODE)
        self.assertIn("isText()&&!arguments[1]", MODE)
        self.assertIn("onerror=\"catPosterFail(this)\"", CATALOG)
        self.assertIn('CATALOG_IMAGE_JS + _listing_body', CATALOG)
        self.assertIn('CATALOG_IMAGE_JS + _detail_body', CATALOG)

    def test_telegram_id_not_truncated_at_300_chars(self):
        tree = ast.parse(CATALOG)
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'clean_url')
        import re
        env = {'re': re, '_URL_RE': re.compile(r'^https?://', re.I),
               '_SCHEME_RE': re.compile(r'^[a-z][a-z0-9+.\-]*:', re.I)}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), '<clean_url>', 'exec'), env)
        value = 'TG_ID:' + 'a' * 400
        self.assertEqual(env['clean_url'](value), value)
        self.assertEqual(env['clean_url']('TG_ID:' + 'a' * 513), '')

    @unittest.skipUnless(shutil.which('node'), 'Node required')
    def test_retry_and_mode_js_behavior(self):
        image_js = constant(ROOT / 'web/catalog.py', 'CATALOG_IMAGE_JS').replace('<script>', '').replace('</script>', '')
        mode_js = constant(ROOT / 'web/mode_assets.py', 'MODE_JS')
        js = r'''
const assert=require('assert');let timers=[];
global.window={addEventListener(){}};
global.document={querySelectorAll(){return []}};
global.localStorage={getItem(){return null},setItem(){}};
global.setTimeout=(fn,delay)=>{timers.push({fn,delay})};
''' + mode_js + image_js + r'''
window.ViewMode.init({});
assert(window.ViewMode.isText());
assert(window.ViewMode.imgAttrs('/cover',true).startsWith('src='));
assert(window.ViewMode.imgAttrs('/cover').startsWith('data-src='));
window.ViewMode.set('poster');assert(window.ViewMode.imgAttrs('/cover').startsWith('src='));
let added=[];let img={dataset:{},isConnected:true,src:'/api/catalog/photo?id=x',
getAttribute(){return this.src},classList:{contains(){return false},add(x){added.push(x)}}};
window.catPosterFail(img);assert.equal(timers[0].delay,1500);timers.shift().fn();assert(img.src.includes('retry=true'));
window.catPosterFail(img);window.catPosterFail(img);window.catPosterFail(img);window.catPosterFail(img);
assert(added.includes('cat-poster-failed'));assert.equal(img.alt,'Poster unavailable');
'''
        result = subprocess.run(['node', '-e', js], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
