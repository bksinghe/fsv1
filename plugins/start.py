import random
from hydrogram import Client, filters, enums
from hydrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from info import PICS, ADMINS
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
# 🔘 HELP BUTTONS (🛡️ ADMIN ONLY FOR ADMINS)
# ======================================================
def help_buttons(is_admin: bool = False):
    row = [InlineKeyboardButton("👤 User Commands", callback_data="user_cmds")]
    if is_admin:
        row.append(
            InlineKeyboardButton("🛡️ Admin Commands", callback_data="admin_cmds")
        )
    return InlineKeyboardMarkup(
        [
            row,
            [InlineKeyboardButton("❌ Close", callback_data="close_data")]
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
# ℹ️ /help & /commands (PM)
#    Group /help stays in plugins/group_mgmt.py (admin only)
# ======================================================
@Client.on_message(filters.command(["help", "commands"]) & filters.private)
async def help_cmd(client, message):
    """Help menu in PM — the same menu as the 👨‍🚒 Help button of /start"""
    caption = script.HELP_TXT.format(message.from_user.mention)
    buttons = help_buttons(message.from_user.id in ADMINS)

    try:
        await message.reply_photo(
            photo=random.choice(PICS),
            caption=caption,
            parse_mode=enums.ParseMode.HTML,
            reply_markup=buttons
        )
    except Exception:
        await message.reply_text(
            text=caption,
            parse_mode=enums.ParseMode.HTML,
            reply_markup=buttons
        )
