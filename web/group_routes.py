"""🗂️ PERMANENT GROUP APIs + group-first search cards.

Rebuilt for fsv1 after **studying** v5 (`JoneySin/v5` → `web/search_api.py` +
`web/dashboard_routes.py`) — not a verbatim copy, no `COLLECTIONS`/primary/cloud/
archive/section, and fsv1 keeps its single collection, sync PyMongo and shared
`.vcard`/filter components.

Endpoints (all admin-only except reading a group poster):
  GET  /api/group/list?q=                group search (name / #number)
  POST /api/group/save                   new permanent group OR add files to an existing one
  POST /api/group/update                 change name / master thumbnail
  POST /api/group/remove_file            remove a file from a group (+ blacklist)
  POST /api/group/delete                 ungroup (files are not deleted)
  POST /api/group/merge                  source group → target group number
  POST /api/group/scan_all               scan the whole library → permanent groups
  GET  /api/group/scan_status            scan progress
  POST /api/group/upload_thumb           custom group poster (multipart)
  GET  /api/group/thumb?gid=             custom group poster bytes
"""

import asyncio
import logging
import re
import time
from collections import defaultdict

from aiohttp import web

import info as _info
from info import BIN_CHANNEL, THUMB_BROWSER_CACHE
from utils import temp
from database.group_db import (
    store, title_key, series_key, group_title, series_title, quality_label, episode_chips,
    episode_label, episode_identity, duration_seconds,
    detect_episodes, guess_kind, normal_kind,
    clean_episode_map, group_kind_meta, KIND_QUALITIES, KIND_EPISODES,
)
from web.web_assets import get_auth
from web.thumb_engine import get_image_bytes, image_content_type, thumb_version
from web.image_validate import is_image_magic

logger = logging.getLogger(__name__)
group_routes = web.RouteTableDef()

_STORAGE_CHANNEL = getattr(_info, "CATALOG_STORAGE_CHANNEL", BIN_CHANNEL)
_MAX_UPLOAD = 5 * 1024 * 1024
SCAN_MAX_GROUP = 30          # a larger quality bucket is a very common name — do not group it
SCAN_MAX_SERIES = 500        # series may contain many episodes but should still be bounded
SCAN_STATE = {"running": False}
_AUTO_GROUP_LOCK = asyncio.Lock()


def _json(data, status=200):
    return web.json_response(data, status=status)


async def _admin(req):
    role, _ = await get_auth(req)
    return role == "admin"


def _denied():
    return _json({"ok": False, "error": "Admins only"}, 403)


async def _body(req):
    try:
        data = await req.json()
        if not isinstance(data, dict):
            raise ValueError("expected object")
        return data, None
    except Exception:
        return None, _json({"ok": False, "error": "Bad JSON"}, 400)


def _fid(value) -> str:
    """User input → safe id. Same whitelist as `file_edit_routes._file_id()` —
    Telegram file_ids + fsv1 short ids; URL/control/markup chars reject."""
    fid = str(value or "").strip()
    return fid[:512] if re.fullmatch(r"[A-Za-z0-9_\-=]{1,512}", fid) else ""


def _items(data):
    """`items:[{id,name}]` → unique `(fid, name)` pairs. Raw dicts never reach the DB."""
    out, seen = [], set()
    for x in data.get("items") or []:
        if not isinstance(x, dict):
            continue
        fid = _fid(x.get("id") or x.get("file_id"))
        if fid and fid not in seen:
            seen.add(fid)
            out.append((fid, str(x.get("name") or "")[:300]))
    return out


def _group_public(g):
    g = g or {}
    return {
        "group_id": str(g.get("_id") or ""),
        "num": g.get("num", ""),
        "name": str(g.get("name") or ""),
        "count": len(g.get("members") or []),
        "members": [str(i) for i in (g.get("members") or [])],
        "files": [{"id": str(f.get("id") or ""), "name": str(f.get("name") or "")}
                  for f in (g.get("files") or [])],
        "auto_keys": list(g.get("auto_keys") or []),
        "excluded": [str(i) for i in (g.get("excluded") or [])],
        "thumb_fid": str(g.get("thumb_fid") or ""),
        "thumb_url": str(g.get("thumb_url") or ""),
        "auto_created": bool(g.get("auto_created")),
        # 🧮 `database/group_db.py` is the single source for type/episode counts
        **group_kind_meta(g),
        "updated_at": int(g.get("updated_at") or 0),
    }


def _group_thumb_url(g, variants):
    """Master thumbnail: custom upload > selected member > highest quality."""
    gid = str(g.get("_id") or "")
    ts = int(g.get("updated_at") or 0)
    custom = str(g.get("thumb_url") or "")
    if custom.startswith("TG_ID:"):
        return f"/api/group/thumb?gid={gid}&v={thumb_version(gid, custom)}"
    chosen = str(g.get("thumb_fid") or "")
    if chosen:
        return f"/api/thumb?file_id={chosen}&v={thumb_version(chosen, str(ts))}"
    for v in reversed(variants or []):
        if v.get("thumb"):
            return v["thumb"]
    return ""


