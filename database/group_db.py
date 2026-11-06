"""🗂️ PERMANENT QUALITY GROUPS — fsv1's own group store.

Adapted from the GitHub reference (`JoneySin/v5`): each group in the `QualityGroups`
collection has its own `_id`/`num`, `members` (file ids), `auto_keys`, `excluded` and
a master thumbnail; `QualityGroupSeq` supplies sequential numbers; each file document
is marked with `group_id`; a new quality of the same title joins the group automatically
via `auto_keys`; files and groups support merge / ungroup / remove / scan_all.

fsv1 has its own implementation (not a verbatim copy):
  * **One** `collection` (fsv1 has no primary/cloud/archive `section`), so there is
    no `thumb_col`, `COLLECTIONS` or `source_col` here.
  * fsv1's **synchronous PyMongo** plus `asyncio.to_thread`; when MongoDB is missing
    a transparent **in-memory fallback** (like `catalog_db.py`) keeps the preview and
    unit tests running without a database.
  * The store exposes only high-level methods (`get`, `by_members`, `add_members`,
    `merge`, …); no raw `$addToSet`/`$pull` queries are written in the routes.
  * Group doc:
    `{_id:"12", num:12, name, members:[fid], files:[{id,name}], auto_keys:[key],
      excluded:[fid], thumb_fid:"", thumb_url:"", auto_created, scan_created,
      created_at, updated_at, scanned_at}`
"""

import asyncio
import logging
import re
import time

try:
    from database.users_chats_db import dbase
except Exception:                                      # pragma: no cover
    dbase = None

logger = logging.getLogger(__name__)

# ── Title normalization (single source for search, scan and auto-join) ──────
NOISE = frozenset("""
144p 240p 360p 480p 576p 720p 1080p 1440p 2160p 4k 8k uhd hd sd
hdr hdr10 hdr10plus dv sdr 10bit 8bit hevc x264 x265 h264 h265 avc xvid divx
bluray blueray brrip bdrip bdremux remux webdl webrip web hdtv dvdrip dvd
cam hdcam predvd ts tc hdrip dvdscr r5
hindi english eng tamil telugu kannada malayalam bengali marathi punjabi
dual multi audio org original esub esubs sub subs subtitle subtitles
dd dd5 dd51 ddp ac3 aac mp3 flac truehd atmos 2ch 5ch 6ch
imax extended proper repack unrated theatrical directors cut
amzn nf netflix dsnp hmax hotstar prime zee sony
mkv mp4 avi mov webm m4v wmv flv mpeg mpg m2ts vob 3gp iso
www http https com net org
""".split())
_EPISODE_RE = re.compile(r"^[se]\d{1,3}$", re.IGNORECASE)
_RES_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:(?:240|360|480|540|576|720|1080|1440|2160|4320)\s*[pP]|4[kK]|8[kK]|[uU][hH][dD])(?![A-Za-z0-9])"
)
_EXT_TAIL_RE = re.compile(
    r"[\s._\-]*(?<![A-Za-z0-9])(?:mp4|mkv|avi|mov|webm|m4v|ts|wmv|flv|mpg|mpeg)\s*$", re.I
)
_S_E_RE = re.compile(r"\bS(\d{1,2})\s*[._\- ]?E(\d{1,3})\b", re.I)
_X_RE = re.compile(r"(?<!\d)(\d{1,2})[xX](\d{2,3})(?!\d)")
_E_RE = re.compile(r"\bE(?:PISODE)?\s*[._\- ]?(\d{1,3})\b", re.I)
_EP_RE = re.compile(r"\b(?:Ep|Episode|Part|Pt|Chapter|Ch)\s*[._\- ]?(\d{1,3})\b", re.I)
_NUM_OF_RE = re.compile(r"\b(\d{1,3})\s*(?:of|/)\s*\d{1,3}\b", re.I)
_EPISODE_PATTERNS = (_S_E_RE, _X_RE, _EP_RE, _E_RE, _NUM_OF_RE)


def _title_key(name, strip_episodes=False) -> str:
    text = re.sub(r"[\[(][^\])]*[\])]", " ", str(name or "").lower())
    if strip_episodes:
        for pattern in _EPISODE_PATTERNS:
            text = pattern.sub(" ", text)
    clean = []
    for token in re.findall(r"[^\W_]+", text, re.UNICODE):
        if token in NOISE or _EPISODE_RE.match(token):
            continue
        if len(token) <= 2 and token.isdigit():
            continue
        clean.append(token)
        if len(clean) == 4:
            break
    return " ".join(clean)


