"""Actor library controls reuse search filters, group cards and text mode."""
import ast
import asyncio
import shutil
import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

ROOT=Path(__file__).resolve().parents[1]
CAT=(ROOT/'web/catalog.py').read_text()
ROUTES=(ROOT/'web/catalog_routes.py').read_text()


class ActorFilterPageTests(unittest.TestCase):
    def test_actor_only_reuses_filter_specs_and_keeps_posts_separate(self):
        section=CAT.split('if cfg["tagMedia"]:',1)[1].split('# 🖼️ / 📸 tab',1)[0]
        self.assertIn('dict(SEARCH_FILTERS[0], id="catMediaMode")',section)
        self.assertIn('dict(SEARCH_FILTERS[1], id="catMediaGroup"',section)
        self.assertIn('aria-label="Search files"',section)
        self.assertIn('class="cat-vgrid vgrid vm-grid"',section)
        self.assertIn('setMediaGroup(this.value)',section)
        self.assertIn('ViewMode.init({storage:ViewMode.storageFor()})',CAT)
        self.assertIn("+'&group='+mode",CAT)
        self.assertNotIn('onclick="loadMedia(0)">🔍 Search',section)

    @unittest.skipUnless(shutil.which('node'),'Node required')
    def test_text_mode_card_markup_defers_individual_and_group_images(self):
        tree=ast.parse(CAT)
        node=next(n for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='DETAIL_JS' for t in n.targets))
        text=ast.literal_eval(node.value)
        code=text[text.index('function mediaCard(f,topLevel){'):text.index('/* ▶ shared player')]
        js=r'''
const assert=require('assert');const window={};let text=true;
const ViewMode={imgAttrs:url=>(text?'data-src="':'src="')+url+'"'};
const esc=s=>String(s||''),vcardChips=()=>'',vcardSize=()=>'';
const vcardHTML=o=>o.IMG_ATTRS;const groupHTML=(f,attrs,err,top)=>attrs+'|'+top;
''' + code + r'''
for(const f of [{file_id:'1',name:'One',thumb:'/thumb'}, {group:true,thumb:'/group'}]){
 let html=mediaCard(f,true);assert(html.includes('data-src='));assert(!html.includes(' src='));
 text=false;html=mediaCard(f,true);assert(html.includes('src='));text=true;
}
assert(window.cardHTML===mediaCard);
'''
        p=subprocess.run(['node','-e',js],capture_output=True,text=True,timeout=10)
        self.assertEqual(p.returncode,0,p.stderr)

    @unittest.skipUnless(shutil.which('node'),'Node required')
    def test_stale_request_does_not_replace_new_filter_results(self):
        tree=ast.parse(CAT)
        node=next(n for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='DETAIL_JS' for t in n.targets))
        text=ast.literal_eval(node.value)
        code=text[text.index('function updateMediaControls(){'):text.index('/* ── 🖼️ Gallery')]
        js=r"""
const assert=require('assert');
let mediaLoaded=false,mediaSeq=0,mediaController=null,mediaGroupMode='all',mediaBusy=false;
let mediaPages=[],mediaPageIndex=0,mediaCursor=0,mediaSourceMore=true,mediaBuffer=[],mediaSeen=Object.create(null),mediaInfo=null;
const D={tagMedia:true,kind:'actors',id:'abc',limit:21},esc=String;
const els={catMediaQ:{value:'name'},catMediaResults:{innerHTML:'',querySelectorAll:()=>[]},catMediaInfo:{textContent:'',innerHTML:''},catMediaPg:{style:{}},catMediaPrev:{},catMediaNext:{},catMediaPage:{}};
const document={getElementById:id=>els[id]},ViewMode={apply(){}},RevealCards={stagger(){},reveal(){}};
const mediaCard=f=>f.name;let pending=[],urls=[];
const fetch=(url)=>{urls.push(url);return new Promise((resolve,reject)=>pending.push({resolve,reject}));};
""" + code + r"""
(async()=>{
 let first=loadMedia(0);mediaGroupMode='ungroup';let second=loadMedia(0);
 pending[1].resolve({ok:true,json:async()=>({results:[{name:'new'}],source:'tags',terms:['x'],total:1,next_offset:''})});await second;
 pending[0].resolve({ok:true,json:async()=>({results:[{name:'old'}],source:'tags',terms:['x'],total:1,next_offset:''})});await first;
 assert.equal(els.catMediaResults.innerHTML,'new');assert(urls[1].includes('&group=ungroup'));
})().catch(e=>{console.error(e);process.exitCode=1});
"""
        p=subprocess.run(['node','-e',js],capture_output=True,text=True,timeout=10)
        self.assertEqual(p.returncode,0,p.stderr)


class ActorFilterAPITests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tree=ast.parse(ROUTES); fn=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='api_media');fn.decorator_list=[]
        self.docs=[{'_id':'one'},{'_id':'two'},{'_id':'three'}]
        self.fetch=AsyncMock(return_value=(self.docs,'12',['Actor'],25,'tags'))
        self.group=AsyncMock(return_value=[{'group':True,'key':'g'},{'file_id':'three'}])
        self.ns={'get_auth':AsyncMock(return_value=('user',1)),'_json':lambda x,*a:x,
                 '_kind':lambda req:req.match_info['kind'], 'CATALOGS':{'actors':{'tagMedia':True},'posts':{'tagMedia':False}},
                 'store':SimpleNamespace(get_item=AsyncMock(return_value={'tags':['Actor']})),
                 '_clean_id':lambda x:x,'_tag_media':self.fetch,
                 '_media_row':lambda d:{'file_id':d['_id']},'group_cards':self.group, '_tag_member_filter':lambda terms: lambda doc: True,
                 'filter_group_cards':lambda cards,mode:[c for c in cards if c.get('group')], 'GROUP_FILTER_LOCK':asyncio.Lock()}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<routes>','exec'),self.ns)
    async def request(self,**q):
        return await self.ns['api_media'](SimpleNamespace(match_info={'kind':'actors'},query=q))
    async def test_ungroup_shows_every_file_without_group_changes(self):
        result=await self.request(id='x',group='ungroup',offset='12',limit='12')
        self.assertEqual([c['file_id'] for c in result['results']],['one','two','three'])
        self.assertEqual(result['next_offset'],'12');self.group.assert_not_awaited()
        self.fetch.assert_awaited_once_with({'tags':['Actor']},'',12,12)
    async def test_all_uses_shared_group_cards_and_raw_pagination(self):
        result=await self.request(id='x',group='all')
        self.assertTrue(result['results'][0]['group']);self.assertEqual(result['total'],25)
        self.group.assert_awaited_once()
    async def test_group_uses_unlimited_scan_and_group_card_pagination(self):
        result=await self.request(id='x',group='group')
        self.assertEqual(result['results'],[{'group':True,'key':'g'}]);self.assertEqual(result['total'],1)
        self.fetch.assert_awaited_once_with({'tags':['Actor']},'',0,0)
    async def test_unauthorized_and_post_do_not_search(self):
        self.ns['get_auth'].return_value=(None,None)
        self.assertIn('error',await self.request(id='x',group='all'))
        self.ns['get_auth'].return_value=('admin',1)
        result=await self.ns['api_media'](SimpleNamespace(match_info={'kind':'posts'},query={}))
        self.assertEqual(result['source'],'disabled');self.fetch.assert_not_awaited()