async def _group_member_meta(g, cache, cards_by_id):
    """Member durations/names for safe auto-join checks; reuse visible search cards."""
    gid = str(g.get("_id") or "")
    if gid in cache:
        return cache[gid]
    members = [str(m) for m in (g.get("members") or [])]
    meta = {}
    for fid in members:
        card = cards_by_id.get(fid)
        if card:
            meta[fid] = {
                "file_name": str(card.get("name") or card.get("file_name") or ""),
                "duration_seconds": duration_seconds(card),
            }
    missing = [fid for fid in members if fid not in meta]
    if missing:
        for doc in await store.files_by_ids(missing):
            meta[str(doc.get("_id") or "")] = doc
    rows = [meta[fid] for fid in members if fid in meta]
    cache[gid] = rows
    return rows


async def _auto_join_compatible(g, card, meta_cache, cards_by_id):
    """Only series episodes or same-duration/same-episode quality files may auto-join."""
    incoming_name = card.get("name") or card.get("file_name") or ""
    incoming_episode = episode_identity(incoming_name)
    if normal_kind(g.get("kind")) == KIND_EPISODES:
        if not incoming_episode:
            return False
        rows = await _group_member_meta(g, meta_cache, cards_by_id)
        names = [str(row.get("file_name") or row.get("name") or "") for row in rows]
        return bool(names) and all(
            episode_identity(name) and series_key(name) == series_key(incoming_name)
            for name in names
        )

    incoming_duration = duration_seconds(card)
    if not incoming_duration:
        return False
    members = [str(m) for m in (g.get("members") or [])]
    rows = await _group_member_meta(g, meta_cache, cards_by_id)
    if not members or len(rows) != len(members):
        return False
    durations = {duration_seconds(row) for row in rows}
    if durations != {incoming_duration}:
        return False

    member_episodes = {
        episode_identity(row.get("file_name") or row.get("name")) for row in rows
    }
    if incoming_episode or any(member_episodes):
        return bool(incoming_episode) and member_episodes == {incoming_episode}
    return True


async def _persist_auto_group(key, candidates, kind, cards_by_id):
    """Save one safe automatic bucket, or add it to a compatible permanent group."""
    if len(candidates) < 2:
        return None, set()
    async with _AUTO_GROUP_LOCK:
        groups = await store.by_keys([key])
        memberships = await store.by_members([c.get("file_id") for c in candidates])
        owners = {}
        for group in memberships:
            for fid in group.get("members") or []:
                owners[str(fid)] = str(group.get("_id") or "")
        meta_cache = {}

        for g in groups:
            if normal_kind(g.get("kind")) != kind:
                continue
            if not await _auto_join_compatible(g, candidates[0], meta_cache, cards_by_id):
                continue
            gid = str(g.get("_id") or "")
            excluded = {str(x) for x in (g.get("excluded") or [])}
            handled, additions = set(), []
            existing = {str(x) for x in (g.get("members") or [])}
            for c in candidates:
                fid = str(c.get("file_id") or "")
                owner_gid = owners.get(fid)
                if fid in excluded or (owner_gid and owner_gid != gid):
                    handled.add(fid)
                    continue
                handled.add(fid)
                if fid not in existing:
                    additions.append((fid, str(c.get("name") or "")))
            if additions:
                g = await store.add_members(gid, additions, auto_keys=[key]) or g
                await store.mark_files([fid for fid, _ in additions], gid)
            return g, handled

        # A concurrent request may have assigned some files while this task waited.
        additions = []
        handled = set()
        for c in candidates:
            fid = str(c.get("file_id") or "")
            if fid and not owners.get(fid):
                handled.add(fid)
                additions.append((fid, str(c.get("name") or "")))
            elif fid:
                handled.add(fid)
        if len(additions) < 2:
            return None, handled

        group_items = additions
        episode_map = detect_episodes(group_items) if kind == KIND_EPISODES else {}
        first_name = group_items[0][1]
        group_name = (series_title(first_name) if kind == KIND_EPISODES
                      else group_title(first_name)) or first_name
        g = await store.create(
            name=group_name,
            items=group_items,
            auto_keys=[key],
            auto_created=True,
            kind=kind,
            episode_map=episode_map,
        )
        await store.mark_files([fid for fid, _ in group_items], str(g["_id"]))
        return g, handled


