import logging

# ==========================
# 🔥 LOGGING CONFIG (KOYEB FRIENDLY)
# ==========================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    handlers=[logging.StreamHandler()]
)

# Silence unnecessary logs
logging.getLogger("hydrogram").setLevel(logging.ERROR)
logging.getLogger("aiohttp.access").setLevel(logging.WARNING)  # Hide uptime bot logs
logging.getLogger("aiohttp.server").setLevel(logging.WARNING)

logger = logging.getLogger("XFILER")


import os
import time
import asyncio
import uvloop
from datetime import datetime
import pytz

from hydrogram import Client, filters
from aiohttp import web

from web import web_app
from info import API_ID, API_HASH, BOT_TOKEN, PORT, ADMINS
from database.runtime_config import runtime_config

from utils import (
    temp,
    cleanup_files_memory,
    premium_expiry_reminder
)

from database.users_chats_db import db
# ❌ REMOVED: from plugins.banned import auto_unban_worker


# ==========================
# 🕒 TIME UTILS
# ==========================
IST = pytz.timezone("Asia/Kolkata")

def ist_time():
    return datetime.now(IST).strftime("%d %b %Y, %I:%M %p")


# ==========================
# ⭐ PREMIUM AUTO-REMOVE BACKGROUND TASK
# ==========================
async def check_and_remove_expired_premium(client):
    """
    Background task to automatically remove expired premium users
    Runs every hour
    """
    logger.info("✅ Premium expiry checker started")
    
    while True:
        try:
            users = await db.get_premium_users()
            now = datetime.utcnow()
            removed_count = 0
            
            for user in users:
                try:
                    plan = user.get("plan", {})
                    expire = plan.get("expire")
                    
                    if not expire:
                        continue
                    
                    # Convert to datetime
                    if isinstance(expire, (int, float)):
                        exp_dt = datetime.utcfromtimestamp(expire)
                    else:
                        exp_dt = expire
                    
                    # Check if expired
                    if exp_dt <= now:
                        uid = user.get("_id") or user.get("id")
                        
                        # Remove premium status
                        await db.update_plan(uid, {
                            "premium": False,
                            "plan": None,
                            "expire": None
                        })
                        
                        removed_count += 1
                        logger.info(f"✅ Removed expired premium for user {uid}")
                        
                        # Optional: Notify user
                        try:
                            await client.send_message(
                                uid,
                                "⚠️ **Premium Expired**\n\n"
                                "Your premium subscription has ended.\n"
                                "Use /plan to renew and continue enjoying premium benefits!"
                            )
                        except Exception as e:
                            logger.debug(f"Could not notify user {uid}: {e}")
                
                except Exception as e:
                    logger.error(f"Error processing user premium expiry: {e}")
                    continue
            
            if removed_count > 0:
                logger.info(f"✅ Removed {removed_count} expired premium users")
            
            # Check every hour (3600 seconds)
            await asyncio.sleep(3600)
            
        except Exception as e:
            logger.error(f"❌ Error in check_and_remove_expired_premium: {e}")
            await asyncio.sleep(600)  # Wait 10 minutes on error


# ==========================
# 🧪 GLOBAL DEBUG: /START LOGGER
# ==========================
@Client.on_message(filters.private & filters.command("start"))
async def debug_start_logger(client, message):
    logger.warning(
        f"/START HIT | user={message.from_user.id} | text='{message.text}'"
    )
    # ⚠️ DO NOT reply, DO NOT delete here
    # This is ONLY for logs


# ==========================
# 🤖 BOT CLASS
# ==========================
class Bot(Client):
    def __init__(self):
        super().__init__(
            name="Auto_Filter_Bot",
            api_id=API_ID,
            api_hash=API_HASH,
            bot_token=BOT_TOKEN,
            plugins={"root": "plugins"}
        )

    async def start(self):
        # Load persisted channel/feature overrides before plugins handle updates.
        try:
            await runtime_config.load()
        except Exception:
            logger.exception("Runtime settings could not be loaded; environment defaults remain active")
        await super().start()

        # ---- runtime globals ----
        temp.START_TIME = time.time()
        temp.BOT = self

        # ---- restart notify ----
        if os.path.exists("restart.txt"):
            try:
                with open("restart.txt") as f:
                    cid, mid = map(int, f.read().split())
                    await self.edit_message_text(
                        cid, mid, "✅ Bot Restarted Successfully!"
                    )
            except:
                pass
            os.remove("restart.txt")

        me = await self.get_me()
        temp.ME = me.id
        temp.U_NAME = me.username
        temp.B_NAME = me.first_name

        # ---- web server ----
        runner = web.AppRunner(web_app)
        await runner.setup()
        await web.TCPSite(
            runner,
            host="0.0.0.0",
            port=PORT
        ).start()
        temp.WEB_START = time.time()   # so /stats can report the web server
        logger.info(f"✅ Web server started on port {PORT}")

        # ==========================
        # 🔁 BACKGROUND TASKS
        # ==========================

        # 🔥 FILE MEMORY LEAK GUARD
        asyncio.create_task(cleanup_files_memory())

        # 🔔 PREMIUM EXPIRY REMINDER
        asyncio.create_task(premium_expiry_reminder(self))

        # ❌ REMOVED: auto_unban_worker — the moderation commands it served
        #    (/ban, /mute, …) are gone, so the worker is not needed anymore.

        # ⭐ PREMIUM AUTO-REMOVE (NEW)
        asyncio.create_task(check_and_remove_expired_premium(self))
        logger.info("✅ Premium auto-remove task started")

        # ---- admin notify ----
        for admin in ADMINS:
            try:
                await self.send_message(
                    admin,
                    "♻️ **Bot Restarted Successfully**\n\n"
                    f"🕒 Time: {ist_time()}\n"
                    "🤖 Status: Online & Stable\n"
                    "⭐ Premium System: Active"
                )
            except:
                pass

        # ---- log channel ----
        try:
            await self.send_message(
                runtime_config.get("LOG_CHANNEL"),
                f"🤖 <b>@{me.username} started successfully</b>\n"
                f"🕒 {ist_time()}\n"
                "⭐ Premium auto-remove: Active"
            )
        except:
            pass

        logger.info(f"Bot @{me.username} started successfully")

    async def stop(self, *args):
        await super().stop()
        logger.info("Bot stopped cleanly")


# ==========================
# 🚀 ENTRYPOINT
# ==========================
async def main():
    uvloop.install()
    bot = Bot()
    try:
        await bot.start()
        await asyncio.Event().wait()
    except (KeyboardInterrupt, SystemExit):
        await bot.stop()


if __name__ == "__main__":
    asyncio.run(main())
