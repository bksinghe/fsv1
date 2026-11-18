"""Telegram Mini App buttons reuse the existing signed streaming endpoint."""
import ast
import html
import logging
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]


def load(path, names, ns):
    tree = ast.parse((ROOT / path).read_text())
    nodes = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names]
    for n in nodes: n.decorator_list=[]
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), str(path), 'exec'), ns)
    return ns


def constant(path, name):
    tree=ast.parse((ROOT/path).read_text())
    node=next(n for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id==name for t in n.targets))
    return ast.literal_eval(node.value)


def button(label, **kwargs): return {'label':label, **kwargs}


class TelegramPlayerButtonTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.ns=dict(Client=object,CallbackQuery=object, logging=logging,__name__='test',urlsplit=urlsplit,
            temp=SimpleNamespace(FILES={1:{'owner':7,'file_id':'fid'}}),
            enums=SimpleNamespace(ChatType=SimpleNamespace(PRIVATE='private')),
            is_premium=AsyncMock(return_value=True), safe_answer_query=AsyncMock(),
            safe_edit_markup=AsyncMock(return_value=True),
            InlineKeyboardButton=button, InlineKeyboardMarkup=lambda rows:rows,
            WebAppInfo=lambda url:SimpleNamespace(url=url), URL='https://example.com/',
            BIN_CHANNEL=-100, USER_LINK_TTL=86400, sign_params=lambda mid, ttl:'e=123&s=signed')
        load('plugins/callbacks.py',{'cb_handler'},self.ns)
        self.client=SimpleNamespace(send_cached_media=AsyncMock(return_value=SimpleNamespace(id=42)))
        self.query=SimpleNamespace(data='stream#fid',from_user=SimpleNamespace(id=7),
                                   message=SimpleNamespace(chat=SimpleNamespace(type='private')))

    async def test_private_https_has_mini_and_original_links(self):
        await self.ns['cb_handler'](self.client,self.query)
        rows=self.ns['safe_edit_markup'].await_args.args[1]
        self.assertEqual(rows[0][0]['web_app'].url,'https://example.com/watch/42?e=123&s=signed&mini=1')
        self.assertEqual(rows[1][0]['url'],'https://example.com/watch/42?e=123&s=signed')
        self.assertEqual(rows[1][1]['url'],'https://example.com/download/42?e=123&s=signed')
        self.client.send_cached_media.assert_awaited_once_with(chat_id=-100,file_id='fid')

    async def test_http_or_non_private_falls_back_to_original_buttons(self):
        for url, chat_type in [('http://example.com/', 'private'),('https://example.com/', 'group')]:
            self.ns['URL']=url; self.query.message.chat.type=chat_type
            await self.ns['cb_handler'](self.client,self.query)
            rows=self.ns['safe_edit_markup'].await_args.args[1]
            self.assertNotIn('web_app',rows[0][0])
            self.assertEqual(rows[0][0]['label'],'▶️ Watch Online')

    async def test_owner_and_premium_checks_still_gate_link_generation(self):
        self.query.from_user.id=8
        await self.ns['cb_handler'](self.client,self.query)
        self.client.send_cached_media.assert_not_awaited()
        self.query.from_user.id=7;self.ns['is_premium'].return_value=False
        await self.ns['cb_handler'](self.client,self.query)
        self.client.send_cached_media.assert_not_awaited()
        self.ns['safe_edit_markup'].assert_not_awaited()


class MiniWatchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        path='web/utils/render_template.py'
        self.info=SimpleNamespace(file_id='id',file_name='A & <B>.mp4',mime_type='video/mp4',is_video=True)
        self.ns=dict(html=html, get_media_info=AsyncMock(return_value=self.info),
                     unpack_new_file_id=lambda x:'fid',
                     WATCH_HTML=constant(path,'WATCH_HTML'), MINI_WATCH_HTML=constant(path,'MINI_WATCH_HTML'),
                     UNSUPPORTED_HTML=constant(path,'UNSUPPORTED_HTML'))
        load(path,{'media_watch', '_mini_ready_page'},self.ns)

    async def test_mini_player_uses_signed_relative_stream_and_escapes(self):
        page=await self.ns['media_watch'](42,query='e=123&s=signed',mini=True)
        self.assertIn('A &amp; &lt;B&gt;.mp4',page)
        self.assertIn('<video controls playsinline',page)
        self.assertIn('<source src="/download/42?e=123&amp;s=signed">',page)
        self.assertIn('telegram-web-app.js',page)
        self.assertIn('WebApp.ready()',page)
        self.assertNotIn('/api/player/group',page)

    async def test_standard_watch_unchanged_and_non_video_has_download(self):
        page=await self.ns['media_watch'](42,query='e=123&s=signed')
        self.assertIn('SIGNED STREAM',page)
        self.info.is_video=False; self.info.mime_type='application/pdf'; self.info.file_name='file.pdf'
        page=await self.ns['media_watch'](42,query='e=123&s=signed',mini=True)
        self.assertIn('Download File',page)
        self.assertIn('WebApp.ready()',page)
        self.assertIn('/download/42?e=123&amp;s=signed',page)

    async def test_watch_route_still_requires_signed_authorization(self):
        web=SimpleNamespace(Response=lambda **kwargs: SimpleNamespace(status=kwargs.get('status', 200), **{k:v for k,v in kwargs.items() if k != 'status'}))
        calls=AsyncMock(return_value='<video>')
        ns={'web':web, '_allowed':lambda req,mid:req.query.get('s')=='valid',
            '_signed_query':lambda req:'e=123&s=valid', 'media_watch':calls,
            'logger':SimpleNamespace(error=lambda *x:None)}
        load('web/stream_routes.py', {'watch_handler'}, ns)
        req=SimpleNamespace(match_info={'message_id':'42'},query={'mini':'1','s':'bad'})
        response=await ns['watch_handler'](req)
        self.assertEqual(response.status,403);calls.assert_not_awaited()
        req.query['s']='valid'
        response=await ns['watch_handler'](req)
        self.assertEqual(response.status,200)
        self.assertEqual(calls.await_args.kwargs['mini'],True)
        self.assertEqual(calls.await_args.kwargs['query'],'e=123&s=valid')
