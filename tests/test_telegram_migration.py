"""Offline tests: real Kurigram wire styles and one-shot conversation replies."""
import asyncio
from importlib.util import find_spec
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from telegram_replies import ReplyWaiters


@unittest.skipUnless(find_spec('pyrogram'), 'requires Kurigram')
class ButtonTests(unittest.IsolatedAsyncioTestCase):
    async def test_serialized_buttons_keep_action_and_style(self):
        from telegram_buttons import styled_button

        for action, color in [('help', 'primary'), ('page#123', 'primary'),
                              ('pay_ok#7#plan#99', 'success'), ('pay_no#7', 'danger'),
                              ('idx#cancel', 'danger'), ('idx#start#3#4', 'success')]:
            with self.subTest(action=action):
                raw = await styled_button('Label', callback_data=action).write(None)
                self.assertTrue(getattr(raw.style, 'bg_' + color))
                self.assertEqual(raw.type.data, action.encode())
                self.assertEqual(raw.text, 'Label')
        url = 'https://example.org/watch'
        raw = await styled_button('Watch', url=url).write(None)
        self.assertTrue(raw.style.bg_success)
        self.assertEqual(raw.type.url, url)


class ReplyTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_expected_sender_chat_and_media_match(self):
        waiters = ReplyWaiters()
        async def text(_, msg):
            return bool(msg.text)
        task = asyncio.create_task(waiters.listen(chat_id=4, user_id=5, filters=text, timeout=3))
        await asyncio.sleep(0)
        for chat, user, body in [(4, 6, 'yes'), (3, 5, 'yes'), (4, 5, None), (4, 5, 'yes')]:
            msg = SimpleNamespace(chat=SimpleNamespace(id=chat), from_user=SimpleNamespace(id=user),
                                  text=body, stop_propagation=Mock())
            await waiters.receive(None, msg)
            self.assertEqual(msg.stop_propagation.called, (chat, user, body) == (4, 5, 'yes'))
        self.assertIs(await task, msg)
        self.assertFalse(waiters.pending)

    async def test_timeout_and_cancel_remove_waiters(self):
        waiters = ReplyWaiters()
        with self.assertRaises(asyncio.TimeoutError):
            await waiters.listen(chat_id=1, user_id=2, timeout=0)
        task = asyncio.create_task(waiters.listen(chat_id=1, user_id=2, timeout=60))
        await asyncio.sleep(0)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertFalse(waiters.pending)
