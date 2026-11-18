"""Regression tests for callback routing, background jobs and destructive cancel."""
import ast
import asyncio
import html
import logging
import re
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

ROOT = Path(__file__).resolve().parents[1]


def load(path, names, ns):
    tree = ast.parse((ROOT / path).read_text())
    nodes = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names]
    for n in nodes: n.decorator_list = []
    ns.setdefault('CallbackQuery', object)
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), str(path), 'exec'), ns)
    return ns


class CallbackRoutingTests(unittest.TestCase):
    def test_catchall_never_intercepts_other_callbacks(self):
        source = (ROOT / 'plugins/callbacks.py').read_text()
        tree = ast.parse(source)
        node = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'cb_handler')
        pattern = node.decorator_list[0].args[0].args[0].value
        for value in ('help','user_cmds','admin_cmds','stream#abc'):
            self.assertRegex(value, pattern)
        for value in ('page#123','buy_premium','cancel_payment','idx#start#1#2','idx#cancel',
                      'resend#abc','pay_ok#1#7 Days#100','site#x','close_data','deleteall_cancel'):
            self.assertIsNone(re.match(pattern,value), value)

    def test_upload_filter_does_not_capture_payment_cancel(self):
        tree = ast.parse((ROOT / 'plugins/tools.py').read_text())
        node = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'callback_handler')
        pattern = node.decorator_list[0].args[0].args[0].value
        self.assertIsNone(re.match(pattern, 'cancel_payment'))
        for value in ('cancel','site#x','do_upload','noop'): self.assertRegex(value, pattern)

    def test_listeners_use_hydrogram_keyword_signature(self):
        for path in ('plugins/premium.py', 'plugins/admin_tools.py'):
            tree = ast.parse((ROOT / path).read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'listen':
                    self.assertFalse(node.args, path)
                    self.assertTrue({'chat_id','user_id'} <= {k.arg for k in node.keywords})


class DeleteAllTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancel_interrupts_listener_and_never_deletes(self):
        ns = dict(asyncio=asyncio, html=html, logging=logging, datetime=datetime,
                  DELETE_ALL_PENDING={}, DELETE_ALL_OWNERS=set(), LOG_CHANNEL=123,
                  ListenerTimeout=type('ListenerTimeout',(Exception,),{}),
                  db_count_documents=lambda:10, delete_all_files=AsyncMock(return_value=10),
                  fmt=lambda x:'now', filters=SimpleNamespace(text='text'),
                  InlineKeyboardMarkup=lambda x:x, InlineKeyboardButton=lambda *a,**kw:kw)
        load('plugins/admin_tools.py', {'delete_all_cmd','_wait_delete_all','cancel_delete_all'}, ns)
        msg = SimpleNamespace(id=55,chat=SimpleNamespace(id=9),edit=AsyncMock())
        user_msg = SimpleNamespace(chat=SimpleNamespace(id=9),from_user=SimpleNamespace(id=7),
                                   reply=AsyncMock(return_value=msg))
        bot = SimpleNamespace(listen=AsyncMock(side_effect=lambda **kw: asyncio.Event().wait()), send_message=AsyncMock())
        async def listen(**kw): await asyncio.Event().wait()
        bot.listen.side_effect=listen
        await ns['delete_all_cmd'](bot,user_msg)
        self.assertEqual(len(ns['DELETE_ALL_PENDING']),1)
        await asyncio.sleep(0)
        stranger = SimpleNamespace(message=msg,from_user=SimpleNamespace(id=8),answer=AsyncMock())
        await ns['cancel_delete_all'](None,stranger)
        self.assertTrue(stranger.answer.await_args.kwargs['show_alert'])
        query = SimpleNamespace(message=msg,from_user=SimpleNamespace(id=7),answer=AsyncMock())
        await ns['cancel_delete_all'](None,query)
        for _ in range(5): await asyncio.sleep(0)
        ns['delete_all_files'].assert_not_awaited()
        self.assertFalse(ns['DELETE_ALL_PENDING'])
        self.assertFalse(ns['DELETE_ALL_OWNERS'])
        bot.listen.assert_awaited_once_with(chat_id=9,user_id=7,filters='text',timeout=30)


    async def test_confirmation_deletes_only_after_user_scoped_listener_returns(self):
        ns = dict(asyncio=asyncio, html=html, logging=logging, datetime=datetime,
                  DELETE_ALL_PENDING={}, DELETE_ALL_OWNERS=set(), LOG_CHANNEL=123,
                  ListenerTimeout=type('ListenerTimeout',(Exception,),{}),
                  db_count_documents=lambda:10, delete_all_files=AsyncMock(return_value=10),
                  fmt=lambda x:'now', filters=SimpleNamespace(text='text'),
                  InlineKeyboardMarkup=lambda x:x, InlineKeyboardButton=lambda *a,**kw:kw)
        load('plugins/admin_tools.py', {'delete_all_cmd','_wait_delete_all'}, ns)
        response=SimpleNamespace(text='CONFIRM DELETE ALL',delete=AsyncMock())
        bot=SimpleNamespace(listen=AsyncMock(return_value=response),send_message=AsyncMock())
        msg=SimpleNamespace(id=55,chat=SimpleNamespace(id=9),edit=AsyncMock())
        user_msg=SimpleNamespace(chat=SimpleNamespace(id=9),from_user=SimpleNamespace(id=7,mention='admin'),
                                 reply=AsyncMock(return_value=msg))
        await ns['delete_all_cmd'](bot,user_msg)
        for _ in range(15): await asyncio.sleep(0)
        ns['delete_all_files'].assert_awaited_once()
        self.assertFalse(ns['DELETE_ALL_PENDING'])
        self.assertFalse(ns['DELETE_ALL_OWNERS'])
        bot.listen.assert_awaited_once_with(chat_id=9,user_id=7,filters='text',timeout=30)


class IndexBackgroundTests(unittest.IsolatedAsyncioTestCase):
    async def test_index_reserves_lock_runs_in_background_and_releases(self):
        started=asyncio.Event(); release=asyncio.Event()
        async def work(*args): started.set(); await release.wait()
        ns = dict(asyncio=asyncio, LOCK=asyncio.Lock(), CANCEL=False, ADMINS=[7],
                  index_worker=work, log_error=Mock())
        load('plugins/index.py', {'index_callback','_run_index'}, ns)
        query = SimpleNamespace(from_user=SimpleNamespace(id=7), data='idx#start#-100#9',
                                answer=AsyncMock(),message=SimpleNamespace(edit=AsyncMock()))
        bot=SimpleNamespace(get_chat=AsyncMock(return_value=SimpleNamespace(title='channel')))
        await ns['index_callback'](bot,query)
        await started.wait()
        self.assertTrue(ns['LOCK'].locked())
        second=SimpleNamespace(from_user=query.from_user,data=query.data,answer=AsyncMock(),message=query.message)
        await ns['index_callback'](bot,second)
        self.assertIn('already running',second.answer.await_args.args[0])
        release.set()
        for _ in range(3): await asyncio.sleep(0)
        self.assertFalse(ns['LOCK'].locked())


class PaymentBackgroundTests(unittest.IsolatedAsyncioTestCase):
    async def test_buy_and_cancel_task_and_reenter(self):
        started=asyncio.Event()
        async def wait_flow(*args): started.set(); await asyncio.Event().wait()
        ns=dict(asyncio=asyncio,logging=logging,active_sessions={},payment_tasks={},
                _buy_premium_flow=wait_flow,buy_btn=lambda:'buy')
        load('plugins/premium.py', {'_start_payment_task','buy_premium','cancel_payment'},ns)
        query=SimpleNamespace(from_user=SimpleNamespace(id=7),answer=AsyncMock(),
                              message=SimpleNamespace(edit=AsyncMock()))
        await ns['buy_premium'](None,query)
        await started.wait()
        self.assertEqual(ns['active_sessions'][7]['step'],'waiting_number')
        self.assertFalse(ns['payment_tasks'][7].done())
        await ns['cancel_payment'](None,query)
        await asyncio.sleep(0)
        self.assertNotIn(7,ns['active_sessions']);self.assertNotIn(7,ns['payment_tasks'])
        ns['active_sessions'][7]={'step':'waiting_duration','number':5}
        await ns['buy_premium'](None,query)
        self.assertEqual(ns['active_sessions'][7]['step'],'waiting_number')
        await ns['cancel_payment'](None,query)

    async def test_duration_rejects_mismatched_or_double_click(self):
        async def wait_flow(*args): await asyncio.Event().wait()
        ns=dict(asyncio=asyncio,logging=logging,active_sessions={7:{'step':'waiting_duration','number':5}},
                payment_tasks={},_duration_flow=wait_flow,plan_quote=lambda u,n:('5 Days',50,5))
        load('plugins/premium.py', {'_start_payment_task','duration_selected'},ns)
        query=SimpleNamespace(from_user=SimpleNamespace(id=7),data='dur#6#day',answer=AsyncMock())
        await ns['duration_selected'](None,query)
        self.assertNotIn(7,ns['payment_tasks'])
        query.data='dur#5#day'; await ns['duration_selected'](None,query)
        task=ns['payment_tasks'][7]; await ns['duration_selected'](None,query)
        self.assertIs(ns['payment_tasks'][7],task)
        task.cancel()
        await asyncio.gather(task,return_exceptions=True)

class PaymentListenTests(unittest.IsolatedAsyncioTestCase):
    async def test_number_listener_is_scoped_and_timeout_cleans_session(self):
        listener_timeout=type('ListenerTimeout',(Exception,),{})
        ns=dict(asyncio=asyncio, ListenerTimeout=listener_timeout, LISTEN_SHORT=180,
                active_sessions={7:{'step':'waiting_number'}}, cancel_btn=lambda:'cancel',
                duration_buttons=lambda n:'duration', _fail=AsyncMock())
        load('plugins/premium.py', {'_buy_premium_flow'},ns)
        query=SimpleNamespace(message=SimpleNamespace(chat=SimpleNamespace(id=22),edit=AsyncMock()))
        client=SimpleNamespace(listen=AsyncMock(side_effect=listener_timeout()))
        await ns['_buy_premium_flow'](client,query,7)
        client.listen.assert_awaited_once_with(chat_id=22,user_id=7,timeout=180)
        self.assertIn('Timeout',ns['_fail'].await_args.args[3])


class WarmupBackgroundTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_one_warmup_runs_without_holding_callback_worker(self):
        started=asyncio.Event(); stop=asyncio.Event()
        async def worker(*args): started.set(); await stop.wait()
        ns=dict(asyncio=asyncio,_warmup_task=None,_run_warmup=worker,logger=logging.getLogger('test'))
        load('plugins/warmup.py', {'warmup_thumbs_cmd'},ns)
        message=SimpleNamespace(reply=AsyncMock())
        await ns['warmup_thumbs_cmd'](None,message)
        await started.wait()
        await ns['warmup_thumbs_cmd'](None,message)
        self.assertIn('already running',message.reply.await_args.args[0])
        stop.set()
        await ns['_warmup_task']

class DeleteBackgroundTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_one_archive_delete_job_at_a_time(self):
        started=asyncio.Event(); release=asyncio.Event()
        async def worker(*args): started.set(); await release.wait()
        ns=dict(asyncio=asyncio,logging=logging,__name__='test_delete',_delete_task=None,_run_delete=worker)
        load('plugins/admin_tools.py', {'delete_cmd'},ns)
        message=SimpleNamespace(reply=AsyncMock())
        await ns['delete_cmd'](None,message)
        await started.wait()
        await ns['delete_cmd'](None,message)
        self.assertIn('already running',message.reply.await_args.args[0])
        release.set(); await ns['_delete_task']
