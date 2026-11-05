import os
import aiohttp
import asyncio
import time
from hydrogram import Client, filters
from hydrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from info import ADMINS
from utils import is_premium, get_size

# Config
MB = 1024 * 1024
MAX_FILE_SIZE = 200 * MB   # hard cap for /upload
UPLOAD_TIMEOUT = aiohttp.ClientTimeout(total=1200, connect=30, sock_read=300)
UPLOAD_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}
UPLOAD_STATE = {}

# Upload Sites Info — only the hosts that actually answer.
#   The two hosts that used to sit here (🟠 permanent-storage host and the
#   🟡 one-download host) were removed: every upload to them ended in
#   "❌ Upload to … failed", so they are no longer offered at all.
#   "max" is the biggest file a host accepts; a file bigger than that is never
#   offered for that host (per-site limits), so no attempt is wasted.
SITES_INFO = {
    "gofile": {
        "name": "GoFile", "icon": "🟢", "desc": "Fast stream · long lived",
        "max": 200 * MB,
    },
    "tmpfiles": {
        "name": "TmpFiles", "icon": "🔵", "desc": "1 hour link",
        "max": 100 * MB,
    },
}


def sites_for(size: int):
    """Site keys able to take a file of `size` bytes (GoFile first)."""
    return [key for key, info in SITES_INFO.items() if size <= info["max"]]


def site_label(key: str) -> str:
    info = SITES_INFO[key]
    return f"{info['icon']} {info['name']}"


# UI Buttons
def site_buttons(uid):
    state = UPLOAD_STATE.get(uid, {})
    size = state.get("size", 0)

    available = sites_for(size) or list(SITES_INFO)
    selected = state.get("site")
    if selected not in available:          # the old pick cannot take the file
        selected = available[0]
        state["site"] = selected

    buttons = []
    for key in available:
        info = SITES_INFO[key]
        check = "✅" if key == selected else ""
        limit = get_size(info["max"])
        buttons.append([InlineKeyboardButton(
            f"{info['icon']} {info['name']} · ≤{limit} {check}",
            callback_data=f"site#{key}"
        )])

    # A file too big for a host is simply not offered — no failed attempt.
    skipped = [site_label(k) for k in SITES_INFO if k not in available]
    if skipped:
        buttons.append([InlineKeyboardButton(
            f"🚫 Too big for {', '.join(skipped)}",
            callback_data="noop"
        )])

    buttons.append([InlineKeyboardButton("🚀 Upload", callback_data="do_upload")])
    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel")])

    return InlineKeyboardMarkup(buttons)

# Progress Tracker
class Progress:
    def __init__(self, total, msg):
        self.total = total
        self.sent = 0
        self.start = time.time()
        self.msg = msg
        self.last = 0

    async def update(self, size):
        self.sent += size
        now = time.time()
        if now - self.last < 2:
            return
        
        elapsed = now - self.start
        if elapsed < 1:
            return
            
        percent = (self.sent / self.total) * 100
        speed = (self.sent / elapsed) / 1024
        eta = int((self.total - self.sent) / (speed * 1024 + 1))
        
        try:
            await self.msg.edit(
                f"⚡ **Uploading...**\n\n"
                f"📊 {percent:.1f}%\n"
                f"🚀 {speed:.1f} KB/s\n"
                f"⏳ {eta}s left"
            )
            self.last = now
        except:
            pass

# Upload to GoFile
async def upload_gofile(file_path):
    async with aiohttp.ClientSession(
        timeout=UPLOAD_TIMEOUT, headers=UPLOAD_HEADERS
    ) as session:
        # Get an upload server
        async with session.get("https://api.gofile.io/servers") as r:
            if r.status != 200:
                return None
            data = await r.json()
            if data.get("status") != "ok":
                return None

            servers = data["data"]["servers"]
            # The API returns either [{"name": …}, …] or a plain list of names
            first = servers[0]
            server = first["name"] if isinstance(first, dict) else first

        # Upload
        url = f"https://{server}.gofile.io/uploadFile"
        with open(file_path, "rb") as f:
            data = aiohttp.FormData()
            data.add_field("file", f, filename=os.path.basename(file_path))

            async with session.post(url, data=data) as r:
                if r.status != 200:
                    return None
                result = await r.json()
                if result.get("status") == "ok":
                    return result["data"]["downloadPage"]
    return None

# Upload to TmpFiles
async def upload_tmpfiles(file_path):
    async with aiohttp.ClientSession(
        timeout=UPLOAD_TIMEOUT, headers=UPLOAD_HEADERS
    ) as session:
        with open(file_path, "rb") as f:
            data = aiohttp.FormData()
            data.add_field("file", f, filename=os.path.basename(file_path))

            async with session.post("https://tmpfiles.org/api/v1/upload", data=data) as r:
                if r.status != 200:
                    return None
                result = await r.json()
                if result.get("status") == "success":
                    url = result["data"]["url"]
                    return url.replace("tmpfiles.org/", "tmpfiles.org/dl/")
    return None

# Upload Handler
UPLOADERS = {
    "gofile": upload_gofile,
    "tmpfiles": upload_tmpfiles,
}


