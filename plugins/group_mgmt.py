from hydrogram import Client, filters, enums


# =========================
# HELPERS
# =========================

async def is_admin(client, chat_id, user_id):
    try:
        member = await client.get_chat_member(chat_id, user_id)
        return member.status in (
            enums.ChatMemberStatus.ADMINISTRATOR,
            enums.ChatMemberStatus.OWNER
        )
    except:
        return False


# =========================
# ANTI BOT PROTECTION
# =========================

@Client.on_message(filters.new_chat_members)
async def anti_bot(client, message):
    for user in message.new_chat_members:
        if user.is_bot and not await is_admin(client, message.chat.id, message.from_user.id):
            await client.ban_chat_member(message.chat.id, user.id)


# =========================
# HELP COMMAND (GROUP ADMIN ONLY)
# =========================

@Client.on_message(filters.group & filters.command("help"))
async def help_command(client, message):
    if not await is_admin(client, message.chat.id, message.from_user.id):
        return

    help_text = (
        "🛠️ **Admin Help Menu**\n"
        "━━━━━━━━━━━━━━━━━━\n\n"

        "🔍 **File Search:**\n"
        "• `/search` – Show the current status\n"
        "• `/search on` – Enable file search here\n"
        "• `/search off` – Disable file search here\n\n"

        "🤖 **Auto Protection:**\n"
        "• Anti-bot system is enabled\n"
        "• Only admins can add bots\n\n"

        "⚠️ **Note:** `/help` is admin-only"
    )

    await message.reply(help_text)
