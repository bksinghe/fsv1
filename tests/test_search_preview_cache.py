"""Bounded, session-scoped search previews with background revalidation."""
import ast
import asyncio
import hashlib
import shutil
import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

ROOT = Path(__file__).resolve().parents[1]


def search_body():
    tree = ast.parse((ROOT / 'web/web_assets.py').read_text())
    node = next(n for n in tree.body if isinstance(n, ast.Assign) and
                any(isinstance(t, ast.Name) and t.id == 'SEARCH_BODY' for t in n.targets))
    return ast.literal_eval(node.value)


class SearchPreviewRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_scope_is_derived_from_authenticated_session_and_page_is_not_cached(self):
        tree = ast.parse((ROOT / 'web/search_routes.py').read_text())
        fn = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'search_page_handler')
        fn.decorator_list = []
        response = SimpleNamespace(headers={})
        page = Mock(return_value=response)
        ns = {'asyncio': asyncio, 'collection': SimpleNamespace(revision=lambda: 42), 'get_auth': AsyncMock(return_value=('user', 42)), 'search_page': page,
              'hashlib': hashlib, 'web': SimpleNamespace(HTTPFound=lambda url: url)}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), '<route>', 'exec'), ns)
        await ns['search_page_handler'](SimpleNamespace(cookies={'user_session': 'secret'}))
        page.assert_called_once_with(42, 'user', cache_scope=hashlib.sha256(b'secret').hexdigest()+':42')
        self.assertEqual(response.headers['Cache-Control'], 'private, no-store')
        ns['get_auth'].return_value = (None, None)
        self.assertEqual(await ns['search_page_handler'](SimpleNamespace(cookies={})), '/login')


@unittest.skipUnless(shutil.which('node'), 'Node required')
class SearchPreviewTests(unittest.TestCase):
    def test_preview_refresh_storage_boundaries_and_failure(self):
        text = search_body()
        code = text[text.index('function readSearchPreview(){'):text.index('function playerGroupContext(')]
        js = r'''
const assert=require('assert');
function el(){return {innerHTML:'',textContent:'',disabled:false,hidden:false,value:'',classList:{add(){},remove(){}},scrollIntoView(){}}}
const els={'#q':el(),'#grid':el(),'#searchPagination':el(),'#searchPrev':el(),'#searchNext':el(),'#searchPage':el(),'#srow':el(),'#searchStatus':el()};
const $=s=>els[s],SEARCH_PAGE_SIZE=21,SEARCH_CACHE_SCOPE='session-1',SEARCH_CACHE_KEY='preview',SEARCH_CACHE_TTL=300000,SEARCH_CACHE_MAX=256*1024;
let curQ='',nextOffset=0,loading=false,hasMore=true,sourceMore=true,pendingCards=[],seenGroups=Object.create(null),pages=[],pageIndex=0,searchController=null,searchSeq=0,groupMode='all';
const card=x=>x.name,cardHTML=(x,top)=>{assert(!top);return x.name},esc=String,RevealCards={reveal(){}};
let data={};const sessionStorage={getItem:k=>data[k]||null,setItem:(k,v)=>data[k]=v,removeItem:k=>delete data[k]};
let replies=[];const fetch=()=>new Promise(resolve=>replies.push(resolve));const location={href:''};
const response=cards=>({ok:true,json:async()=>({results:cards,next_offset:''})});
''' + code + r'''
(async()=>{
 writeSearchPreview('old query','all',[{name:'cached'}]);
 let p=load(true,true);
 assert.equal(els['#grid'].innerHTML,'cached');assert.equal(els['#q'].value,'old query');
 assert(els['#searchStatus'].textContent.includes('refreshing'));
 assert(els['#searchPagination'].hidden);
 replies.shift()(response([{name:'fresh'}]));await p;
 assert.equal(els['#grid'].innerHTML,'fresh');assert.equal(els['#searchStatus'].textContent,'');
 assert.equal(JSON.parse(data.preview).cards[0].name,'fresh');
 // Network error preserves the preview but does not enable stale paging.
 p=load(true,true);replies.shift()({ok:false,status:503});await p;
 assert.equal(els['#grid'].innerHTML,'fresh');assert(els['#searchStatus'].textContent.includes('saved'));
 assert(els['#searchPagination'].hidden);
 // Session expiry clears saved content before redirecting to login.
 p=load(true,true);replies.shift()({ok:false,status:401});await p;
 assert.equal(els['#grid'].innerHTML,'');assert(!data.preview);assert(location.href.startsWith('/login'));
 writeSearchPreview('old query','all',[{name:'fresh'}]);
 // A newer search wins even if an older preview request eventually resolves.
 p=load(true,true);curQ='new';let q=load(true);let old=replies.shift(),newer=replies.shift();
 newer(response([{name:'new result'}]));await q;old(response([{name:'outdated'}]));await p;
 assert.equal(els['#grid'].innerHTML,'new result');assert.equal(JSON.parse(data.preview).query,'new');
 // Foreign sessions, filters and expired data are never rendered.
 writeSearchPreview('x','all',[{name:'private'}]);let c=JSON.parse(data.preview);c.scope='other';data.preview=JSON.stringify(c);
 assert.equal(readSearchPreview(),null);assert(!data.preview);
 writeSearchPreview('x','all',[{name:'private'}]);groupMode='ungroup';assert.equal(readSearchPreview(),null);
 groupMode='all';writeSearchPreview('x','all',[{name:'private'}]);c=JSON.parse(data.preview);c.time=Date.now()-SEARCH_CACHE_TTL-1;data.preview=JSON.stringify(c);assert.equal(readSearchPreview(),null);
 writeSearchPreview('x','all',[{name:'x'.repeat(SEARCH_CACHE_MAX)}]);assert(!data.preview);
 // Storage failures never break normal fetching.
 sessionStorage.getItem=()=>{throw Error('blocked')};sessionStorage.setItem=()=>{throw Error('blocked')};
 p=load(true,true);assert(els['#grid'].innerHTML.includes('Loading results'));
 replies.shift()(response([{name:'online'}]));await p;assert.equal(els['#grid'].innerHTML,'online');
})().catch(e=>{console.error(e);process.exitCode=1});
'''
        result = subprocess.run(['node', '-e', js], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
