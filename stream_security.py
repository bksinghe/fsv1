"""🔐 Signed (HMAC) stream links.

The `/watch` and `/download` links created by the web UI (and the bot's /stream buttons)
carry `e` (expiry) + `s` (signature); new links also carry `c`, the signed storage
chat ID, so they remain valid if BIN_CHANNEL changes. Guessing a random message ID
therefore cannot stream a file from BIN_CHANNEL.

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

USER_LINK_TTL = 24 * 3600          # links obtained from the Telegram bot (1 day)
STREAM_TTL = 6 * 3600              # "Play / Stream" links from web search (6 hours)
MAX_LINK_TTL = 365 * 24 * 3600     # upper limit for any custom link


def _sig(mid: int, exp: int, chat_id=None) -> str:
    payload = f"{int(mid)}:{int(exp)}"
    if chat_id is not None:
        payload += f":{int(chat_id)}"
    mac = hmac.new(_SECRET, payload.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac[:16]).decode().rstrip("=")


def sign_params(mid: int, ttl=STREAM_TTL, chat_id=None) -> str:
    """Query string ``e=..&s=..``; optional ``c`` binds the link to a chat.

    ``ttl=None`` => never expires (e=0). Links without ``chat_id`` keep the
    original signature format for backwards compatibility.
    """
    if ttl is not None:
        ttl = max(60, min(int(ttl), MAX_LINK_TTL))
    exp = 0 if ttl is None else int(time.time()) + ttl
    params = f"e={exp}&s={_sig(mid, exp, chat_id)}"
    if chat_id is not None:
        params += f"&c={int(chat_id)}"
    return params


def verify(mid: int, exp, sig, chat_id=None) -> bool:
    try:
        exp = int(exp)
        if chat_id is not None:
            chat_id = int(chat_id)
    except (TypeError, ValueError):
        return False
    if exp < 0 or (exp and exp < time.time()):
        return False
    return hmac.compare_digest(_sig(mid, exp, chat_id), str(sig or ""))
