"""Private-chat admin UI for safe, live bot and Telegram channel settings."""

import html
import logging
import re
import secrets
import time
from datetime import datetime, timezone

from hydrogram import Client, enums, filters
from hydrogram.errors import ListenerTimeout
from hydrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from info import ADMINS
from database.runtime_config import (
    BOOLEAN_SETTING_KEYS,
    CHANNEL_SETTING_KEYS,
    INTEGER_SETTING_RANGES,
    ConfigValueError,
    normalize_setting,
    parse_index_channel_ids,
    runtime_config,
)

logger = logging.getLogger(__name__)

_CHANNEL_SETTINGS = {
    "bin": ("BIN_CHANNEL", "📦 BIN channel", "File storage and Telegram streaming cache"),
    "log": ("LOG_CHANNEL", "📋 LOG channel", "Bot event logs and admin-setting audit"),
    "index": ("INDEX_CHANNELS", "📥 INDEX channels", "Automatic source indexing"),
    "index_log": ("INDEX_LOG_CHANNEL", "🧾 INDEX log channel", "Indexer logs"),
    "catalog": ("CATALOG_STORAGE_CHANNEL", "🗂 Catalog storage", "Posters and catalog images"),
}
_FEATURE_SETTINGS = {
    "caption": (
        "USE_CAPTION_FILTER",
        "🔎 Caption search",
        "Search captions as well as filenames. Off uses filename-only search and may be slower.",
    ),
    "protect": (
        "PROTECT_CONTENT",
        "🛡️ Protect PM files",
        "Prevents forwarding/saving newly delivered private-chat files where Telegram supports it.",
    ),
    "stream": (
        "IS_STREAM",
        "▶️ PM stream buttons",
        "Controls new Watch / Download buttons; disabling also rejects old stream buttons.",
    ),
    "delete_time": (
        "PM_FILE_DELETE_TIME",
        "⏱ PM file auto-delete",
        "Timeout for new private deliveries only; existing deletion timers are unchanged.",
    ),
    "pm_results": (
        "RESULTS_PER_PAGE_PM",
        "📄 PM results per page",
        "Number of file results shown per private-chat search page.",
    ),
    "group_results": (
        "RESULTS_PER_PAGE_GROUP",
        "👥 Group results per page",
        "Number of file results shown per group search page.",
    ),
    "web_results": (
        "MAX_WEB_RESULTS",
        "🌐 Web results per page",
        "Maximum number of results returned to the web search for each page.",
    ),
}
_SETTINGS = {**_CHANNEL_SETTINGS, **_FEATURE_SETTINGS}
_BOOLEAN_KEYS = frozenset(BOOLEAN_SETTING_KEYS)
_MAX_PENDING_SECONDS = 5 * 60
_PENDING_CHANGES = {}
_ACTIVE_INPUTS = set()


def _button(text, data):
    return InlineKeyboardButton(text, callback_data=data)


def _home_markup():
    return InlineKeyboardMarkup([
        [
            _button("📦 BIN", "admincfg:set:bin"),
            _button("📋 LOG", "admincfg:set:log"),
        ],
        [
            _button("📥 INDEX", "admincfg:set:index"),
            _button("🧾 INDEX log", "admincfg:set:index_log"),
        ],
        [_button("🗂 Catalog storage", "admincfg:set:catalog")],
        [_button("⚙️ Features & limits", "admincfg:features")],
        [
            _button("🕘 Audit / undo", "admincfg:audit"),
            _button("🔄 Refresh", "admincfg:home"),
        ],
        [_button("✖️ Close", "admincfg:close")],
    ])


