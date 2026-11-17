import ast
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('node'), 'Node is required')
class CatalogUploadSafetyTests(unittest.TestCase):
    def test_upload_must_finish_before_save_and_stale_results_are_ignored(self):
        tree = ast.parse((ROOT / 'web/catalog.py').read_text())
        node = next(n for n in tree.body if isinstance(n, ast.Assign) and
                    any(isinstance(t, ast.Name) and t.id == 'CATALOG_JS' for t in n.targets))
        text = ast.literal_eval(node.value)
        upload = text[text.index('async function uploadImage(input){'):text.index('async function pickMedia(){')]
        save = text[text.index('async function saveEditor(){'):text.index('async function removeItem(id){')]
        script = r'''
const assert=require('assert');
let resolveUpload, fetches=0, alerts=[];
const els={'#fUploadNote':{textContent:''},'#catSave':{disabled:false},'#fImage':{value:''},'#fTitle':{focus(){}}};
const state={uploadSeq:0,uploadPending:false,uploadError:false,saving:false};
const $=s=>els[s]; const markDirty=()=>{}; const setPreview=()=>{};
const toast=(s)=>alerts.push(s); const collect=()=>({title:'test',image:els['#fImage'].value});
const document={querySelector(){return {disabled:false,textContent:''}}};
const CFG={kind:'posts'};const FormData=class{append(){}};
let fetch=()=>{fetches++;return new Promise(r=>resolveUpload=r)};
''' + upload + save + r'''
(async()=>{
 const input={files:[{}],value:'selected'};
 const pending=uploadImage(input);
 assert(state.uploadPending);assert(els['#catSave'].disabled);
 await saveEditor();assert.equal(fetches,1);assert(alerts.pop().includes('Wait'));
 resolveUpload({ok:true,json:async()=>({ok:true,value:'TG_ID:abc'})});await pending;
 assert.equal(els['#fImage'].value,'TG_ID:abc');assert(!state.uploadPending);assert(!els['#catSave'].disabled);
 const bad=uploadImage(input);resolveUpload({ok:false,json:async()=>({ok:false,error:'denied'})});await bad;
 assert(state.uploadError);await saveEditor();assert.equal(fetches,2);assert(alerts.pop().includes('failed'));
 const stale=uploadImage(input);state.uploadSeq++;els['#fImage'].value='https://new';
 resolveUpload({ok:true,json:async()=>({ok:true,value:'TG_ID:old'})});await stale;
 assert.equal(els['#fImage'].value,'https://new');
})().catch(e=>{console.error(e);process.exitCode=1});
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_editor_clears_upload_state_and_guards_manual_override(self):
        text = (ROOT / 'web/catalog.py').read_text()
        self.assertIn('state.uploadSeq++; state.uploadPending=false; state.uploadError=false;', text)
        self.assertIn("state.uploadPending=true;state.uploadError=false;markDirty()", text)
        self.assertIn("if(seq!==state.uploadSeq)return", text)
        self.assertIn("if(state.uploadError)", text)
