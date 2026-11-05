import random
from hydrogram import Client, filters, enums
from hydrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from info import PICS
from Script import script


# ======================================================
# 🔘 START BUTTONS (MINIMAL)
# ======================================================
def start_buttons():
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("👨‍🚒 Help", callback_data="help")
            ]
        ]
    )


# ======================================================
# 🚀 /start COMMAND (NORMAL - NOT FILE DELIVERY)
# ======================================================
@Client.on_message(
    filters.command("start") &
    filters.private &
    ~filters.regex(r"file_")  # ✅ Exclude file delivery
)
async def start_cmd(client, message):
    """Handle /start command for normal users"""
    caption = script.START_TXT.format(
        message.from_user.mention,
        (await client.get_me()).mention
    )
    try:
        await message.reply_photo(
            photo=random.choice(PICS),
            caption=caption,
            parse_mode=enums.ParseMode.HTML,
            reply_markup=start_buttons()
        )
    except Exception:
        # Fallback if photo fails
        await message.reply_text(
            text=caption,
            parse_mode=enums.ParseMode.HTML,
            reply_markup=start_buttons()
        )


# ======================================================
# 🆔 /id COMMAND (PM + GROUP | USER + STICKER | ADMIN BADGE)
#    Moved here from the deleted plugins/misc.py — this file
#    now holds every plain-user command that is not search,
#    premium or upload related.
# ======================================================
@Client.on_message(filters.command("id"))
async def get_id(client, message):

    reply = message.reply_to_message

    # ---------- USER TARGET ----------
    user = (
        reply.from_user
        if reply and reply.from_user
        else message.from_user
    )

    # ---------- ADMIN BADGE ----------
    badge = "👤 Member"
    if message.chat.type in (enums.ChatType.GROUP, enums.ChatType.SUPERGROUP):
        try:
            member = await message.chat.get_member(user.id)
            if member.status == enums.ChatMemberStatus.OWNER:
                badge = "👑 Owner"
            elif member.status in (
                enums.ChatMemberStatus.ADMINISTRATOR,
                enums.ChatMemberStatus.ADMIN
            ):
                badge = "🛡 Admin"
        except Exception:
            pass

    # ---------- USER INFO ----------
    text = (
        "🆔 <b>ID INFORMATION</b>\n\n"
        f"👤 <b>Name:</b> {user.first_name or ''} {user.last_name or ''}\n"
        f"🦹 <b>User ID:</b> <code>{user.id}</code>\n"
        f"🏷 <b>Username:</b> @{user.username if user.username else 'N/A'}\n"
        f"🌐 <b>DC ID:</b> <code>{user.dc_id or 'Unknown'}</code>\n"
        f"🤖 <b>Bot:</b> {'Yes' if user.is_bot else 'No'}\n"
        f"{badge}\n"
        f"🔗 <b>Profile:</b> <a href='tg://user?id={user.id}'>Open</a>\n"
    )

    # ---------- CHAT & MESSAGE INFO ----------
    text += (
        "\n💬 <b>CHAT & MESSAGE INFO</b>\n\n"
        f"🆔 <b>Chat ID:</b> <code>{message.chat.id}</code>\n"
        f"🏷 <b>Chat Type:</b> <code>{message.chat.type.name}</code>\n"
        f"📩 <b>Message ID:</b> <code>{message.id}</code>\n"
    )

    # ---------- GROUP INFO ----------
    if message.chat.type in (enums.ChatType.GROUP, enums.ChatType.SUPERGROUP):
        text += (
            "\n👥 <b>GROUP INFORMATION</b>\n\n"
            f"📛 <b>Title:</b> {message.chat.title}\n"
            f"🆔 <b>Group ID:</b> <code>{message.chat.id}</code>\n"
            f"🔗 <b>Username:</b> @{message.chat.username if message.chat.username else 'N/A'}\n"
        )

    # ---------- STICKER INFO ----------
    if reply and reply.sticker:
        st = reply.sticker
        text += (
            "\n🎭 <b>STICKER INFORMATION</b>\n\n"
            f"🆔 <b>File ID:</b> <code>{st.file_id}</code>\n"
            f"📦 <b>Set Name:</b> <code>{st.set_name or 'N/A'}</code>\n"
            f"🔖 <b>Emoji:</b> {st.emoji or 'N/A'}\n"
            f"📐 <b>Size:</b> {st.width}×{st.height}\n"
            f"🎞 <b>Animated:</b> {'Yes' if st.is_animated else 'No'}\n"
            f"🧩 <b>Video:</b> {'Yes' if st.is_video else 'No'}\n"
        )

    await message.reply_text(
        text,
        parse_mode=enums.ParseMode.HTML,
        disable_web_page_preview=True
    )
