from pymongo import MongoClient, ReturnDocument
from datetime import datetime, timezone
import hashlib
import hmac
import secrets
import time
import asyncio
import logging

from info import DATABASE_NAME, DATA_DATABASE_URL

# =========================
# 🔗 MongoDB Connection
# =========================
try:
    client = MongoClient(
        DATA_DATABASE_URL,
        serverSelectionTimeoutMS=5000,
        connectTimeoutMS=10000,
        socketTimeoutMS=10000,
        maxPoolSize=50,
        retryWrites=True
    )
    client.server_info()
    dbase = client[DATABASE_NAME]
    print("✅ Database connected successfully")
except Exception as e:
    print(f"❌ Database connection failed: {e}")
    dbase = None


class Database:

    # =========================
    # DEFAULT STRUCTURES
    # =========================
    default_settings = {
        "pm_search": True,
        "group_search": True,
        "auto_delete": False,
        "anti_link": False,
    }

    default_plan = {
        "premium": False,
        "plan": "free",
        "expire": None,
        "invoices": [],
        "last_reminder": None,
        "activated_at": None,
    }

    # =========================
    # INIT
    # =========================
    def __init__(self):
        if dbase is None:
            raise Exception("Database not connected")

        self.users = dbase.users
        self.groups = dbase.groups
        self.premium = dbase.premium
        self.reminders = dbase.reminders
        self.bans = dbase.bans
        self.warns = dbase.warns

        self._create_indexes()

    def _create_indexes(self):
        try:
            self.users.create_index("id", unique=True)
            self.groups.create_index("id", unique=True)
            self.bans.create_index("id")
            self.bans.create_index("until")
            self.warns.create_index([("user_id", 1), ("chat_id", 1)])
            self.premium.create_index("id", unique=True)
            self.reminders.create_index([("sent", 1), ("remind_at", 1)])
        except:
            pass

    # =========================
    # USERS
    # =========================

    async def total_users_count(self):
        return await asyncio.to_thread(self.users.count_documents, {})

    # =========================
    # GROUPS
    # =========================

    async def get_settings(self, chat_id: int):
        group = await asyncio.to_thread(self.groups.find_one, {"id": chat_id})
        settings = self.default_settings.copy()
        if group and "settings" in group:
            settings.update(group["settings"])
        return settings

    async def update_settings(self, chat_id: int, settings: dict):
        await asyncio.to_thread(
            self.groups.update_one,
            {"id": chat_id},
            {"$set": {"settings": settings}},
            upsert=True
        )
        return True

    # =========================
    # 💎 PREMIUM (🔥 FIXED)
    # =========================
    async def get_plan(self, user_id: int):
        data = await asyncio.to_thread(
            self.premium.find_one,
            {"id": user_id}
        )

        if not data:
            return self.default_plan.copy()

        return data.get("plan", self.default_plan.copy())

    async def update_plan(self, user_id: int, plan_data: dict):
        await asyncio.to_thread(
            self.premium.update_one,
            {"id": user_id},
            {"$set": {"plan": plan_data}},
            upsert=True
        )
        return True

    async def get_premium_users(self):
        return await asyncio.to_thread(
            lambda: list(self.premium.find({"plan.premium": True}))
        )


# ======================================================================
# 🌐 WEB AUTHENTICATION (login / register / OTP / session)
#    Same flow as v5, adapted to fsv1's synchronous PyMongo client.
#    All DB calls go through asyncio.to_thread() so the bot's event loop
#    is never blocked.
# ======================================================================

logger = logging.getLogger(__name__)

OTP_TTL = 600            # An OTP stays valid for 10 minutes
OTP_MAX_TRIES = 5        # Maximum wrong attempts for a single OTP
OTP_MAX_SENDS = 3        # Maximum OTPs per Telegram ID in a 10-minute window
MIN_PASSWORD_LEN = 6


class OTPRateLimited(Exception):
    """Raised when OTPs are requested too frequently."""


def hash_password(password: str, salt: str = "") -> str:
    """PBKDF2-HMAC-SHA256 with a per-user salt — safer than plain sha256."""
    salt = salt or secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac(
        "sha256", str(password).encode(), bytes.fromhex(salt), 120_000
    ).hex()
    return f"pbkdf2_sha256$120000${salt}${dk}"


def check_password(password: str, encoded: str) -> bool:
    try:
        algo, iterations, salt, expected = str(encoded).split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", str(password).encode(), bytes.fromhex(salt), int(iterations)
        ).hex()
        return hmac.compare_digest(dk, expected)
    except Exception:
        return False


