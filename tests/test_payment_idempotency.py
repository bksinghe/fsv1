"""Durable receipt decisions and one-time grants without a Mongo transaction."""
import ast
import asyncio
import importlib.util
import logging
import sys
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

try:
    import mongomock
    import pymongo
except ImportError:
    mongomock = None

ROOT = Path(__file__).resolve().parents[1]


def load_payment(col):
    spec = importlib.util.spec_from_file_location('isolated_payment_db', ROOT / 'database/payment_db.py')
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {'database.users_chats_db': SimpleNamespace(db=SimpleNamespace(premium=col))}):
        spec.loader.exec_module(module)
    return module


@unittest.skipIf(mongomock is None, 'requires mongomock and pymongo')
class PaymentIdempotencyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.col = mongomock.MongoClient().db.premium
        self.mod = load_payment(self.col)

    async def test_same_receipt_concurrent_retry_and_restart(self):
        async def approve(): return await self.mod.decide_payment(12, -100, 5, 'approved', '7 Days', 100, timedelta(days=7))
        results = await asyncio.gather(*(approve() for _ in range(15)))
        self.assertEqual(sum(r['status'] == 'applied' for r in results), 1)
        doc = self.col.find_one({'id': 12})
        self.assertEqual(len(doc['plan']['invoices']), 1)
        self.assertEqual(len(doc['payment_decisions']), 1)
        restarted = load_payment(self.col)
        again = await restarted.decide_payment(12, -100, 5, 'approved', '7 Days', 100, timedelta(days=7))
        self.assertEqual(again['status'], 'already_decided')
        self.assertEqual(self.col.find_one({'id': 12})['plan'], doc['plan'])

    async def test_different_receipts_extend_same_account_without_lost_update(self):
        now = datetime.now(timezone.utc)
        self.col.insert_one({'id': 12, 'plan': {'premium':True, 'expire':(now+timedelta(days=3)).timestamp(), 'invoices':[]}})
        results = await asyncio.gather(*(self.mod.decide_payment(12, -100, i, 'approved', '7 Days', 10, timedelta(days=7)) for i in range(1,9)))
        self.assertTrue(all(r['status']=='applied' for r in results))
        plan = self.col.find_one({'id':12})['plan']
        self.assertEqual(len(plan['invoices']),8)
        self.assertAlmostEqual(plan['expire'], (now + timedelta(days=59)).timestamp(), places=3)

    async def test_approve_and_reject_compete_on_same_receipt(self):
        approve, reject = await asyncio.gather(
            self.mod.decide_payment(12, 9, 3, 'approved', '7 Days', 10, timedelta(days=7)),
            self.mod.decide_payment(12, 9, 3, 'rejected'))
        self.assertEqual(sum(r['status']=='applied' for r in (approve,reject)),1)
        decision = next(r['decision'] for r in (approve,reject) if r['status']=='applied')
        doc = self.col.find_one({'id':12})
        self.assertEqual(bool(doc.get('plan', {}).get('premium')), decision == 'approved')
        self.assertEqual((await self.mod.decide_payment(12, 9, 3, 'rejected'))['decision'],decision)

    async def test_receipt_ids_are_scoped_to_chat_and_legacy_plan_supported(self):
        expiry = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=2)
        self.col.insert_one({'id':12, 'plan':{'expire':expiry, 'invoices':[{'id':'old'}]}})
        a = await self.mod.decide_payment(12, 1, 99, 'approved','7 Days',10,timedelta(days=7))
        b = await self.mod.decide_payment(12, 2, 99, 'approved','7 Days',10,timedelta(days=7))
        self.assertEqual((a['status'], b['status']),('applied','applied'))
        doc = self.col.find_one({'id':12})
        self.assertEqual(len(doc['plan']['invoices']),3)
        self.assertEqual(len(doc['payment_decisions']),2)

    async def test_ambiguous_write_response_does_not_double_grant(self):
        class Ambiguous:
            def __init__(self, col): self.col=col; self.failed=False
            def __getattr__(self, name): return getattr(self.col,name)
            def with_options(self, **kwargs): return self
            def update_one(self, query, update, **kwargs):
                result=self.col.update_one(query,update,**kwargs)
                if not self.failed and any(k.startswith('payment_decisions.') for k in update.get('$set',{})):
                    self.failed=True
                    raise RuntimeError('connection dropped after write')
                return result
        mod = load_payment(Ambiguous(self.col))
        with self.assertRaises(RuntimeError):
            await mod.decide_payment(12, 1, 1, 'approved','7 Days',10,timedelta(days=7))
        retry = await mod.decide_payment(12, 1, 1, 'approved','7 Days',10,timedelta(days=7))
        self.assertEqual(retry['status'],'already_decided')
        self.assertEqual(len(self.col.find_one({'id':12})['plan']['invoices']),1)

    async def test_invalid_inputs_fail_closed(self):
        with self.assertRaises(ValueError): await self.mod.decide_payment(1, 1, 1, 'approved', duration=timedelta(0))
        with self.assertRaises(ValueError): await self.mod.decide_payment(1, 1, 1, 'unknown')
        self.assertEqual(self.col.count_documents({}),0)