# ─────────────────────────────────────────────────────────────
# 🎴 GROUP-FIRST SEARCH — turn the page's cards into groups
# ─────────────────────────────────────────────────────────────
async def group_cards(cards, normalize=None, auto_join=True):
    """Normalized card dicts → the same list, but buckets of 2+ become one group card.

    * Saved group (`members`/`auto_keys`) → **permanent** group card, `gid` + `num`,
      and **every** group member appears as a variant (even off-page ones).
    * Safe same-duration quality buckets and multi-episode series are auto-created
      as permanent DB groups; only unknown/mismatched-duration quality files stay single.
    * `auto_join`: a new file matching a saved group's `auto_keys` is joined only
      when its group kind/duration/episode identity is compatible; exclusions stay out.
    * Input dicts are not mutated; ranking is preserved (the group takes the first file's slot).
    """
    cards = list(cards or [])
    if not cards:
        return cards
    ids = [str(c.get("file_id") or "") for c in cards]
    keys = {title_key(c.get("name")) for c in cards}
    keys.update(series_key(c.get("name")) for c in cards
                if episode_identity(c.get("name")))
    keys.discard("")

    found = await store.by_members(ids)
    found += await store.by_keys(sorted(keys))
    by_gid = {}
    for g in found:
        by_gid[str(g.get("_id"))] = g
    groups = list(by_gid.values())

    owner, key2groups = {}, defaultdict(list)
    cards_by_id = {str(c.get("file_id") or ""): c for c in cards if c.get("file_id")}
    member_meta_cache = {}
    for g in groups:
        for m in (g.get("members") or []):
            owner[str(m)] = g
        for k in (g.get("auto_keys") or []):
            if all(str(x.get("_id") or "") != str(g.get("_id") or "")
                   for x in key2groups[str(k)]):
                key2groups[str(k)].append(g)

    # 🆕 New files join a saved group only when its kind and metadata agree.
    joins = defaultdict(list)
    join_auto_keys = defaultdict(set)
    if auto_join:
        for c in cards:
            fid = str(c.get("file_id") or "")
            if not fid or fid in owner:
                continue
            file_keys = [title_key(c.get("name"))]
            if episode_identity(c.get("name")):
                file_keys.append(series_key(c.get("name")))
            seen_groups = set()
            for key in file_keys:
                for g in key2groups.get(key, []):
                    gid = str(g.get("_id") or "")
                    if gid in seen_groups:
                        continue
                    seen_groups.add(gid)
                    if fid in {str(x) for x in (g.get("excluded") or [])}:
                        continue
                    if await _auto_join_compatible(g, c, member_meta_cache, cards_by_id):
                        owner[fid] = g
                        name = str(c.get("name") or "")
                        joins[gid].append((fid, name))
                        join_key = series_key(name) if normal_kind(g.get("kind")) == KIND_EPISODES \
                            else title_key(name)
                        if join_key:
                            join_auto_keys[gid].add(join_key)
                        break
                if fid in owner:
                    break
        for gid, items in joins.items():
            await store.add_members(gid, items, auto_keys=sorted(join_auto_keys[gid]))
            await store.mark_files([i for i, _ in items], gid)
        if joins:
            # Re-read memberships after joins; same-title groups may have different durations.
            fresh = await store.by_members(ids)
            fresh += await store.by_keys(sorted(keys))
            by_gid = {str(g.get("_id")): g for g in fresh}
            groups = list(by_gid.values())
            owner, key2groups = {}, defaultdict(list)
            member_meta_cache = {}
            for g in groups:
                for m in (g.get("members") or []):
                    owner[str(m)] = g
                for k in (g.get("auto_keys") or []):
                    key2groups[str(k)].append(g)

    # Episode names get a shared series key; same-episode quality variants keep
    # their episode-specific title key and are still duration-matched as qualities.
    unowned, seen_unowned = [], set()
    for c in cards:
        fid = str(c.get("file_id") or "")
        if fid and fid not in owner and fid not in seen_unowned:
            unowned.append(c)
            seen_unowned.add(fid)
    episode_buckets = defaultdict(list)
    for c in unowned:
        if episode_identity(c.get("name")):
            key = series_key(c.get("name"))
            if len(key) >= 3:
                episode_buckets[key].append(c)

    auto_candidates = []
    series_ids = set()
    for key, entries in episode_buckets.items():
        if guess_kind([c.get("name") for c in entries]) == KIND_EPISODES:
            auto_candidates.append((key, KIND_EPISODES, entries, f"series:{key}"))
            series_ids.update(str(c.get("file_id") or "") for c in entries)

    quality_buckets = defaultdict(list)
    for c in unowned:
        fid = str(c.get("file_id") or "")
        if fid in series_ids:
            continue
        key = title_key(c.get("name"))
        secs = duration_seconds(c)
        if key and secs:
            quality_buckets[(key, secs, episode_identity(c.get("name")))].append(c)
    for (key, secs, ep_id), bucket in quality_buckets.items():
        if len(bucket) >= 2:
            auto_candidates.append((key, KIND_QUALITIES, bucket,
                                    f"quality:{key}:{secs}:{ep_id}"))

    virtual_buckets = {}
    virtual_group_for = {}
    if auto_join:
        for key, kind, candidates, bucket_key in auto_candidates:
            try:
                g, handled = await _persist_auto_group(key, candidates, kind, cards_by_id)
            except Exception as e:
                logger.warning(f"automatic group save skipped ({key}): {e}")
                g, handled = None, set()
            handled = {str(fid) for fid in handled}
            if g:
                by_gid[str(g.get("_id") or "")] = g
                group_members = {str(m) for m in (g.get("members") or [])}
                for m in group_members:
                    owner[str(m)] = g
                continue
            if handled:
                continue
            # A DB hiccup should not remove the safe visual grouping for this response.
            virtual_buckets[bucket_key] = {
                "g": None,
                "key": bucket_key,
                "title": (series_title(candidates[0].get("name")) if kind == KIND_EPISODES
                          else group_title(candidates[0].get("name")))
                         or candidates[0].get("name"),
                "kind": kind,
                "fids": [str(c.get("file_id") or "") for c in candidates],
            }
            for c in candidates:
                virtual_group_for[str(c.get("file_id") or "")] = bucket_key
    elif auto_candidates:
        for key, kind, candidates, bucket_key in auto_candidates:
            virtual_buckets[bucket_key] = {
                "g": None,
                "key": bucket_key,
                "title": (series_title(candidates[0].get("name")) if kind == KIND_EPISODES
                          else group_title(candidates[0].get("name")))
                         or candidates[0].get("name"),
                "kind": kind,
                "fids": [str(c.get("file_id") or "") for c in candidates],
            }
            for c in candidates:
                virtual_group_for[str(c.get("file_id") or "")] = bucket_key

    # Include groups created during this search in the normal expand/render path.
    if auto_join and auto_candidates:
        groups = list(by_gid.values())
        for g in groups:
            for m in (g.get("members") or []):
                owner[str(m)] = g

    # Load the remaining members of saved groups (not found on this page) from the DB
    needed = []
    have = set(ids)
    for g in groups:
        for m in (g.get("members") or []):
            if str(m) not in have and str(m) not in needed:
                needed.append(str(m))
    extra = []
    if needed and normalize:
        for doc in await store.files_by_ids(needed):
            extra.append(normalize(doc))
    pool = defaultdict(list)
    for c in cards:
        pool[str(c.get("file_id") or "")].append(c)
    for c in extra:
        fid = str(c.get("file_id") or "")
        if fid not in pool:
            pool[fid].append(c)

    order, buckets = [], {}
    for c in cards:
        fid = str(c.get("file_id") or "")
        g = owner.get(fid)
        if g:
            k = "m:" + str(g.get("_id"))
            if k not in buckets:
                buckets[k] = {"g": g, "key": k, "fids": []}
                order.append(("group", k))
        else:
            virtual_key = virtual_group_for.get(fid)
            if not virtual_key:
                order.append(("single", c))
                continue
            k = "a:" + virtual_key
            if k not in buckets:
                buckets[k] = dict(virtual_buckets[virtual_key])
                buckets[k]["key"] = k
                order.append(("group", k))
        if fid not in buckets[k]["fids"]:
            buckets[k]["fids"].append(fid)

    out = []
    for kind, value in order:
        if kind == "single":
            out.append(value)
            continue
        b = buckets[value]
        g = b["g"]
        if g:
            fids = [str(m) for m in (g.get("members") or [])]
        else:
            fids = list(b["fids"])
        variants = []
        for fid in fids:
            for c in pool.get(fid, []):
                variants.append(dict(c))
        if len(variants) < 2:
            out.extend(variants[:1])
            continue
        for v in variants:
            lab, h = quality_label(v.get("res"), v.get("name"), v.get("quality"))
            v["ql"] = lab
            v["qh"] = h
            v["gid"] = str(g["_id"]) if g else ""
            v["gnum"] = g.get("num", "") if g else ""
        # 🎞️ qualities of one file ⇄ 📺 separate episodes of a series
        # For a saved group use the admin's chosen `kind`; guess from names for auto buckets.
        if g:
            gkind = normal_kind(g.get("kind"))
            emap = clean_episode_map(g.get("episode_map"))
        else:
            gkind = normal_kind(b.get("kind"), guess_kind([v.get("name") for v in variants]))
            emap = {}
        if gkind == KIND_EPISODES:
            chips, episodes = episode_chips(variants, emap)
            variants.sort(key=lambda v: episode_label(v.get("el"), 0)[1])
            qualities = 0
            # 📺 Every episode has its own duration → showing one duration
            #    on the group would be wrong. It appears on each individual `.vcard`.
            duration = ""
        else:
            variants.sort(key=lambda v: v["qh"])
            chips, seen = [], {}
            for i, v in enumerate(variants):
                fid = str(v.get("file_id") or "")
                v["el"] = emap.get(fid) or episode_label(v.get("name"), i)[0]
            for v in variants:
                lab = v["ql"] or "?"
                if lab in seen:
                    seen[lab]["count"] += 1
                else:
                    seen[lab] = {"label": lab, "count": 1}
                    chips.append(seen[lab])
            episodes = 0
            qualities = len(variants)
            # 🎞️ Different qualities of one file ⇒ all durations are the same.
            #    If they ever differ, pick the most common (mode) duration,
            #    never a random file's value.
            durs = [str(v.get("duration") or "").strip() for v in variants]
            durs = [x for x in durs if x]
            duration = max(set(durs), key=durs.count) if durs else ""
        gid = str(g["_id"]) if g else ""
        rep = variants[-1]
        if g:
            title = str(g.get("name") or "") or str(rep.get("name") or "Group")
        else:
            title = str(b.get("title") or "") or group_title(rep.get("name")) \
                or str(rep.get("name") or "Group")
        out.append({
            "group": True,
            "manual": bool(g),
            "gid": gid,
            "num": g.get("num", "") if g else "",
            "key": ("m" + gid) if g else f"{value[2:]}",
            "nkey": "" if g else value[2:],
            "name": title,
            "count": len(variants),
            # ⚠️ No "VIDEO"/"FILE" type chip — just like the shared `.vcard`,
            #    group thumbnails show only quality/res/duration/group meta.
            # ⚠️ A single file's SIZE never appears on a group card — members have
            #    different sizes (each `.vcard` shows its own on expand).
            #    DURATION only on qualities groups: one file ⇒ a shared duration
            #    is correct; series/episode groups leave it empty.
            "duration": duration,
            "kind": gkind,
            "qualities": qualities,
            "episodes": episodes,
            "episode_map": emap,
            "thumb": _group_thumb_url(g or {}, variants),
            "custom_thumb": bool(g and str(g.get("thumb_url") or "").startswith("TG_ID:")),
            "chips": chips,
            "variants": variants,
        })
    return out


