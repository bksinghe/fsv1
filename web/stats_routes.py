"""📊 Database Stats — a stats page modelled on JoneySin/v5's `web/stats_routes.py`.

* Like v5, an admin-only "Database Stats" link in the sidebar and counters in cards.
* The "🆕 Recently Added — N files" count that used to appear in the `/search`
  meta line is now shown here on "Database Stats" (the same `get_recent_files()`
  total — not a new or different count).
* fsv1's PyMongo (sync) helpers run via `asyncio.to_thread()` so the bot's
  event loop is never blocked.
* Every number comes from `database.stats_db.snapshot()` — the same call the
  bot's `/stats` command uses, so this page and that command always agree.
"""

import logging
from html import escape

from aiohttp import web

from info import PORT
from database.stats_db import snapshot, uptime, web_numbers
from web.admin_ui import ADMIN_CSS, ADMIN_CONFIRM_JS, admin_header
from web.web_assets import get_auth, app_page

logger = logging.getLogger(__name__)
stats_routes = web.RouteTableDef()


# Count-up animation like v5's stats JS
_STATS_JS = """<script>
(function(){
  function countUp(el, target, duration){
    var start=performance.now();
    requestAnimationFrame(function step(now){
      var p=Math.min((now-start)/duration,1);
      el.textContent=Math.floor((1-Math.pow(1-p,3))*target).toLocaleString('en-IN');
      if(p<1)requestAnimationFrame(step);
    });
  }
  if(window.matchMedia('(prefers-reduced-motion: reduce)').matches)return;
  document.querySelectorAll('#statsDashboard [data-count]').forEach(function(el){
    countUp(el, parseFloat(el.dataset.count), 360);
  });
})();
</script>"""


# The scan endpoints remain admin-only; the page only supplies controls and status.
_SCAN_JS = """<script>
(function(){
  var button=document.getElementById('statsGroupScan');
  var status=document.getElementById('statsGroupScanStatus');
  var timer=null, active=false, requestId=0;
  function message(text){status.textContent=text;}
  function schedule(){clearTimeout(timer);timer=setTimeout(check,3000);}
  async function json(url,options){
    var r=await fetch(url,options), data=await r.json();
    if(!r.ok||data.ok===false)throw new Error(data.error||('HTTP '+r.status));
    return data;
  }
  async function check(){
    var id=++requestId;
    try{
      var s=await json('/api/group/scan_status',{credentials:'same-origin',cache:'no-store'});
      if(id!==requestId)return;
      active=!!s.running;button.disabled=active;
      if(active){message('⏳ '+(s.phase||'Scanning')+' ('+(s.scanned||0)+' / '+(s.total||0)+')');schedule();}
      else if(s.error)message('⚠️ Scan failed: '+s.error);
      else if(s.finished)message('✅ Scan complete: '+(s.created||0)+' new groups, '+(s.added||0)+' files added. Refresh the page to update counts.');
      else message('Scan the library to build or update permanent groups.');
    }catch(e){
      if(id!==requestId)return;
      message('⚠️ Could not check scan status. Retrying…');
      button.disabled=active;schedule();
    }
  }
  button.addEventListener('click',async function(){
    if(button.disabled)return;
    if(!await confirmAdminAction('Build permanent groups?', 'Scan the whole library to build or update groups. This can take a few minutes.', 'Start scan') || button.disabled)return;
    ++requestId;button.disabled=true;clearTimeout(timer);message('⏳ Starting scan…');
    try{
      await json('/api/group/scan_all',{method:'POST',credentials:'same-origin'});
      active=true;await check();
    }catch(e){button.disabled=false;message('⚠️ Could not start scan: '+e.message);schedule();}
  });
  check();
})();
</script>"""


async def _stats_numbers():
    """The page and /api/db_stats read the shared counter snapshot"""
    return web_numbers(await snapshot())