def _features_markup():
    rows = []
    for token in ("caption", "protect", "stream"):
        key, label, _description = _FEATURE_SETTINGS[token]
        state = "ON" if runtime_config.get(key) else "OFF"
        rows.append([
            _button(f"{label}: {state}", f"admincfg:toggle:{token}"),
            _button("Default", f"admincfg:reset:{token}"),
        ])
    for token in ("delete_time", "pm_results", "group_results", "web_results"):
        key, label, _description = _FEATURE_SETTINGS[token]
        rows.append([
            _button(f"{label}: {_button_value(key)}", f"admincfg:set:{token}"),
            _button("Default", f"admincfg:reset:{token}"),
        ])
    rows.extend([
        [_button("🕘 Audit / undo", "admincfg:audit"), _button("🔙 Back", "admincfg:home")],
        [_button("✖️ Close", "admincfg:close")],
    ])
    return InlineKeyboardMarkup(rows)


def _escape(value):
    return html.escape(str(value), quote=False)


def _plain_alert(value):
    return re.sub(r"<[^>]*>", "", str(value))[:190]


def _format_duration(seconds):
    seconds = int(seconds)
    if seconds % 86400 == 0:
        days = seconds // 86400
        return f"{days} day" + ("s" if days != 1 else "")
    if seconds % 3600 == 0:
        hours = seconds // 3600
        return f"{hours} hour" + ("s" if hours != 1 else "")
    if seconds % 60 == 0:
        minutes = seconds // 60
        return f"{minutes} min"
    return f"{seconds} sec"


def _button_value(key):
    value = runtime_config.get(key)
    if key == "PM_FILE_DELETE_TIME":
        return _format_duration(value)
    return str(value)


def _format_value(key, value):
    if key == "INDEX_CHANNELS":
        if not value:
            return "<i>none</i>"
        return ", ".join(f"<code>{_escape(item)}</code>" for item in value)
    if key in _BOOLEAN_KEYS:
        return f"<code>{'ON' if value else 'OFF'}</code>"
    if key == "PM_FILE_DELETE_TIME":
        return f"<code>{_escape(_format_duration(value))}</code>"
    return f"<code>{_escape(value)}</code>"


def _setting_name(key):
    for setting, label, _description in _SETTINGS.values():
        if setting == key:
            return label
    return key


def _format_audit_value(key, value):
    if key == "INDEX_CHANNELS" and isinstance(value, (list, tuple)) and len(value) > 5:
        return _format_value(key, value[:5]) + f" <i>+{len(value) - 5} more</i>"
    return _format_value(key, value)


def _format_time(value):
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return "time unavailable"


async def _panel_text():
    lines = [
        "🛡️ <b>Bot Admin Panel</b>",
        "🟢 Status: bot online · settings loaded from MongoDB",
        "",
        "<b>Channels</b>",
    ]
    for key, label, description in _CHANNEL_SETTINGS.values():
        lines.append(
            f"{label}: {_format_value(key, runtime_config.get(key))}"
            f"  <i>({html.escape(runtime_config.source(key))})</i>"
        )
        lines.append(f"   <i>{html.escape(description)}</i>")
    lines.extend(["", "<b>Features &amp; limits</b>"])
    for key, label, description in _FEATURE_SETTINGS.values():
        lines.append(
            f"{label}: {_format_value(key, runtime_config.get(key))}"
            f"  <i>({html.escape(runtime_config.source(key))})</i>"
        )
        lines.append(f"   <i>{html.escape(description)}</i>")
    lines.extend([
        "",
        "Changes apply live; no restart is normally needed. Each change is audited.",
        "Auto-delete changes apply to new deliveries; existing timers keep their original timeout.",
        "Credentials, payment settings, and security-sensitive link options are not managed here.",
    ])
    latest = await runtime_config.latest_audit()
    if latest:
        lines.extend([
            "",
            f"Last change: <b>{html.escape(_setting_name(latest.get('setting', '')))}</b> "
            f"by <code>{_escape(latest.get('actor_id', 'unknown'))}</code> "
            f"at {_escape(_format_time(latest.get('changed_at')))}.",
        ])
    return "\n".join(lines)