def filter_group_cards(cards, mode):
    """`group` = group cards only, `ungroup` = single files only, `all` = everything."""
    if mode == "group":
        return [c for c in cards if c.get("group")]
    if mode == "ungroup":
        return [c for c in cards if not c.get("group")]
    return cards


# ─────────────────────────────────────────────────────────────
# 📋 LIST / SAVE / UPDATE / REMOVE / DELETE / MERGE
# ─────────────────────────────────────────────────────────────
@group_routes.get("/api/group/list")
async def api_group_list(req):
    if not await _admin(req):
        return _denied()
    try:
        limit = max(1, min(int(req.query.get("limit", "25")), 200))
    except ValueError:
        limit = 25
    groups = await store.list(req.query.get("q", ""), limit)
    return _json({"ok": True, "groups": groups})


@group_routes.post("/api/group/save")
async def api_group_save(req):
    """Create a new group (new number) OR add files to an existing `group_id`.

    A file that belonged to another group is removed from it and **blacklisted**
    (`excluded`) so auto-key cannot bring it back — the same rule as v5.
    """
    if not await _admin(req):
        return _denied()
    data, err = await _body(req)
    if err:
        return err
    items = _items(data)
    if not items:
        return _json({"ok": False, "error": "No files selected"}, 400)
    gid = _fid(data.get("group_id") or "")
    name = str(data.get("name") or "").strip()[:200]
    raw_kind = data.get("kind")
    target_group = await store.get(gid) if gid else None
    # ⚠️ Check that the target exists before any side effect (removing from other groups)
    if gid and not target_group:
        return _json({"ok": False, "error": "Group not found"}, 404)
    kind = (
        normal_kind(raw_kind) if raw_kind
        else normal_kind(target_group.get("kind")) if target_group
        else guess_kind([n for _, n in items])
    )
    auto_keys = sorted({
        (series_key(n) if kind == KIND_EPISODES else title_key(n))
        for _, n in items
        if (series_key(n) if kind == KIND_EPISODES else title_key(n))
    })
    raw_emap = data.get("episode_map")
    if not gid and not name:
        return _json({"ok": False, "error": "Enter a group name"}, 400)

    # First remove these files from all other groups (excluded = never rejoin)
    fids = [i for i, _ in items]
    await store.pull_files(fids, exclude=True)
    if gid:
        g = await store.add_members(gid, items, auto_keys=auto_keys)
        # ✏️ Adding files to an existing group from the Edit modal also sends a new name.
        #    It used to be ignored, so a rename never reached the database.
        #    An empty name = no rename (just adding files to another group).
        upd = {}
        if name and name != str(g.get("name") or ""):
            upd["name"] = name
        # If no type is sent, keep the group's existing choice.
        if raw_kind is None:
            kind = normal_kind(g.get("kind"))
        # The Edit modal can also change the group type (qualities ⇄ episodes)
        if raw_kind is not None or "episode_map" in data:
            upd["kind"] = kind
            if "episode_map" in data:
                upd["episode_map"] = clean_episode_map(raw_emap)
        if upd:
            g = await store.update(gid, upd)
    else:
        g = await store.create(name=name, items=items, auto_keys=auto_keys,
                               kind=kind,
                               episode_map=clean_episode_map(raw_emap)
                               or detect_episodes(items))
    await store.mark_files(fids, str(g["_id"]))
    await store.cleanup_empty()
    return _json({"ok": True, "group": _group_public(g),
                  "group_id": str(g["_id"]), "num": g.get("num", ""),
                  "group_name": str(g.get("name") or "")})


