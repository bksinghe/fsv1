import re
from os import environ
import logging

logger = logging.getLogger(__name__)

# ================= BASIC UTILS =================

def is_enabled(type, value):
    data = environ.get(type, str(value))
    if data.lower() in ["true", "yes", "1", "enable", "y"]:
        return True
    elif data.lower() in ["false", "no", "0", "disable", "n"]:
        return False
    else:
        logger.error(f'{type} is invalid, exiting now')
        exit()

def is_valid_ip(ip):
    ip_pattern = r'\b(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.' \
                 r'(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.' \
                 r'(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.' \
                 r'(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b'
    return re.match(ip_pattern, ip) is not None

# ================= BOT INFO =================

API_ID = environ.get('API_ID', '')
if not API_ID:
    logger.error('API_ID is missing')
    exit()
API_ID = int(API_ID)

API_HASH = environ.get('API_HASH', '')
if not API_HASH:
    logger.error('API_HASH is missing')
    exit()

BOT_TOKEN = environ.get('BOT_TOKEN', '')
if not BOT_TOKEN:
    logger.error('BOT_TOKEN is missing')
    exit()

PORT = int(environ.get('PORT', '80'))

# ================= IMAGES =================

PICS = environ.get(
    'PICS',
    'https://i.postimg.cc/8C15CQ5y/1.png'
).split()

# ================= ADMINS / CHANNELS =================

ADMINS = environ.get('ADMINS', '')
if not ADMINS:
    logger.error('ADMINS is missing')
    exit()
ADMINS = [int(x) for x in ADMINS.split()]

INDEX_CHANNELS = [
    int(x) if x.startswith("-") else x
    for x in environ.get('INDEX_CHANNELS', '').split()
]

LOG_CHANNEL = environ.get('LOG_CHANNEL', '')
if not LOG_CHANNEL:
    logger.error('LOG_CHANNEL is missing')
    exit()
LOG_CHANNEL = int(LOG_CHANNEL)

# 🔥 INDEX LOG CHANNEL
INDEX_LOG_CHANNEL = environ.get('INDEX_LOG_CHANNEL', '')
if not INDEX_LOG_CHANNEL:
    logger.info('INDEX_LOG_CHANNEL not set, using LOG_CHANNEL')
    INDEX_LOG_CHANNEL = LOG_CHANNEL
else:
    INDEX_LOG_CHANNEL = int(INDEX_LOG_CHANNEL)

BIN_CHANNEL = environ.get("BIN_CHANNEL", "")
if not BIN_CHANNEL:
    logger.error('BIN_CHANNEL is missing')
    exit()
BIN_CHANNEL = int(BIN_CHANNEL)

# 📚 Cover images and avatars for Posts / Actors are uploaded to this Telegram channel.
# If BIN_CHANNEL is also in INDEX_CHANNELS (so covers do not appear in file search),
# set a separate private channel id here; otherwise BIN_CHANNEL is used by default.
CATALOG_STORAGE_CHANNEL = environ.get("CATALOG_STORAGE_CHANNEL", "")
CATALOG_STORAGE_CHANNEL = (
    int(CATALOG_STORAGE_CHANNEL) if CATALOG_STORAGE_CHANNEL else BIN_CHANNEL
)

# ================= DATABASE =================

DATA_DATABASE_URL = environ.get('DATA_DATABASE_URL', "")
if not DATA_DATABASE_URL:
    logger.error('DATA_DATABASE_URL is missing')
    exit()

DATABASE_NAME = environ.get('DATABASE_NAME', "bot_db")
COLLECTION_NAME = environ.get('COLLECTION_NAME', 'files')
MAX_BTN = int(environ.get('MAX_BTN', 8))

# ================= FILE / STREAM SETTINGS =================

# Admin-editable limits are clamped here as well as in runtime_config so an
# out-of-range environment value cannot prevent the bot from starting.
PM_FILE_DELETE_TIME = max(
    60, min(int(environ.get('PM_FILE_DELETE_TIME', 3600)), 7 * 24 * 60 * 60)
)
RESULTS_PER_PAGE_PM = max(1, min(int(environ.get('RESULTS_PER_PAGE_PM', 12)), 30))
RESULTS_PER_PAGE_GROUP = max(1, min(int(environ.get('RESULTS_PER_PAGE_GROUP', 10)), 30))

USE_CAPTION_FILTER = is_enabled('USE_CAPTION_FILTER', True)
PROTECT_CONTENT = is_enabled('PROTECT_CONTENT', False)
IS_STREAM = is_enabled('IS_STREAM', True)

