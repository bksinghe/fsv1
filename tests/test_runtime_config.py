#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Mongo-backed runtime config behavior without Telegram/Mongo dependencies."""

import copy
import os
import unittest
from types import SimpleNamespace

# info.py requires the normal bot settings. RuntimeConfig itself is tested with
# an injected in-memory collection, so no real network/database is contacted.
for _name, _value in {
    "API_ID": "12345",
    "API_HASH": "test-api-hash",
    "BOT_TOKEN": "12345:test-token",
    "ADMINS": "1",
    "LOG_CHANNEL": "-1001001",
    "BIN_CHANNEL": "-1001002",
    "DATA_DATABASE_URL": "mongodb://127.0.0.1:27017",
    "URL": "https://example.invalid/",
}.items():
    os.environ.setdefault(_name, _value)

from database.runtime_config import (  # noqa: E402
    RuntimeConfig,
    normalize_setting,
    parse_channel_id,
    parse_index_channel_ids,
)
from stream_security import sign_params, verify  # noqa: E402


class MemoryCollection:
    """The small subset of the PyMongo collection API used by RuntimeConfig."""

    def __init__(self):
        self.document = None

    def find_one(self, query):
        if self.document and self.document.get("_id") == query.get("_id"):
            return copy.deepcopy(self.document)
        return None

    def update_one(self, query, update, upsert=False):
        if self.document is None:
            if not upsert:
                return SimpleNamespace(matched_count=0)
            self.document = {"_id": query["_id"]}

        for key, value in update.get("$set", {}).items():
            self.document[key] = copy.deepcopy(value)
        for key in update.get("$unset", {}):
            self.document.pop(key, None)
        push = update.get("$push", {}).get("audit")
        if push:
            items = push.get("$each", [])
            self.document.setdefault("audit", []).extend(copy.deepcopy(items))
            limit = abs(push.get("$slice", 200))
            self.document["audit"] = self.document["audit"][-limit:]
        return SimpleNamespace(matched_count=1)


DEFAULTS = {
    "BIN_CHANNEL": -10010,
    "LOG_CHANNEL": -10020,
    "INDEX_CHANNELS": [-10030],
    "INDEX_LOG_CHANNEL": -10020,
    "CATALOG_STORAGE_CHANNEL": -10010,
    "USE_CAPTION_FILTER": True,
    "PROTECT_CONTENT": False,
    "IS_STREAM": True,
    "PM_FILE_DELETE_TIME": 3600,
    "RESULTS_PER_PAGE_PM": 12,
    "RESULTS_PER_PAGE_GROUP": 10,
    "MAX_WEB_RESULTS": 21,
}


def make_config(collection, env_defaults=None):
    return RuntimeConfig(
        DEFAULTS,
        env_defaults=env_defaults or {},
        collection_provider=lambda: collection,
    )


