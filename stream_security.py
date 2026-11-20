"""🔐 Signed (HMAC) stream links.

The `/watch` and `/download` links created by the web UI (and the bot's /stream buttons)
carry `e` (expiry) + `s` (signature). Guessing a random message id therefore cannot
stream a file from BIN_CHANNEL.

Secret: the `STREAM_SECRET` env var (recommended); when it is missing, the value is
derived from `BOT_TOKEN`. Changing the secret invalidates every existing link immediately.
"""

import base64
import hashlib
import hmac
import time
from os import environ

from info import BOT_TOKEN

_SECRET = hashlib.sha256(
    b"fsv1-stream-link:" + (environ.get("STREAM_SECRET") or BOT_TOKEN).encode()
).digest()

REPLY_LINK_TTL = 5 * 3600          # /link replies only
USER_LINK_TTL = 24 * 3600          # links obtained from the Telegram bot (1 day)
STREAM_TTL = 6 * 3600              # "Play / Stream" links from web search (6 hours)
MAX_LINK_TTL = 365 * 24 * 3600     # upper limit for any custom link


def _sig(mid: int, exp: int) -> str:
    mac = hmac.new(_SECRET, f"{int(mid)}:{int(exp)}".encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac[:16]).decode().rstrip("=")


def sign_params(mid: int, ttl=STREAM_TTL) -> str:
    """Query string ``e=..&s=..``. ``ttl=None`` => never expires (e=0)."""
    if ttl is not None:
        ttl = max(60, min(int(ttl), MAX_LINK_TTL))
    exp = 0 if ttl is None else int(time.time()) + ttl
    return f"e={exp}&s={_sig(mid, exp)}"


def verify(mid: int, exp, sig) -> bool:
    try:
        exp = int(exp)
    except (TypeError, ValueError):
        return False
    if exp < 0 or (exp and exp < time.time()):
        return False
    return hmac.compare_digest(_sig(mid, exp), str(sig or ""))