# ================= WEB SEARCH / LOGIN =================
# How many results to show per web page (pagination / load-more)
# 21 = 3 columns × 7 rows on desktop; 21 rows on mobile
MAX_WEB_RESULTS = max(1, min(int(environ.get('MAX_WEB_RESULTS', '21')), 100))

# Web login cookie lifetime in seconds — defaults to 7 days
WEB_SESSION_TTL = int(environ.get('WEB_SESSION_TTL', 7 * 24 * 3600))

# Web stream link lifetime in seconds — defaults to 6 hours
WEB_STREAM_TTL = int(environ.get('WEB_STREAM_TTL', 6 * 3600))

# 📸 Only the Telegram thumbnail file_id ("TG_ID:..." string) is stored in the DB.
# No image bytes in the DB or in a server RAM cache — they live in the browser's HTTP cache.
# There is no server-side RAM cache (Koyeb's free tier has 512 MB); the browser keeps
# posters in its own HTTP cache using ETag + max-age (see below).
THUMB_BROWSER_CACHE = int(environ.get('THUMB_BROWSER_CACHE', 7 * 24 * 3600))
# How many Telegram thumbnail downloads may run at once (only files with a known TG_ID)
THUMB_FETCH_CONCURRENCY = max(1, min(int(environ.get('THUMB_FETCH_CONCURRENCY', '6')), 20))

# ── 🖼️ FIRST-TIME THUMBNAIL EXTRACTION (like JoneySin/v5's warmup engine) ──
# Opening 21 new files at once can trigger Telegram FLOOD_WAIT, so probes
# run one at a time with a random gap between files.
#
# ⏱️ PACING: a bot may send ~20 messages per minute to the same chat — one
#    every 3s. Each probe costs more than that one send (download + delete),
#    so the default gap is 3.0–5.0s (≈12–20 probes/min). The old 1.2–3.0s
#    average (~28/min) sat above the limit and kept returning FloodWait
#    during /warmup_thumbs. Tune with the env vars, no code change needed.
THUMB_PROBE_GAP_MIN = max(1.0, float(environ.get('THUMB_PROBE_GAP_MIN', '3.0')))
THUMB_PROBE_GAP_MAX = max(THUMB_PROBE_GAP_MIN, float(environ.get('THUMB_PROBE_GAP_MAX', '5.0')))
THUMB_PROBE_ATTEMPTS = max(1, min(int(environ.get('THUMB_PROBE_ATTEMPTS', '5')), 10))
# On FLOOD_WAIT, wait for Telegram's requested seconds plus this extra buffer
THUMB_FLOOD_EXTRA = max(0, int(environ.get('THUMB_FLOOD_EXTRA', '10')))

# ── 🛡️ REAL-THUMBNAIL VALIDATION (reject fake "NO IMAGE" cards in /warmup_thumbs) ──
# Telegram sometimes returns a generated placeholder, a 1×1 pixel or a blank frame.
# Images that fail these thresholds are never saved as `TG_ID:` — they become NO_THUMB.
THUMB_MIN_BYTES = int(environ.get('THUMB_MIN_BYTES', '512'))
THUMB_MIN_DIM = int(environ.get('THUMB_MIN_DIM', '48'))          # px (both width and height)
# RGB channel stddev — a blank placeholder ≈ 0, a real video frame ≫ 6
THUMB_MIN_STDDEV = float(environ.get('THUMB_MIN_STDDEV', '6.0'))

# Older unsigned /watch/<id> links may have been shared before deployment.
# Default False = only signed links work. Set True for backward compatibility.
ALLOW_UNSIGNED_LINKS = is_enabled('ALLOW_UNSIGNED_LINKS', False)

# ================= PUBLIC URL =================

URL = environ.get("URL", "")
if not URL:
    logger.error('URL is missing')
    exit()

if URL.startswith(('https://', 'http://')):
    if not URL.endswith("/"):
        URL += '/'
elif is_valid_ip(URL):
    URL = f'http://{URL}/'
else:
    logger.error('URL is invalid')
    exit()

# ================= PREMIUM =================

IS_PREMIUM = is_enabled('IS_PREMIUM', True)
PRE_DAY_AMOUNT = int(environ.get('PRE_DAY_AMOUNT', '10'))

UPI_ID = environ.get("UPI_ID", "")
UPI_NAME = environ.get("UPI_NAME", "")
RECEIPT_SEND_USERNAME = environ.get("RECEIPT_SEND_USERNAME", "")

if not UPI_ID or not UPI_NAME:
    logger.info('Premium disabled due to missing UPI details')
    IS_PREMIUM = False
