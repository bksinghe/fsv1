import ast
import asyncio
import math
import shutil
import subprocess
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

ROOT = Path(__file__).resolve().parents[1]


class FakeCollection:
    def __init__(self):
        self.docs = {}

    def find_one(self, query, projection):
        return self.docs.get(query['_id'])

    def update_one(self, query, update, **kwargs):
        key = query['_id']
        if isinstance(update, list):
            expr = update[0]['$set']['items']['$slice'][0]['$concatArrays']
            item = expr[0]['$literal'][0]
            fid = expr[1]['$filter']['cond']['$ne'][1]['$literal']
            old = self.docs.get(key, {}).get('items', [])
            self.docs[key] = {'items': ([item] + [x for x in old if x['file_id'] != fid])[:30]}
        elif key in self.docs:
            fid = update['$pull']['items']['file_id']
            self.docs[key]['items'] = [x for x in self.docs[key]['items'] if x['file_id'] != fid]


def handlers():
    tree = ast.parse((ROOT / 'web/progress_routes.py').read_text())
    nodes = [x for x in tree.body if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef)) and x.name != '_collection']
    for node in nodes:
        node.decorator_list = []
    db = FakeCollection()
    auth = AsyncMock(return_value=('user', 1))
    docs = AsyncMock(side_effect=lambda fid: {'file_name': 'Name ' + fid} if fid != 'missing' else None)
    web = SimpleNamespace(json_response=lambda data, status=200, headers=None: (data, status, headers))
    env = dict(asyncio=asyncio, math=math, time=time, MAX_ITEMS=30, MAX_SECONDS=604800,
               get_auth=auth, get_file_details=docs, _collection=lambda: db, web=web,
               logger=SimpleNamespace(exception=lambda *a: None))
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), '<progress>', 'exec'), env)
    return env, db, auth


def request(data=None, query=None):
    return SimpleNamespace(query=query or {}, json=AsyncMock(return_value=data))


class ProgressTests(unittest.IsolatedAsyncioTestCase):
    async def test_auth_privacy_bounded_entries_and_delete(self):
        env, db, auth = handlers()
        auth.return_value = (None, None)
        self.assertEqual((await env['get_progress'](request()))[1], 401)
        self.assertEqual((await env['save_progress'](request()))[1], 401)
        self.assertEqual((await env['delete_progress'](request()))[1], 401)
        auth.return_value = ('user', 1)
        for i in range(35):
            response = await env['save_progress'](request({'file_id': str(i), 'position': 10, 'duration': 100}))
            self.assertEqual(response[1], 200)
        self.assertEqual(len(db.docs[1]['items']), 30)
        auth.return_value = ('user', 2)
        self.assertEqual((await env['get_progress'](request()))[0]['items'], [])
        await env['delete_progress'](request(query={'file_id': '34'}))
        self.assertEqual(len(db.docs[1]['items']), 30)
        auth.return_value = ('user', 1)
        self.assertEqual((await env['get_progress'](request(query={'file_id': '34'})))[0]['item']['position'], 10)
        await env['delete_progress'](request(query={'file_id': '34'}))
        self.assertIsNone((await env['get_progress'](request(query={'file_id': '34'})))[0]['item'])

    async def test_validation_resume_update_and_completion(self):
        env, db, auth = handlers()
        for data in ({'file_id': 'a', 'position': float('nan'), 'duration': 10},
                     {'file_id': 'a', 'position': -1, 'duration': 10},
                     {'file_id': 'a', 'position': 20, 'duration': 10},
                     {'file_id': 'a', 'position': True, 'duration': 10},
                     {'file_id': 'x' * 513, 'position': 5, 'duration': 10}):
            self.assertEqual((await env['save_progress'](request(data)))[1], 400)
        self.assertEqual((await env['save_progress'](request({'file_id': 'missing', 'position': 5, 'duration': 100})))[1], 404)
        await env['save_progress'](request({'file_id': 'a', 'position': 20, 'duration': 100, 'name': 'untrusted'}))
        await env['save_progress'](request({'file_id': 'a', 'position': 30, 'duration': 100}))
        item = db.docs[1]['items'][0]
        self.assertEqual((len(db.docs[1]['items']), item['position'], item['name']), (1, 30, 'Name a'))
        result = await env['save_progress'](request({'file_id': 'a', 'position': 96, 'duration': 100}))
        self.assertTrue(result[0]['completed'])
        self.assertEqual(db.docs[1]['items'], [])

    def test_shared_player_and_continue_section_use_safe_dom(self):
        src = (ROOT / 'web/web_assets.py').read_text()
        for fragment in ('Continue Watching', 'window.removePlaybackProgress', 'v.onloadedmetadata',
                         'progressQueue.then', "video.addEventListener('ended'", 'name.textContent=item.name',
                         'window.play(item.file_id,item.name', "window.addEventListener('pagehide'"):
            self.assertIn(fragment, src)
        self.assertIn('progress_routes as _progress_routes', (ROOT / 'web/__init__.py').read_text())


