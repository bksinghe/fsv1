"""Saved quality/episode group offers and one-shot delivery (offline)."""
import asyncio
import logging
import re
import unittest
from collections import namedtuple
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
from test_telegram_callback_audit import load

Offer = namedtuple('Offer', 'owner seed gid label')


class BatchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.group = {'_id':'g', 'name':'Series', 'kind':'episodes',
                      'members':['seed','two','one','two','gone'], 'episode_map':{'one':'S01E01'}}
        self.store = NS(by_members=AsyncMock(return_value=[self.group]), get=AsyncMock(return_value=self.group),
                        files_by_ids=AsyncMock(return_value=[{'_id':'two','file_name':'S02E01'},
                                                              {'_id':'one','file_name':'Z'}]))
        self.ns = dict(store=self.store, BatchOffer=Offer, KIND_EPISODES='episodes', re=re,
                       episode_label=lambda name, idx:(name, int(name[-2:])), logging=logging,
                       asyncio=asyncio, batch_offers={}, batch_jobs={}, has_premium_or_grace=AsyncMock(return_value=True),
                       db=NS(get_settings=AsyncMock(return_value={})), enums=NS(ChatType=NS(GROUP='g', SUPERGROUP='sg')))
        load('plugins/file_deliver.py', {'lookup_offer','remaining_files','send_all','send_batch'}, self.ns)

    async def test_only_grouped_files_offer_and_select_remaining_in_episode_order(self):
        offer = await self.ns['lookup_offer'](7, 'seed')
        self.assertIn('episodes', offer.label)
        self.assertEqual([d['_id'] for d in await self.ns['remaining_files'](offer)], ['one','two'])
        self.group['kind'] = 'qualities'
        self.assertIn('qualities', (await self.ns['lookup_offer'](7, 'seed')).label)
        self.group['members'] = ['seed']
        self.assertIsNone(await self.ns['lookup_offer'](7, 'seed'))
        self.store.by_members.return_value = []
        self.assertIsNone(await self.ns['lookup_offer'](7, 'seed'))

    async def test_only_owner_can_claim_once_even_on_concurrent_taps(self):
        msg = NS(chat=NS(id=-100,type='sg'),id=12,message_thread_id=4)
        key = (-100,12)
        offer = self.ns['batch_offers'][key] = Offer(7,'seed','g','Button')
        self.ns['send_batch'] = AsyncMock()
        query = NS(message=msg,from_user=NS(id=8),answer=AsyncMock())
        await self.ns['send_all'](None, query)
        self.assertIn(key, self.ns['batch_offers'])
        query.from_user.id = 7
        await asyncio.gather(*(self.ns['send_all'](None, query) for _ in range(2)))
        await asyncio.sleep(0)
        self.ns['send_batch'].assert_awaited_once_with(None, msg, offer, True)
        self.assertNotIn(key, self.ns['batch_offers'])

    async def test_batch_preserves_chat_topic_no_nested_offer_and_rechecks_mode(self):
        self.ns.update(send_delivery=AsyncMock(), asyncio=NS(sleep=AsyncMock()))
        msg = NS(chat=NS(id=-100), message_thread_id=4, reply_text=AsyncMock())
        offer = Offer(7,'seed','g','Button')
        self.ns['db'].get_settings.side_effect = [{}, {'group_mode':False}]
        await self.ns['send_batch'](None, msg, offer, True)
        self.ns['send_delivery'].assert_awaited_once_with(None,-100,7,'one',{'_id':'one','file_name':'Z'},
                                                         group=True,topic=4,offer_batch=False)
        msg.reply_text.assert_awaited_once()
