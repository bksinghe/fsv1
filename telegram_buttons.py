"""Color outgoing Telegram buttons by action, never by translated label."""
from copy import copy

from pyrogram.enums import ButtonStyle
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

_DANGER = {'cancel', 'cancel_payment', 'close_data', 'deleteall_cancel', 'idx#close', 'idx#cancel', 'pay_no', 'noop'}
_SUCCESS = {'buy_premium', 'do_upload', 'idx#start', 'pay_ok', 'resend', 'stream', 'send_all'}


def styled_button(text, *, callback_data=None, url=None):
    action = (callback_data or '').split('#')
    key = '#'.join(action[:2]) if action[0] == 'idx' else action[0]
    if key in _DANGER:
        style = ButtonStyle.DANGER
    elif url or key in _SUCCESS:
        style = ButtonStyle.SUCCESS
    else:
        style = ButtonStyle.PRIMARY
    return InlineKeyboardButton(text, callback_data=callback_data, url=url, style=style)


def styled_keyboard(rows):
    """Contrast matching pairs without changing singletons or callback/URL payloads."""
    keyboard = []
    for row in rows:
        if len(row) == 2 and row[0].style == row[1].style:
            left, right = row
            # Keep the right-hand action green/red if both share that meaning.
            if left.style == ButtonStyle.PRIMARY:
                right = copy(right)
                right.style = ButtonStyle.SUCCESS
            else:
                left = copy(left)
                left.style = ButtonStyle.PRIMARY
            row = [left, right]
        keyboard.append(row)
    return InlineKeyboardMarkup(keyboard)
