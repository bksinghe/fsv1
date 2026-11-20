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


class DeliveryCaptionTests(unittest.IsolatedAsyncioTestCase):
    async def test_delivery_uses_only_the_bold_filename(self):
        ns = dict(asyncio=asyncio, html=html, logging=logging, get_file_details=AsyncMock(),
                  has_premium_or_grace=AsyncMock(return_value=True), IS_STREAM=False,
                  styled_button=Mock(), styled_keyboard=Mock(), PROTECT_CONTENT=True,
                  enums=SimpleNamespace(ParseMode=SimpleNamespace(HTML='html')),
                  schedule_file_deletion=AsyncMock(), active_tasks={})
        load('plugins/file_deliver.py', {'deliver_file', 'file_caption', 'track_expiry'}, ns)
        for name, expected in [(' Film <HD> & Co.mkv ', '<b>Film &lt;HD&gt; &amp; Co.mkv</b>'), (None, '')]:
            with self.subTest(name=name):
                ns['get_file_details'].return_value = {'file_name': name, 'caption': 'Original channel caption'}
                client = SimpleNamespace(send_cached_media=AsyncMock(return_value=SimpleNamespace(id=1)))
                await ns['deliver_file'](client, 7, 0, 'file')
                kwargs = client.send_cached_media.await_args.kwargs
                self.assertEqual(kwargs['caption'], expected)
                self.assertEqual(kwargs['parse_mode'], 'html')
                await ns['active_tasks'][(7, 1)]


class GroupDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_group_result_delivers_only_to_its_group_and_topic(self):
        ns = dict(Client=object, enums=SimpleNamespace(ChatType=SimpleNamespace(GROUP='group', SUPERGROUP='supergroup'),
                  ParseMode=SimpleNamespace(HTML='html')), html=html, PROTECT_CONTENT=True,
                  search_expiry=SimpleNamespace(touch=AsyncMock(return_value=True)), track_expiry=Mock(),
                  has_premium_or_grace=AsyncMock(return_value=True), get_file_details=AsyncMock(return_value={'file_name':'A&B'}))
        load('plugins/file_deliver.py', {'file_button_handler', 'file_caption'}, ns)
        client = SimpleNamespace(send_cached_media=AsyncMock())
        msg = SimpleNamespace(id=10, chat=SimpleNamespace(id=-100, type='supergroup'), message_thread_id=3,
                              reply_markup=SimpleNamespace(inline_keyboard=[[SimpleNamespace(callback_data='file#abc')]]))
        query = SimpleNamespace(message=msg, data='file#abc', from_user=SimpleNamespace(id=42), answer=AsyncMock())
        await ns['file_button_handler'](client, query)
        client.send_cached_media.assert_awaited_once_with(chat_id=-100, reply_to_message_id=10, message_thread_id=3,
            file_id='abc', caption='<b>A&amp;B</b>', parse_mode='html', protect_content=True)
        ns['track_expiry'].assert_called_once_with(client, client.send_cached_media.return_value, -100, 'abc', group=True)
        for premium, active in [(False, True), (True, False)]:
            client.send_cached_media.reset_mock()
            ns['has_premium_or_grace'].return_value = premium
            ns['search_expiry'].touch.return_value = active
            await ns['file_button_handler'](client, query)
            client.send_cached_media.assert_not_awaited()


class DeliveryExpiryTests(unittest.IsolatedAsyncioTestCase):
    async def test_closing_one_pm_does_not_disable_expiry_in_another(self):
        state = SimpleNamespace(FILES={})
        ready = asyncio.Event()
        async def sleep(delay):
            if delay == 10:
                await ready.wait()
        ns = dict(temp=state, asyncio=SimpleNamespace(sleep=sleep, CancelledError=asyncio.CancelledError),
                  PM_FILE_DELETE_TIME=10, RESEND_EXPIRE_TIME=1, safe_answer=AsyncMock(),
                  styled_keyboard=lambda rows: rows, styled_button=lambda *a, **kw: kw)
        load('plugins/file_deliver.py', {'schedule_file_deletion'}, ns)
        load('plugins/admin_tools.py', {'close_callback'}, ns)
        client = SimpleNamespace(send_message=AsyncMock(return_value=SimpleNamespace(delete=AsyncMock())))
        messages = [SimpleNamespace(id=9, chat=SimpleNamespace(id=uid), delete=AsyncMock()) for uid in (1, 2)]
        tasks = [asyncio.create_task(ns['schedule_file_deletion'](client, msg, msg.chat.id, 'file')) for msg in messages]
        await asyncio.sleep(0)
        self.assertEqual(set(state.FILES), {(1, 9), (2, 9)})
        await ns['close_callback'](client, SimpleNamespace(message=messages[0], from_user=messages[0].chat))
        self.assertEqual(set(state.FILES), {(2, 9)})
        ready.set()
        await asyncio.gather(*tasks)
        self.assertFalse(state.FILES)
        for msg in messages:
            msg.delete.assert_awaited_once()
        client.send_message.assert_awaited_once()
        self.assertEqual(client.send_message.await_args.args[0], 2)


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

    def test_listeners_are_scoped_to_chat_and_user(self):
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
                  styled_keyboard=lambda x:x, styled_button=lambda *a,**kw:kw)
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
                  styled_keyboard=lambda x:x, styled_button=lambda *a,**kw:kw)
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
        ns=dict(asyncio=asyncio, LISTEN_SHORT=180,
                active_sessions={7:{'step':'waiting_number'}}, cancel_btn=lambda:'cancel',
                duration_buttons=lambda n:'duration', _fail=AsyncMock())
        load('plugins/premium.py', {'_buy_premium_flow'},ns)
        query=SimpleNamespace(message=SimpleNamespace(chat=SimpleNamespace(id=22),edit=AsyncMock()))
        client=SimpleNamespace(listen=AsyncMock(side_effect=asyncio.TimeoutError()))
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