def title_key(name) -> str:
    """Quality-group key: strips quality/language/codec but preserves episode identity."""
    return _title_key(name)


def series_key(name) -> str:
    """Series key: `title_key` plus stripping S01E02 / 1x02 / Ep 2 markers."""
    return _title_key(name, strip_episodes=True)


def group_title(name) -> str:
    """A clean, display-ready title (original case, without quality and extension)."""
    s = _EXT_TAIL_RE.sub("", str(name or ""))
    s = _RES_TOKEN_RE.sub(" ", s)
    s = re.sub(r"\s+", " ", s)
    return re.sub(r"^[\s|\-–_.]+|[\s|\-–_.]+$", "", s)


def series_title(name) -> str:
    """Display title for an automatic series group, without episode markers."""
    s = str(name or "")
    for pattern in _EPISODE_PATTERNS:
        s = pattern.sub(" ", s)
    return group_title(s)


def quality_height(res, name=""):
    """`1920×1080` / `1080p` → sortable height (used by the chips)."""
    m = re.search(r"(\d{3,5})\D+(\d{3,5})", str(res or ""))
    if m:
        w, h = int(m.group(1)), int(m.group(2))
        return max(h, int(w * 9 / 16))
    m = re.search(r"(?<!\d)(2160|1440|1080|720|576|480|360|240)[pP]?(?!\d)", str(name or ""))
    return int(m.group(1)) if m else 0


def quality_label(res, name="", quality=None):
    """Return a chip label like `('1080p', 1080)` for the group card's quality chips.

    It reuses the exact `quality` value shown by the shared `.vcard` chip (`vcard_meta()`)
    so labels stay identical inside and outside the group; falls back to `res`/name.
    """
    q = str(quality or "").strip()
    m = re.fullmatch(r"(\d{3,4})[pP]", q)
    if m:
        return q.lower(), int(m.group(1))
    if re.fullmatch(r"4[kK]", q):
        return "2160p", 2160
    if re.fullmatch(r"8[kK]", q):
        return "8K", 4320
    h = quality_height(res, name)
    for floor, label in ((4000, "8K"), (2000, "2160p"), (1300, "1440p"),
                         (1000, "1080p"), (650, "720p"), (450, "480p"),
                         (330, "360p"), (220, "240p")):
        if h >= floor:
            return label, h
    return (f"{h}p", h) if h else ("?", 0)


# ── 📺 EPISODE DETECTION + GROUP KIND ────────────────────────────────
# Some groups hold different qualities of one file, others hold different episodes of
# a series. They need separate identities so the card can show "3 QUALITIES" or
# "12 EPISODES" correctly (and never show the size/duration of a single file).
KIND_QUALITIES = "qualities"
KIND_EPISODES = "episodes"
KINDS = (KIND_QUALITIES, KIND_EPISODES)

def episode_label(name, fallback=0):
    """File name → `('S01E03'|'E03'|'EP 3', episode_number)`.

    An admin can override any label through `episode_map`.
    When no marker is found, labels fall back to `E01/E02/…` in order,
    so every episode gets its own chip and the count stays correct.
    """
    text = str(name or "")
    m = _S_E_RE.search(text)
    if m:
        return f"S{int(m.group(1)):02d}E{int(m.group(2)):02d}", int(m.group(2))
    m = _X_RE.search(text)
    if m:
        return f"S{int(m.group(1)):02d}E{int(m.group(2)):02d}", int(m.group(2))
    m = _E_RE.search(text) or _EP_RE.search(text) or _NUM_OF_RE.search(text)
    if m:
        n = int(m.group(1))
        return f"E{n:02d}", n
    n = int(fallback or 0) + 1
    return f"E{n:02d}", n


def has_episode_marker(name) -> bool:
    """Whether a filename contains a recognized season/episode marker."""
    text = str(name or "")
    return any(pattern.search(text) for pattern in _EPISODE_PATTERNS)


def episode_identity(name) -> str:
    """Stable identity for an episode (including season where it is present)."""
    return episode_label(name, 0)[0] if has_episode_marker(name) else ""


