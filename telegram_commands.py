"""Telegram slash menus. Scopes control discoverability, not authorization."""
import logging

from pyrogram.types import (
    BotCommand, BotCommandScopeAllPrivateChats, BotCommandScopeAllGroupChats,
    BotCommandScopeAllChatAdministrators, BotCommandScopeChat,
)

SHARED = (
    ('id', 'Show user, chat or sticker ID'),
    ('link', 'Reply to a file for 5-hour watch and download links (premium)'),
)
PRIVATE = (
    ('start', 'Open the welcome and help menu'),
    *SHARED,
    ('plan', 'View premium plans and pricing'),
    ('myplan', 'Check or renew your plan'),
    ('invoice', 'Show your latest invoice'),
    ('upload', 'Reply to a file to upload it (premium, up to 200 MB)'),
    ('cancel_upload', 'Cancel a pending upload'),
)
GROUP_ADMIN = (
    ('help', 'Show group admin help'),
    ('search', 'Check group search or switch it on/off'),
    ('group_mode', 'Choose group file buttons (on) or PM links (off)'),
)
BOT_ADMIN = (
    ('sendall', 'Check or switch Send All on/off for the whole bot'),
    ('stats', 'Show bot, web and database statistics'),
    ('addpremium', 'Grant a premium plan: user_id days'),
    ('extendpremium', 'Extend a premium plan: user_id days'),
    ('removepremium', 'Remove premium access: user_id'),
    ('delete', 'Delete a file by reply or keyword'),
    ('deleteall', 'Request deletion of all indexed files (confirmation required)'),
    ('warmup_thumbs', 'Scan indexed files for thumbnails and metadata'),
)


async def sync_command_menus(client, admins):
    # Telegram uses the most specific matching list; it does not merge scopes.
    menus = [
        (BotCommandScopeAllPrivateChats(), PRIVATE),
        (BotCommandScopeAllGroupChats(), SHARED),
        (BotCommandScopeAllChatAdministrators(), SHARED + GROUP_ADMIN),
    ]
    menus.extend((BotCommandScopeChat(uid), PRIVATE + BOT_ADMIN)
                 for uid in dict.fromkeys(admins) if uid > 0)
    for scope, entries in menus:
        try:
            await client.set_bot_commands([BotCommand(*entry) for entry in entries], scope=scope)
        except Exception:
            # E.g. an admin's private chat may not be known to Telegram yet.
            logging.getLogger(__name__).warning('Could not sync menu for %s', scope, exc_info=True)