class TestChannelIdParsing(unittest.TestCase):
    def test_single_chat_id(self):
        self.assertEqual(parse_channel_id(" -100123 "), -100123)

    def test_index_ids_accept_spaces_commas_and_remove_duplicates(self):
        self.assertEqual(
            parse_index_channel_ids("-1001, -1002 -1001"),
            [-1001, -1002],
        )

    def test_index_channels_can_be_cleared(self):
        self.assertEqual(parse_index_channel_ids("none"), [])
        self.assertEqual(parse_index_channel_ids(""), [])

    def test_invalid_or_zero_chat_ids_are_rejected(self):
        for value in ("@channel", "abc", "0"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_channel_id(value)


class TestSafeSettingValidation(unittest.TestCase):
    def test_boolean_settings_accept_clear_on_off_values(self):
        self.assertTrue(normalize_setting("USE_CAPTION_FILTER", "on"))
        self.assertFalse(normalize_setting("USE_CAPTION_FILTER", "OFF"))
        self.assertTrue(normalize_setting("PROTECT_CONTENT", 1))
        self.assertFalse(normalize_setting("IS_STREAM", False))
        with self.assertRaisesRegex(ValueError, "on/off"):
            normalize_setting("IS_STREAM", "sometimes")

    def test_numeric_settings_enforce_operational_bounds(self):
        self.assertEqual(normalize_setting("PM_FILE_DELETE_TIME", 60), 60)
        self.assertEqual(normalize_setting("RESULTS_PER_PAGE_PM", "30"), 30)
        self.assertEqual(normalize_setting("MAX_WEB_RESULTS", 100), 100)
        for key, value in (
            ("PM_FILE_DELETE_TIME", 59),
            ("RESULTS_PER_PAGE_GROUP", 0),
            ("MAX_WEB_RESULTS", 101),
            ("RESULTS_PER_PAGE_PM", True),
        ):
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                normalize_setting(key, value)


class TestChannelBoundStreamLinks(unittest.TestCase):
    def test_new_links_are_bound_to_the_bin_channel(self):
        from urllib.parse import parse_qs

        params = parse_qs(sign_params(55, ttl=300, chat_id=-100123))
        self.assertEqual(params["c"], ["-100123"])
        self.assertTrue(verify(55, params["e"][0], params["s"][0], chat_id=-100123))
        self.assertFalse(verify(55, params["e"][0], params["s"][0], chat_id=-100999))

    def test_legacy_links_keep_the_original_signature_format(self):
        from urllib.parse import parse_qs

        params = parse_qs(sign_params(56, ttl=300))
        self.assertNotIn("c", params)
        self.assertTrue(verify(56, params["e"][0], params["s"][0]))


class TestRuntimeConfig(unittest.IsolatedAsyncioTestCase):
    async def test_defaults_follow_bin_and_log_when_optional_overrides_are_absent(self):
        config = make_config(MemoryCollection())
        self.assertEqual(config.get("INDEX_LOG_CHANNEL"), -10020)
        self.assertEqual(config.get("CATALOG_STORAGE_CHANNEL"), -10010)
        self.assertEqual(config.source("INDEX_LOG_CHANNEL"), "follows LOG_CHANNEL")
        self.assertEqual(config.source("CATALOG_STORAGE_CHANNEL"), "follows BIN_CHANNEL")

    async def test_log_channel_update_flows_to_index_log_until_explicitly_overridden(self):
        collection = MemoryCollection()
        config = make_config(collection)
        await config.load()
        await config.set_value("LOG_CHANNEL", -10021, actor_id=1)
        self.assertEqual(config.get("INDEX_LOG_CHANNEL"), -10021)

        await config.set_value("INDEX_LOG_CHANNEL", -10022, actor_id=1)
        await config.set_value("LOG_CHANNEL", -10023, actor_id=1)
        self.assertEqual(config.get("INDEX_LOG_CHANNEL"), -10022)
        await config.reset_value("INDEX_LOG_CHANNEL", actor_id=1)
        self.assertEqual(config.get("INDEX_LOG_CHANNEL"), -10023)

    async def test_settings_persist_and_audit_survives_a_new_config_instance(self):
        collection = MemoryCollection()
        first = make_config(collection)
        await first.load()
        event = await first.set_value("BIN_CHANNEL", -10099, actor_id=77)

        second = make_config(collection)
        await second.load()
        self.assertEqual(second.get("BIN_CHANNEL"), -10099)
        history = await second.audit_history(5)
        self.assertEqual(history[0]["id"], event["id"])
        self.assertEqual(history[0]["actor_id"], 77)
        self.assertEqual(history[0]["old_value"], -10010)
        self.assertEqual(history[0]["new_value"], -10099)

    async def test_latest_change_can_be_rolled_back_and_the_rollback_is_audited(self):
        collection = MemoryCollection()
        config = make_config(collection)
        await config.load()
        change = await config.set_value("CATALOG_STORAGE_CHANNEL", -10088, actor_id=11)
        rollback = await config.rollback_latest(change["id"], actor_id=22)

        self.assertEqual(config.get("CATALOG_STORAGE_CHANNEL"), -10010)
        self.assertEqual(rollback["action"], "rollback")
        self.assertEqual(rollback["rollback_of"], change["id"])
        self.assertEqual(rollback["actor_id"], 22)
        self.assertEqual((await config.latest_audit())["id"], rollback["id"])

    async def test_rollback_refuses_to_overwrite_a_newer_change(self):
        collection = MemoryCollection()
        config = make_config(collection)
        await config.load()
        first = await config.set_value("BIN_CHANNEL", -10040, actor_id=1)
        await config.set_value("LOG_CHANNEL", -10050, actor_id=2)
        with self.assertRaisesRegex(RuntimeError, "newer change"):
            await config.rollback_latest(first["id"], actor_id=3)

    async def test_feature_and_limit_settings_persist_audit_and_rollback(self):
        collection = MemoryCollection()
        config = make_config(collection)
        await config.load()

        caption_change = await config.set_value("USE_CAPTION_FILTER", "off", actor_id=7)
        self.assertFalse(config.get("USE_CAPTION_FILTER"))
        self.assertEqual(caption_change["old_value"], True)
        self.assertEqual(caption_change["new_value"], False)

        page_change = await config.set_value("MAX_WEB_RESULTS", 50, actor_id=7)
        self.assertEqual(config.get("MAX_WEB_RESULTS"), 50)
        await config.rollback_latest(page_change["id"], actor_id=8)
        self.assertEqual(config.get("MAX_WEB_RESULTS"), 21)
        self.assertEqual(config.get("USE_CAPTION_FILTER"), False)

        second = make_config(collection)
        await second.load()
        self.assertFalse(second.get("USE_CAPTION_FILTER"))
        self.assertEqual(second.get("MAX_WEB_RESULTS"), 21)
        self.assertEqual((await second.audit_history(5))[0]["action"], "rollback")

    async def test_reset_uses_environment_default(self):
        collection = MemoryCollection()
        config = make_config(collection, env_defaults={"INDEX_LOG_CHANNEL": -10077})
        await config.load()
        await config.set_value("INDEX_LOG_CHANNEL", -10078, actor_id=1)
        await config.reset_value("INDEX_LOG_CHANNEL", actor_id=1)
        self.assertEqual(config.get("INDEX_LOG_CHANNEL"), -10077)
        self.assertEqual(config.source("INDEX_LOG_CHANNEL"), "environment default")


if __name__ == "__main__":
    unittest.main()
