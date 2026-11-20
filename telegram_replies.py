"""Chat- and user-scoped one-shot replies for the purchase and admin dialogs."""
import asyncio


class ReplyWaiters:
    def __init__(self):
        self.pending = {}

    async def listen(self, *, chat_id, user_id, timeout, filters=None):
        key = chat_id, user_id
        if key in self.pending:
            raise RuntimeError('Already waiting for a reply in this chat')
        future = asyncio.get_running_loop().create_future()
        self.pending[key] = future, filters
        try:
            return await asyncio.wait_for(future, timeout)
        finally:
            self.pending.pop(key, None)

    async def receive(self, client, message):
        if not message.chat or not message.from_user or (message.text or "").startswith("/"):
            return
        waiter = self.pending.get((message.chat.id, message.from_user.id))
        if waiter:
            future, check = waiter
            if (check is None or await check(client, message)) and not future.done():
                future.set_result(message)
                message.stop_propagation()
