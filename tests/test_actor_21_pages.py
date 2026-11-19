"""Actor tag results use 21-card pages with safe grouping and navigation."""
import ast
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


class Actor21PagesTests(unittest.TestCase):
    def test_detail_config_sets_21(self):
        tree=ast.parse((ROOT/'web/catalog.py').read_text())
        fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='build_detail_page')
        cfg=next(n.value for n in fn.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='detail_cfg' for t in n.targets))
        item=next(v for k,v in zip(cfg.keys,cfg.values) if ast.literal_eval(k)=='limit')
        self.assertEqual(ast.literal_eval(item),21)

    @unittest.skipUnless(shutil.which('node'),'Node required')
    def test_21_distinct_results_prev_next_and_failure_retry(self):
        tree=ast.parse((ROOT/'web/catalog.py').read_text())
        node=next(n for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='DETAIL_JS' for t in n.targets))
        text=ast.literal_eval(node.value)
        code=text[text.index('function updateMediaControls(){'):text.index('/* ── 🖼️ Gallery')]
        js=r'''
const assert=require('assert');
let mediaLoaded=false,mediaSeq=0,mediaController=null,mediaGroupMode='all',mediaBusy=false;
let mediaPages=[],mediaPageIndex=0,mediaCursor=0,mediaSourceMore=true,mediaBuffer=[],mediaSeen=Object.create(null),mediaInfo=null;
const D={tagMedia:true,kind:'actors',id:'abc',limit:21},esc=String;
const els={catMediaQ:{value:''},catMediaResults:{innerHTML:'',querySelectorAll:()=>[]},catMediaInfo:{textContent:'',innerHTML:''},catMediaPg:{style:{}},catMediaPrev:{},catMediaNext:{},catMediaPage:{}};
const document={getElementById:id=>els[id]},ViewMode={apply(){}},RevealCards={stagger(){},reveal(){}};
const mediaCard=f=>f.name+'|';let replies=[],urls=[];
const fetch=url=>{urls.push(url);return Promise.resolve(replies.shift())};
const response=(results,next)=>({ok:true,json:async()=>({results,next_offset:next,source:'tags',terms:['a'],total:70})});
const singles=(n,p)=>Array.from({length:n},(_,i)=>({name:p+i}));
''' + code + r'''
(async()=>{
 const group={group:true,key:'g',name:'group'};
 replies.push(response([group,...singles(9,'a')],'21'),response([group,...singles(20,'b')],'42'));
 await loadMedia(0);assert.equal(mediaPages[0].length,21);assert.equal(mediaBuffer.length,9);
 assert.equal(mediaPages[0].filter(x=>x.group).length,1);assert(urls.every(x=>x.includes('limit=21')));
 assert.equal(els.catMediaPage.textContent,'Page 1');assert(!els.catMediaNext.disabled);
 const first=els.catMediaResults.innerHTML;
 replies.push({ok:false,status:503});await mediaPage(1);
 assert.equal(els.catMediaResults.innerHTML,first);assert.equal(mediaPageIndex,0);assert(!els.catMediaNext.disabled);
 replies.push(response(singles(12,'c'),''));await mediaPage(1);
 assert.equal(mediaPages[1].length,21);assert.equal(els.catMediaPage.textContent,'Page 2');
 assert(els.catMediaNext.disabled);assert(!els.catMediaPrev.disabled);
 mediaPage(-1);assert.equal(els.catMediaResults.innerHTML,first);assert(els.catMediaPrev.disabled);
 await mediaPage(1);assert.equal(mediaPageIndex,1);assert.equal(replies.length,0);
 // Search/filter change resets page history.
 mediaGroupMode='ungroup';replies.push(response(singles(2,'fresh'),''));await loadMedia(0);
 assert.equal(mediaPages.length,1);assert.equal(mediaPages[0].length,2);assert(els.catMediaNext.disabled);
 assert(urls.at(-1).includes('group=ungroup'));
})().catch(e=>{console.error(e);process.exitCode=1});
'''
        p=subprocess.run(['node','-e',js],capture_output=True,text=True,timeout=10)
        self.assertEqual(p.returncode,0,p.stderr)
