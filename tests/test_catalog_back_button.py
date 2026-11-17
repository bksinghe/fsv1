import ast
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'web/catalog.py').read_text()


class BackButtonTests(unittest.TestCase):
    def test_both_detail_pages_share_static_back_button(self):
        self.assertIn('class="cat-btn ghost cat-back" href="{cfg[\'base\']}"', SOURCE)
        self.assertIn('.cat-btn.ghost.cat-back,.cat-btn.ghost.cat-back:hover{display:inline-flex', SOURCE)
        self.assertIn('.cat-back.cat-ripple i{background:rgba(229,9,20,.5)', SOURCE)
        self.assertNotIn('cat-back.is-pressed', SOURCE)
        self.assertIn('prefers-reduced-motion: reduce', SOURCE)

    @unittest.skipUnless(shutil.which('node'), 'Node required')
    def test_navigation_ripple_and_native_modified_click(self):
        tree = ast.parse(SOURCE)
        node = next(n for n in tree.body if isinstance(n, ast.Assign) and
                    any(isinstance(t, ast.Name) and t.id == 'DETAIL_JS' for t in n.targets))
        text = ast.literal_eval(node.value)
        start = text.index("// Keep native modified/keyboard clicks")
        end = text.index("const mq=document.getElementById('catMediaQ');", start)
        script = r'''
const assert=require('assert');let handler, timers=[], dest='', reduced=false;
global.document={addEventListener:(kind,fn)=>handler=fn};
global.window={matchMedia:()=>({matches:reduced}),addEventListener(){}};
global.document.querySelectorAll=()=>[];
global.location={assign:url=>dest=url};global.setTimeout=(fn,t)=>{timers.push([fn,t])};
''' + text[start:end] + r'''
let values=new Set();let link={href:'/posts',target:'',dataset:{},hasAttribute:()=>false,classList:{contains:v=>values.has(v),add:v=>values.add(v)}};
function ev(options={}){return Object.assign({target:{closest:()=>link},button:0,detail:1,defaultPrevented:false,preventDefault(){this.prevented=true}},options)}
let e=ev();handler(e);assert(e.prevented);assert.equal(link.dataset.backNavigating,'1');assert.equal(timers[0][1],220);timers[0][0]();assert.equal(dest,'/posts');
for(const args of [{ctrlKey:true},{metaKey:true},{button:1},{detail:0}]){let x=ev(args);handler(x);assert(!x.prevented)}
reduced=true;let r=ev();handler(r);assert(!r.prevented);
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
