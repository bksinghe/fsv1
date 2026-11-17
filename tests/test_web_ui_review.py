import ast
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CAT = (ROOT / 'web/catalog.py').read_text()
WEB = (ROOT / 'web/web_assets.py').read_text()


def string_constant(path, name):
    tree = ast.parse(path.read_text())
    node = next(n for n in tree.body if isinstance(n, ast.Assign) and
                any(isinstance(t, ast.Name) and t.id == name for t in n.targets))
    return ast.literal_eval(node.value)


def node_run(script):
    result = subprocess.run(['node', '-e', script], capture_output=True, text=True, timeout=10)
    if result.returncode:
        raise AssertionError(result.stderr)


class UIReviewTests(unittest.TestCase):
    def test_tabs_and_search_controls_have_accessible_names(self):
        self.assertIn('id="q" type="search" aria-label="Search files"', WEB)
        self.assertIn('id="searchStatus" role="status" aria-live="polite"', WEB)
        self.assertIn('id="catQ" aria-label=', CAT)
        for name in ('overview', 'videos', 'gallery'):
            self.assertIn(f'id="tab-{name}" role="tab"', CAT)
            self.assertIn(f'role="tabpanel" aria-labelledby="tab-{name}"', CAT)
        self.assertIn("focused.classList.contains('cat-tab')", CAT)
        self.assertIn("['ArrowLeft','ArrowRight','Home','End'].includes(e.key)", CAT)
        self.assertIn("t.setAttribute('aria-selected',String(active))", CAT)

    @unittest.skipUnless(shutil.which('node'), 'Node is required')
    def test_search_pagination_failure_keeps_previous_results_and_can_retry(self):
        text = string_constant(ROOT / 'web/web_assets.py', 'SEARCH_BODY')
        code = text[text.index('async function load(reset){'):text.index('function playerGroupContext(')]
        script = r'''
const assert=require('assert');
function el(){const classes=new Set();return {innerHTML:'',textContent:'',disabled:false,children:[{}],classList:{add:x=>classes.add(x),remove:x=>classes.delete(x),toggle:(x,on)=>on?classes.add(x):classes.delete(x),contains:x=>classes.has(x)},insertAdjacentHTML(pos,html){this.innerHTML+=html}}}
const els={'#grid':el(),'#more':el(),'#srow':el(),'#searchStatus':el()};
const $=s=>els[s];let curQ='',offset=0,loading=false,hasMore=false,seenGroups={},searchController=null,searchSeq=0,groupMode='all';
const skeletons=()=>'<skeleton>'; const card=x=>x.name; const esc=x=>String(x);const RevealCards={reveal(){}};
let replies=[];const fetch=()=>Promise.resolve(replies.shift());
''' + code + r'''
(async()=>{
 replies.push({ok:true,json:async()=>({results:[{name:'existing'}],next_offset:10})});
 await load(true);assert.equal(els['#grid'].innerHTML,'existing');assert(els['#more'].classList.contains('show'));
 replies.push({ok:false,status:503});await load(false);
 assert.equal(els['#grid'].innerHTML,'existing');assert(els['#searchStatus'].textContent.includes('try again'));
 assert(els['#more'].classList.contains('show'));assert(!els['#more'].disabled);assert.equal(offset,10);
 replies.push({ok:true,json:async()=>({results:[{name:'more'}],next_offset:0})});await load(false);
 assert.equal(els['#grid'].innerHTML,'existingmore');assert.equal(els['#searchStatus'].textContent,'');
})().catch(e=>{console.error(e);process.exitCode=1});
'''
        node_run(script)

    @unittest.skipUnless(shutil.which('node'), 'Node is required')
    def test_catalog_stale_failure_does_not_overwrite_new_results(self):
        text = string_constant(ROOT / 'web/catalog.py', 'CATALOG_JS')
        code = text[text.index('async function load(reset){'):text.index('function openDetail(card)')]
        script = r'''
const assert=require('assert'); let resolves=[];
const cls={add(){},remove(){}};
const els={'#catGrid':{innerHTML:''},'#catSearch':{classList:cls},'#catCount':{textContent:''}};
const $=s=>els[s];const state={offset:0,page:1,hasNext:false,req:0,q:'',cat:'all'};
const CFG={kind:'posts'},LIMIT=20;const skeletons=()=>'loading';const emptyHTML=()=>'empty';const cardHTML=x=>x.title;
const esc=x=>String(x),updatePg=()=>{},bump=()=>{},flashSaved=()=>{};
const ViewMode={apply(){}},RevealCards={reveal(){}};
const fetch=()=>new Promise((resolve,reject)=>resolves.push({resolve,reject}));
''' + code + r'''
(async()=>{
 const old=load(true); const fresh=load(true);
 resolves[1].resolve({ok:true,json:async()=>({items:[{id:1,title:'new'}],total:1})});await fresh;
 resolves[0].reject(new Error('old network failure'));await old;
 assert.equal(els['#catGrid'].innerHTML,'new');
 const bad=load(true);resolves[2].resolve({ok:false,status:503});await bad;
 assert(els['#catGrid'].innerHTML.includes('HTTP 503'));
})().catch(e=>{console.error(e);process.exitCode=1});
'''
        node_run(script)