@group_routes.post("/api/group/update")
async def api_group_update(req):
    """Change the name / master thumbnail. `thumb_file_id:''` = AUTO (highest quality)."""
    if not await _admin(req):
        return _denied()
    data, err = await _body(req)
    if err:
        return err
    gid = _fid(data.get("group_id"))
    g = await store.get(gid)
    if not g:
        return _json({"ok": False, "error": "Group not found"}, 404)
    fields = {}
    if "name" in data:
        name = str(data.get("name") or "").strip()[:200]
        if not name:
            return _json({"ok": False, "error": "Name cannot be empty"}, 400)
        fields["name"] = name
    if "thumb_file_id" in data:
        tf = _fid(data.get("thumb_file_id"))
        # Only a member of this group can become its master thumbnail
        if tf and tf not in {str(m) for m in (g.get("members") or [])}:
            return _json({"ok": False, "error": "This file is not in the group"}, 400)
        fields["thumb_fid"] = tf
        if tf:
            fields["thumb_url"] = ""       # remove the custom upload, use the selected member
    if data.get("auto_keys"):
        fields["auto_keys"] = sorted({title_key(k) for k in data["auto_keys"] if title_key(k)})
    if data.get("clear_custom"):
        fields["thumb_url"] = ""
    if "kind" in data:
        k = str(data.get("kind") or "").strip().lower()
        if k not in (KIND_QUALITIES, KIND_EPISODES):
            return _json({"ok": False, "error": "Invalid group type"}, 400)
        fields["kind"] = k
    if "episode_map" in data:
        fields["episode_map"] = clean_episode_map(data.get("episode_map"))
    updated = await store.update(gid, fields)
    return _json({"ok": True, "group": _group_public(updated)})


