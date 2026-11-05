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

from aiohttp import web

from info import PORT
from database.stats_db import snapshot, uptime, web_numbers
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
  document.querySelectorAll('[data-count]').forEach(function(el){
    countUp(el, parseFloat(el.dataset.count), 360);
  });
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

    body = f'''<style>
#statsDashboard{{max-width:1160px;margin:0 auto;padding:26px 4% 40px}}
#statsDashboard .stat-title{{font-size:26px;letter-spacing:-.6px}}
#statsDashboard .stat-lead{{margin-bottom:18px}}
#statsDashboard .stat-hero{{display:grid;grid-template-columns:1fr auto;align-items:center;padding:20px 24px;border-radius:14px;background:linear-gradient(115deg,var(--card),var(--bg3));}}
#statsDashboard .stat-hero::before{{width:4px;height:auto;bottom:0;right:auto;background:var(--red)}}
#statsDashboard .stat-hero-label{{margin:0 0 5px}}
#statsDashboard .stat-hero-num{{font-size:40px}}
#statsDashboard .stat-hero-sub{{grid-column:1/-1;margin-top:12px;padding-top:10px;border-top:1px solid var(--line)}}
#statsDashboard .stat-grid{{grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}}
#statsDashboard .st-card{{padding:15px;border-radius:11px;background:linear-gradient(150deg,var(--card),color-mix(in srgb,var(--card) 88%,var(--bg3)));}}
#statsDashboard .st-card:nth-child(7){{grid-column:span 2;border-color:rgba(229,9,20,.28);background:linear-gradient(120deg,var(--card),rgba(229,9,20,.07))}}
#statsDashboard .st-card:nth-child(7) .st-sub{{font-size:11px}}
#statsDashboard .st-label{{font-size:9px;letter-spacing:.65px}}
#statsDashboard .st-val{{font-size:28px;margin-bottom:5px}}
#statsDashboard .st-sub{{font-size:10px;line-height:1.4}}
@media(max-width:850px){{#statsDashboard .stat-grid{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}
@media(max-width:520px){{#statsDashboard{{padding:18px 4% 28px}}#statsDashboard .stat-hero{{padding:17px}}#statsDashboard .stat-hero-num{{font-size:34px}}#statsDashboard .st-card:nth-child(7){{grid-column:span 2}}}}
@media(prefers-reduced-motion:reduce){{#statsDashboard .anim-card{{animation:none}}}}
</style><div id="statsDashboard" class="main">
  <div class="stat-title anim-card">📊 Database Stats</div>
  <div class="stat-lead anim-card">A quick overview of your files, users and library activity.</div>

  <div class="stat-hero anim-card">
    <div class="stat-hero-label">🆕 Recently Added Files</div>
    <div class="stat-hero-num" data-count="{s['recent_files']}" data-delay="0">{s['recent_files']:,}</div>
    <div class="stat-hero-sub">Total files in the "Recently Added" grid for an empty search · <a href="/search" style="color:var(--red)">Home / Search →</a></div>
  </div>

  <div class="stat-grid">
    <div class="st-card anim-card"><div class="st-bar" style="background:#3399ff"></div>
      <div class="st-label">Total Files in Database</div>
      <div class="st-val" style="color:#3399ff" data-count="{s['total_files']}" data-delay="100">{s['total_files']:,}</div>
      <div class="st-sub">Indexed media documents</div></div>

    <div class="st-card anim-card"><div class="st-bar" style="background:#9933ff"></div>
      <div class="st-label">🖼️ Poster IDs saved</div>
      <div class="st-val" style="color:#9933ff" data-count="{s['thumbnails']}" data-delay="160">{s['thumbnails']:,}</div>
      <div class="st-sub">Files with a Telegram poster reference</div></div>

    <div class="st-card anim-card"><div class="st-bar" style="background:#00d2c4"></div>
      <div class="st-label">🌐 Web Accounts</div>
      <div class="st-val" style="color:#00d2c4" data-count="{s['web_accounts']}" data-delay="220">{s['web_accounts']:,}</div>
      <div class="st-sub">Registered email logins</div></div>

    <div class="st-card anim-card"><div class="st-bar" style="background:#ff9933"></div>
      <div class="st-label">🤖 Bot Users</div>
      <div class="st-val" style="color:#ff9933" data-count="{s['bot_users']}" data-delay="280">{s['bot_users']:,}</div>
      <div class="st-sub">Active database records</div></div>

    <div class="st-card anim-card"><div class="st-bar" style="background:var(--gold)"></div>
      <div class="st-label">💎 Premium Users</div>
      <div class="st-val" style="color:var(--gold)" data-count="{s['premium_users']}" data-delay="340">{s['premium_users']:,}</div>
      <div class="st-sub">Active premium plans</div></div>

    <div class="st-card anim-card"><div class="st-bar" style="background:#28a745"></div>
      <div class="st-label">🟢 Server Uptime</div>
      <div class="st-val" style="color:#28a745;font-size:22px">{uptime(short=True)}</div>
      <div class="st-sub">Port {PORT} · worker operational</div></div>

    <div class="st-card anim-card"><div class="st-bar" style="background:var(--red)"></div>
      <div class="st-label">⏳ Thumb Warmup Queue</div>
      <div class="st-val" style="color:var(--red)" data-count="{s['thumb_queue']['queued']}" data-delay="400">{s['thumb_queue']['queued']:,}</div>
      <div class="st-sub">posters <b>one at a time</b> · {s['thumb_queue'].get('ok', 0):,} verified · {s['thumb_queue'].get('meta', 0):,} meta saved · {s['thumb_queue'].get('rejected', 0):,} fake rejected · {s['thumb_queue'].get('no_thumb', 0):,} NO_THUMB</div></div>

    <div class="st-card anim-card"><div class="st-bar" style="background:#e50914"></div>
      <div class="st-label">📝 Content Posts</div>
      <div class="st-val" style="color:#e50914" data-count="{s['posts']}" data-delay="440">{s['posts']:,}</div>
      <div class="st-sub">Published catalog entries</div></div>

    <div class="st-card anim-card"><div class="st-bar" style="background:#00d2c4"></div>
      <div class="st-label">🎭 Directory Profiles</div>
      <div class="st-val" style="color:#00d2c4" data-count="{s['actors']}" data-delay="480">{s['actors']:,}</div>
      <div class="st-sub">Actors · Apps · Websites</div></div>

    <div class="st-card anim-card"><div class="st-bar" style="background:#7dd3fc"></div>
      <div class="st-label">🗂️ Permanent Groups</div>
      <div class="st-val" style="color:#7dd3fc" data-count="{s['groups']}" data-delay="520">{s['groups']:,}</div>
      <div class="st-sub">🎞️ {s['quality_groups']:,} quality groups · 📺 {s['episode_groups']:,} series groups ({s['episodes_total']:,} episodes) — every group has its own id / #number</div></div>
  </div>
</div>{_STATS_JS}'''

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