def _features_text():
    lines = [
        "⚙️ <b>Features &amp; limits</b>",
        "Changes are confirmed before saving; numeric values are bounded.",
        "",
    ]
    for key, label, description in _FEATURE_SETTINGS.values():
        lines.append(f"{label}: {_format_value(key, runtime_config.get(key))}")
        lines.append(f"   <i>{html.escape(description)}</i>")
    lines.extend([
        "",
        "Caption filtering affects bot and web searches immediately.",
        "Turning off PM stream buttons also rejects previously sent stream buttons.",
        "PM auto-delete timing changes apply only to new deliveries.",
    ])
    return "\n".join(lines)


def _is_private_admin(query):
    user = getattr(query, "from_user", None)
    message = getattr(query, "message", None)
    return bool(
        user
        and user.id in ADMINS
        and message
        and getattr(getattr(message, "chat", None), "type", None) == enums.ChatType.PRIVATE
    )


def _status_name(member):
    status = getattr(member, "status", "")
    return str(getattr(status, "name", None) or status).rsplit(".", 1)[-1].upper()


def _chat_reference(value):
    if isinstance(value, str):
        raw = value.strip()
        if raw and not raw.lstrip("-").isdigit():
            return "@" + raw.lstrip("@")
        if raw:
            return int(raw)
    return value


async def _validate_one_chat(client, key, value, bot_id):
    try:
        chat = await client.get_chat(_chat_reference(value))
    except Exception as exc:
        raise ConfigValueError(
            f"Telegram could not access <code>{_escape(value)}</code>. "
            "Check the ID and make sure the bot has been added."
        ) from exc

    chat_type = getattr(chat, "type", None)
    if key == "INDEX_CHANNELS":
        if chat_type != enums.ChatType.CHANNEL:
            raise ConfigValueError(
                f"<code>{_escape(value)}</code> is not a channel. INDEX_CHANNELS accepts channels only."
            )
    elif chat_type not in {
        enums.ChatType.CHANNEL,
        enums.ChatType.GROUP,
        enums.ChatType.SUPERGROUP,
    }:
        raise ConfigValueError(
            f"<code>{_escape(value)}</code> is not a channel or group that can receive bot messages."
        )

    try:
        member = await client.get_chat_member(chat.id, bot_id)
    except Exception as exc:
        raise ConfigValueError(
            f"Could not verify the bot's membership in <code>{_escape(value)}</code>."
        ) from exc

    status = _status_name(member)
    if key == "INDEX_CHANNELS":
        if status not in {"OWNER", "ADMINISTRATOR"}:
            raise ConfigValueError(
                f"The bot must be an administrator in source channel <code>{_escape(value)}</code> "
                "to receive channel posts."
            )
        return

    if status in {"LEFT", "BANNED"}:
        raise ConfigValueError(f"The bot is not a member of <code>{_escape(value)}</code>.")
    needs_media = key in {"BIN_CHANNEL", "CATALOG_STORAGE_CHANNEL"}
    if status == "RESTRICTED":
        permissions = getattr(member, "permissions", None)
        if not getattr(permissions, "can_send_messages", False):
            raise ConfigValueError(f"The bot cannot send messages to <code>{_escape(value)}</code>.")
        if needs_media and not getattr(permissions, "can_send_media_messages", False):
            raise ConfigValueError(f"The bot cannot send media to <code>{_escape(value)}</code>.")
    elif chat_type in {enums.ChatType.GROUP, enums.ChatType.SUPERGROUP} and status not in {"OWNER", "ADMINISTRATOR"}:
        defaults = getattr(chat, "permissions", None)
        if defaults is not None and getattr(defaults, "can_send_messages", None) is False:
            raise ConfigValueError(f"The group does not allow the bot to send messages to <code>{_escape(value)}</code>.")
        if needs_media and defaults is not None and getattr(defaults, "can_send_media_messages", None) is False:
            raise ConfigValueError(f"The group does not allow the bot to send media to <code>{_escape(value)}</code>.")
    if chat_type == enums.ChatType.CHANNEL:
        if status not in {"OWNER", "ADMINISTRATOR"}:
            raise ConfigValueError(
                f"The bot must be an administrator in destination channel <code>{_escape(value)}</code>."
            )
        privileges = getattr(member, "privileges", None)
        if status != "OWNER" and not getattr(privileges, "can_post_messages", False):
            raise ConfigValueError(
                f"The bot needs the <i>Post Messages</i> permission in <code>{_escape(value)}</code>."
            )


