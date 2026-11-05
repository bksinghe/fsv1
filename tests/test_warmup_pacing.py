#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""⏱️ `/warmup_thumbs` anti-flood pacing.

Stdlib-only; runs without MongoDB / Telegram / hydrogram:

    python3 -m unittest discover -s tests -v

`/warmup_thumbs` sends one `send_cached_media` per file to BIN_CHANNEL, and a
bot may only send ~20 messages per minute **to the same chat** — one every 3s.
The old 1.2–3.0s gap averaged ~2.1s (~28 probes/min), which is above that
limit, so long warmups kept coming back with FLOOD_WAIT.

The defaults now live in `info.py` (`THUMB_PROBE_GAP_MIN` / `MAX`) and the
engine adds a penalty after every FloodWait. These tests keep the pacing
honest: the defaults must stay at or above the 3s floor, and the sleep must
keep using the env constants (plus the penalty).
"""

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INFO = (ROOT / "info.py").read_text(encoding="utf-8")
ENGINE = (ROOT / "web" / "thumb_engine.py").read_text(encoding="utf-8")
WARMUP = (ROOT / "plugins" / "warmup.py").read_text(encoding="utf-8")
# The changelog at the end may quote old values — only the live docs must
# describe the current pacing.
README = (ROOT / "README.md").read_text(encoding="utf-8")
LIVE_README = README.split("### 🧹 Dead-code cleanup")[0]

# Telegram's per-chat send limit for bots: ~20 messages / minute
SECONDS_PER_SEND = 60 / 20


def env_default(name: str):
    """The fallback string of `environ.get('NAME', 'fallback')` in info.py"""
    tree = ast.parse(INFO)
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr != "get" or len(node.args) < 2:
            continue
        key, fallback = node.args[0], node.args[1]
        if (isinstance(key, ast.Constant) and key.value == name
                and isinstance(fallback, ast.Constant)):
            return fallback.value
    return None


class TestProbeGapDefaults(unittest.TestCase):
    """info.py must keep /warmup_thumbs below Telegram's per-chat limit."""

    def test_minimum_gap_is_at_least_one_send_per_3s(self):
        value = float(env_default("THUMB_PROBE_GAP_MIN"))
        self.assertGreaterEqual(
            value, SECONDS_PER_SEND,
            f"THUMB_PROBE_GAP_MIN={value}s — a bot may send ~20 msgs/min to one "
            "chat, so the gap must never go below 3s again",
        )

    def test_maximum_gap_is_wider_than_the_minimum(self):
        low = float(env_default("THUMB_PROBE_GAP_MIN"))
        high = float(env_default("THUMB_PROBE_GAP_MAX"))
        self.assertGreater(high, low, "a random gap needs a range")

    def test_gap_cannot_be_switched_off_by_a_typo(self):
        """A 0 / negative env value must not disable the pacing entirely."""
        self.assertIn(
            "THUMB_PROBE_GAP_MIN = max(", INFO,
            "clamp THUMB_PROBE_GAP_MIN so a bad env value cannot drop the gap to 0",
        )
        self.assertIn(
            "THUMB_PROBE_GAP_MAX = max(THUMB_PROBE_GAP_MIN,", INFO,
            "THUMB_PROBE_GAP_MAX must never fall below the minimum",
        )


class TestEnginePacing(unittest.TestCase):
    """web/thumb_engine.py must actually sleep with those constants."""

    def test_sleep_uses_the_env_constants_and_the_penalty(self):
        self.assertIn(
            "random.uniform(THUMB_PROBE_GAP_MIN, THUMB_PROBE_GAP_MAX) + _GAP_PENALTY",
            ENGINE,
            "the anti-flood sleep must use the tunable gap plus the FloodWait penalty",
        )

    def test_penalty_grows_after_a_flood_wait(self):
        self.assertIn("def _add_flood_penalty(", ENGINE)
        self.assertIn("def _clear_flood_penalty(", ENGINE)
        self.assertIn("if wait:\n                        flooded = True", ENGINE)
        self.assertIn("_GAP_PENALTY_MAX", ENGINE)

    def test_penalty_clears_again(self):
        """Otherwise one bad minute would throttle the bot forever."""
        self.assertIn("_CLEAN_PROBES_TO_RESET", ENGINE)
        self.assertIn("if not flooded:\n                    _clear_flood_penalty()", ENGINE)


class TestDocsMatchTheCode(unittest.TestCase):
    """No stale "1.2–3.0s" left anywhere after the change."""

    def test_warmup_docstring_is_current(self):
        self.assertNotIn("1.2–3.0", WARMUP)
        self.assertIn("3.0–5.0", WARMUP)

    def test_engine_docstring_is_current(self):
        self.assertNotIn("1.2–3.0", ENGINE)
        self.assertIn("3.0–5.0", ENGINE)

    def test_readme_is_current(self):
        self.assertNotIn("1.2–3.0", LIVE_README, "the README still documents the old gap")
        self.assertIn("3.0–5.0", LIVE_README)
        self.assertIn("`3.0` / `5.0`", LIVE_README)


if __name__ == "__main__":
    unittest.main(verbosity=2)
