"""Mongo-backed live settings for the bot.

Channel IDs and a small allowlist of safe feature/limit settings are managed
here; credentials and security-sensitive options stay in the environment. The
collection is obtained from ia_filterdb's existing Mongo database so this
module never opens another Mongo client.
"""

from __future__ import annotations

import asyncio
import copy
import logging
import re
from datetime import datetime, timezone
from os import environ
from uuid import uuid4

import info

logger = logging.getLogger(__name__)

CHANNEL_SETTING_KEYS = (
    "BIN_CHANNEL",
    "LOG_CHANNEL",
    "INDEX_CHANNELS",
    "INDEX_LOG_CHANNEL",
    "CATALOG_STORAGE_CHANNEL",
)
BOOLEAN_SETTING_KEYS = (
    "USE_CAPTION_FILTER",
    "PROTECT_CONTENT",
    "IS_STREAM",
)
INTEGER_SETTING_RANGES = {
    # Seconds, bounded to a practical 1 minute–7 day range.
    "PM_FILE_DELETE_TIME": (60, 7 * 24 * 60 * 60),
    "RESULTS_PER_PAGE_PM": (1, 30),
    "RESULTS_PER_PAGE_GROUP": (1, 30),
    "MAX_WEB_RESULTS": (1, 100),
}
SETTING_KEYS = CHANNEL_SETTING_KEYS + BOOLEAN_SETTING_KEYS + tuple(INTEGER_SETTING_RANGES)
_CHANNEL_ID_SETTINGS = frozenset({
    "BIN_CHANNEL", "LOG_CHANNEL", "INDEX_LOG_CHANNEL", "CATALOG_STORAGE_CHANNEL"
})
_MAX_INDEX_CHANNELS = 50
_MAX_AUDIT_ENTRIES = 200
# Keep the original ID so existing channel overrides/audit history remain visible.
_DOCUMENT_ID = "channel_settings"


class ConfigValueError(ValueError):
    """Raised when a runtime setting cannot be safely normalized."""


def parse_channel_id(value) -> int:
    """Parse a non-zero Telegram chat ID supplied by an administrator."""
    if isinstance(value, bool):
        raise ConfigValueError("Send a numeric Telegram channel/chat ID.")
    try:
        channel_id = int(str(value).strip())
    except (TypeError, ValueError):
        raise ConfigValueError("Send a numeric Telegram channel/chat ID.") from None
    if channel_id == 0 or abs(channel_id) > 10**16:
        raise ConfigValueError("That Telegram chat ID is out of range.")
    return channel_id


def parse_index_channel_ids(value) -> list[int]:
    """Parse a PM entry for INDEX_CHANNELS (space/comma-separated IDs or none)."""
    text = str(value or "").strip()
    if text.lower() in {"", "none", "clear", "off"}:
        return []
    parts = re.split(r"[\s,]+", text)
    if len(parts) > _MAX_INDEX_CHANNELS:
        raise ConfigValueError(f"A maximum of {_MAX_INDEX_CHANNELS} index channels can be set.")
    out = []
    seen = set()
    for part in parts:
        channel_id = parse_channel_id(part)
        if channel_id not in seen:
            out.append(channel_id)
            seen.add(channel_id)
    return out