@group_routes.post("/api/group/remove_file")
async def api_group_remove_file(req):
    if not await _admin(req):
        return _denied()
    data, err = await _body(req)
    if err:
        return err
    gid, fid = _fid(data.get("group_id")), _fid(data.get("file_id"))
    if not gid or not fid:
        return _json({"ok": False, "error": "Missing inputs"}, 400)
    g = await store.remove_member(gid, fid)
    if not g:
        return _json({"ok": False, "error": "Group not found"}, 404)
    await store.mark_files([fid], "")
    await store.cleanup_empty()
    return _json({"ok": True, "group": _group_public(g)})


@group_routes.post("/api/group/delete")
async def api_group_delete(req):
    """Ungroup — only the group is deleted, not the files (they can auto-group again)."""
    if not await _admin(req):
        return _denied()
    data, err = await _body(req)
    if err:
        return err
    gid = _fid(data.get("group_id"))
    if not await store.get(gid):
        return _json({"ok": False, "error": "Group not found"}, 404)
    members = await store.delete(gid)
    await store.mark_files(members, "")
    return _json({"ok": True, "removed": len(members)})


@group_routes.post("/api/group/merge")
async def api_group_merge(req):
    """Move all files + auto_keys of the source group into the target number; drop the source."""
    if not await _admin(req):
        return _denied()
    data, err = await _body(req)
    if err:
        return err
    src = _fid(data.get("source"))
    tgt = _fid(str(data.get("target") or "").strip().lstrip("#"))
    if not src or not tgt:
        return _json({"ok": False, "error": "Enter a group number"}, 400)
    if src == tgt:
        return _json({"ok": False, "error": "Cannot merge a group into itself"}, 400)
    if not await store.get(src) or not await store.get(tgt):
        return _json({"ok": False, "error": "Source or target group not found"}, 404)
    merged = await store.merge(src, tgt)
    await store.mark_files([str(m) for m in (merged.get("members") or [])], tgt)
    await store.cleanup_empty()
    return _json({"ok": True, "group": _group_public(merged),
                  "group_id": tgt, "num": merged.get("num", ""),
                  "group_name": str(merged.get("name") or "")})


