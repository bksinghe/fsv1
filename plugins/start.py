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
