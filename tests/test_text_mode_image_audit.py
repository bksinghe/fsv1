"""Mode-aware image loading across search, groups, retries and file edits."""
import ast
import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'web'


def constant(file, name):
    tree = ast.parse((ROOT / file).read_text())
    node = next(n for n in tree.body if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == name for t in n.targets))
    return ast.literal_eval(node.value)


@unittest.skipUnless(shutil.which('node'), 'Node required')
class TextModeImageAudit(unittest.TestCase):
    def test_search_group_retries_and_editor(self):
        mode = constant('mode_assets.py', 'MODE_JS')
        video = constant('web_assets.py', '_VCARD_JS_TPL').replace(
            '__VCARD_TEMPLATE__', json.dumps(constant('web_assets.py', 'VCARD_TEMPLATE'))).replace(
            '__VCARD_SAVE__', json.dumps(constant('web_assets.py', 'VCARD_SAVE'))).replace(
            '__VCARD_CHIP_SPEC__', json.dumps(constant('web_assets.py', 'VCARD_CHIP_SPEC')))
        group = constant('group_assets.py', '_GROUP_JS_TPL').replace(
            '__GROUP_CARD_TEMPLATE__', json.dumps(constant('group_assets.py', 'GROUP_CARD_TEMPLATE')))
        search = constant('web_assets.py', 'SEARCH_BODY')
        cards = search[search.index('function imgAttrs(f)'):search.index('function card(f)')]
        retry = search[search.index('function thumbFail(img)'):search.index('async function load(reset,')]
        editor = constant('web_assets.py', 'FILE_EDIT_JS')
        sync = editor[editor.index('function syncCard(f)'):editor.index('function setPoster(f)')]
        catalog_retry = constant('catalog.py', 'CATALOG_IMAGE_JS').replace('<script>', '').replace('</script>', '')
        js = r'''
const assert=require('assert'); let timers=[],images=[],requests=[];
const grid={classList:{toggle(){}}};
global.window={addEventListener(){},escapeHTML:s=>String(s==null?'':s)};
global.localStorage={getItem(){return null},setItem(){}};
global.document={querySelectorAll(s){if(s==='.vm-grid')return [grid];
 if(s==='.vm-grid img.vm-img[data-src]')return images;return []},addEventListener(){}};
global.setTimeout=fn=>timers.push(fn);
''' + mode + video + group + r'''
const ViewMode=window.ViewMode, esc=window.escapeHTML,
 vcardHTML=window.vcardHTML, vcardChips=window.vcardChips,
 vcardSize=window.vcardSize, groupHTML=window.groupHTML;
''' + cards + retry + catalog_retry + r'''
ViewMode.init({});
let one={file_id:'1',name:'one',thumb:'/thumb1'}, two={file_id:'2',name:'two',thumb:'/thumb2'};
let html=cardHTML({group:true,key:'g',name:'group',thumb:'/group',variants:[one,two]},true);
for(const id of ['1','2']){
 const btn='data-save-file="'+id+'"';assert.equal(html.split(btn).length,2);
 assert(html.lastIndexOf('vadmin vm-actions',html.indexOf(btn))>html.lastIndexOf('vbody vm-body',html.indexOf(btn)));
}
const single=cardHTML(one,true);assert(single.indexOf('data-save-file="1"')>single.indexOf('vbody vm-body'));
for(let url of ['/group','/thumb1','/thumb2']){
 assert(html.includes('data-src="'+url+'"'));assert(!html.includes(' src="'+url+'"'));
}
assert(cardHTML(one,true).includes('data-src="/thumb1"'));
function image(url){
 let cls=new Set(), im={dataset:{thumb:url},isConnected:true,_src:url,
  getAttribute(k){return k==='src'?this._src:null},removeAttribute(k){if(k==='src')this._src=''},
  closest(s){return s==='.vm-grid'?grid:null},
  classList:{contains(x){return cls.has(x)},add(x){cls.add(x)},remove(...xs){xs.forEach(x=>cls.delete(x))}}};
 Object.defineProperty(im,'src',{get(){return this._src},set(v){this._src=v;requests.push(v)}});
 images.push(im);return im;
}
ViewMode.set('poster');let im=image('/thumb1');thumbFail(im);
ViewMode.set('text');timers.shift()();assert.equal(requests.length,0);
assert(im.dataset.src.includes('retry=true'));assert.equal(im._src,'');
ViewMode.set('poster');assert.equal(requests.length,1);assert(im.src.includes('retry=true'));
let cat=image('/cover');window.catPosterFail(cat);ViewMode.set('text');timers.shift()();
assert.equal(requests.length,1);assert(cat.dataset.src.includes('retry=true'));
ViewMode.set('poster');assert.equal(requests.length,2);
ViewMode.set('text');
const card={dataset:{label:'1'},querySelector(s){return s==='.vimg'?im:null}};
function cards(){return [card]}
''' + sync + r'''
syncCard({file_id:'1',thumb:'/edited'});
assert.equal(requests.length,2);assert.equal(im.dataset.src,'/edited');assert.equal(im.dataset.thumb,'/edited');
ViewMode.set('poster');assert(requests.includes('/edited'));
// An explicitly opened detail image is outside the mode-controlled grid.
let detail=image('/detail'); detail.closest=()=>null; ViewMode.set('text');
window.catPosterFail(detail);timers.shift()();assert(detail.src.includes('retry=true'));
'''
        result = subprocess.run(['node', '-e', js], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
