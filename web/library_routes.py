"""Private web library: all owner IDs come from the authenticated session."""

import asyncio
from datetime import datetime, timedelta, timezone
from html import escape
from urllib.parse import urlencode

from aiohttp import web
from database import personal_library as library
from database.ia_filterdb import collection, get_file_details
from web.web_assets import (
    app_page,
    get_auth,
    filter_select,
    PLAYER_MODAL_HTML,
    PLAYER_JS,
)
from web.library_ui import LIBRARY_JS, LIBRARY_CSS

routes = web.RouteTableDef()
IST = timezone(timedelta(hours=5, minutes=30))


async def user(req):
    role, uid = await get_auth(req)
    if not role:
        raise web.HTTPUnauthorized(text="Sign in required")
    return role, uid


def json(data):
    return web.json_response(data, headers={"Cache-Control": "private, no-store"})


@routes.get("/api/playlists")
async def list_names(req):
    _, uid = await user(req)
    doc = await library.read(uid, "playlists")
    return json({"lists": [{"id": p["id"], "name": p["name"]} for p in doc["lists"]]})


@routes.post("/api/library/{kind:playlists|history}")
async def mutate(req):
    _, uid = await user(req)
    if req.content_type != "application/json":
        raise web.HTTPUnsupportedMediaType()
    try:
        data = await req.json()
        if not isinstance(data, dict):
            raise ValueError("Invalid request.")

        def field(k, limit):
            v = data.get(k, "")
            if not isinstance(v, str) or len(v) > limit:
                raise ValueError("Invalid " + k)
            return v.strip()

        action, fid = field("action", 12), field("file_id", 512)
        if req.match_info["kind"] == "history":
            if action not in ("clear", "pause", "unpause", "remove"):
                raise ValueError("Invalid history action.")
            await library.edit_history(uid, action, fid)
            return json({"ok": True})
        if action == "add" or (action == "create" and fid):
            if not fid or not await get_file_details(fid):
                raise web.HTTPNotFound(text="File unavailable")
        key = await library.edit_playlist(
            uid, action, field("list", 40), fid, field("name", 80)
        )
        return json({"ok": True, "id": key})
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)


def button(label, action):
    return f'<button class="tbtn" type="button" data-act="{action}">{label}</button>'


def clock(sec):
    mins, s = divmod(int(sec), 60)
    return f"{mins}:{s:02}"