def normalize_setting(key: str, value):
    """Normalize persisted channel IDs, feature flags, and bounded limits."""
    if key not in SETTING_KEYS:
        raise ConfigValueError("Unknown runtime setting.")
    if key in _CHANNEL_ID_SETTINGS:
        return parse_channel_id(value)
    if key in BOOLEAN_SETTING_KEYS:
        if isinstance(value, bool):
            return value
        if isinstance(value, int) and value in (0, 1):
            return bool(value)
        normalized = str(value).strip().lower()
        if normalized in {"on", "true", "yes", "1", "enabled"}:
            return True
        if normalized in {"off", "false", "no", "0", "disabled"}:
            return False
        raise ConfigValueError("Use on/off for this setting.")
    if key in INTEGER_SETTING_RANGES:
        if isinstance(value, bool):
            raise ConfigValueError("Send a whole number for this setting.")
        try:
            number = int(str(value).strip())
        except (TypeError, ValueError):
            raise ConfigValueError("Send a whole number for this setting.") from None
        minimum, maximum = INTEGER_SETTING_RANGES[key]
        if not minimum <= number <= maximum:
            raise ConfigValueError(f"Value must be between {minimum} and {maximum}.")
        return number

    if isinstance(value, str):
        # Admin updates use numeric IDs, while this also accepts a legacy
        # environment-style list should one be copied into Mongo manually.
        value = value.strip()
        if value.lower() in {"", "none", "clear", "off"}:
            return []
        values = re.split(r"[\s,]+", value)
    elif isinstance(value, (list, tuple, set)):
        values = list(value)
    else:
        raise ConfigValueError("INDEX_CHANNELS must be a list of channel IDs.")

    if len(values) > _MAX_INDEX_CHANNELS:
        raise ConfigValueError(f"A maximum of {_MAX_INDEX_CHANNELS} index channels can be set.")
    out = []
    seen = set()
    for item in values:
        if isinstance(item, int) and not isinstance(item, bool):
            normalized = parse_channel_id(item)
        else:
            raw = str(item or "").strip()
            if re.fullmatch(r"-?\d+", raw):
                normalized = parse_channel_id(raw)
            else:
                username = raw.lstrip("@").strip()
                if not re.fullmatch(r"[A-Za-z0-9_]{1,32}", username):
                    raise ConfigValueError("INDEX_CHANNELS contains an invalid channel username/ID.")
                normalized = "@" + username
        marker = str(normalized).casefold()
        if marker not in seen:
            out.append(normalized)
            seen.add(marker)
    return out


def _copy(value):
    return copy.deepcopy(value)


def _settings_collection():
    """Reuse the database/client already created by database.ia_filterdb."""
    from database.ia_filterdb import db

    return db["bot_runtime_config"]


