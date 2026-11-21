"""Admin stats scan controls, progress, and per-worker scan reservation."""
import ast
import asyncio
import runpy
import shutil
import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

ROOT = Path(__file__).resolve().parents[1]
STATS = (ROOT / 'web/stats_routes.py').read_text()
GROUP = (ROOT / 'web/group_routes.py').read_text()


def node_for(source, name):
    return next(n for n in ast.parse(source).body if getattr(n, 'name', None) == name)


class StatsScanRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_stats_page_admin_only_and_has_scan_controls(self):
        fn = node_for(STATS, 'stats_page'); fn.decorator_list = []
        counts = dict.fromkeys(('recent_files','total_files','thumbnails','web_accounts','bot_users','premium_users','posts','actors','groups','quality_groups','episode_groups','episodes_total'), 0)
        counts['thumb_queue'] = {'queued': 0}
        auth = AsyncMock(return_value=(None,None))
        ui = runpy.run_path(str(ROOT / "web/admin_ui.py"))
        ns = {'get_auth':auth, 'web':SimpleNamespace(HTTPFound=lambda x:x), '_stats_numbers':AsyncMock(return_value=counts),
              **{k:ui[k] for k in ('admin_header','ADMIN_CSS','ADMIN_CONFIRM_JS','escape')}, 'uptime':lambda **kwargs:'now', 'PORT':80, '_STATS_JS':'', '_SCAN_JS':'scan-js', 'app_page':lambda title,body,**kw:body}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), '<stats>', 'exec'),ns)
        self.assertEqual(await ns['stats_page'](None),'/login')
        auth.return_value=('user',1);self.assertEqual(await ns['stats_page'](None),'/search')
        ns['_stats_numbers'].assert_not_awaited()
        auth.return_value=('admin',1);body=await ns['stats_page'](None)
        self.assertEqual(body.count('<article class="metric">'), 10)
        self.assertIn('<h1>Database Stats</h1>',body)
        self.assertIn('⚙️ Scan &amp; Build Groups',body)
        self.assertIn('id="statsGroupScan"',body)
        self.assertIn('aria-live="polite"',body)
        self.assertIn('scan-js',body)

    async def test_scan_reservation_prevents_duplicate_start_before_task_runs(self):
        fn=node_for(GROUP,'api_group_scan_all'); fn.decorator_list=[]
        async def scan(): pass
        tasks=[]
        def create_task(coro): tasks.append(coro)
        state={'running':False}
        ns={'_admin':AsyncMock(return_value=True),'_denied':lambda:'denied','_json':lambda x:x,
            'SCAN_STATE':state,'asyncio':SimpleNamespace(create_task=create_task),'_scan_all_groups':scan}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<groups>','exec'),ns)
        try:
            self.assertTrue((await ns['api_group_scan_all'](None))['started'])
            self.assertFalse((await ns['api_group_scan_all'](None))['started'])
            self.assertEqual(len(tasks),1)
            ns['_admin'].return_value=False
            self.assertEqual(await ns['api_group_scan_all'](None),'denied')
        finally:
            for coro in tasks: coro.close()


@unittest.skipUnless(shutil.which('node'),'Node required')
class StatsScanJavascriptTests(unittest.TestCase):
    def test_scan_confirm_progress_completion_and_errors(self):
        tree=ast.parse(STATS)
        node=next(n for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='_SCAN_JS' for t in n.targets))
        code=ast.literal_eval(node.value).replace('<script>','').replace('</script>','')
        js=r'''
const assert=require('assert'); let handler, confirms=false, timers=[], requests=[];
const button={disabled:true,addEventListener:(event,fn)=>handler=fn},status={textContent:''};
const document={getElementById:id=>id==='statsGroupScan'?button:status};
const confirmAdminAction=async()=>confirms;
const setTimeout=fn=>{timers.push(fn);return timers.length},clearTimeout=()=>{};
let replies=[];const fetch=(url,options)=>{requests.push({url,options});return Promise.resolve(replies.shift())};
const response=data=>({ok:true,json:async()=>data});
const flush=()=>new Promise(r=>setImmediate(r));
replies.push(response({ok:true,running:false}));
''' + code + r'''
(async()=>{
 await flush();assert(!button.disabled);assert(status.textContent.includes('Scan the library'));
 await handler();assert.equal(requests.length,1); // cancelled confirmation
 confirms=true;replies.push(response({ok:true,started:true}),response({ok:true,running:true,phase:'Scanning',scanned:4,total:10}));
 await handler();assert(button.disabled);assert(status.textContent.includes('4 / 10'));assert.equal(requests[1].options.method,'POST');
 replies.push(response({ok:true,running:false,finished:1,created:2,added:3}));timers.pop()();await flush();
 assert(!button.disabled);assert(status.textContent.includes('2 new groups'));assert(status.textContent.includes('3 files'));
 replies.push({ok:false,status:403,json:async()=>({error:'Admins only'})});await handler();
 assert(!button.disabled);assert(status.textContent.includes('Admins only'));
})().catch(e=>{console.error(e);process.exitCode=1});
'''
        result=subprocess.run(['node','-e',js],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
