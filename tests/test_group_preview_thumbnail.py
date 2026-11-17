"""Exercise preview image retry behavior without Telegram or a browser."""
import ast
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('node'), 'Node is required for the JS behavior test')
class PreviewThumbnailTests(unittest.TestCase):
    def test_loading_retry_success_and_changed_target(self):
        tree = ast.parse((ROOT / 'web/group_assets.py').read_text())
        node = next(n for n in tree.body if isinstance(n, ast.Assign) and
                    any(isinstance(t, ast.Name) and t.id == '_GROUP_JS_TPL' for t in n.targets))
        js = ast.literal_eval(node.value).replace('__GROUP_CARD_TEMPLATE__', '""')
        script = r'''
const assert=require('assert');
let timers=[];
global.setTimeout=(fn,delay)=>{timers.push({fn,delay});return timers.length};
global.clearTimeout=()=>{};
function elem(){return {children:[],hidden:false,isConnected:true,classList:{toggle(){},remove(){}},
 appendChild(x){this.children.push(x)},replaceChildren(){this.children=[]},
 addEventListener(){},removeEventListener(){},setAttribute(){}}}
global.document={createElement:elem,addEventListener(){}};
global.window={};
global.fetch=()=>Promise.resolve({ok:true,json:()=>Promise.resolve({ok:true,group:{id:'12',num:12,name:'Group',count:2,thumb:'/api/thumb?file_id=a'}})});
''' + js + r'''
(async()=>{
 const input=elem(),box=elem();input.value='12';
 const control=window.GroupPreview(input,box);control.update();
 const task=timers.shift();assert.strictEqual(task.delay,250);task.fn();
 await new Promise(resolve=>setImmediate(resolve));
 const poster=box.children[0], placeholder=poster.children[0], img=poster.children[1];
 assert.strictEqual(img.src,'/api/thumb?file_id=a');assert.strictEqual(img.hidden,true);
 img.onerror();const retry=timers.shift();assert.strictEqual(retry.delay,1500);retry.fn();
 assert(img.src.includes('retry=true'));img.onload();
 assert.strictEqual(img.hidden,false);assert.strictEqual(placeholder.hidden,true);
 img.onerror();const stale=timers.shift();input.value='13';control.update();
 const prev=img.src;stale.fn();assert.strictEqual(img.src,prev);
 console.log('ok');
})().catch(e=>{console.error(e);process.exitCode=1});
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('ok', result.stdout)

    def test_placeholder_css_allows_image_to_show(self):
        src = (ROOT / 'web/group_assets.py').read_text()
        self.assertIn('.gpreview-img[hidden],.gpreview-placeholder[hidden]{display:none}', src)
        self.assertIn('poster.appendChild(img);if(g.thumb)img.src=g.thumb;', src)
