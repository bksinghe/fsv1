import asyncio
import traceback
import time
from datetime import datetime, timedelta

from hydrogram.errors import FloodWait
from hydrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from info import ADMINS, IS_PREMIUM
from database.users_chats_db import db


# ======================================================
# 🧠 GLOBAL RUNTIME STATE (Koyeb Optimized)
# ======================================================

class temp(object):
    START_TIME = 0
    BOT = None
    ME = None
    U_NAME = None
    B_NAME = None

    SETTINGS = {}
    FILES = {}          # msg_id -> delivery data
    PREMIUM = {}        # RAM premium cache
    KEYWORDS = {}       # learned keywords (RAM)
    BANNED_USERS = set()  # banned users set

    # 🌐 Web login sessions / registration OTP (web/web_assets.py, web/auth_routes.py)
    USER_SESSIONS = {}  # session_id -> {'tg_id': int, 'expiry': float}
    REG_PENDING = {}    # tg_id -> {'email', 'password', 'otp', 'expiry', 'tries'}

    INDEX_STATS = {
        "running": False,
        "start": 0,
        "scanned": 0,
        "saved": 0,
        "dup": 0,
        "err": 0
    }
    
    # Koyeb optimization flags
    _cleanup_running = False
    _reminder_running = False


# ======================================================
# 👑 PREMIUM CONFIG (Synced with premium.py)
# ======================================================

GRACE_PERIOD = timedelta(minutes=30)
PREMIUM_CACHE_TTL = 600  # 10 min cache


# ======================================================
# ⚡ ULTRA FAST PREMIUM CHECK (Required by premium.py)
# ======================================================

async def is_premium(user_id, bot=None) -> bool:
    """
    Koyeb optimized premium check with extended cache
    Returns True if user is premium, False otherwise
    Synced with premium.py grace period logic
    ✅ REQUIRED BY PREMIUM.PY
    """
    # Admins always have premium
    if user_id in ADMINS:
        return True
    
    # If premium system is disabled, everyone has access
    if not IS_PREMIUM:
        return True

    now_ts = time.time()
    cached = temp.PREMIUM.get(user_id)

    # Check cache first (10 min TTL)
    if cached and now_ts - cached["checked_at"] < PREMIUM_CACHE_TTL:
        expire = cached["expire"]
        if expire:
            return datetime.utcnow() <= expire + GRACE_PERIOD
        return False

    # Fetch from database
    try:
        plan = await db.get_plan(user_id)
    except Exception as e:
        print(f"[ERROR] is_premium DB error for user {user_id}: {e}")
        # On error, return cached value if exists
        if cached:
            expire = cached["expire"]
            return bool(expire and datetime.utcnow() <= expire + GRACE_PERIOD)
        return False

    # No plan or not premium
    if not plan or not plan.get("premium"):
        temp.PREMIUM[user_id] = {"expire": None, "checked_at": now_ts}
        return False

    # Get expiry date (older plans hold a raw timestamp, newer ones a datetime)
    expire = plan.get("expire")
    if not isinstance(expire, (int, float, datetime)):
        temp.PREMIUM[user_id] = {"expire": None, "checked_at": now_ts}
        return False
    expire = get_expiry_datetime(expire)

    # Check if expired (with grace period)
    now_utc = datetime.utcnow()
    if now_utc > expire + GRACE_PERIOD:
        # Don't auto-remove here - let background task handle it
        temp.PREMIUM[user_id] = {"expire": None, "checked_at": now_ts}
        return False

    # Cache and return
    temp.PREMIUM[user_id] = {"expire": expire, "checked_at": now_ts}
    return True


# ======================================================
# 📅 DATETIME HELPERS (Required by premium.py)
# ======================================================

def get_expiry_datetime(expire):
    """
    Convert expire timestamp/datetime to datetime object
    ✅ REQUIRED BY PREMIUM.PY
    """
    if isinstance(expire, (int, float)):
        return datetime.utcfromtimestamp(expire)
    return expire


def fmt(dt):
    """
    Format datetime to readable string
    ✅ REQUIRED BY PREMIUM.PY
    """
    if isinstance(dt, (int, float)):
        dt = datetime.utcfromtimestamp(dt)
    return dt.strftime("%d %b %Y, %I:%M %p")