async def _validate_setting_value(client, key, value):
    if key not in CHANNEL_SETTING_KEYS:
        return
    if key == "INDEX_CHANNELS":
        channels = list(value or [])
    else:
        channels = [value]
    if not channels:
        return
    me = await client.get_me()
    for channel_id in channels:
        await _validate_one_chat(client, key, channel_id, me.id)


def _parse_duration(text):
    match = re.fullmatch(r"(\d+)\s*(s|sec|m|min|h|hr|d|day)?", text.strip().lower())
    if not match:
        raise ConfigValueError("Use a duration such as <code>30m</code>, <code>2h</code>, or <code>1d</code>.")
    amount = int(match.group(1))
    unit = match.group(2) or "m"  # Bare values are minutes in this prompt.
    multiplier = {
        "s": 1, "sec": 1,
        "m": 60, "min": 60,
        "h": 3600, "hr": 3600,
        "d": 86400, "day": 86400,
    }[unit]
    seconds = amount * multiplier
    if not 60 <= seconds <= 7 * 24 * 60 * 60:
        raise ConfigValueError("PM auto-delete must be between 1 minute and 7 days.")
    return normalize_setting("PM_FILE_DELETE_TIME", seconds)


def _value_from_input(key, text):
    if key == "INDEX_CHANNELS":
        return parse_index_channel_ids(text)
    if key == "PM_FILE_DELETE_TIME":
        return _parse_duration(text)
    return normalize_setting(key, text)


def _display_update(key, value, reset=False):
    if reset:
        detail = {
            "INDEX_LOG_CHANNEL": "follow LOG_CHANNEL when no environment override exists",
            "CATALOG_STORAGE_CHANNEL": "follow BIN_CHANNEL when no environment override exists",
        }.get(key, "restore the environment/built-in default")
        return f"<i>{html.escape(detail)}</i> → {_format_value(key, value)}"
    return _format_value(key, value)


async def _show_confirmation(client, message, key, value, actor_id, *, reset=False):
    await _validate_setting_value(client, key, value)
    token = secrets.token_hex(8)
    _PENDING_CHANGES[token] = {
        "actor_id": actor_id,
        "key": key,
        "value": value,
        "reset": reset,
        "expires_at": time.monotonic() + _MAX_PENDING_SECONDS,
    }
    label = _setting_name(key)
    current = runtime_config.get(key)
    if key in CHANNEL_SETTING_KEYS:
        assurance = (
            "The bot's Telegram membership/permissions were checked. They will be checked again "
            "before saving."
        )
    else:
        assurance = "This bounded setting is applied live and recorded in the audit history."
    confirm_text = (
        "⚠️ <b>Confirm setting change</b>\n\n"
        f"Setting: <b>{html.escape(label)}</b>\n"
        f"Current: {_format_value(key, current)}\n"
        f"New: {_display_update(key, value, reset)}\n\n"
        f"{assurance}"
    )
    await message.edit(
        confirm_text,
        parse_mode=enums.ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [_button("✅ Confirm", f"admincfg:confirm:{token}"), _button("Cancel", f"admincfg:cancel:{token}")]
        ]),
    )


