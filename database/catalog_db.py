"""📚 Unified catalog store — Posts + Directory profiles.

In the reference implementation, `web/post_routes.py` and `web/actor_routes.py` used separate collections,
separate CRUD helpers and two ~700-line pages. Here both share **one** store:

* `_id` is a short random hex string (not an ObjectId), so invalid ids cannot crash
  the app, there is no bson dependency and URLs stay readable.
* fsv1 uses synchronous PyMongo, so every DB call runs via `asyncio.to_thread()`.
* When MongoDB is unavailable (local development / preview) a transparent
  **in-memory fallback** keeps the feature working (production always uses Mongo).
* `created_at` / `updated_at` are managed automatically; writes are idempotent.
"""

import asyncio
import logging
import re
import secrets
import time

try:
    from database.users_chats_db import dbase
except Exception:                                  # pragma: no cover - preview/local
    dbase = None

logger = logging.getLogger(__name__)

KINDS = ("posts", "actors")
_FIELDS = ("title", "category", "body", "tags", "image", "gallery", "links", "videos")


def _now() -> int:
    return int(time.time())


def _public(doc: dict) -> dict:
    out = {k: v for k, v in doc.items() if not k.startswith("_")}
    out["id"] = str(doc.get("_id") or "")
    return out


class _Memory:
    """Small in-memory store used when MongoDB is unavailable (preview / unit tests)."""

    def __init__(self):
        self.data = {k: {} for k in KINDS}

    def list(self, kind, rx, category, offset, limit):
        docs = sorted(
            self.data[kind].values(),
            key=lambda d: d.get("created_at", 0),
            reverse=True,
        )
        out = []
        for d in docs:
            if category and d.get("category") != category:
                continue
            if rx:
                hay = " ".join(
                    str(d.get(f) or "") for f in ("title", "body", "category")
                ) + " " + " ".join(str(t) for t in (d.get("tags") or []))
                if rx not in hay.lower():
                    continue
            out.append(dict(d))
        return out[offset:offset + limit + 1]

    def count(self, kind, rx, category):
        return len(self._all(kind, rx, category))

    def _all(self, kind, rx, category):
        out = []
        for d in self.data[kind].values():
            if category and d.get("category") != category:
                continue
            if rx:
                hay = " ".join(
                    str(d.get(f) or "") for f in ("title", "body", "category")
                ) + " " + " ".join(str(t) for t in (d.get("tags") or []))
                if rx not in hay.lower():
                    continue
            out.append(d)
        return out

    def get(self, kind, item_id):
        return self.data[kind].get(item_id)

    def save(self, kind, item_id, doc):
        self.data[kind][item_id] = doc
        return doc

    def delete(self, kind, item_id):
        return self.data[kind].pop(item_id, None) is not None


class CatalogStore:
    def __init__(self, database):
        self.cols = (
            {k: database[f"catalog_{k}"] for k in KINDS} if database is not None else None
        )
        self.mem = _Memory() if self.cols is None else None
        if self.cols:
            self._indexes()
        else:
            logger.warning("⚠️ catalog: MongoDB unavailable — using the in-memory fallback")

    def _indexes(self):
        for kind, col in self.cols.items():
            try:
                col.create_index("created_at")
                col.create_index(
                    [("title", "text"), ("body", "text"), ("tags", "text")],
                    name="catalog_text",
                )
            except Exception as e:
                logger.debug(f"catalog index skipped ({kind}): {e}")

    @staticmethod
    def _mongo_query(rx: str, category: str) -> dict:
        query = {}
        if category and category != "all":
            query["category"] = category
        if rx:
            r = {"$regex": re.escape(rx), "$options": "i"}
            query["$or"] = [
                {"title": r}, {"body": r}, {"tags": r}, {"category": r},
            ]
        return query

    async def list_items(self, kind, q="", category="", offset=0, limit=20):
        """Return (items, has_next) — newest first, paginated with the limit+1 trick."""
        kind = self._kind(kind)
        rx = str(q or "").strip().lower()
        cat = str(category or "").strip()
        offset, limit = max(0, int(offset)), max(1, min(int(limit), 60))
        if self.cols:
            def _do():
                cur = (
                    self.cols[kind]
                    .find(self._mongo_query(rx, cat))
                    .sort("created_at", -1)
                    .skip(offset)
                    .limit(limit + 1)
                )
                return [dict(d) for d in cur]
            docs = await asyncio.to_thread(_do)
        else:
            docs = self.mem.list(kind, rx, cat if cat != "all" else "", offset, limit)
        return [_public(d) for d in docs[:limit]], len(docs) > limit

    async def count(self, kind, q="", category=""):
        kind = self._kind(kind)
        rx = str(q or "").strip().lower()
        cat = str(category or "").strip()
        if self.cols:
            def _do():
                return self.cols[kind].count_documents(self._mongo_query(rx, cat))
            return await asyncio.to_thread(_do)
        return self.mem.count(kind, rx, cat if cat != "all" else "")

    async def get_item(self, kind, item_id):
        kind = self._kind(kind)
        if self.cols:
            doc = await asyncio.to_thread(self.cols[kind].find_one, {"_id": item_id})
        else:
            doc = self.mem.get(kind, item_id)
        return _public(dict(doc)) if doc else None

    async def save_item(self, kind, data: dict, item_id: str = "", allow_create: bool = False):
        """Create or update an item — always returns the complete public record.

        `allow_create=True` is used only by Undo-delete: when the entry is already gone,
        it is recreated under the same id so existing `/post/<id>` links keep working.
        """
        kind = self._kind(kind)
        clean = {k: data.get(k) for k in _FIELDS if k in data}
        now = _now()
        clean["updated_at"] = now

        if item_id:
            existing = await self.get_item(kind, item_id)
            if not existing and not allow_create:
                return None
            created = existing.get("created_at", now) if existing else now
        else:
            item_id = secrets.token_hex(8)
            created = now

        doc = {**clean, "_id": item_id, "created_at": created}
        if self.cols:
            await asyncio.to_thread(
                self.cols[kind].replace_one, {"_id": item_id}, doc, True
            )
        else:
            self.mem.save(kind, item_id, doc)
        return _public(doc)

    async def delete_item(self, kind, item_id) -> bool:
        kind = self._kind(kind)
        if self.cols:
            res = await asyncio.to_thread(self.cols[kind].delete_one, {"_id": item_id})
            return bool(res.deleted_count)
        return self.mem.delete(kind, item_id)

    async def counts(self) -> dict:
        return {k: await self.count(k) for k in KINDS}

    @staticmethod
    def _kind(kind):
        return kind if kind in KINDS else KINDS[0]


store = CatalogStore(dbase)