# ======================================================
# 🔔 PREMIUM EXPIRY REMINDER (Koyeb Optimized)
# ======================================================

REMINDER_STEPS = [
    ("1 day", timedelta(days=1)),
    ("6 hours", timedelta(hours=6)),
    ("1 hour", timedelta(hours=1))
]

async def premium_expiry_reminder(bot):
    """
    Koyeb optimized reminder with batch processing
    Sends reminders at: 1 day, 6 hours, 1 hour before expiry
    ✅ REQUIRED FOR PREMIUM SYSTEM
    """
    if temp._reminder_running:
        print("[INFO] Reminder task already running, skipping...")
        return
    
    temp._reminder_running = True
    print("[INFO] ✅ Premium expiry reminder task started")
    
    while True:
        try:
            now = datetime.utcnow()
            users = await db.get_premium_users()
            
            if not users:
                await asyncio.sleep(1800)  # 30 min
                continue
            
            reminder_count = 0
            
            for user in users:
                try:
                    uid = user.get("_id") or user.get("id")
                    
                    if not uid or uid in ADMINS:
                        continue

                    plan = user.get("plan", {})
                    expire = plan.get("expire")
                    last = plan.get("last_reminder")

                    if not expire or not isinstance(expire, (int, float, datetime)):
                        continue
                    expire = get_expiry_datetime(expire)

                    # Check each reminder step
                    for tag, delta in REMINDER_STEPS:
                        # Skip if already sent this reminder
                        if last == tag:
                            continue
                        
                        # Check if it's time for this reminder
                        if expire - delta <= now < expire:
                            try:
                                await bot.send_message(
                                    uid,
                                    "⏰ **Premium Expiry Alert**\n\n"
                                    f"Your premium will expire in **{tag}**.\n\n"
                                    "Use /plan to renew and continue enjoying premium benefits!"
                                )
                                
                                # Update last reminder
                                plan["last_reminder"] = tag
                                await db.update_plan(uid, plan)
                                
                                reminder_count += 1
                                print(f"[INFO] Sent {tag} reminder to user {uid}")
                                
                            except FloodWait as e:
                                print(f"[WARN] FloodWait {e.value}s for user {uid}")
                                await asyncio.sleep(e.value)
                            except Exception as e:
                                print(f"[ERROR] Failed to send reminder to {uid}: {e}")
                            
                            break  # Only send one reminder per user per iteration
                    
                    await asyncio.sleep(0.2)  # Rate limiting
                    
                except Exception as e:
                    print(f"[ERROR] Error processing reminder for user: {e}")
                    continue
            
            if reminder_count > 0:
                print(f"[INFO] Sent {reminder_count} premium expiry reminders")
                    
        except Exception as e:
            print(f"[ERROR] Premium reminder task error: {e}")
        
        await asyncio.sleep(1800)  # Run every 30 minutes


# ======================================================
# 🧠 SEARCH LEARNING + SUGGESTIONS (Koyeb Optimized)
# ======================================================

def learn_keywords(text: str):
    """Lightweight keyword learning with memory limit"""
    try:
        # Prevent memory bloat
        if len(temp.KEYWORDS) > 10000:
            sorted_kw = sorted(temp.KEYWORDS.items(), key=lambda x: x[1], reverse=True)
            temp.KEYWORDS = dict(sorted_kw[:5000])
        
        # Learn keywords from search text
        for w in text.lower().split():
            if 3 <= len(w) <= 50:
                temp.KEYWORDS[w] = temp.KEYWORDS.get(w, 0) + 1
    except Exception as e:
        print(f"[ERROR] Keyword learn error: {e}")


def fast_similarity(a: str, b: str) -> int:
    """Fast similarity check (0-100)"""
    try:
        if a == b:
            return 100
        a_set, b_set = set(a.split()), set(b.split())
        common = a_set & b_set
        if not common:
            return 0
        return min(int((len(common) / max(len(a_set), len(b_set))) * 100), 100)
    except:
        return 0