async def do_upload(file_path, site, msg):
    uploader = UPLOADERS.get(site)
    if not uploader:
        return None

    try:
        link = await uploader(file_path)
        return link
    except Exception as e:
        print(f"[UPLOAD] {site} error: {e}")
        return None

# /upload Command
@Client.on_message(filters.command("upload") & filters.private)
async def upload_cmd(bot, message):
    uid = message.from_user.id
    
    if uid not in ADMINS and not await is_premium(uid, bot):
        return await message.reply("❌ Premium only")
    
    if not message.reply_to_message or not message.reply_to_message.media:
        return await message.reply("❗ Reply to a file with /upload")
    
    media = message.reply_to_message
    file = media.document or media.video or media.audio
    size = getattr(file, "file_size", 0)
    
    if size > MAX_FILE_SIZE:
        return await message.reply(
            f"❌ File too large — the limit is {get_size(MAX_FILE_SIZE)}."
        )

    # Only the hosts that can take this file are offered
    available = sites_for(size)
    if not available:
        biggest = max(info["max"] for info in SITES_INFO.values())
        return await message.reply(
            f"❌ No host accepts a file of {get_size(size)} "
            f"(max {get_size(biggest)})."
        )

    if uid in UPLOAD_STATE and UPLOAD_STATE[uid].get("uploading"):
        return await message.reply("⚠️ Already uploading")

    UPLOAD_STATE[uid] = {
        "media": media,
        "site": available[0],
        "size": size,
        "uploading": False
    }

    skipped = [site_label(k) for k in SITES_INFO if k not in available]
    note = (
        f"\n🚫 Skipped (file too big): {', '.join(skipped)}"
        if skipped else ""
    )

    await message.reply(
        f"📤 **Select Upload Site**\n\n"
        f"📁 Size: {get_size(size)}\n"
        f"📝 Name: `{getattr(file, 'file_name', 'file')}`"
        f"{note}",
        reply_markup=site_buttons(uid)
    )

# Callback Handler
@Client.on_callback_query(filters.regex("^(site#|do_upload|cancel|noop)"))
async def callback_handler(bot, query: CallbackQuery):
    uid = query.from_user.id
    state = UPLOAD_STATE.get(uid)
    
    if not state:
        return await query.answer("❌ Session expired", True)
    
    data = query.data

    # Disabled "too big for …" row
    if data == "noop":
        return await query.answer("📏 This file is too big for that host", True)
    
    # Site Selection
    if data.startswith("site#"):
        site = data.split("#")[1]
        if site not in sites_for(state.get("size", 0)):
            return await query.answer("📏 This file is too big for that host", True)

        state["site"] = site
        info = SITES_INFO[site]
        
        await query.message.edit_reply_markup(site_buttons(uid))
        await query.answer(f"{info['icon']} {info['name']} - {info['desc']}", True)
        return
    
    # Cancel
    if data == "cancel":
        UPLOAD_STATE.pop(uid, None)
        await query.message.edit("❌ Cancelled")
        return
    
    # Upload
    if data == "do_upload":
        if state.get("uploading"):
            return await query.answer("⚠️ Already uploading", True)
        
        state["uploading"] = True
        await query.message.edit("📥 Downloading...")
        
        asyncio.create_task(start_upload(bot, query.message, uid))

# Main Upload Task
async def start_upload(bot, msg, uid):
    state = UPLOAD_STATE.get(uid)
    if not state:
        return
    
    file_path = None
    
    try:
        media = state["media"]
        site = state["site"]
        site_info = SITES_INFO[site]
        
        # Download
        file_path = await media.download()
        if not file_path or not os.path.exists(file_path):
            return await msg.edit("❌ Download failed")

        real_size = os.path.getsize(file_path)

        # Upload — if the chosen host fails, fall back to the others that can
        # take this file instead of showing "❌ Upload to X failed".
        tried = []
        link = None
        for key in [site] + [k for k in sites_for(real_size) if k != site]:
            tried.append(key)
            info = SITES_INFO[key]
            await msg.edit(f"⚡ Uploading to {info['icon']} {info['name']}...")
            link = await do_upload(file_path, key, msg)
            if link:
                site = key
                site_info = info
                break

        if not link:
            names = ", ".join(site_label(k) for k in tried)
            return await msg.edit(
                "❌ **Upload failed**\n\n"
                f"Tried: {names}\n"
                "Please try again in a few minutes."
            )

        # Success with button
        btn = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔗 Open Link", url=link)
        ]])

        switched = "" if len(tried) == 1 else f"\n↪️ Fell back from {site_label(tried[0])}"

        await msg.edit(
            f"✅ **Upload Complete**\n\n"
            f"📤 Site: {site_info['icon']} {site_info['name']}{switched}\n"
            f"🔗 Link: `{link}`",
            reply_markup=btn,
            disable_web_page_preview=True
        )
        
    except Exception as e:
        await msg.edit(f"❌ Error: {str(e)[:100]}")
    
    finally:
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except:
                pass
        UPLOAD_STATE.pop(uid, None)

# Cancel Command
@Client.on_message(filters.command("cancel_upload") & filters.private)
async def cancel_cmd(_, message):
    uid = message.from_user.id
    UPLOAD_STATE.pop(uid, None)
    await message.reply("✅ Cancelled")