class WebAuthDB:
    """Web users (``web_users``) + persistent login sessions (``web_sessions``)."""

    def __init__(self, database):
        self.col = database["web_users"] if database is not None else None
        self.sessions = database["web_sessions"] if database is not None else None
        self._ensure_indexes()

    def _ensure_indexes(self):
        try:
            if self.col is None:
                return
            self.col.create_index("tg_id", unique=True)
            self.col.create_index("email", unique=True)
            # TTL index: MongoDB removes expired sessions automatically
            self.sessions.create_index("expire_at", expireAfterSeconds=0)
        except Exception as e:
            logger.debug(f"Web auth index setup skipped: {e}")

    # ───────────────────── USERS ─────────────────────
    async def create_user(self, tg_id: int, email: str, password: str):
        email = str(email or "").strip().lower()
        if await asyncio.to_thread(
            self.col.find_one,
            {"$or": [{"tg_id": tg_id}, {"email": email}]},
            {"_id": 1},
        ):
            return False, "Telegram ID or Email already registered!"
        try:
            await asyncio.to_thread(
                self.col.insert_one,
                {
                    "tg_id": tg_id,
                    "email": email,
                    "password": hash_password(password),
                    "created_at": time.time(),
                    "last_login": 0,
                },
            )
        except Exception as e:
            logger.warning(f"Web user create failed: {e}")
            return False, "Could not create account. Please try again."
        return True, "Account Created Successfully!"

    async def verify_login(self, email: str, password: str):
        email = str(email or "").strip().lower()
        user = await asyncio.to_thread(self.col.find_one, {"email": email})
        if user and check_password(password, user.get("password", "")):
            return user
        return None

    async def identity_exists(self, tg_id: int, email: str) -> bool:
        """True if the Telegram ID or email is already registered."""
        doc = await asyncio.to_thread(
            self.col.find_one,
            {"$or": [{"tg_id": tg_id}, {"email": str(email).strip().lower()}]},
            {"_id": 1},
        )
        return bool(doc)

    async def update_last_login(self, tg_id: int):
        await asyncio.to_thread(
            self.col.update_one, {"tg_id": tg_id}, {"$set": {"last_login": time.time()}}
        )

    # ───────────────── PROFILE SETTINGS (as in v5) ─────────────────
    async def get_profile(self, tg_id: int):
        """Lightweight document for the /profile page (email + timestamps)."""
        doc = await asyncio.to_thread(
            self.col.find_one,
            {"tg_id": tg_id},
            {"email": 1, "last_login": 1, "created_at": 1},
        )
        return doc or {}

    async def email_taken(self, email: str, tg_id: int) -> bool:
        """/api/update_profile — never reuse another account's email."""
        doc = await asyncio.to_thread(
            self.col.find_one,
            {"email": str(email).strip().lower(), "tg_id": {"$ne": tg_id}},
            {"_id": 1},
        )
        return bool(doc)

    async def update_profile(self, tg_id: int, email: str, password: str = ""):
        """Update the email and, optionally, the password — mirrors v5's /api/update_profile.

        When a password is supplied it is stored via hash_password(); invalidating
        sessions is the route's responsibility (the same flow as reset_password).
        """
        data = {"email": str(email).strip().lower()}
        if password:
            data["password"] = hash_password(password)
        await asyncio.to_thread(
            self.col.update_one, {"tg_id": tg_id}, {"$set": data}, upsert=True
        )
        return True

    # ───────────────── PASSWORD RESET OTP ─────────────────
    async def generate_otp(self, tg_id: int):
        user = await asyncio.to_thread(
            self.col.find_one, {"tg_id": tg_id}, {"otp_win": 1, "otp_sends": 1}
        )
        if not user:
            return None
        now = time.time()
        win, sends = user.get("otp_win", 0), user.get("otp_sends", 0)
        if now - win > OTP_TTL:
            win, sends = now, 0
        if sends >= OTP_MAX_SENDS:
            raise OTPRateLimited()
        otp = str(secrets.randbelow(900000) + 100000)
        await asyncio.to_thread(
            self.col.update_one,
            {"tg_id": tg_id},
            {"$set": {"otp": otp, "otp_exp": now + OTP_TTL, "otp_tries": 0,
                      "otp_win": win, "otp_sends": sends + 1}},
        )
        return otp

    async def verify_otp_and_reset(self, tg_id: int, otp: str, new_password: str):
        otp = str(otp or "").strip()
        if not otp or not new_password:
            return False
        user = await asyncio.to_thread(
            lambda: self.col.find_one_and_update(
                {"tg_id": tg_id, "otp": {"$exists": True}},
                {"$inc": {"otp_tries": 1}},
                projection={"otp": 1, "otp_exp": 1, "otp_tries": 1},
                return_document=ReturnDocument.AFTER,
            )
        )
        if not user:
            return False
        clear = {"$unset": {"otp": "", "otp_exp": "", "otp_tries": ""}}
        if user.get("otp_exp", 0) <= time.time() or user.get("otp_tries", 0) > OTP_MAX_TRIES:
            await asyncio.to_thread(self.col.update_one, {"tg_id": tg_id}, clear)
            return False
        if not hmac.compare_digest(str(user.get("otp", "")).encode(), otp.encode()):
            if user.get("otp_tries", 0) >= OTP_MAX_TRIES:
                await asyncio.to_thread(self.col.update_one, {"tg_id": tg_id}, clear)
            return False
        await asyncio.to_thread(
            self.col.update_one,
            {"tg_id": tg_id},
            {"$set": {"password": hash_password(new_password)}, **clear},
        )
        return True

    # ───────────────── LOGIN SESSIONS ─────────────────
    async def create_session(self, sid: str, tg_id: int, expiry: float):
        await asyncio.to_thread(
            self.sessions.replace_one,
            {"_id": sid},
            {"_id": sid, "tg_id": tg_id, "expiry": expiry,
             "expire_at": datetime.fromtimestamp(expiry, tz=timezone.utc)},
            True,   # upsert
        )

    async def get_session(self, sid: str):
        doc = await asyncio.to_thread(
            self.sessions.find_one, {"_id": sid}, {"tg_id": 1, "expiry": 1}
        )
        if doc and doc.get("expiry", 0) > time.time():
            return {"tg_id": doc["tg_id"], "expiry": doc["expiry"]}
        return None

    async def delete_session(self, sid: str):
        await asyncio.to_thread(self.sessions.delete_one, {"_id": sid})

    async def delete_user_sessions(self, tg_id: int):
        await asyncio.to_thread(self.sessions.delete_many, {"tg_id": tg_id})


# =========================
# EXPORT
# =========================
db = Database()
web_db = WebAuthDB(dbase)