def duration_seconds(value) -> int:
    """Normalize file docs/cards' numeric or `H:MM:SS` duration to seconds; unknown → 0."""
    if isinstance(value, dict):
        raw = value.get("duration_seconds")
        if raw in (None, "", 0, "0"):
            raw = value.get("duration")
    else:
        raw = value
    try:
        seconds = int(raw or 0)
        if seconds > 0:
            return seconds
    except (TypeError, ValueError):
        pass
    text = str(raw or "").strip().replace("：", ":")
    if not text:
        return 0
    if text.isdigit():
        return max(0, int(text))
    parts = text.split(":")
    if len(parts) not in (2, 3) or any(not p.strip().isdigit() for p in parts):
        return 0
    nums = [int(p) for p in parts]
    seconds = nums[-1] + nums[-2] * 60 + (nums[-3] * 3600 if len(nums) == 3 else 0)
    return seconds if seconds > 0 else 0


def detect_episodes(items):
    """`[(fid, name), …]` → `{fid: label}` — only names containing an episode marker."""
    out = {}
    for i, (fid, name) in enumerate(items or []):
        if has_episode_marker(name):
            out[str(fid)] = episode_label(name, i)[0]
    return out


def guess_kind(names):
    """Guess from the names: 2+ distinct episode identities → series, otherwise qualities."""
    identities = {episode_identity(name) for name in (names or [])}
    identities.discard("")
    return KIND_EPISODES if len(identities) >= 2 else KIND_QUALITIES


def normal_kind(value, default=KIND_QUALITIES):
    v = str(value or "").strip().lower()
    return v if v in KINDS else default


def clean_episode_map(value):
    """Validate a user-supplied `{fid: 'E05'}` map — safe ids and lengths only, no markup."""
    if not isinstance(value, dict):
        return {}
    out = {}
    for fid, lab in list(value.items())[:200]:
        fid = str(fid).strip()
        if not re.fullmatch(r"[A-Za-z0-9_\-=]{1,512}", fid):
            continue
        lab = str(lab or "").strip()[:24]
        lab = re.sub(r"[<>&\"']", "", lab)
        if lab:
            out[fid] = lab
    return out


def group_kind_meta(doc):
    """Group document → `{kind, qualities, episodes, episode_map}` — one calculation.

    `qualities` = number of files/qualities in the group, `episodes` = distinct episode labels.
    """
    d = doc or {}
    members = [str(m) for m in (d.get("members") or [])]
    emap = clean_episode_map(d.get("episode_map"))
    files = {str(f.get("id")): str(f.get("name") or "")
             for f in (d.get("files") or [])}
    labels = {emap.get(fid) or episode_label(files.get(fid, ""), i)[0]
              for i, fid in enumerate(members)}
    kind = normal_kind(d.get("kind"))
    return {"kind": kind,
            "qualities": len(members) if kind == KIND_QUALITIES else 0,
            "episodes": len(labels) if kind == KIND_EPISODES else 0,
            "episode_map": emap}


def episode_chips(variants, episode_map=None):
    """Chips for an episode-kind group: `E01, E02, …` plus the count of each label.

    Returns `(chips, episodes_count)` — `episodes_count` is the number of distinct episodes.
    """
    emap = clean_episode_map(episode_map)
    rows = []
    for i, v in enumerate(variants or []):
        fid = str(v.get("file_id") or "")
        lab = emap.get(fid) or episode_label(v.get("name"), i)[0]
        n = episode_label(lab, i)[1]
        rows.append((n, lab, v))
    rows.sort(key=lambda r: r[0])
    chips, seen = [], {}
    distinct = set()
    for _, lab, v in rows:
        distinct.add(lab)
        v["el"] = lab
        if lab in seen:
            seen[lab]["count"] += 1
        else:
            seen[lab] = {"label": lab, "count": 1}
            chips.append(seen[lab])
    return chips, len(distinct)


def file_collection():
    """fsv1's only file collection — lazy import (None when MongoDB is unavailable)."""
    try:
        from database.ia_filterdb import collection
        return collection
    except Exception:
        return None


