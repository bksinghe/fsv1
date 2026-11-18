"""Search pages display 21 distinct cards and keep reliable navigation."""
import ast
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def search_body():
    tree=ast.parse((ROOT/'web/web_assets.py').read_text())
    node=next(n for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='SEARCH_BODY' for t in n.targets))
    return ast.literal_eval(node.value)


class SearchPageTests(unittest.TestCase):
    def test_controls_and_page_size(self):
        body=search_body()
        self.assertIn('const SEARCH_PAGE_SIZE=21;',body)
        self.assertIn('id="searchPrev"',body)
        self.assertIn('id="searchNext"',body)
        self.assertIn('aria-label="Search result pages"',body)
        self.assertNotIn('Show more ⬇',body)
        self.assertNotIn('id="more"',body)
        self.assertIn('&limit=${SEARCH_PAGE_SIZE}',body)

    @unittest.skipUnless(shutil.which('node'),'Node required')
    def test_grouped_batches_fill_pages_dedupe_and_reset(self):
        text=search_body()
        code=text[text.index('function updatePages(){'):text.index('function playerGroupContext(')]
        js=r'''
const assert=require('assert');
function el(){return {innerHTML:'',textContent:'',disabled:false,hidden:false,classList:{add(){},remove(){}},scrollIntoView(){}}}
const els={'#grid':el(),'#searchPagination':el(),'#searchPrev':el(),'#searchNext':el(),'#searchPage':el(),'#srow':el(),'#searchStatus':el()};
const $=s=>els[s],SEARCH_PAGE_SIZE=21; let curQ='',nextOffset=0,loading=false,hasMore=true,sourceMore=true,pendingCards=[],seenGroups=Object.create(null),pages=[],pageIndex=0,searchController=null,searchSeq=0,groupMode='all';
const readSearchPreview=()=>null,writeSearchPreview=()=>{},clearSearchPreview=()=>{};const card=x=>x.name+'|';const esc=String,RevealCards={reveal(){}};
let calls=[],replies=[];const fetch=(url)=>{calls.push(url);return Promise.resolve(replies.shift())};
const response=(items,next)=>({ok:true,json:async()=>({results:items,next_offset:next})});
''' + code + r'''
(async()=>{
 let group={name:'group',group:true,key:'g'}, distinct=(n,prefix)=>Array.from({length:n},(_,i)=>({name:prefix+i}));
 replies.push(response([group,...distinct(9,'a')],'21'),response([group,...distinct(11,'b')],'33'));
 await load(true);assert.equal(pages[0].length,21);assert.equal(pages[0].filter(x=>x.group).length,1);
 assert(calls[0].includes('limit=21'));assert(calls[1].includes('limit=21'));
 assert.equal(nextOffset,33);assert.equal(els['#searchPage'].textContent,'Page 1');
 replies.push(response([group,...distinct(20,'c')],'54'),response([group,{name:'last'}],''));
 await load(false);assert.equal(pages[1].length,21);assert.equal(pageIndex,1);assert(els['#searchNext'].disabled);
 assert(!els['#grid'].innerHTML.includes('a0|'));assert.equal(els['#searchPage'].textContent,'Page 2');
 prevPage();assert.equal(pageIndex,0);assert(els['#searchPrev'].disabled);
 await load(false);assert.equal(pageIndex,1);assert.equal(replies.length,0);
 curQ='new';groupMode='ungroup';replies.push(response([{name:'fresh'}],''));await load(true);
 assert.equal(pages.length,1);assert.equal(els['#grid'].innerHTML,'fresh|');assert.equal(pageIndex,0);
 assert(calls.at(-1).includes('q=new'));assert(calls.at(-1).includes('group=ungroup'));
 // A grouped response can leave more cards than fit on the current page.
 curQ='buffer';groupMode='all';
 replies.push(response(distinct(15,'x'),'21'),response(distinct(21,'y'),''));
 await load(true);assert.equal(pages[0].length,21);assert.equal(pendingCards.length,15);
 assert(!els['#searchNext'].disabled);const before=calls.length;
 await load(false);assert.equal(pages[1].length,15);assert.equal(calls.length,before);
 assert(els['#searchNext'].disabled);
})().catch(e=>{console.error(e);process.exitCode=1});
'''
        result=subprocess.run(['node','-e',js],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