class ApprovalHandlerTests(unittest.IsolatedAsyncioTestCase):
    def load(self):
        tree = ast.parse((ROOT/'plugins/premium.py').read_text())
        nodes = [n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name in ('approve_payment','reject_payment')]
        for n in nodes: n.decorator_list=[]
        ns = dict(CallbackQuery=object, ADMINS=[99], logging=logging, __name__='test_payment',
                  temp=SimpleNamespace(PREMIUM={12: {'expire':None}}),
                  parse_duration=lambda x:timedelta(days=7),normalise_duration=lambda x:x,
                  decide_payment=AsyncMock(),notify_user=AsyncMock(), fmt=str,
                  stamp_receipt=lambda caption, verdict, username:caption+' '+verdict)
        exec(compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),'<premium>', 'exec'),ns)
        return ns

    async def test_duplicate_never_notifies_or_credits_again(self):
        ns=self.load();ns['decide_payment'].return_value={'status':'already_decided','decision':'approved'}
        q=SimpleNamespace(from_user=SimpleNamespace(id=99,username='admin'),data='pay_ok#12#7 Days#100',
                          message=SimpleNamespace(chat=SimpleNamespace(id=-100),id=5,caption='receipt',edit_caption=AsyncMock()),answer=AsyncMock())
        await ns['approve_payment'](None,q)
        self.assertIn('already approved',q.answer.await_args.args[0])
        self.assertNotIn(12, ns['temp'].PREMIUM)
        ns['notify_user'].assert_not_awaited();q.message.edit_caption.assert_not_awaited()
        self.assertEqual(ns['decide_payment'].await_args.args[:4],(12,-100,5,'approved'))


    async def test_success_is_durable_even_if_receipt_edit_fails(self):
        ns = self.load()
        ns['decide_payment'].side_effect = [
            {'status':'applied', 'decision':'approved', 'expire':datetime.now(timezone.utc), 'invoice':{'id':'inv'}},
            {'status':'already_decided','decision':'approved'},
        ]
        q=SimpleNamespace(from_user=SimpleNamespace(id=99,username='admin'),data='pay_ok#12#7 Days#100',
                          message=SimpleNamespace(chat=SimpleNamespace(id=1),id=5,caption='receipt',
                                                  edit_caption=AsyncMock(side_effect=RuntimeError('offline'))),answer=AsyncMock())
        with self.assertLogs('test_payment', level='ERROR'):
            await ns['approve_payment'](None,q)
        await ns['approve_payment'](None,q)
        self.assertEqual(ns['notify_user'].await_count,1)
        self.assertIn('already approved',q.answer.await_args.args[0])

    async def test_rejection_honours_existing_approval(self):
        ns=self.load();ns['decide_payment'].return_value={'status':'already_decided','decision':'approved'}
        q=SimpleNamespace(from_user=SimpleNamespace(id=99,username='admin'),data='pay_no#12',
                          message=SimpleNamespace(chat=SimpleNamespace(id=1),id=5,caption='receipt',edit_caption=AsyncMock()),answer=AsyncMock())
        await ns['reject_payment'](None,q)
        self.assertIn('already approved',q.answer.await_args.args[0]);ns['notify_user'].assert_not_awaited()

    async def test_unauthorized_cannot_decide(self):
        ns=self.load();q=SimpleNamespace(from_user=SimpleNamespace(id=1),answer=AsyncMock())
        await ns['approve_payment'](None,q); await ns['reject_payment'](None,q)
        ns['decide_payment'].assert_not_awaited()
