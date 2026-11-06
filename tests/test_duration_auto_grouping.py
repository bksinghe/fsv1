#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Duration-aware automatic quality/series grouping regression tests.

The route functions are loaded from their AST so these tests need no aiohttp,
MongoDB, Telegram bot, or running application.
"""
import ast
import asyncio
import copy
import logging
import time
import unittest
from collections import defaultdict
from pathlib import Path
from unittest.mock import patch

from database import group_db

ROOT = Path(__file__).resolve().parents[1]


def load_functions(path, names, namespace):
    source = Path(path).read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    functions = [node for node in tree.body
                 if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and node.name in names]
    found = {node.name for node in functions}
    if found != set(names):
        raise AssertionError(f"missing functions: {set(names) - found}")
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(path), "exec"), namespace)
    return namespace


class MemoryStore:
    """Small async store implementing the GroupStore methods used by these paths."""

    def __init__(self, files=()):
        self.files = {str(d["_id"]): copy.deepcopy(d) for d in files}
        self.groups = {}
        self.sequence = 0

    async def all_groups(self):
        return copy.deepcopy(list(self.groups.values()))

    async def scan_files(self, limit=20000):
        return copy.deepcopy(list(self.files.values())[:limit])

    async def by_members(self, ids):
        ids = {str(i) for i in ids if i}
        return [copy.deepcopy(g) for g in self.groups.values()
                if ids.intersection(str(i) for i in g.get("members", []))]

    async def by_keys(self, keys):
        keys = {str(k) for k in keys if k}
        return [copy.deepcopy(g) for g in self.groups.values()
                if keys.intersection(str(k) for k in g.get("auto_keys", []))]

    async def files_by_ids(self, ids):
        return [copy.deepcopy(self.files[str(i)]) for i in ids if str(i) in self.files]

    async def create(self, *, name, items, auto_keys=(), auto_created=False,
                     scan_created=False, kind=group_db.KIND_QUALITIES,
                     episode_map=None):
        self.sequence += 1
        gid = str(self.sequence)
        group = {
            "_id": gid,
            "num": self.sequence,
            "name": name,
            "members": [str(fid) for fid, _ in items],
            "files": [{"id": str(fid), "name": str(n)} for fid, n in items],
            "auto_keys": sorted(set(auto_keys)),
            "excluded": [],
            "thumb_fid": "",
            "thumb_url": "",
            "kind": kind,
            "episode_map": dict(episode_map or {}),
            "auto_created": bool(auto_created),
            "scan_created": bool(scan_created),
            "updated_at": int(time.time()),
        }
        self.groups[gid] = group
        return copy.deepcopy(group)

    async def update(self, gid, fields):
        group = self.groups.get(str(gid))
        if not group:
            return None
        group.update(copy.deepcopy(fields))
        group["updated_at"] = int(time.time())
        return copy.deepcopy(group)

    async def add_members(self, gid, items, auto_keys=(), unexclude=True, scanned_at=0):
        group = self.groups.get(str(gid))
        if not group:
            return None
        members = list(group.get("members") or [])
        by_id = {str(f["id"]): f for f in (group.get("files") or [])}
        for fid, name in items:
            fid = str(fid)
            if fid not in members:
                members.append(fid)
            by_id[fid] = {"id": fid, "name": str(name or "")}
        group["members"] = members
        group["files"] = [by_id[fid] for fid in members]
        group["auto_keys"] = sorted(set(group.get("auto_keys") or []) | set(auto_keys))
        if unexclude:
            added = {str(fid) for fid, _ in items}
            group["excluded"] = [fid for fid in group.get("excluded", [])
                                  if str(fid) not in added]
        if scanned_at:
            group["scanned_at"] = scanned_at
        group["updated_at"] = int(time.time())
        return copy.deepcopy(group)

    async def mark_files(self, ids, gid, only_if=None):
        for fid in ids:
            doc = self.files.get(str(fid))
            if not doc:
                continue
            if only_if is not None and str(doc.get("group_id") or "") != str(only_if):
                continue
            if gid:
                doc["group_id"] = str(gid)
            else:
                doc.pop("group_id", None)

    async def cleanup_empty(self):
        for gid in [gid for gid, g in self.groups.items() if not g.get("members")]:
            del self.groups[gid]


ROUTE_NAMESPACE = {
    "asyncio": asyncio,
    "time": time,
    "defaultdict": defaultdict,
    "logger": logging.getLogger("duration_auto_group_test"),
    "SCAN_STATE": {},
    "SCAN_MAX_GROUP": 30,
    "SCAN_MAX_SERIES": 500,
    "_AUTO_GROUP_LOCK": asyncio.Lock(),
    "_group_thumb_url": lambda _g, _variants: "",
}
for _name in (
    "title_key", "series_key", "group_title", "series_title", "quality_label",
    "episode_chips", "episode_label", "episode_identity", "duration_seconds",
    "detect_episodes", "guess_kind", "normal_kind", "clean_episode_map",
    "KIND_QUALITIES", "KIND_EPISODES",
):
    ROUTE_NAMESPACE[_name] = getattr(group_db, _name)
load_functions(
    ROOT / "web" / "group_routes.py",
    {"_group_member_meta", "_auto_join_compatible", "_persist_auto_group",
     "group_cards", "_scan_all_groups"},
    ROUTE_NAMESPACE,
)

INDEX_NAMESPACE = {}
load_functions(ROOT / "database" / "ia_filterdb.py", {"_auto_join_group"}, INDEX_NAMESPACE)


class TestDurationAwareSearchGrouping(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.store = MemoryStore()
        ROUTE_NAMESPACE["store"] = self.store

    async def test_quality_groups_require_matching_positive_durations_and_are_persisted(self):
        cards = [
            {"file_id": "q1", "name": "Alpha Feature Film 1080p.mkv",
             "duration": "1:30:00", "duration_seconds": 5400},
            {"file_id": "q2", "name": "Alpha Feature Film 720p.mkv",
             "duration": "1:30:00", "duration_seconds": 5400},
            {"file_id": "q3", "name": "Alpha Feature Film 480p.mkv",
             "duration": "1:30:01", "duration_seconds": 5401},
            {"file_id": "q4", "name": "Alpha Feature Film 360p.mkv",
             "duration": "", "duration_seconds": 0},
        ]

        grouped = await ROUTE_NAMESPACE["group_cards"](cards)
        self.assertEqual(len(self.store.groups), 1)
        group = next(iter(self.store.groups.values()))
        self.assertEqual(group["kind"], group_db.KIND_QUALITIES)
        self.assertEqual(set(group["members"]), {"q1", "q2"})
        self.assertEqual(sum(bool(card.get("group")) for card in grouped), 1)
        self.assertEqual({card.get("file_id") for card in grouped if not card.get("group")},
                         {"q3", "q4"})

        # A repeated search finds the saved group instead of creating a duplicate.
        await ROUTE_NAMESPACE["group_cards"](cards)
        self.assertEqual(len(self.store.groups), 1)

    async def test_different_episode_durations_share_a_persisted_series_group(self):
        cards = [
            {"file_id": "e1", "name": "North Star S01E01 1080p.mkv",
             "duration": "24:00", "duration_seconds": 1440},
            {"file_id": "e2", "name": "North Star S01E02 720p.mkv",
             "duration": "47:00", "duration_seconds": 2820},
            {"file_id": "e3", "name": "North Star S02E01 1080p.mkv",
             "duration": "31:00", "duration_seconds": 1860},
        ]
        grouped = await ROUTE_NAMESPACE["group_cards"](cards)
        self.assertEqual(len(self.store.groups), 1)
        group = next(iter(self.store.groups.values()))
        self.assertEqual(group["kind"], group_db.KIND_EPISODES)
        self.assertEqual(group["auto_keys"], [group_db.series_key(cards[0]["name"])])
        group_card = next(card for card in grouped if card.get("group"))
        self.assertEqual(group_card["kind"], group_db.KIND_EPISODES)
        self.assertEqual(group_card["episodes"], 3)
        self.assertEqual(group_card["duration"], "")

    async def test_series_join_rejects_incomplete_member_metadata(self):
        self.store.files["known"] = {
            "_id": "known", "file_name": "North Star S01E01.mkv", "duration": 1500,
        }
        group = await self.store.create(
            name="North Star", items=[("known", "North Star S01E01.mkv"),
                                      ("missing", "North Star S01E02.mkv")],
            auto_keys=[group_db.series_key("North Star S01E01.mkv")],
            kind=group_db.KIND_EPISODES,
        )
        compatible = await ROUTE_NAMESPACE["_auto_join_compatible"](
            group, {"name": "North Star S01E03.mkv", "duration_seconds": 2100},
            {}, {},
        )
        self.assertFalse(compatible)

    async def test_series_titles_sharing_four_word_prefix_are_not_merged(self):
        cards = [
            {"file_id": "batman", "name": "The Amazing Adventures of Batman S01E01.mkv",
             "duration_seconds": 1800},
            {"file_id": "superman", "name": "The Amazing Adventures of Superman S01E02.mkv",
             "duration_seconds": 1800},
        ]
        grouped = await ROUTE_NAMESPACE["group_cards"](cards)
        self.assertEqual(self.store.groups, {})
        self.assertEqual(len(grouped), 2)

    async def test_short_numeric_series_title_is_still_grouped_by_episode_identity(self):
        cards = [
            {"file_id": "24e1", "name": "24 S01E01 1080p.mkv", "duration_seconds": 1800},
            {"file_id": "24e2", "name": "24 S01E02 720p.mkv", "duration_seconds": 2100},
        ]
        grouped = await ROUTE_NAMESPACE["group_cards"](cards)
        self.assertEqual(len(self.store.groups), 1)
        group = next(iter(self.store.groups.values()))
        self.assertEqual(group["auto_keys"], ["24"])
        self.assertEqual(group["kind"], group_db.KIND_EPISODES)
        self.assertTrue(any(card.get("group") for card in grouped))

    async def test_large_search_quality_bucket_is_left_ungrouped(self):
        cards = [
            {"file_id": str(i), "name": f"Alpha Feature Film 1080p (copy {i}).mkv",
             "duration_seconds": 5400}
            for i in range(31)
        ]
        grouped = await ROUTE_NAMESPACE["group_cards"](cards)
        self.assertEqual(self.store.groups, {})
        self.assertEqual(len(grouped), 31)
        self.assertTrue(all(not card.get("group") for card in grouped))

    async def test_unequal_or_unknown_quality_durations_never_form_search_groups(self):
        cards = [
            {"file_id": "a", "name": "Quiet River 1080p.mkv", "duration_seconds": 6000},
            {"file_id": "b", "name": "Quiet River 720p.mkv", "duration_seconds": 6001},
            {"file_id": "c", "name": "Blue Valley 1080p.mkv", "duration_seconds": 0},
            {"file_id": "d", "name": "Blue Valley 720p.mkv", "duration_seconds": 0},
        ]
        grouped = await ROUTE_NAMESPACE["group_cards"](cards)
        self.assertEqual(self.store.groups, {})
        self.assertEqual(len(grouped), len(cards))
        self.assertTrue(all(not card.get("group") for card in grouped))


class TestWholeLibraryScanGrouping(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        files = [
            {"_id": "q1", "file_name": "Alpha Feature Film 1080p.mkv", "duration": 5400},
            {"_id": "q2", "file_name": "Alpha Feature Film 720p.mkv", "duration": 5400},
            {"_id": "qdiff", "file_name": "Alpha Feature Film 480p.mkv", "duration": 5401},
            {"_id": "u1", "file_name": "Beta Feature Film 1080p.mkv", "duration": 0},
            {"_id": "u2", "file_name": "Beta Feature Film 720p.mkv", "duration": 0},
            {"_id": "e1", "file_name": "Good Series S01E01 1080p.mkv", "duration": 1800},
            {"_id": "e2", "file_name": "Good Series S01E02 720p.mkv", "duration": 2700},
        ]
        self.store = MemoryStore(files)
        ROUTE_NAMESPACE["store"] = self.store
        ROUTE_NAMESPACE["SCAN_STATE"].clear()

    async def test_scan_partitions_by_duration_and_joins_series_across_durations_idempotently(self):
        scan = ROUTE_NAMESPACE["_scan_all_groups"]
        await scan()
        self.assertEqual(ROUTE_NAMESPACE["SCAN_STATE"]["phase"], "complete")
        self.assertEqual(ROUTE_NAMESPACE["SCAN_STATE"]["created"], 2)
        self.assertEqual(len(self.store.groups), 2)

        groups = list(self.store.groups.values())
        quality = next(g for g in groups if g["kind"] == group_db.KIND_QUALITIES)
        series = next(g for g in groups if g["kind"] == group_db.KIND_EPISODES)
        self.assertEqual(set(quality["members"]), {"q1", "q2"})
        self.assertEqual(set(series["members"]), {"e1", "e2"})
        self.assertTrue(all(g["auto_created"] and g["scan_created"] for g in groups))
        self.assertNotIn("group_id", self.store.files["qdiff"])
        self.assertNotIn("group_id", self.store.files["u1"])
        self.assertNotIn("group_id", self.store.files["u2"])

        # New same-duration quality and same-series episode files join the existing
        # groups. The episode's runtime may differ; the quality runtime may not.
        self.store.files["q3"] = {
            "_id": "q3", "file_name": "Alpha Feature Film 4K.mkv", "duration": 5400,
        }
        self.store.files["e3"] = {
            "_id": "e3", "file_name": "Good Series S01E03 480p.mkv", "duration": 2100,
        }
        await scan()
        self.assertEqual(ROUTE_NAMESPACE["SCAN_STATE"]["added"], 2)
        quality = next(g for g in self.store.groups.values()
                       if g["kind"] == group_db.KIND_QUALITIES)
        series = next(g for g in self.store.groups.values()
                      if g["kind"] == group_db.KIND_EPISODES)
        self.assertIn("q3", quality["members"])
        self.assertIn("e3", series["members"])
        self.assertNotIn("qdiff", quality["members"])

        await scan()
        self.assertEqual(ROUTE_NAMESPACE["SCAN_STATE"]["created"], 0)
        self.assertEqual(ROUTE_NAMESPACE["SCAN_STATE"]["added"], 0)
        self.assertEqual(len(self.store.groups), 2)


class TestIndexTimeAutoJoin(unittest.IsolatedAsyncioTestCase):
    async def test_quality_duration_must_match_but_series_duration_may_differ(self):
        quality_store = MemoryStore([
            {"_id": "old", "file_name": "Red Planet 1080p.mkv", "duration": 5000},
            {"_id": "good", "file_name": "Red Planet 720p.mkv", "duration": 5000},
        ])
        quality = await quality_store.create(
            name="Red Planet", items=[("old", "Red Planet 1080p.mkv")],
            auto_keys=[group_db.title_key("Red Planet 1080p.mkv")],
            kind=group_db.KIND_QUALITIES,
        )
        with patch.object(group_db, "store", quality_store):
            await INDEX_NAMESPACE["_auto_join_group"]("good", "Red Planet 720p.mkv", 5000)
        self.assertIn("good", quality_store.groups[quality["_id"]]["members"])

        mismatch_store = MemoryStore([
            {"_id": "old", "file_name": "Red Planet 1080p.mkv", "duration": 5000},
            {"_id": "bad", "file_name": "Red Planet 720p.mkv", "duration": 5001},
        ])
        mismatch = await mismatch_store.create(
            name="Red Planet", items=[("old", "Red Planet 1080p.mkv")],
            auto_keys=[group_db.title_key("Red Planet 1080p.mkv")],
            kind=group_db.KIND_QUALITIES,
        )
        with patch.object(group_db, "store", mismatch_store):
            await INDEX_NAMESPACE["_auto_join_group"]("bad", "Red Planet 720p.mkv", 5001)
        self.assertEqual(mismatch_store.groups[mismatch["_id"]]["members"], ["old"])

        series_store = MemoryStore([
            {"_id": "e1", "file_name": "River Town S01E01.mkv", "duration": 1600},
            {"_id": "e2", "file_name": "River Town S01E02.mkv", "duration": 2600},
            {"_id": "e3", "file_name": "River Town S01E03.mkv", "duration": 1900},
        ])
        series = await series_store.create(
            name="River Town", items=[("e1", "River Town S01E01.mkv"),
                                      ("e2", "River Town S01E02.mkv")],
            auto_keys=[group_db.series_key("River Town S01E01.mkv")],
            kind=group_db.KIND_EPISODES,
        )
        with patch.object(group_db, "store", series_store):
            await INDEX_NAMESPACE["_auto_join_group"]("e3", "River Town S01E03.mkv", 1900)
        self.assertIn("e3", series_store.groups[series["_id"]]["members"])


class TestDurationAndEpisodeKeys(unittest.TestCase):
    def test_series_key_preserves_quality_episode_identity_separately(self):
        first = "Northern Lights S01E02 1080p.mkv"
        another = "Northern Lights S01E03 720p.mkv"
        self.assertNotEqual(group_db.title_key(first), group_db.title_key(another))
        self.assertEqual(group_db.series_key(first), group_db.series_key(another))
        self.assertNotEqual(group_db.episode_identity(first), group_db.episode_identity(another))
        self.assertEqual(
            group_db.series_title("Northern Lights [S01E02] WEB-DL 1080p.mkv"),
            "Northern Lights",
        )

    def test_duration_normalizes_numeric_and_clock_values(self):
        self.assertEqual(group_db.duration_seconds({"duration": "1:02:03"}), 3723)
        self.assertEqual(group_db.duration_seconds({"duration_seconds": 3723}), 3723)
        self.assertEqual(group_db.duration_seconds("00:00"), 0)
        self.assertEqual(group_db.duration_seconds("unknown"), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