# ─────────────────────────────────────────────────────────────
# ⚙️ SCAN ALL — build permanent groups from the whole library (idempotent)
# ─────────────────────────────────────────────────────────────
async def _scan_all_groups():
    st = SCAN_STATE
    st.update(running=True, phase="Loading groups", scanned=0, total=0,
              created=0, added=0, skipped_big=0, skipped_keys=[], fixed_marks=0,
              existing_groups=0, multi_buckets=0, error="", started=time.time(),
              finished=0)
    try:
        existing = await store.all_groups()
        groups_by_key, owner, group_by_id = defaultdict(list), {}, {}
        for g in existing:
            gid = str(g.get("_id") or "")
            if not gid:
                continue
            group_by_id[gid] = g
            for member in (g.get("members") or []):
                owner[str(member)] = gid

            kind = normal_kind(g.get("kind"))
            group_keys = {str(k) for k in (g.get("auto_keys") or []) if k}
            # Rebuild missing/legacy keys from names already stored on the group.
            for f in (g.get("files") or []):
                name = str(f.get("name") or "")
                key = series_key(name) if kind == KIND_EPISODES else title_key(name)
                if key:
                    group_keys.add(key)
            if group_keys != {str(k) for k in (g.get("auto_keys") or []) if k}:
                g = await store.update(gid, {"auto_keys": sorted(group_keys)}) or g
                group_by_id[gid] = g
            for key in group_keys:
                if all(str(x.get("_id") or "") != gid for x in groups_by_key[key]):
                    groups_by_key[key].append(g)
        st["existing_groups"] = len(group_by_id)

        docs = await store.scan_files()
        docs_by_id = {str(d.get("_id") or ""): d for d in docs if d.get("_id")}
        st["total"] = len(docs)
        st["phase"] = "Scanning files"
        fix_set, fix_unset = defaultdict(list), []
        for d in docs:
            st["scanned"] += 1
            fid = str(d.get("_id") or "")
            if not fid:
                continue
            owner_gid = owner.get(fid)
            marked_gid = str(d.get("group_id") or "")
            if owner_gid and marked_gid != owner_gid:
                fix_set[owner_gid].append(fid)
            elif not owner_gid and marked_gid:
                fix_unset.append(fid)
            if st["scanned"] % 2000 == 0:
                await asyncio.sleep(0)

        st["phase"] = "Building groups"
        now = int(time.time())
        meta_cache = {}

        async def attach_to_existing(key, candidates, kind):
            """Attach compatible unowned rows; return (attached, excluded ids)."""
            blocked = set()
            for g in groups_by_key.get(key, []):
                if normal_kind(g.get("kind")) != kind:
                    continue
                if not candidates or not await _auto_join_compatible(
                        g, candidates[0], meta_cache, docs_by_id):
                    continue
                gid = str(g.get("_id") or "")
                excluded = {str(x) for x in (g.get("excluded") or [])}
                fresh = []
                for d in candidates:
                    fid = str(d.get("_id") or "")
                    if fid in owner:
                        continue
                    if fid in excluded:
                        blocked.add(fid)
                        continue
                    fresh.append((fid, str(d.get("file_name") or "")))
                if not fresh:
                    continue
                updated = await store.add_members(
                    gid, fresh, auto_keys=[key], scanned_at=now
                )
                if not updated:
                    continue
                group_by_id[gid] = updated
                for key2, group_list in groups_by_key.items():
                    for i, old in enumerate(group_list):
                        if str(old.get("_id") or "") == gid:
                            group_list[i] = updated
                for fid, _ in fresh:
                    owner[fid] = gid
                    fix_set[gid].append(fid)
                meta_cache.pop(gid, None)
                st["added"] += len(fresh)
                return True, blocked
            return False, blocked

        # A series is identified by its normalized show title, not its duration.
        episode_buckets = defaultdict(list)
        for d in docs:
            name = str(d.get("file_name") or "")
            if episode_identity(name):
                key = series_key(name)
                if len(key) >= 3:
                    episode_buckets[key].append(d)

        series_ids = set()
        for key, rows in episode_buckets.items():
            names = [str(d.get("file_name") or "") for d in rows]
            if guess_kind(names) != KIND_EPISODES:
                continue
            series_ids.update(str(d.get("_id") or "") for d in rows)
            if len(rows) >= 2:
                st["multi_buckets"] += 1
            candidates = [d for d in rows
                          if str(d.get("_id") or "") not in owner]
            if not candidates:
                continue
            attached, blocked = await attach_to_existing(
                key, candidates, KIND_EPISODES
            )
            if attached:
                continue
            candidates = [d for d in candidates
                          if str(d.get("_id") or "") not in blocked]
            if (len(candidates) < 2
                    or guess_kind([d.get("file_name") for d in candidates]) != KIND_EPISODES):
                continue
            if len(candidates) > SCAN_MAX_SERIES:
                st["skipped_big"] += 1
                if len(st["skipped_keys"]) < 20:
                    st["skipped_keys"].append(f"{key} ({len(candidates)} episodes)")
                continue
            items = [(str(d["_id"]), str(d.get("file_name") or ""))
                     for d in candidates]
            group_name = series_title(items[0][1]) or items[0][1]
            g = await store.create(
                name=group_name, items=items, auto_keys=[key], auto_created=True,
                scan_created=True, kind=KIND_EPISODES,
                episode_map=detect_episodes(items),
            )
            gid = str(g["_id"])
            g = await store.update(gid, {"scanned_at": now}) or g
            group_by_id[gid] = g
            groups_by_key[key].append(g)
            for fid, _ in items:
                owner[fid] = gid
                fix_set[gid].append(fid)
            st["created"] += 1

        # Quality variants must share a known duration. Episode identity is also
        # part of the bucket so different episodes never collapse into one group.
        quality_buckets = defaultdict(list)
        for d in docs:
            fid = str(d.get("_id") or "")
            if fid in series_ids:
                continue
            name = str(d.get("file_name") or "")
            key = title_key(name)
            secs = duration_seconds(d)
            if len(key) >= 3 and secs:
                quality_buckets[(key, secs, episode_identity(name))].append(d)

        for (key, _secs, _episode), rows in quality_buckets.items():
            if len(rows) >= 2:
                st["multi_buckets"] += 1
            candidates = [d for d in rows
                          if str(d.get("_id") or "") not in owner]
            if not candidates:
                continue
            attached, blocked = await attach_to_existing(
                key, candidates, KIND_QUALITIES
            )
            if attached:
                continue
            candidates = [d for d in candidates
                          if str(d.get("_id") or "") not in blocked]
            if len(candidates) < 2:
                continue
            if len(candidates) > SCAN_MAX_GROUP:
                st["skipped_big"] += 1
                if len(st["skipped_keys"]) < 20:
                    st["skipped_keys"].append(f"{key} ({len(candidates)} files)")
                continue
            items = [(str(d["_id"]), str(d.get("file_name") or ""))
                     for d in candidates]
            group_name = group_title(items[0][1]) or items[0][1]
            g = await store.create(
                name=group_name, items=items, auto_keys=[key], auto_created=True,
                scan_created=True, kind=KIND_QUALITIES,
            )
            gid = str(g["_id"])
            g = await store.update(gid, {"scanned_at": now}) or g
            group_by_id[gid] = g
            groups_by_key[key].append(g)
            for fid, _ in items:
                owner[fid] = gid
                fix_set[gid].append(fid)
            st["created"] += 1

        st["phase"] = "Marking files with group_id"
        if fix_unset:
            unset_ids = list(dict.fromkeys(fix_unset))
            await store.mark_files(unset_ids, "")
            st["fixed_marks"] += len(unset_ids)
        for gid, ids in fix_set.items():
            unique_ids = list(dict.fromkeys(ids))
            if unique_ids:
                await store.mark_files(unique_ids, gid)
                st["fixed_marks"] += len(unique_ids)
        await store.cleanup_empty()
        st["phase"] = "complete"
    except Exception as e:
        logger.error(f"group scan failed: {e}")
        st["error"] = str(e)
        st["phase"] = "error"
    finally:
        st["running"] = False
        st["finished"] = time.time()
        logger.info(f"🗂️ Group scan: scanned={st.get('scanned')}/{st.get('total')} "
                    f"created={st.get('created')} added={st.get('added')} "
                    f"fixed={st.get('fixed_marks')} err={st.get('error')}")