class RuntimeConfig:
    """Small Mongo-persisted runtime settings store with an atomic audit trail."""

    def __init__(self, defaults, env_defaults=None, collection_provider=None):
        self._defaults = {
            key: normalize_setting(key, defaults[key])
            for key in SETTING_KEYS
        }
        self._env_defaults = {
            key: normalize_setting(key, value)
            for key, value in (env_defaults or {}).items()
            if key in SETTING_KEYS
        }
        self._collection_provider = collection_provider or _settings_collection
        self._collection_obj = None
        self._overrides = {}
        self._loaded = False
        self._load_error = None
        self._lock = asyncio.Lock()

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    @property
    def load_error(self):
        return self._load_error

    def _collection(self):
        if self._collection_obj is None:
            self._collection_obj = self._collection_provider()
        return self._collection_obj

    def _effective(self, key, overrides):
        if key in overrides:
            return _copy(overrides[key])
        if key in self._env_defaults:
            return _copy(self._env_defaults[key])
        if key == "INDEX_LOG_CHANNEL":
            return self._effective("LOG_CHANNEL", overrides)
        if key == "CATALOG_STORAGE_CHANNEL":
            return self._effective("BIN_CHANNEL", overrides)
        return _copy(self._defaults[key])

    def get(self, key: str):
        """Get an effective setting; mutable values are returned as copies."""
        if key not in SETTING_KEYS:
            raise KeyError(key)
        return self._effective(key, self._overrides)

    def get_all(self):
        return {key: self.get(key) for key in SETTING_KEYS}

    def default_value(self, key: str):
        """Effective environment/default value, excluding any Mongo override."""
        if key not in SETTING_KEYS:
            raise KeyError(key)
        return self._effective(key, {})

    def has_override(self, key: str) -> bool:
        return key in self._overrides

    def source(self, key: str) -> str:
        if key in self._overrides:
            return "MongoDB override"
        if key in self._env_defaults:
            return "environment default"
        if key == "INDEX_LOG_CHANNEL":
            return "follows LOG_CHANNEL"
        if key == "CATALOG_STORAGE_CHANNEL":
            return "follows BIN_CHANNEL"
        return "environment default"

    @staticmethod
    def _overrides_from_document(document):
        overrides = {}
        if not document:
            return overrides
        for key in SETTING_KEYS:
            if key not in document:
                continue
            try:
                overrides[key] = normalize_setting(key, document[key])
            except (ConfigValueError, TypeError, ValueError) as exc:
                logger.warning("Ignoring invalid stored setting %s: %s", key, exc)
        return overrides

    async def load(self, force: bool = False) -> bool:
        """Load the persisted document before handlers start; return True on success."""
        if self._loaded and not force:
            return True
        async with self._lock:
            if self._loaded and not force:
                return True
            try:
                collection = self._collection()
                document = await asyncio.to_thread(
                    collection.find_one, {"_id": _DOCUMENT_ID}
                )
                self._overrides = self._overrides_from_document(document)
                self._loaded = True
                self._load_error = None
                return True
            except Exception as exc:
                self._loaded = False
                self._load_error = str(exc)
                logger.warning("Could not load runtime settings: %s", exc)
                raise

    async def _read_document(self):
        collection = self._collection()
        return await asyncio.to_thread(collection.find_one, {"_id": _DOCUMENT_ID})

    async def _write_document(self, key, new_overrides, event, actor_id):
        collection = self._collection()
        update = {
            "$set": {
                "updated_at": event["changed_at"],
                "updated_by": int(actor_id),
            },
            "$push": {
                "audit": {
                    "$each": [event],
                    "$slice": -_MAX_AUDIT_ENTRIES,
                }
            },
        }
        if key in new_overrides:
            update["$set"][key] = _copy(new_overrides[key])
        else:
            update["$unset"] = {key: ""}
        await asyncio.to_thread(
            collection.update_one,
            {"_id": _DOCUMENT_ID},
            update,
            upsert=True,
        )

    def _event(self, key, action, actor_id, old_overrides, new_overrides, rollback_of=None):
        old_set = key in old_overrides
        new_set = key in new_overrides
        event = {
            "id": uuid4().hex,
            "setting": key,
            "action": action,
            "actor_id": int(actor_id),
            "changed_at": datetime.now(timezone.utc),
            "old_value": self._effective(key, old_overrides),
            "new_value": self._effective(key, new_overrides),
            "old_override_set": old_set,
            "old_override": _copy(old_overrides[key]) if old_set else None,
            "new_override_set": new_set,
            "new_override": _copy(new_overrides[key]) if new_set else None,
        }
        if rollback_of:
            event["rollback_of"] = rollback_of
        return event

    async def _change(self, key, value, actor_id, *, reset=False, action=None, rollback_of=None):
        if key not in SETTING_KEYS:
            raise ConfigValueError("Unknown runtime setting.")
        if not self._loaded:
            await self.load()

        normalized = None if reset else normalize_setting(key, value)
        async with self._lock:
            collection = self._collection()
            # Refresh before auditing so changes made by another running instance
            # are not silently hidden by this process's in-memory snapshot.
            document = await asyncio.to_thread(
                collection.find_one, {"_id": _DOCUMENT_ID}
            )
            old_overrides = self._overrides_from_document(document)
            new_overrides = dict(old_overrides)
            if reset:
                new_overrides.pop(key, None)
            else:
                new_overrides[key] = normalized
            event = self._event(
                key,
                action or ("reset" if reset else "set"),
                actor_id,
                old_overrides,
                new_overrides,
                rollback_of=rollback_of,
            )
            await self._write_document(key, new_overrides, event, actor_id)
            self._overrides = new_overrides
            self._loaded = True
            self._load_error = None
            return _copy(event)

    async def set_value(self, key: str, value, actor_id: int):
        return await self._change(key, value, actor_id)

    async def reset_value(self, key: str, actor_id: int):
        """Remove a Mongo override and resume the environment/default behavior."""
        return await self._change(key, None, actor_id, reset=True)

    async def audit_history(self, limit: int = 10):
        if not self._loaded:
            await self.load()
        document = await self._read_document()
        entries = (document or {}).get("audit") or []
        limit = max(1, min(int(limit), _MAX_AUDIT_ENTRIES))
        return _copy(list(reversed(entries[-limit:])))

    async def latest_audit(self):
        entries = await self.audit_history(1)
        return entries[0] if entries else None

    def rollback_target(self, event):
        """Compute the effective value restored by rolling back this event."""
        key = event.get("setting")
        if key not in SETTING_KEYS:
            raise ConfigValueError("This audit record has an unknown setting.")
        if event.get("old_override_set"):
            return normalize_setting(key, event.get("old_override"))
        return self.default_value(key)

    async def rollback_latest(self, audit_id: str, actor_id: int):
        """Undo only the newest recorded edit, then append a rollback audit event."""
        if not self._loaded:
            await self.load()
        async with self._lock:
            collection = self._collection()
            document = await asyncio.to_thread(
                collection.find_one, {"_id": _DOCUMENT_ID}
            )
            entries = (document or {}).get("audit") or []
            if not entries:
                raise RuntimeError("There is no runtime-setting change to undo.")
            latest = entries[-1]
            if str(latest.get("id")) != str(audit_id):
                raise RuntimeError("A newer change exists. Refresh the audit panel and try again.")

            key = latest.get("setting")
            if key not in SETTING_KEYS:
                raise RuntimeError("The audit record cannot be rolled back safely.")
            current_overrides = self._overrides_from_document(document)
            current_set = key in current_overrides
            latest_new_set = bool(latest.get("new_override_set"))
            if current_set != latest_new_set or (
                current_set and current_overrides[key] != normalize_setting(key, latest.get("new_override"))
            ):
                raise RuntimeError("The setting changed since this audit record. Refresh and try again.")

            restored_overrides = dict(current_overrides)
            if latest.get("old_override_set"):
                restored_overrides[key] = normalize_setting(key, latest.get("old_override"))
            else:
                restored_overrides.pop(key, None)

            event = self._event(
                key,
                "rollback",
                actor_id,
                current_overrides,
                restored_overrides,
                rollback_of=str(latest.get("id")),
            )
            await self._write_document(key, restored_overrides, event, actor_id)
            self._overrides = restored_overrides
            self._loaded = True
            self._load_error = None
            return _copy(event)