def suggest_query(query: str):
    """Suggest similar query based on learned keywords"""
    try:
        best, score = None, 0
        query_lower = query.lower()
        
        # Check top 500 keywords only
        for i, k in enumerate(temp.KEYWORDS):
            if i > 500:
                break
            s = fast_similarity(query_lower, k)
            if s > score:
                best, score = k, s
            
        return best if score >= 60 else None
    except Exception as e:
        print(f"[ERROR] Suggest query error: {e}")
        return None


# ======================================================
# 🔁 FILE MEMORY CLEANER (Koyeb Optimized)
# ======================================================

async def cleanup_files_memory():
    """
    Koyeb optimized memory cleanup
    Removes expired files and old premium cache
    """
    if temp._cleanup_running:
        print("[INFO] Cleanup task already running, skipping...")
        return
    
    temp._cleanup_running = True
    print("[INFO] ✅ File memory cleanup task started")
    
    while True:
        try:
            now = int(time.time())
            
            # Cleanup expired files
            expired = [k for k, v in temp.FILES.items() if v.get("expire", 0) <= now]
            if expired:
                for k in expired:
                    temp.FILES.pop(k, None)
                print(f"[INFO] Cleaned {len(expired)} expired files from memory")
            
            # Cleanup old premium cache (keep only 1000 most recent)
            if len(temp.PREMIUM) > 1000:
                old_keys = list(temp.PREMIUM.keys())[:500]
                for k in old_keys:
                    temp.PREMIUM.pop(k, None)
                print(f"[INFO] Cleaned {len(old_keys)} old premium cache entries")
            
            # Cleanup keywords if too many
            if len(temp.KEYWORDS) > 10000:
                sorted_kw = sorted(temp.KEYWORDS.items(), key=lambda x: x[1], reverse=True)
                temp.KEYWORDS = dict(sorted_kw[:5000])
                print("[INFO] Cleaned keywords, kept top 5000")
                    
        except Exception as e:
            print(f"[ERROR] Cleanup task error: {e}")
        
        await asyncio.sleep(120)  # Run every 2 minutes


# ======================================================
# 🧰 UTILITIES
# ======================================================

# ======================================================
# 🔒 PREMIUM PROMPT (ONE SOURCE FOR EVERY FEATURE)
#    PM search, the group file button and PM file delivery
#    used to build this message five times over.
# ======================================================

PREMIUM_BENEFITS = (
    "💎 Get unlimited search access\n"
    "⚡ Faster responses\n"
    "🎯 Priority support\n\n"
    "Upgrade now to unlock this feature!"
)


def premium_required_text(reason):
    """The 🔒 Premium Required message — `reason` says which feature blocked it."""
    return (
        "🔒 <b>Premium Required</b>\n\n"
        f"{reason}\n\n"
        f"{PREMIUM_BENEFITS}"
    )


def premium_buy_markup(close=False):
    """💰 Buy / Renew Premium (+ an optional ❌ Close row)"""
    rows = [[InlineKeyboardButton("💰 Buy / Renew Premium", callback_data="buy_premium")]]
    if close:
        rows.append([InlineKeyboardButton("❌ Close", callback_data="close_data")])
    return InlineKeyboardMarkup(rows)


def log_error(context, error):
    """One console error report (message + traceback) for every handler"""
    print(f"{context} error: {error}")
    traceback.print_exc()


def get_size(size):
    """Convert bytes to human readable format"""
    try:
        size = float(size)
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if size < 1024:
                return f"{size:.2f} {unit}"
            size /= 1024
        return f"{size:.2f} PB"
    except:
        return "0 B"


def get_readable_time(seconds):
    """Convert seconds to readable time"""
    try:
        periods = [("d", 86400), ("h", 3600), ("m", 60), ("s", 1)]
        out = ""
        for name, sec in periods:
            if seconds >= sec:
                val, seconds = divmod(seconds, sec)
                out += f"{int(val)}{name} "
        return out.strip() or "0s"
    except:
        return "0s"


async def get_settings(group_id):
    """Get group settings with caching"""
    try:
        if group_id not in temp.SETTINGS:
            temp.SETTINGS[group_id] = await db.get_settings(group_id)
        return temp.SETTINGS[group_id]
    except Exception as e:
        print(f"[ERROR] Get settings error for group {group_id}: {e}")
        return {}
