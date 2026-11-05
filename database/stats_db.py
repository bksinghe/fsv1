"""📊 ONE PLACE THAT COUNTS EVERYTHING

The web "Database Stats" page (`web/stats_routes.py` → `/stats` and
`/api/db_stats`) and the bot's `/stats` command (`plugins/admin_tools.py`)
used to count the same things in two different places. Both now call
`snapshot()`, so the two screens can never disagree.

Every counter is independent: one failing query never takes the report down.
"""

import asyncio
import time
from datetime import datetime

from info import PORT, URL
from utils import temp, get_size, get_readable_time, fmt
from database.ia_filterdb import db_count_documents, get_recent_files, collection
from database.users_chats_db import db as user_db, web_db
from database.catalog_db import store as catalog_store
from database.group_db import store as group_store


EMPTY_QUEUE = {
    "queued": 0, "done": 0, "ok": 0, "no_thumb": 0,
    "failed": 0, "rejected": 0, "meta": 0,
}


async def _safe(awaitable, default):
    """A single failing counter must not take the whole report down"""
    try:
        return await awaitable
    except Exception as e:
        print(f"Stats counter skipped: {e}")
        return default


def _count(coll, query=None):
    """count_documents() that tolerates a collection that is not connected"""
    if coll is None:
        return 0
    return coll.count_documents(query or {})


def uptime(short=False):
    """Bot uptime — `short` is the compact form the web card uses"""
    started = getattr(temp, "START_TIME", 0) or 0
    if not started:
        return "N/A"

    secs = max(0, int(time.time() - started))
    if short:
        d, rem = divmod(secs, 86400)
        h, rem = divmod(rem, 3600)
        m, _ = divmod(rem, 60)
        return f"{d}d {h}h {m}m" if d else f"{h}h {m}m"
    return get_readable_time(secs)


def web_status():
    """(state, uptime) of the aiohttp site started in bot.py"""
    started = getattr(temp, "WEB_START", 0) or 0
    if not started:
        return "🔴 Not running", "N/A"
    return "🟢 Running", get_readable_time(time.time() - started)


def thumb_queue():
    """🖼️ poster warmup queue (owned by web/thumb_engine.py)"""
    try:
        from web.thumb_engine import thumb_queue_state
        return thumb_queue_state()
    except Exception:
        return dict(EMPTY_QUEUE)


async def snapshot():
    """Every counter, read concurrently — the report waits for the slowest query only."""
    (total_files, recent_result, bot_users, premium_users, chats,
     web_accounts, web_sessions, thumbnails, catalog, groups, gkinds,
     dbstats) = await asyncio.gather(
        _safe(asyncio.to_thread(db_count_documents), 0),
        _safe(get_recent_files(0, 1), ([], "", 0)),
        _safe(user_db.total_users_count(), 0),
        _safe(asyncio.to_thread(_count, user_db.premium, {"plan.premium": True}), 0),
        _safe(asyncio.to_thread(_count, user_db.groups), 0),
        _safe(asyncio.to_thread(_count, web_db.col), 0),
        _safe(asyncio.to_thread(_count, web_db.sessions), 0),
        _safe(asyncio.to_thread(_count, collection, {"thumb_url": {"$exists": True}}), 0),
        _safe(catalog_store.counts(), {"posts": 0, "actors": 0}),
        _safe(group_store.count(), 0),
        _safe(group_store.kind_counts(),
              {"quality_groups": 0, "episode_groups": 0, "episodes_total": 0}),
        _safe(asyncio.to_thread(user_db.users.database.command, "dbstats"), {}),
    )

    web_state, web_uptime = web_status()

    return {
        # 🤖 bot
        "users": bot_users,
        "chats": chats,
        "files": total_files,
        "recent_files": recent_result[2] or total_files,
        "premium": premium_users,
        "db_size": get_size(dbstats.get("dataSize", 0)),
        "uptime": uptime(),
        "uptime_short": uptime(short=True),
        "now": fmt(datetime.now()),
        # 🌐 web
        "web_state": web_state,
        "web_uptime": web_uptime,
        "url": URL or "not set",
        "port": PORT,
        "web_accounts": web_accounts,
        "web_sessions": web_sessions,
        "live_sessions": len(getattr(temp, "USER_SESSIONS", {}) or {}),
        "posts": catalog.get("posts", 0),
        "actors": catalog.get("actors", 0),
        "groups": groups,
        "quality_groups": gkinds.get("quality_groups", 0),
        "episode_groups": gkinds.get("episode_groups", 0),
        "episodes_total": gkinds.get("episodes_total", 0),
        "thumbnails": thumbnails,
        "thumb_queue": thumb_queue(),
    }


def web_numbers(s):
    """The key names `web/stats_routes.py` (page + /api/db_stats) is built around"""
    return {
        "total_files": s["files"],
        "recent_files": s["recent_files"],
        "bot_users": s["users"],
        "premium_users": s["premium"],
        "web_accounts": s["web_accounts"],
        "thumbnails": s["thumbnails"],
        "thumb_queue": s["thumb_queue"],
        "posts": s["posts"],
        "actors": s["actors"],
        "groups": s["groups"],
        "quality_groups": s["quality_groups"],
        "episode_groups": s["episode_groups"],
        "episodes_total": s["episodes_total"],
    }
