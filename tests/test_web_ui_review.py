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
        code = text[text.index('function updatePages(){'):text.index('function playerGroupContext(')]
        script = r"""
const assert=require('assert');
function el(){return {innerHTML:'',textContent:'',disabled:false,hidden:false,classList:{add(){},remove(){}},scrollIntoView(){}}}
const els={'#grid':el(),'#searchPagination':el(),'#searchPrev':el(),'#searchNext':el(),'#searchPage':el(),'#srow':el(),'#searchStatus':el()};
const $=s=>els[s];const SEARCH_PAGE_SIZE=21;
let curQ='',nextOffset=0,loading=false,hasMore=true,sourceMore=true,pendingCards=[],seenGroups=Object.create(null),pages=[],pageIndex=0,searchController=null,searchSeq=0,groupMode='all';
const card=x=>x.name;const esc=x=>String(x);const RevealCards={reveal(){}};
let replies=[];const fetch=()=>Promise.resolve(replies.shift());
""" + code + r"""
(async()=>{
 replies.push({ok:true,json:async()=>({results:Array.from({length:21},(_,i)=>({name:'A'+i})),next_offset:'21'})});
 await load(true);assert.equal(pages[0].length,21);assert.equal(pageIndex,0);assert(!els['#searchNext'].disabled);
 const first=els['#grid'].innerHTML;
 replies.push({ok:false,status:503});await load(false);
 assert.equal(els['#grid'].innerHTML,first);assert(els['#searchStatus'].textContent.includes('try again'));
 assert(!els['#searchNext'].disabled);assert.equal(nextOffset,21);
 replies.push({ok:true,json:async()=>({results:[{name:'last'}],next_offset:''})});await load(false);
 assert.equal(els['#grid'].innerHTML,'last');assert(els['#searchNext'].disabled);
 prevPage();assert.equal(els['#grid'].innerHTML,first);assert(!els['#searchNext'].disabled);
 await load(false);assert.equal(els['#grid'].innerHTML,'last');assert.equal(replies.length,0);
})().catch(e=>{console.error(e);process.exitCode=1});
"""
        node_run(script)

    @unittest.skipUnless(shutil.which('node'), 'Node is required')
    def test_search_loading_is_static_and_replaced_when_results_arrive(self):
        text = string_constant(ROOT / 'web/web_assets.py', 'SEARCH_BODY')
        self.assertNotIn('rv-skel', text)
        self.assertNotIn('class="spin"', text)
        code = text[text.index('function updatePages(){'):text.index('function playerGroupContext(')]
        script = r"""
const assert=require('assert');
function el(){return {innerHTML:'',textContent:'',disabled:false,hidden:false,classList:{add(){},remove(){}},scrollIntoView(){}}}
const els={'#grid':el(),'#searchPagination':el(),'#searchPrev':el(),'#searchNext':el(),'#searchPage':el(),'#srow':el(),'#searchStatus':el()};
const $=s=>els[s],SEARCH_PAGE_SIZE=21;
let curQ='',nextOffset=0,loading=false,hasMore=true,sourceMore=true,pendingCards=[],seenGroups=Object.create(null),pages=[],pageIndex=0,searchController=null,searchSeq=0,groupMode='all';
const card=x=>x.name,esc=String,RevealCards={reveal(){}};let resolve;
const fetch=()=>new Promise(r=>resolve=r);
""" + code + r"""
(async()=>{
 const request=load(true);
 assert(els['#grid'].innerHTML.includes('Loading results…'));
 assert(els['#grid'].innerHTML.includes('role="status"'));
 assert(!els['#grid'].innerHTML.includes('rv-skel'));
 resolve({ok:true,json:async()=>({results:[{name:'video'}],next_offset:''})});
 await request;assert.equal(els['#grid'].innerHTML,'video');
})().catch(e=>{console.error(e);process.exitCode=1});
"""
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