async def _begin_setting_change(client, panel_message, key, actor_id):
    if actor_id in _ACTIVE_INPUTS:
        await panel_message.reply_text("Finish or cancel your current settings prompt first.")
        return

    _ACTIVE_INPUTS.add(actor_id)
    label = _setting_name(key)
    if key == "INDEX_CHANNELS":
        instructions = (
            "Send channel IDs separated by spaces or commas. Send <code>none</code> to disable "
            "automatic source indexing."
        )
    elif key == "PM_FILE_DELETE_TIME":
        instructions = (
            "Send a duration such as <code>30m</code>, <code>2h</code>, or <code>1d</code>. "
            "A bare number means minutes. Allowed range: 1 minute to 7 days."
        )
    elif key in _BOOLEAN_KEYS:
        instructions = "Send <code>on</code> or <code>off</code>."
    elif key in INTEGER_SETTING_RANGES:
        minimum, maximum = INTEGER_SETTING_RANGES[key]
        instructions = f"Send a whole number between <code>{minimum}</code> and <code>{maximum}</code>."
    else:
        instructions = "Send one numeric Telegram channel/chat ID."
    instructions += "\nSend <code>default</code> to restore the configured default, or <code>/cancel</code> to stop."
    prompt = await panel_message.reply_text(
        f"<b>{html.escape(label)}</b>\n\n{instructions}\n\n"
        f"Current value: {_format_value(key, runtime_config.get(key))}",
        parse_mode=enums.ParseMode.HTML,
    )
    try:
        try:
            response = await client.listen(
                filters=filters.text,
                timeout=120,
                chat_id=actor_id,
                user_id=actor_id,
            )
        except ListenerTimeout:
            await prompt.edit("⌛ Timed out. No setting was changed.", reply_markup=_home_markup())
            return

        raw = (getattr(response, "text", None) or "").strip()
        try:
            await response.delete()
        except Exception:
            pass
        if raw.lower().startswith("/cancel"):
            await prompt.edit("Cancelled — no setting was changed.", reply_markup=_home_markup())
            return
        if len(raw) > 1000:
            await prompt.edit("❌ Input is too long. Reopen /admin and try again.", reply_markup=_home_markup())
            return

        is_reset = raw.lower() in {"default", "env", "reset"}
        try:
            value = runtime_config.default_value(key) if is_reset else _value_from_input(key, raw)
            await _show_confirmation(client, prompt, key, value, actor_id, reset=is_reset)
        except ConfigValueError as exc:
            await prompt.edit(
                f"❌ {exc}\n\nNo setting was changed. Reopen /admin to try again.",
                parse_mode=enums.ParseMode.HTML,
                reply_markup=_features_markup() if key not in CHANNEL_SETTING_KEYS else _home_markup(),
            )
            return
        except Exception:
            logger.exception("Setting validation failed for %s", key)
            await prompt.edit(
                "❌ Could not validate this setting. No change was saved; check the input and try again.",
                reply_markup=_features_markup() if key not in CHANNEL_SETTING_KEYS else _home_markup(),
            )
            return
    finally:
        _ACTIVE_INPUTS.discard(actor_id)


async def _send_audit_log(client, event):
    try:
        key = event["setting"]
        await client.send_message(
            runtime_config.get("LOG_CHANNEL"),
            "🛠️ <b>Bot setting changed</b>\n"
            f"Setting: <b>{html.escape(_setting_name(key))}</b>\n"
            f"Action: <code>{html.escape(event.get('action', 'set'))}</code>\n"
            f"By admin: <code>{_escape(event.get('actor_id', 'unknown'))}</code>\n"
            f"Old: {_format_value(key, event.get('old_value'))}\n"
            f"New: {_format_value(key, event.get('new_value'))}",
            parse_mode=enums.ParseMode.HTML,
        )
    except Exception as exc:
        logger.warning("Could not mirror bot settings audit to LOG_CHANNEL: %s", exc)


async def _show_audit(query):
    entries = await runtime_config.audit_history(5)
    if not entries:
        text = "🕘 <b>Bot settings audit</b>\n\nNo changes have been recorded yet."
        markup = InlineKeyboardMarkup([[_button("🔙 Back", "admincfg:home")]])
        await query.message.edit(text, parse_mode=enums.ParseMode.HTML, reply_markup=markup)
        return

    lines = ["🕘 <b>Bot settings audit</b> (newest first)", ""]
    for event in entries:
        key = event.get("setting", "")
        action = event.get("action", "set")
        action_text = "rolled back" if action == "rollback" else ("reset" if action == "reset" else "changed")
        lines.append(
            f"• {_escape(_format_time(event.get('changed_at')))} — "
            f"<b>{html.escape(_setting_name(key))}</b> {action_text}\n"
            f"  {_format_audit_value(key, event.get('old_value'))} → {_format_audit_value(key, event.get('new_value'))}\n"
            f"  by admin <code>{_escape(event.get('actor_id', 'unknown'))}</code>"
        )
    newest = entries[0]
    markup = InlineKeyboardMarkup([
        [_button("↩️ Undo latest change", f"admincfg:undo:{newest.get('id', '')}")],
        [_button("🔙 Back", "admincfg:home")],
    ])
    await query.message.edit("\n".join(lines), parse_mode=enums.ParseMode.HTML, reply_markup=markup)