# ── In-memory fallback ────────────────────────────────────────────────────
class _MemoryGroups:
    """A small PyMongo-like store for the DB-less preview and unit tests."""

    def __init__(self):
        self.data = {}
        self.seq = 0

    def get(self, gid):
        d = self.data.get(str(gid))
        return dict(d) if d else None

    def all(self):
        return [dict(d) for d in self.data.values()]

    def insert(self, doc):
        self.data[str(doc["_id"])] = dict(doc)
        return dict(doc)

    def save(self, doc):
        self.data[str(doc["_id"])] = dict(doc)
        return dict(doc)

    def delete(self, gid):
        return self.data.pop(str(gid), None)

    def next_num(self):
        self.seq += 1
        return self.seq


class GroupStore:
    """The single store for permanent groups — MongoDB or in-memory, same API."""

    def __init__(self, database):
        self.col = database["quality_groups"] if database is not None else None
        self.seq = database["quality_group_seq"] if database is not None else None
        self.mem = _MemoryGroups() if self.col is None else None

    # ── low-level sync helpers ───────────────────────────────────────────
    def _get(self, gid):
        if self.mem:
            return self.mem.get(gid)
        return self.col.find_one({"_id": str(gid)})

    def _all(self):
        if self.mem:
            return self.mem.all()
        return list(self.col.find({}))

    def _save(self, doc):
        if self.mem:
            return self.mem.save(doc)
        # ⚠️ MongoDB treats `_id` as immutable — including it in `$set` raises an error
        fields = {k: v for k, v in doc.items() if k != "_id"}
        self.col.update_one({"_id": doc["_id"]}, {"$set": fields}, upsert=True)
        return doc

    def _insert(self, doc):
        if self.mem:
            return self.mem.insert(doc)
        self.col.insert_one(doc)
        return doc

    def _delete(self, gid):
        if self.mem:
            return self.mem.delete(gid)
        old = self.col.find_one({"_id": str(gid)})
        self.col.delete_one({"_id": str(gid)})
        return old

    def _next_num(self):
        if self.mem:
            return self.mem.next_num()
        # default = the document BEFORE the update; on upsert None → 1
        d = self.seq.find_one_and_update(
            {"_id": "seq"}, {"$inc": {"n": 1}}, upsert=True
        )
        return int((d or {}).get("n", 0)) + 1

    # ── async public API ─────────────────────────────────────────────────
    async def get(self, gid):
        return await asyncio.to_thread(self._get, gid)

    async def all_groups(self):
        return await asyncio.to_thread(self._all)

    async def list(self, q="", limit=25):
        """Group search — by name or number (`#12`), newest first."""
        def _run():
            needle = str(q or "").strip().lstrip("#")
            docs = self._all()
            if needle:
                ql = needle.lower()
                docs = [d for d in docs
                        if needle == str(d.get("_id") or "") or needle == str(d.get("num") or "")
                        or ql in str(d.get("name") or "").lower()]
            docs.sort(key=lambda d: int(d.get("updated_at") or 0), reverse=True)
            def _meta(d):
                m = group_kind_meta(d)
                m.update({"id": str(d["_id"]), "num": d.get("num", ""),
                          "name": d.get("name", ""),
                          "count": len(d.get("members") or []),
                          "thumb_fid": d.get("thumb_fid", ""),
                          "thumb_url": d.get("thumb_url", "")})
                return m
            return [_meta(d) for d in docs[:max(1, min(int(limit or 25), 200))]]
        return await asyncio.to_thread(_run)

    async def by_members(self, ids):
        """Return the saved groups that contain any of the given file ids."""
        def _run():
            s = {str(i) for i in ids if i}
            if not s:
                return []
            if self.mem:
                return [dict(d) for d in self.mem.all()
                        if s.intersection(str(m) for m in (d.get("members") or []))]
            return list(self.col.find({"members": {"$in": list(s)}}))
        return await asyncio.to_thread(_run)

    async def by_keys(self, keys):
        """Groups matched by `auto_keys` — this is where new qualities auto-join."""
        def _run():
            s = {str(k) for k in keys if k}
            if not s:
                return []
            if self.mem:
                return [dict(d) for d in self.mem.all()
                        if s.intersection(str(k) for k in (d.get("auto_keys") or []))]
            return list(self.col.find({"auto_keys": {"$in": list(s)}}))
        return await asyncio.to_thread(_run)

    async def next_num(self):
        return await asyncio.to_thread(self._next_num)

    async def create(self, *, name, items, auto_keys=(), auto_created=False,
                     scan_created=False, kind=KIND_QUALITIES, episode_map=None):
        """Create a PERMANENT group with its own number, members, files and auto_keys."""
        now = int(time.time())
        num = await self.next_num()
        gid = str(num)
        doc = {
            "_id": gid, "num": num,
            "name": str(name or "").strip()[:200],
            "members": [str(i) for i, _ in items],
            "files": [{"id": str(i), "name": str(n or "")[:300]} for i, n in items],
            "auto_keys": sorted({str(k) for k in auto_keys if k}),
            "excluded": [], "thumb_fid": "", "thumb_url": "",
            "kind": normal_kind(kind), "episode_map": clean_episode_map(episode_map),
            "auto_created": bool(auto_created), "scan_created": bool(scan_created),
            "created_at": now, "updated_at": now, "scanned_at": 0,
        }
        await asyncio.to_thread(self._insert, doc)
        return doc

    async def update(self, gid, fields):
        """Update name / master thumbnail / timestamps — only whitelisted keys."""
        allowed = {"name", "thumb_fid", "thumb_url", "auto_keys", "excluded",
                   "kind", "episode_map", "updated_at", "scanned_at", "scan_created"}

        def _run():
            g = self._get(gid)
            if not g:
                return None
            clean = {k: v for k, v in (fields or {}).items() if k in allowed}
            clean["updated_at"] = int(time.time())
            g.update(clean)
            self._save(g)
            return g
        return await asyncio.to_thread(_run)

    async def add_members(self, gid, items, auto_keys=(), unexclude=True,
                          scanned_at=0):
        """Add files to a group (idempotent) — like `$addToSet`, but in Python."""
        def _run():
            g = self._get(gid)
            if not g:
                return None
            members = list(g.get("members") or [])
            files = list(g.get("files") or [])
            by_id = {str(f.get("id")): f for f in files}
            for fid, name in items:
                fid = str(fid)
                if fid not in members:
                    members.append(fid)
                by_id[fid] = {"id": fid, "name": str(name or "")[:300]}
            g["members"] = members
            g["files"] = [by_id[i] for i in members]
            g["auto_keys"] = sorted(set(map(str, g.get("auto_keys") or []))
                                    | {str(k) for k in auto_keys if k})
            if unexclude:
                added = {str(i) for i, _ in items}
                g["excluded"] = [x for x in (g.get("excluded") or []) if str(x) not in added]
            if scanned_at:
                g["scanned_at"] = int(scanned_at)
            g["updated_at"] = int(time.time())
            self._save(g)
            return g
        return await asyncio.to_thread(_run)

    async def rename_member(self, gid, fid, name):
        """Keep `files[].name` in sync when the file editor renames a file."""
        def _run():
            g = self._get(gid)
            if not g:
                return None
            target = str(fid)
            for f in (g.get("files") or []):
                if str(f.get("id")) == target:
                    f["name"] = str(name or "")[:300]
            g["updated_at"] = int(time.time())
            self._save(g)
            return g
        return await asyncio.to_thread(_run)

    async def remove_member(self, gid, fid, exclude=True):
        """Remove a file from a group and blacklist it so auto-key cannot re-add it."""
        def _run():
            g = self._get(gid)
            if not g:
                return None
            target = str(fid)
            g["members"] = [m for m in (g.get("members") or []) if str(m) != target]
            g["files"] = [f for f in (g.get("files") or []) if str(f.get("id")) != target]
            if exclude:
                ex = list(map(str, g.get("excluded") or []))
                if target not in ex:
                    ex.append(target)
                g["excluded"] = ex
            if str(g.get("thumb_fid") or "") == target:
                g["thumb_fid"] = ""
            g["updated_at"] = int(time.time())
            self._save(g)
            return g
        return await asyncio.to_thread(_run)

    async def delete(self, gid):
        """Delete a group — files are only ungrouped, never removed."""
        def _run():
            old = self._delete(gid)
            return list((old or {}).get("members") or [])
        return await asyncio.to_thread(_run)

    async def pull_files(self, ids, exclude=False):
        """Remove files from every group (delete or reassign via the file editor)."""
        def _run():
            s = {str(i) for i in ids if i}
            changed = []
            for g in self._all():
                hit = s.intersection(str(m) for m in (g.get("members") or []))
                if not hit:
                    continue
                g["members"] = [m for m in g["members"] if str(m) not in s]
                g["files"] = [f for f in (g.get("files") or []) if str(f.get("id")) not in s]
                if str(g.get("thumb_fid") or "") in s:
                    g["thumb_fid"] = ""
                if exclude:
                    g["excluded"] = sorted(set(map(str, g.get("excluded") or [])) | s)
                g["updated_at"] = int(time.time())
                self._save(g)
                changed.append(str(g["_id"]))
            return changed
        return await asyncio.to_thread(_run)

    async def cleanup_empty(self):
        """Drop groups with fewer than 2 members and clear their file markers."""
        def _run():
            gone, ungrouped = [], {}
            for g in self._all():
                members = [str(m) for m in (g.get("members") or [])]
                if len(members) < 2:
                    gid = str(g["_id"])
                    self._delete(gid)
                    gone.append(gid)
                    ungrouped.setdefault(gid, []).extend(members)
            return gone, ungrouped

        gone, ungrouped = await asyncio.to_thread(_run)
        for gid, members in ungrouped.items():
            await self.mark_files(members, "", only_if=gid)
        return gone

    async def merge(self, source, target):
        """Move all files/auto_keys from the source group into the target; drop the source."""
        src = await self.get(source)
        tgt = await self.get(target)
        if not src or not tgt:
            return None
        items = [(i, next((f.get("name", "") for f in (src.get("files") or [])
                           if str(f.get("id")) == str(i)), "")) for i in src.get("members") or []]
        keys = list(src.get("auto_keys") or []) + list(tgt.get("auto_keys") or [])
        await self.add_members(str(tgt["_id"]), items, auto_keys=keys)
        await self.delete(str(src["_id"]))
        return await self.get(target)

    # ── file collection helpers (fsv1 has just one collection) ────────────
    async def mark_files(self, ids, gid, only_if=None):
        """Mark / unset `group_id`; `only_if` guards cleanup against stale memberships."""
        ids = [str(i) for i in ids if i]
        if not ids:
            return 0
        def _run():
            col = file_collection()
            if col is None:
                return 0
            try:
                upd = {"$set": {"group_id": str(gid)}} if gid else {"$unset": {"group_id": ""}}
                query = {"_id": {"$in": ids}}
                if only_if is not None:
                    query["group_id"] = str(only_if)
                res = col.update_many(query, upd)
                return int(getattr(res, "modified_count", 0) or 0)
            except Exception as e:
                logger.warning(f"group mark_files skipped: {e}")
                return 0
        return await asyncio.to_thread(_run)

    async def files_by_ids(self, ids):
        """Full documents for all group members, even those not on the current page."""
        ids = [str(i) for i in ids if i]
        if not ids:
            return []
        def _run():
            col = file_collection()
            if col is None:
                return []
            try:
                return list(col.find({"_id": {"$in": ids}}))
            except Exception as e:
                logger.warning(f"group files_by_ids skipped: {e}")
                return []
        return await asyncio.to_thread(_run)

    async def scan_files(self, limit=20000):
        """Lightweight `{_id, file_name, group_id, duration}` list used by scan-all."""
        def _run():
            col = file_collection()
            if col is None:
                return []
            try:
                return list(col.find({}, {"_id": 1, "file_name": 1, "group_id": 1,
                                          "duration": 1}).limit(limit))
            except Exception as e:
                logger.warning(f"group scan_files skipped: {e}")
                return []
        return await asyncio.to_thread(_run)

    async def count(self):
        def _run():
            return len(self._all())
        return await asyncio.to_thread(_run)

    async def kind_counts(self):
        # /stats: number of quality groups, series groups and episodes in total
        def _run():
            out = {"quality_groups": 0, "episode_groups": 0, "episodes_total": 0}
            for d in self._all():
                m = group_kind_meta(d)
                if m["kind"] == KIND_EPISODES:
                    out["episode_groups"] += 1
                    out["episodes_total"] += m["episodes"]
                else:
                    out["quality_groups"] += 1
            return out
        return await asyncio.to_thread(_run)


store = GroupStore(dbase)
