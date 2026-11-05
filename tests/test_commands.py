#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🤖 Telegram commands — the help menu must never advertise a dead command.

Stdlib-only; runs without MongoDB / Telegram / hydrogram:

    python3 -m unittest discover -s tests -v

The bot exposes two lists in `Script.py` (`USER_COMMAND_TXT` and
`ADMIN_COMMAND_TXT`) through the 👤 User Commands / 🛡️ Admin Commands buttons
of the help menu, plus command hints written inside replies (the /admin panel,
the group /help text). Every command that is *shown* must have a real
`filters.command(...)` handler in `plugins/`, otherwise a user taps a command
that does nothing.

The source is parsed with `ast` (never imported), so hydrogram is not needed:

* `registered_commands()`  — every command a handler is actually bound to.
* `listed_commands(...)`   — every `/cmd` written in a Script.py block.
* `referenced_commands()`  — every `/cmd` written in a reply / instruction.

`ALLOWED_REFERENCES` holds the few `/word` tokens that are paths, not commands.
"""
import ast
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGINS = sorted((ROOT / "plugins").glob("*.py"))
SCRIPT = (ROOT / "Script.py").read_text(encoding="utf-8")
CALLBACKS = (ROOT / "plugins" / "callbacks.py").read_text(encoding="utf-8")

# `/word` tokens that are not Telegram commands (URLs, file paths, …)
ALLOWED_REFERENCES = {
    "start",  # "https://t.me/<bot>?start=file_…" deep links
}

# Commands the PM help menu must keep advertising (they are the bot's features)
EXPECTED_USER_COMMANDS = {
    "start",
    "plan", "myplan", "invoice",
    "upload", "cancel_upload",
    "id",
}

EXPECTED_ADMIN_COMMANDS = {
    "stats",
    "addpremium", "extendpremium", "removepremium",
    "delete", "deleteall",
    "warmup_thumbs",
}

# Group-only commands (they live in the group /help text, not in the PM menu)
EXPECTED_GROUP_COMMANDS = {
    "search", "help",
}

# Features that were removed on purpose: no handler may come back, and no list
# or reply may mention them again (broadcast, group moderation, blacklist,
# delayed-delete, and the PM /help · /commands shortcuts).
FORBIDDEN_COMMANDS = {
    "broadcast", "broadcast_all", "broadcast_premium", "broadcast_free",
    "pin_broadcast", "grp_broadcast", "pin_grp_broadcast",
    "mute", "unmute", "ban", "warn", "resetwarn",
    "addblacklist", "removeblacklist", "blacklist", "blacklistwarn",
    "dlink", "removedlink", "dlinklist",
    "commands", "ping", "botinfo",
    "admin", "dashboard",
}


# ----------------------------------------------------------------------
# 🔍 PARSERS
# ----------------------------------------------------------------------

def _string_args(call):
    """String literals passed to filters.command("x") / filters.command([...])"""
    found = []
    for arg in call.args:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            found.append(arg.value)
        elif isinstance(arg, (ast.List, ast.Tuple, ast.Set)):
            for elt in arg.elts:
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                    found.append(elt.value)
    return found


def registered_commands():
    """{command: [plugin files that register a handler for it]}"""
    cmds = {}
    for path in PLUGINS:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "command"
            ):
                for raw in _string_args(node):
                    cmds.setdefault(raw.lstrip("/"), []).append(path.name)
    return cmds


def _block(name):
    """Value of a `NAME = ( … )` string block in Script.py.

    The block is a group of implicitly concatenated string literals, so it is
    evaluated (never executed — `ast.literal_eval`) to get the real text that
    Telegram receives, escapes and all.
    """
    match = re.search(rf"^\s*{name}\s*=\s*\((.*?)\n\s*\)", SCRIPT, re.S | re.M)
    assert match, f"{name} block not found in Script.py"
    return ast.literal_eval("(" + match.group(1) + ")")


def _tokens(text):
    """/cmd tokens, ignoring URLs ("/t.me", "…/search" inside a link, …).

    A "/" right after a digit, "}" or "." is a unit/path (₹{X}/day, {speed}/s,
    https://t.me/…), never a Telegram command.
    """
    return {
        m.group("cmd")
        for m in re.finditer(r"(?<![A-Za-z0-9_./:<}\]])/(?P<cmd>[a-z_]+)", text)
    }


def listed_commands(name):
    """/cmd tokens written inside a Script.py command block"""
    return _tokens(_block(name))


def referenced_commands():
    """/cmd tokens written in every reply / instruction of the bot"""
    found = set()
    for path in PLUGINS:
        found |= _tokens(path.read_text(encoding="utf-8"))
    found |= _tokens(SCRIPT)
    return {cmd for cmd in found if cmd not in ALLOWED_REFERENCES}


# ----------------------------------------------------------------------
# ✅ TESTS
# ----------------------------------------------------------------------

class TestCommandLists(unittest.TestCase):
    """Script.py lists vs. the handlers that really exist in plugins/."""

    def setUp(self):
        self.registered = registered_commands()

    def test_user_command_list_has_no_dead_command(self):
        for cmd in sorted(listed_commands("USER_COMMAND_TXT")):
            with self.subTest(command=cmd):
                self.assertIn(
                    cmd, self.registered,
                    f"/{cmd} is shown in USER_COMMAND_TXT but no handler exists",
                )

    def test_admin_command_list_has_no_dead_command(self):
        for cmd in sorted(listed_commands("ADMIN_COMMAND_TXT")):
            with self.subTest(command=cmd):
                self.assertIn(
                    cmd, self.registered,
                    f"/{cmd} is shown in ADMIN_COMMAND_TXT but no handler exists",
                )

    def test_every_reply_reference_is_a_real_command(self):
        """Admin-panel hints like "<code>/addpremium …</code>" must work."""
        for cmd in sorted(referenced_commands()):
            with self.subTest(command=cmd):
                self.assertIn(
                    cmd, self.registered,
                    f"/{cmd} is written in a reply but no handler exists",
                )

    def test_expected_user_commands_are_registered(self):
        for cmd in sorted(EXPECTED_USER_COMMANDS):
            with self.subTest(command=cmd):
                self.assertIn(cmd, self.registered, f"/{cmd} handler is missing")

    def test_expected_admin_commands_are_registered(self):
        for cmd in sorted(EXPECTED_ADMIN_COMMANDS):
            with self.subTest(command=cmd):
                self.assertIn(cmd, self.registered, f"/{cmd} handler is missing")

    def test_expected_group_commands_are_registered(self):
        for cmd in sorted(EXPECTED_GROUP_COMMANDS):
            with self.subTest(command=cmd):
                self.assertIn(cmd, self.registered, f"/{cmd} handler is missing")

    def test_user_list_advertises_the_pm_features(self):
        listed = listed_commands("USER_COMMAND_TXT")
        for cmd in ("start", "plan", "myplan", "invoice", "upload",
                    "cancel_upload", "id"):
            with self.subTest(command=cmd):
                self.assertIn(cmd, listed, f"/{cmd} is missing from the user list")

    def test_admin_list_advertises_the_admin_features(self):
        listed = listed_commands("ADMIN_COMMAND_TXT")
        for cmd in ("stats", "delete", "deleteall", "warmup_thumbs",
                    "addpremium", "extendpremium", "removepremium"):
            with self.subTest(command=cmd):
                self.assertIn(cmd, listed, f"/{cmd} is missing from the admin list")

    def test_removed_features_stay_removed(self):
        """Broadcast / moderation / blacklist / dlink / PM /commands are gone."""
        for cmd in sorted(FORBIDDEN_COMMANDS):
            with self.subTest(command=cmd):
                self.assertNotIn(
                    cmd, self.registered,
                    f"/{cmd} was removed — do not register a handler again",
                )

    def test_removed_features_are_not_advertised(self):
        listed = listed_commands("USER_COMMAND_TXT") | listed_commands("ADMIN_COMMAND_TXT")
        for cmd in sorted(FORBIDDEN_COMMANDS):
            with self.subTest(command=cmd):
                self.assertNotIn(
                    cmd, listed,
                    f"/{cmd} is listed in the help menu but the feature is gone",
                )

    def test_no_broadcast_plugin_left(self):
        self.assertFalse(
            (ROOT / "plugins" / "broadcast.py").exists(),
            "plugins/broadcast.py was deleted — keep it that way",
        )
        self.assertNotIn(
            "broadcast", (ROOT / "utils.py").read_text(encoding="utf-8").lower(),
            "utils.py still carries broadcast helpers",
        )


class TestHelpMenu(unittest.TestCase):
    """The help menu is reachable in PM and hides admin commands from users."""

    def test_pm_help_and_commands_handlers_are_gone(self):
        """/help and /commands were removed from PM — the 👨‍🚒 Help button is the menu."""
        start = (ROOT / "plugins" / "start.py").read_text(encoding="utf-8")
        self.assertNotRegex(
            start, r'filters\.command\(\[[^\]]*"(help|commands)"',
            "PM /help and /commands handlers were removed — keep it that way",
        )
        self.assertRegex(
            start, r'filters\.command\("start"\)', "/start must still have a PM handler"
        )
        # The 👨‍🚒 Help button is the way in, so its callback must survive
        self.assertIn('callback_data="help"', start)

    def test_admin_commands_button_is_gated(self):
        self.assertRegex(
            CALLBACKS,
            r'if data == "admin_cmds":\s*\n\s*if uid not in ADMINS:',
            "the 🛡️ Admin Commands callback must stay admin-only",
        )

    def test_help_text_points_at_the_buttons_not_a_missing_command(self):
        """HELP_TXT must not reference a command nobody registered."""
        registered = registered_commands()
        for cmd in _tokens(_block("HELP_TXT")):
            with self.subTest(command=cmd):
                self.assertIn(cmd, registered | ALLOWED_REFERENCES)


class TestPluginLayout(unittest.TestCase):
    """Plugins that were merged into another file must not come back."""

    def test_misc_plugin_is_gone(self):
        self.assertFalse(
            (ROOT / "plugins" / "misc.py").exists(),
            "plugins/misc.py was merged into plugins/start.py — keep it that way",
        )

    def test_id_command_lives_in_start(self):
        start = (ROOT / "plugins" / "start.py").read_text(encoding="utf-8")
        self.assertIn('filters.command("id")', start, "/id now lives in start.py")

    def test_group_mgmt_is_gone(self):
        """Its last two features moved to plugins/filter.py."""
        self.assertFalse(
            (ROOT / "plugins" / "group_mgmt.py").exists(),
            "plugins/group_mgmt.py was merged into plugins/filter.py — keep it that way",
        )

    def test_group_features_live_in_filter(self):
        src = (ROOT / "plugins" / "filter.py").read_text(encoding="utf-8")
        self.assertIn("filters.new_chat_members", src, "🤖 anti-bot lives in filter.py")
        self.assertIn(
            'filters.group & filters.command("help")', src,
            "the group /help command lives in filter.py",
        )
        self.assertIn("async def is_group_admin(", src)


class TestSharedPremiumCode(unittest.TestCase):
    """Pass 8: the premium text, the plan write and the checks exist once.

    plugins/premium.py, plugins/filter.py and plugins/file_deliver.py used to
    build the same 🔒 Premium Required message, the same datetime formatter and
    the same "is this user premium" lookup in every place they needed them.
    Those now live in utils.py / premium.py — these tests keep it that way.
    """

    def _read(self, name):
        return (ROOT / name).read_text(encoding="utf-8")

    def test_premium_prompt_is_defined_once(self):
        """The 🔒 Premium Required text is written once — in utils.py."""
        utils = self._read("utils.py")
        self.assertIn("def premium_required_text(", utils)
        self.assertIn("def premium_buy_markup(", utils)

        for plugin in PLUGINS:
            with self.subTest(plugin=plugin.name):
                self.assertNotIn(
                    "🔒 <b>Premium Required</b>", plugin.read_text(encoding="utf-8"),
                    f"{plugin.name} rebuilds the premium prompt — call "
                    "utils.premium_required_text() instead",
                )

    def test_premium_prompt_is_shared_by_every_feature(self):
        for name in ("plugins/filter.py", "plugins/file_deliver.py"):
            src = self._read(name)
            with self.subTest(plugin=name):
                self.assertIn("premium_required_text", src)
                self.assertIn("premium_buy_markup", src)

    def test_datetime_formatter_lives_in_utils_only(self):
        """admin_tools.py and premium.py each used to carry a copy of fmt()."""
        utils = self._read("utils.py")
        self.assertIn("def fmt(", utils)

        for plugin in PLUGINS:
            with self.subTest(plugin=plugin.name):
                self.assertNotIn(
                    "def fmt(", plugin.read_text(encoding="utf-8"),
                    f"{plugin.name} re-defines fmt() — import it from utils",
                )

    def test_plan_is_written_through_one_helper(self):
        """apply_premium() / revoke_premium() own every db.update_plan() write."""
        premium = self._read("plugins/premium.py")
        self.assertIn("async def apply_premium(", premium)
        self.assertIn("async def revoke_premium(", premium)
        self.assertLessEqual(
            premium.count("db.update_plan("), 2,
            "a new plan write bypasses apply_premium()/revoke_premium()",
        )

    def test_pricing_comes_from_one_table(self):
        premium = self._read("plugins/premium.py")
        self.assertIn("PLAN_UNITS = {", premium)
        self.assertIn("def plan_quote(", premium)
        # the duration buttons and the selection handler quote the same way
        self.assertEqual(
            len(re.findall(r"= plan_quote\(", premium)), 2,
            "duration_buttons() and duration_selected() must quote the same way",
        )

    def test_premium_check_is_not_reimplemented(self):
        """file_deliver used to run its own DB lookup with its own grace rule."""
        file_deliver = self._read("plugins/file_deliver.py")
        self.assertNotIn("GRACE_PERIOD", file_deliver)
        self.assertIn("await is_premium(user_id)", file_deliver)

    def test_error_reporting_uses_one_helper(self):
        for plugin in PLUGINS:
            src = plugin.read_text(encoding="utf-8")
            with self.subTest(plugin=plugin.name):
                self.assertNotIn(
                    "import traceback", src,
                    f"{plugin.name} imports traceback inline — use utils.log_error()",
                )


class TestUploadSites(unittest.TestCase):
    """/upload offers only the hosts that answer (and only when they fit)."""

    def setUp(self):
        self.tools = (ROOT / "plugins" / "tools.py").read_text(encoding="utf-8")

    def test_dead_hosts_are_gone(self):
        """The two hosts that always failed must not come back.

        "https://file.io" (and not the harmless "gofile.io" of the GoFile API)
        is what a re-added File.io uploader would contain.
        """
        low = self.tools.lower()
        for host in ("catbox", "fileio", "https://file.io"):
            with self.subTest(host=host):
                self.assertNotIn(
                    host, low, f"{host} always failed — do not add it back"
                )

    def test_only_two_hosts_are_offered(self):
        keys = re.findall(r'^\s{4}"(\w+)": \{$', self.tools, re.M)
        self.assertEqual(sorted(keys), ["gofile", "tmpfiles"])

    def test_every_host_declares_a_size_limit(self):
        for key, block in re.findall(r'^\s{4}"(\w+)": \{(.*?)\n\s{4}\},?$',
                                     self.tools, re.M | re.S):
            with self.subTest(host=key):
                self.assertIn('"max"', block, f"{key} has no per-site limit")

    def test_upload_limit_is_200_mb(self):
        self.assertIn("MAX_FILE_SIZE = 200 * MB", self.tools)

    def test_hosts_are_filtered_by_size(self):
        self.assertIn("def sites_for(", self.tools)
        self.assertIn("sites_for(size)", self.tools)


class TestCommandTexts(unittest.TestCase):
    """The two lists are shown with HTML parse mode — keep them renderable."""

    # Telegram allows 1024 characters in a photo caption; the help menu is a
    # photo, so every block shown through it must stay below that (UTF-16
    # code units — an emoji counts as 2).
    MAX_CAPTION = 1024

    def _block(self, name):
        return _block(name)

    def test_blocks_fit_inside_a_photo_caption(self):
        for name in ("START_TXT", "HELP_TXT",
                     "USER_COMMAND_TXT", "ADMIN_COMMAND_TXT"):
            with self.subTest(block=name):
                length = len(self._block(name).encode("utf-16-le")) // 2
                self.assertLessEqual(
                    length, self.MAX_CAPTION,
                    f"{name} is {length} chars — edit_caption would fail",
                )

    def test_no_unescaped_angle_brackets(self):
        for name in ("USER_COMMAND_TXT", "ADMIN_COMMAND_TXT"):
            for tag in re.findall(r"<[^>]+>", self._block(name)):
                with self.subTest(block=name, tag=tag):
                    self.assertIn(
                        tag, {"<b>", "</b>", "<i>", "</i>", "<code>", "</code>"},
                        f"{tag} in {name} is not a supported HTML tag",
                    )

    def test_ampersands_are_escaped(self):
        for name in ("USER_COMMAND_TXT", "ADMIN_COMMAND_TXT", "HELP_TXT", "START_TXT"):
            for amp in re.finditer(r"&(?![a-zA-Z]+;|#\d+;)", self._block(name)):
                with self.subTest(block=name):
                    self.fail(f"unescaped '&' in {name}: use &amp;")

    def test_placeholders_match_the_callers(self):
        self.assertEqual(_block("START_TXT").count("{}"), 2, "START_TXT: user + bot mention")
        self.assertEqual(_block("HELP_TXT").count("{}"), 1, "HELP_TXT: user mention")
        for name in ("USER_COMMAND_TXT", "ADMIN_COMMAND_TXT"):
            self.assertNotIn("{}", _block(name), f"{name} is never .format()-ed")


if __name__ == "__main__":
    unittest.main(verbosity=2)