async def _begin_rollback(client, query, audit_id):
    event = await runtime_config.latest_audit()
    if not event or str(event.get("id")) != str(audit_id):
        await query.answer("A newer change exists. Refresh the audit panel.", show_alert=True)
        return
    key = event.get("setting")
    try:
        target = runtime_config.rollback_target(event)
        await _validate_setting_value(client, key, target)
    except ConfigValueError as exc:
        await query.answer(_plain_alert(exc), show_alert=True)
        return
    except Exception:
        logger.exception("Rollback validation failed")
        await query.answer("Could not validate the rollback; nothing was changed.", show_alert=True)
        return

    assurance = (
        "The target chat permissions were checked and will be checked again before saving."
        if key in CHANNEL_SETTING_KEYS
        else "This setting will be restored and recorded in the audit history."
    )
    await query.message.reply_text(
        "⚠️ <b>Confirm rollback</b>\n\n"
        f"Setting: <b>{html.escape(_setting_name(key))}</b>\n"
        f"Current: {_format_value(key, event.get('new_value'))}\n"
        f"Restore: {_format_value(key, target)}\n\n"
        f"{assurance}",
        parse_mode=enums.ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [_button("✅ Confirm rollback", f"admincfg:rollback:{audit_id}"), _button("Cancel", "admincfg:cancel")]
        ]),
    )
    await query.answer()


@Client.on_message(filters.private & filters.command("admin"))
async def admin_panel_command(client, message):
    """Open the bot-settings panel in an administrator's private chat."""
    user = getattr(message, "from_user", None)
    if not user or user.id not in ADMINS:
        return await message.reply_text("This command is available to bot admins only.")
    try:
        await runtime_config.load()
        text = await _panel_text()
    except Exception:
        logger.exception("Unable to open admin settings panel")
        return await message.reply_text(
            "⚠️ Could not load bot settings from MongoDB. No changes can be made right now; try again shortly."
        )
    await message.reply_text(text, parse_mode=enums.ParseMode.HTML, reply_markup=_home_markup())