@unittest.skipUnless(shutil.which('node'), 'Node is required')
class PlayerProgressRuntimeTests(unittest.TestCase):
    def test_resume_save_completion_and_switching(self):
        tree = ast.parse((ROOT / 'web/web_assets.py').read_text())
        assign = next(n for n in tree.body if isinstance(n, ast.Assign) and
                      any(isinstance(t, ast.Name) and t.id == 'PLAYER_JS' for t in n.targets))
        js = ast.literal_eval(assign.value).replace('<script>', '').replace('</script>', '')
        script = r'''
const assert=require('assert');let calls=[],saved={a:{position:42,duration:100}},listeners={};
function element(){return {classList:{add(){},remove(){}},removeAttribute(){},replaceChildren(){},appendChild(){},setAttribute(){},addEventListener(){},hidden:false,textContent:''}}
const v=element();Object.assign(v,{currentTime:0,duration:100,paused:false,addEventListener:(n,f)=>listeners[n]=f,
 pause(){this.paused=true; if(listeners.pause)listeners.pause()},load(){},play(){this.paused=false;return Promise.resolve()}});
const els={'#player':v,'#modal':element(),'#pChoices':element(),'#pChoicesList':element(),'#pTitle':element(),'#pNote':element(),'#pDl':element()};
global.document={querySelector:s=>els[s],createElement:element,dispatchEvent(){},addEventListener(){}};
global.window={addEventListener(){}};global.Event=class{};global.location={origin:'https://example.com'};global.navigator={};
const guest=process.argv[1]==='guest',stream='/download/42?e=123&s=abc';
if(guest){delete els['#modal'];v.src=stream;els['#pReturn']=Object.assign(element(),{href:'https://t.me/ExampleBot'});els['#signedPlayer']={dataset:{account:'0',fileId:'abc',name:'Film',stream,poster:''}};
 Object.assign(location,{pathname:'/watch/42',search:'?e=123&s=abc',assign(url){this.href=url}})}
global.fetch=async(url,opt={})=>{
 calls.push({url,opt});
 if(url.startsWith('/api/progress?') && !opt.method){const fid=decodeURIComponent(url.split('=')[1]);return {ok:true,json:async()=>({item:saved[fid]||null})}}
 if(url==='/api/progress'){const d=JSON.parse(opt.body);if(d.position>=d.duration*.95)delete saved[d.file_id];else if(d.position>=5)saved[d.file_id]=d;return {ok:true}}
 if(url.startsWith('/api/progress?') && opt.method==='DELETE'){delete saved[decodeURIComponent(url.split('=')[1])];return {ok:true}}
 if(url.startsWith('/api/player/group'))return {ok:true,json:async()=>({items:[]})};
 if(url==='/api/stream')return {ok:true,json:async()=>({stream:'/video',watch:'/watch',download:'/download'})};
 throw Error(url);
};
''' + js + r'''
(async()=>{
 if(guest){
   await new Promise(r=>setTimeout(r,0));assert.equal(v.src,stream);assert.equal(els['#pDl'].href,stream);
   window.copyLink();assert.equal(els['#pNote'].textContent,'https://example.com/watch/42?e=123&s=abc');
   listeners.timeupdate();window.closePlayer();assert.equal(location.href,'https://t.me/ExampleBot');assert.deepEqual(calls,[]);return;
 }
 await window.play('a','A');v.onloadedmetadata();assert.equal(v.currentTime,42);
 v.currentTime=55;listeners.timeupdate();await new Promise(r=>setTimeout(r,0));assert.equal(saved.a.position,55);
 await window.play('b','B');v.currentTime=23;listeners.pause();await new Promise(r=>setTimeout(r,0));assert.equal(saved.b.position,23);assert.equal(saved.a.position,55);
 v.currentTime=99;listeners.ended();await new Promise(r=>setTimeout(r,0));assert.equal(saved.b,undefined);
 await window.removePlaybackProgress('a');assert.equal(saved.a,undefined);
 window.closePlayer();
})().catch(e=>{console.error(e);process.exitCode=1});
'''
        for mode in ('search', 'guest'):
            with self.subTest(mode=mode):
                result = subprocess.run(['node', '-e', script, mode], capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)


class MongoPipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_pipeline_with_real_expression_interpreter_when_available(self):
        try:
            import mongomock
        except ImportError:
            self.skipTest('optional mongomock not installed')
        env, _, auth = handlers()
        col = mongomock.MongoClient().db.progress
        env['_collection'] = lambda: col
        env['get_file_details'] = AsyncMock(return_value={'file_name': '$Special'})
        for fid in ('a', '$b', 'a'):
            data, status, _ = await env['save_progress'](request({'file_id': fid, 'position': 25, 'duration': 100}))
            self.assertEqual(status, 200, data)
        items = col.find_one({'_id': 1})['items']
        self.assertEqual([x['file_id'] for x in items], ['a', '$b'])
        self.assertEqual(items[0]['name'], '$Special')