@routes.get("/playlists")
@routes.get("/watch-history")
async def personal_page(req):
    role, uid = await get_auth(req)
    if not role:
        raise web.HTTPFound("/login")
    hist = req.path == "/watch-history"
    kind = "history" if hist else "playlists"
    doc = await library.read(uid, kind)
    title = "Watch History" if hist else "My Playlists"
    pid = req.query.get("list", "later")
    query = req.query.get("q", "").strip()[:120]
    try:
        page = max(0, int(req.query.get("page", 0)))
    except ValueError:
        raise web.HTTPBadRequest(text="Invalid page")
    if hist:
        entries = {x["file_id"]: x for x in doc["items"]}
        ids = list(entries)
        last = ""
        toolbar = button(
            "Resume history" if doc["paused"] else "Pause history",
            "unpause" if doc["paused"] else "pause",
        ) + button("Clear history", "clear")
        if doc["paused"]:
            toolbar += "<strong>Recording paused</strong>"
    else:
        lists = doc["lists"]
        p = next((x for x in lists if x["id"] == pid), None)
        if not p:
            raise web.HTTPNotFound(text="Playlist unavailable")
        ids = p["files"]
        last = p["last"]
        toolbar = (
            "<nav>"
            + "".join(
                f'<a class="tbtn" href="?list={x["id"]}" aria-current="{str(x == p).lower()}">{escape(x["name"])}</a>'
                for x in lists
            )
            + "</nav>"
        )
        toolbar += (
            button("＋ New playlist", "create")
            + button("Rename", "rename")
            + (button("Delete playlist", "delete") if pid != "later" else "")
        )

    def visible():
        return {
            x["_id"]: x.get("file_name") or "Video"
            for x in collection.find({"_id": {"$in": ids}}, {"file_name": 1})
        }

    names = await asyncio.to_thread(visible)
    visible_ids = [f for f in ids if f in names]
    matches = [f for f in visible_ids if query.casefold() in names[f].casefold()]
    page = min(page, max(0, (len(matches) - 1) // 21))

    def url(n):
        return "?" + escape(urlencode({"list": pid, "q": query, "page": n}))

    cards = []
    today = datetime.now(IST).date()
    prev_day = None
    for fid in matches[page * 21 : (page + 1) * 21]:
        if hist:
            x = entries[fid]
            t = datetime.fromtimestamp(x["updated_at"], IST)
            day = t.date()
            if day != prev_day:
                heading = (
                    "Today"
                    if day == today
                    else "Yesterday"
                    if day == today - timedelta(days=1)
                    else day.strftime("%d %b %Y")
                )
                cards.append(f'<h2 class="lib-day">{heading}</h2>')
                prev_day = day
            meta = (
                t.strftime("%I:%M %p IST")
                + " · "
                + (
                    "✓ Watched"
                    if x["position"] >= 0.95 * x["duration"]
                    else clock(x["position"]) + " / " + clock(x["duration"])
                )
            )
            actions = button("＋ Playlist", "save")
        else:
            meta = "Video " + str(visible_ids.index(fid) + 1)
            actions = button("↑ Move up", "up") + button("↓ Move down", "down")
        poster = "/api/thumb?" + escape(urlencode({"file_id": fid}))
        cards.append(
            f'<article class="vm-card" data-file="{escape(fid)}"><img alt="" class="vm-img" loading="lazy" data-src="{poster}" onerror="this.hidden=true">'
            f'<button class="lib-name" data-act="play">▶ {escape(names[fid])}</button><small>{meta}</small><div>{actions}{button("Remove", "remove")}</div></article>'
        )
    paging = (
        (f'<a href="{url(page - 1)}">← Previous</a>' if page else "")
        + f" <span>Page {page + 1}</span> "
        + (
            f'<a href="{url(page + 1)}">Next →</a>'
            if (page + 1) * 21 < len(matches)
            else ""
        )
    )
    mode = filter_select(
        "libMode", options="view", cap="View mode", label="View mode", vm=True
    )
    controls = (
        button("▶ Continue playlist", "continue") if not hist and visible_ids else ""
    )
    # Hidden options carry the full ordered queue (also across page boundaries); no stream URLs.
    resume = (
        {
            f: (0 if x["position"] >= 0.95 * x["duration"] else x["position"])
            for f, x in entries.items()
        }
        if hist
        else {}
    )
    last = last if last in names else ""
    queue = "".join(
        f'<option data-resume="{resume.get(f, "")}" value="{escape(f)}">{escape(names[f])}</option>'
        for f in visible_ids
    )
    items = "".join(cards) or (
        "<p>No videos match this search.</p>" if query else "<p>No videos here yet.</p>"
    )
    if req.headers.get("Accept") == "application/json":
        return json({"items": items, "navigation": paging, "queue": queue})
    body = (
        LIBRARY_CSS
        + f'<main class="library" data-kind="{kind}" data-list="{escape(pid)}" data-last="{escape(last)}"><h1>{title}</h1><div>{toolbar}</div>'
        f'<form role="search"><input type="hidden" name="list" value="{escape(pid)}"><input type="search" name="q" value="{escape(query)}" placeholder="Search by filename" aria-label="Search by filename" maxlength="120">{mode}</form>{controls}'
        f'<select hidden id="libQueue">{queue}</select><section class="vgrid vm-grid mode-text">'
        f'{items}</section><nav id="libPaging">{paging}</nav><p role="status"></p></main>'
        + PLAYER_MODAL_HTML
        + PLAYER_JS
        + LIBRARY_JS
    )
    resp = app_page(title, body, uid, role, kind)
    resp.headers["Cache-Control"] = "private, no-store"
    return resp