_DEFAULTS = {
    "BIN_CHANNEL": info.BIN_CHANNEL,
    "LOG_CHANNEL": info.LOG_CHANNEL,
    "INDEX_CHANNELS": info.INDEX_CHANNELS,
    "INDEX_LOG_CHANNEL": info.INDEX_LOG_CHANNEL,
    "CATALOG_STORAGE_CHANNEL": info.CATALOG_STORAGE_CHANNEL,
    "USE_CAPTION_FILTER": info.USE_CAPTION_FILTER,
    "PROTECT_CONTENT": info.PROTECT_CONTENT,
    "IS_STREAM": info.IS_STREAM,
    "PM_FILE_DELETE_TIME": info.PM_FILE_DELETE_TIME,
    "RESULTS_PER_PAGE_PM": info.RESULTS_PER_PAGE_PM,
    "RESULTS_PER_PAGE_GROUP": info.RESULTS_PER_PAGE_GROUP,
    "MAX_WEB_RESULTS": info.MAX_WEB_RESULTS,
}
_ENV_DEFAULTS = {}
if environ.get("INDEX_LOG_CHANNEL"):
    _ENV_DEFAULTS["INDEX_LOG_CHANNEL"] = info.INDEX_LOG_CHANNEL
if environ.get("CATALOG_STORAGE_CHANNEL"):
    _ENV_DEFAULTS["CATALOG_STORAGE_CHANNEL"] = info.CATALOG_STORAGE_CHANNEL

runtime_config = RuntimeConfig(_DEFAULTS, env_defaults=_ENV_DEFAULTS)
