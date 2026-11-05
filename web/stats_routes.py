"""📊 Database Stats — a stats page modelled on JoneySin/v5's `web/stats_routes.py`.

* Like v5, an admin-only "Database Stats" link in the sidebar and counters in cards.
* The "🆕 Recently Added — N files" count that used to appear in the `/search`
  meta line is now shown here on "Database Stats" (the same `get_recent_files()`
  total — not a new or different count).
* fsv1's PyMongo (sync) helpers run via `asyncio.to_thread()` so the bot's
  event loop is never blocked.
"""

import asyncio
import logging
import time

from aiohttp import web

from info import PORT
from utils import temp
from database.ia_filterdb import db_count_documents, get_recent_files, collection
from database.users_chats_db import db as user_db, web_db
from database.catalog_db import store as catalog_store
from database.group_db import store as group_store
from web.web_assets import get_auth, app_page
from web.thumb_engine import thumb_queue_state

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


async def _safe(awaitable, default):
    """A single failing DB counter must not take down the whole page (v5-style fail-safe)."""
    try:
        return await awaitable
    except Exception as e:
        logger.debug(f"Stats counter skipped: {e}")
        return default


def _count(coll, query=None) -> int:
    if coll is None:
        return 0
    return coll.count_documents(query or {})


async def _stats_numbers():
    """Read independent counters concurrently so the page waits for the slowest query only."""
    (total_files, recent_result, bot_users, premium_users, web_accounts,
     thumbnails, catalog, groups, gkinds) = await asyncio.gather(
        _safe(asyncio.to_thread(db_count_documents), 0),
        _safe(get_recent_files(0, 1), ([], "", 0)),
        _safe(user_db.total_users_count(), 0),
        _safe(user_db.get_premium_users(), []),
        _safe(asyncio.to_thread(_count, web_db.col), 0),
        _safe(asyncio.to_thread(_count, collection, {"thumb_url": {"$exists": True}}), 0),
        _safe(catalog_store.counts(), {"posts": 0, "actors": 0}),
        _safe(group_store.count(), 0),
        _safe(group_store.kind_counts(),
              {"quality_groups": 0, "episode_groups": 0, "episodes_total": 0}),
    )
    recent_files = recent_result[2] or total_files
    queue = thumb_queue_state()
    return {
        "total_files": total_files, "recent_files": recent_files,
        "bot_users": bot_users, "premium_users": len(premium_users),
        "web_accounts": web_accounts, "thumbnails": thumbnails,
        "thumb_queue": queue, "posts": catalog.get("posts", 0),
        "actors": catalog.get("actors", 0), "groups": groups,
        "quality_groups": gkinds.get("quality_groups", 0),
        "episode_groups": gkinds.get("episode_groups", 0),
        "episodes_total": gkinds.get("episodes_total", 0),
    }


def _uptime() -> str:
    started = getattr(temp, "START_TIME", 0) or 0
    if not started:
        return "Starting…"
    secs = max(0, int(time.time() - started))
    d, rem = divmod(secs, 86400)
    h, rem = divmod(rem, 3600)
    m, _ = divmod(rem, 60)
    return f"{d}d {h}h {m}m" if d else f"{h}h {m}m"


@stats_routes.get("/stats")
async def stats_page(req):
    role, tg_id = await get_auth(req)
    if not role:
        return web.HTTPFound("/login")
    # In v5 the "Database Stats" tab is visible only to admins
    if role != "admin":
        return web.HTTPFound("/search")

    s = await _stats_numbers()

    body = f'''<div class="main" style="padding-top:24px;">
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
      <div class="st-label">🖼️ Cached Thumbnails</div>
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
      <div class="st-val" style="color:#28a745;font-size:22px">{_uptime()}</div>
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