@Client.on_callback_query(filters.regex(r"^admincfg:"), group=-1)
async def admin_panel_callback(client, query):
    if not _is_private_admin(query):
        try:
            await query.answer("This private admin panel is only for bot admins.", show_alert=True)
        except Exception:
            pass
        return

    parts = (query.data or "").split(":")
    action = parts[1] if len(parts) > 1 else ""
    try:
        if not runtime_config.is_loaded:
            await runtime_config.load()

        if action == "home":
            text = await _panel_text()
            await query.message.edit(
                text,
                parse_mode=enums.ParseMode.HTML,
                reply_markup=_home_markup(),
            )
            await query.answer()
        elif action == "features":
            await query.message.edit(
                _features_text(),
                parse_mode=enums.ParseMode.HTML,
                reply_markup=_features_markup(),
            )
            await query.answer()
        elif action == "close":
            await query.message.delete()
            await query.answer("Closed")
        elif action == "set" and len(parts) == 3 and parts[2] in _SETTINGS:
            await query.answer()
            key = _SETTINGS[parts[2]][0]
            await _begin_setting_change(client, query.message, key, query.from_user.id)
        elif action == "toggle" and len(parts) == 3 and parts[2] in _FEATURE_SETTINGS:
            key = _FEATURE_SETTINGS[parts[2]][0]
            if key not in _BOOLEAN_KEYS:
                return await query.answer("This setting is not a toggle.", show_alert=True)
            value = not runtime_config.get(key)
            await _show_confirmation(client, query.message, key, value, query.from_user.id)
            await query.answer()
        elif action == "reset" and len(parts) == 3 and parts[2] in _FEATURE_SETTINGS:
            key = _FEATURE_SETTINGS[parts[2]][0]
            value = runtime_config.default_value(key)
            await _show_confirmation(
                client, query.message, key, value, query.from_user.id, reset=True
            )
            await query.answer()
        elif action == "confirm" and len(parts) == 3:
            token = parts[2]
            pending = _PENDING_CHANGES.get(token)
            if (
                not pending
                or pending["actor_id"] != query.from_user.id
                or pending["expires_at"] < time.monotonic()
            ):
                _PENDING_CHANGES.pop(token, None)
                return await query.answer("This confirmation expired. Start again from /admin.", show_alert=True)
            key = pending["key"]
            value = runtime_config.default_value(key) if pending["reset"] else pending["value"]
            await _validate_setting_value(client, key, value)
            if pending["reset"]:
                event = await runtime_config.reset_value(key, query.from_user.id)
            else:
                event = await runtime_config.set_value(key, value, query.from_user.id)
            if key == "USE_CAPTION_FILTER":
                # Caption policy is part of the search-cache key as well, but
                # clear immediately so the new policy takes effect cleanly.
                from database.ia_filterdb import cache_clear
                cache_clear()
            _PENDING_CHANGES.pop(token, None)
            try:
                await query.answer("Saved")
            except Exception:
                pass
            await _send_audit_log(client, event)
            await query.message.edit(
                "✅ <b>Setting saved</b>\n\n"
                f"{html.escape(_setting_name(key))}: {_format_value(key, event.get('new_value'))}\n"
                "The change is live and its audit record is stored in MongoDB.",
                parse_mode=enums.ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([[_button("🛡️ Admin panel", "admincfg:home")]]),
            )
        elif action == "cancel":
            if len(parts) > 2:
                _PENDING_CHANGES.pop(parts[2], None)
            await query.answer("Cancelled")
            await query.message.edit(
                "Cancelled — no setting was changed.",
                reply_markup=InlineKeyboardMarkup([[_button("🛡️ Admin panel", "admincfg:home")]]),
            )
        elif action == "audit":
            await _show_audit(query)
            await query.answer()
        elif action == "undo" and len(parts) == 3:
            await _begin_rollback(client, query, parts[2])
        elif action == "rollback" and len(parts) == 3:
            audit_id = parts[2]
            event = await runtime_config.latest_audit()
            if not event or str(event.get("id")) != audit_id:
                return await query.answer("A newer change exists. Refresh the audit panel.", show_alert=True)
            key = event.get("setting")
            target = runtime_config.rollback_target(event)
            await _validate_setting_value(client, key, target)
            applied = await runtime_config.rollback_latest(audit_id, query.from_user.id)
            if key == "USE_CAPTION_FILTER":
                from database.ia_filterdb import cache_clear
                cache_clear()
            try:
                await query.answer("Rolled back")
            except Exception:
                pass
            await _send_audit_log(client, applied)
            await query.message.edit(
                "✅ <b>Latest setting rolled back</b>\n\n"
                f"{html.escape(_setting_name(key))}: {_format_value(key, applied.get('new_value'))}\n"
                "The rollback is live and has been added to the audit history.",
                parse_mode=enums.ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([[_button("🛡️ Admin panel", "admincfg:home")]]),
            )
        else:
            await query.answer("Unknown admin-panel action.", show_alert=True)
    except ConfigValueError as exc:
        await query.answer(_plain_alert(exc), show_alert=True)
    except Exception:
        logger.exception("Admin settings action failed")
        try:
            await query.answer(
                "Could not complete the request. Refresh /admin and check the audit history.",
                show_alert=True,
            )
        except Exception:
            pass