@stats_routes.get("/stats")
async def stats_page(req):
    role, tg_id = await get_auth(req)
    if not role:
        return web.HTTPFound("/login")
    # In v5 the "Database Stats" tab is visible only to admins
    if role != "admin":
        return web.HTTPFound("/search")

    s = await _stats_numbers()

    def metric(label, value, detail):
        number = (f'<span data-count="{value}">{value:,}</span>' if isinstance(value, int)
                  else escape(str(value)))
        return (f'<article class="metric"><h3>{escape(label)}</h3><strong>{number}</strong>'
                f'<p>{escape(detail)}</p></article>')

    def section(label, rows):
        return (f'<section><h2 class="admin-section-title">{escape(label)}</h2><div class="metrics">'
                + ''.join(metric(*row) for row in rows) + '</div></section>')

    queue = s['thumb_queue']
    library = section('Library inventory', [
        ('Indexed files', s['total_files'], 'Media in the active library'),
        ('Saved posters', s['thumbnails'], 'Files with a Telegram poster reference'),
        ('Content posts', s['posts'], 'Published catalog entries'),
        ('Directory profiles', s['actors'], 'Actors, apps and websites'),
    ])
    accounts = section('Accounts', [
        ('Web accounts', s['web_accounts'], 'Registered email logins'),
        ('Bot users', s['bot_users'], 'Active database records'),
        ('Premium users', s['premium_users'], 'Active premium plans'),
    ])
    operations = section('Library operations', [
        ('Permanent groups', s['groups'], f"{s['quality_groups']:,} quality groups · {s['episode_groups']:,} series · {s['episodes_total']:,} episodes"),
        ('Poster warmup queue', queue['queued'], f"{queue.get('ok', 0):,} verified · {queue.get('meta', 0):,} metadata saved · {queue.get('rejected', 0):,} rejected · {queue.get('no_thumb', 0):,} without posters"),
        ('Server uptime', uptime(short=True), f'Worker operational · Port {PORT}'),
    ])
    header = admin_header('Database Stats', 'A snapshot of your media library, accounts and background jobs.', 'stats')
    body = ADMIN_CSS + f'''<style>
#statsDashboard{{max-width:64rem;margin:2rem auto;padding:0 1rem 2rem}}
.stats-recent,.scan-tools{{display:flex;align-items:center;gap:14px;padding:16px 18px;background:var(--card);border:1px solid var(--line);border-radius:12px;margin-top:14px}}
.stats-recent strong{{font-size:clamp(25px,4vw,36px);letter-spacing:-.04em;font-variant-numeric:tabular-nums}}.stats-recent span,.scan-status,.metric p{{color:var(--mut);font-size:13px;line-height:1.45}}.stats-recent a{{margin-left:auto;white-space:nowrap}}
.metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,185px),1fr));gap:10px}}.metric{{padding:17px;border:1px solid var(--line);border-radius:12px;background:var(--card);min-width:0;overflow-wrap:anywhere}}.metric h3{{font-size:13px;color:var(--mut);font-weight:700}}.metric strong{{display:block;font-size:clamp(23px,3vw,30px);font-variant-numeric:tabular-nums;letter-spacing:-.04em;margin:7px 0 5px}}.metric p{{font-size:12px}}
.scan-tools{{flex-wrap:wrap}}.scan-tools>div{{flex:1 1 14rem}}.scan-tools h3{{font-size:16px;margin-bottom:4px}}.scan-button{{background:var(--red);border:none;color:white;border-radius:9px;padding:11px 16px;font:inherit;font-size:13px;font-weight:750;cursor:pointer}}.scan-button:disabled{{opacity:.55;cursor:wait}}#statsDashboard :focus-visible{{outline:2px solid var(--red);outline-offset:2px}}
@media(max-width:520px){{.metrics{{grid-template-columns:repeat(2,minmax(0,1fr))}}.metric{{padding:13px}}.metric:last-child:nth-child(odd){{grid-column:1/-1}}.stats-recent{{flex-wrap:wrap}}}}
</style><main id="statsDashboard">{header}
  <div class="stats-recent"><strong data-count="{s['recent_files']}">{s['recent_files']:,}</strong><span>Recently added files</span><a class="tbtn" href="/search">View library →</a></div>
  {library}{accounts}{operations}
  <section class="scan-tools" aria-label="Group scan"><div><h3>Group scan</h3><p id="statsGroupScanStatus" class="scan-status" role="status" aria-live="polite">Checking scan status…</p></div>
    <button id="statsGroupScan" class="scan-button" type="button" disabled>⚙️ Scan &amp; Build Groups</button></section>
</main>{ADMIN_CONFIRM_JS}{_STATS_JS}{_SCAN_JS}'''

    return app_page(
        "Database Stats - Fast Finder", body,
        tg_id=tg_id, role=role, active_tab="stats",
    )


@stats_routes.get("/api/db_stats")
async def api_db_stats(req):
    """JSON counters — a lightweight endpoint like v5's /api/db_stats."""
    role, _ = await get_auth(req)
    if not role:
        return web.json_response({"error": "Login required", "login": "/login"}, status=401)
    if role != "admin":
        return web.json_response({"error": "Admins only"}, status=403)
    return web.json_response(await _stats_numbers())
