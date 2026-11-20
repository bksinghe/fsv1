"""Color outgoing Telegram buttons by action, never by translated label."""
from pyrogram.enums import ButtonStyle
from pyrogram.types import InlineKeyboardButton

_DANGER = {'cancel', 'cancel_payment', 'close_data', 'deleteall_cancel', 'idx#close', 'idx#cancel', 'pay_no', 'noop'}
_SUCCESS = {'buy_premium', 'do_upload', 'idx#start', 'pay_ok', 'resend', 'stream'}


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