@group_routes.post("/api/group/scan_all")
async def api_group_scan_all(req):
    if not await _admin(req):
        return _denied()
    if SCAN_STATE.get("running"):
        return _json({"ok": True, "started": False, "running": True})
    asyncio.create_task(_scan_all_groups())
    return _json({"ok": True, "started": True})


@group_routes.get("/api/group/scan_status")
async def api_group_scan_status(req):
    if not await _admin(req):
        return _denied()
    return _json({"ok": True, **SCAN_STATE})


# ─────────────────────────────────────────────────────────────
# 🖼️ MASTER THUMBNAIL — custom upload / pick a member / serve
# ─────────────────────────────────────────────────────────────
@group_routes.post("/api/group/upload_thumb")
async def api_group_upload_thumb(req):
    if not await _admin(req):
        return _denied()
    try:
        reader = await req.multipart()
        gid, raw = "", b""
        while True:
            part = await reader.next()
            if part is None:
                break
            if part.name == "group_id":
                gid = _fid((await part.read()).decode("utf-8", "replace"))
            elif part.name == "image":
                raw = await part.read()
    except Exception as e:
        return _json({"ok": False, "error": f"Bad upload: {e}"}, 400)
    if not gid or not await store.get(gid):
        return _json({"ok": False, "error": "Group not found"}, 404)
    if not raw or len(raw) > _MAX_UPLOAD or not is_image_magic(raw):
        return _json({"ok": False, "error": "JPG/PNG/WEBP only, up to 5 MB"}, 400)
    bot = getattr(temp, "BOT", None)
    if bot is None:
        return _json({"ok": False, "error": "The bot is not ready yet"}, 503)
    try:
        import io
        buf = io.BytesIO(raw)
        buf.name = "group_poster.jpg"
        msg = await bot.send_photo(chat_id=_STORAGE_CHANNEL, photo=buf)
        photo = getattr(msg, "photo", None)
        sizes = getattr(photo, "sizes", None) if photo else None
        tid = sizes[-1].file_id if sizes else getattr(photo, "file_id", "")
    except Exception as e:
        logger.warning(f"group thumb upload failed: {e}")
        return _json({"ok": False, "error": "Telegram upload failed"}, 502)
    if not tid:
        return _json({"ok": False, "error": "No thumbnail file_id returned"}, 502)
    g = await store.update(gid, {"thumb_url": "TG_ID:" + str(tid), "thumb_fid": ""})
    return _json({"ok": True, "group": _group_public(g),
                  "thumb": f"/api/group/thumb?gid={gid}&v={thumb_version(gid, 'TG_ID:' + str(tid))}"})


@group_routes.get("/api/group/thumb")
async def api_group_thumb(req):
    role, _ = await get_auth(req)
    if not role:
        return web.Response(status=401)
    gid = _fid(req.query.get("gid"))
    g = await store.get(gid) if gid else None
    ref = str((g or {}).get("thumb_url") or "")
    if not ref.startswith("TG_ID:"):
        return web.Response(status=404)
    etag = f'"{req.query.get("v") or thumb_version(gid, ref)}"'
    headers = {"Cache-Control": f"private, max-age={THUMB_BROWSER_CACHE}", "ETag": etag}
    if req.headers.get("If-None-Match") == etag:
        return web.Response(status=304, headers=headers)
    data = await get_image_bytes(ref[len("TG_ID:"):])
    if not data:
        return web.Response(status=404, headers={"Cache-Control": "no-store"})
    return web.Response(body=data, content_type=image_content_type(data), headers=headers)
