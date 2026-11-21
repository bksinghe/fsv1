"""Exercise real HTTP handlers and the Mongo file view with offline transports."""
import importlib.util
import os
import sys
import time
import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch, AsyncMock


@unittest.skipUnless(all(importlib.util.find_spec(x) for x in ('mongomock', 'aiohttp', 'pyrogram', 'pymongo', 'PIL')), 'requires runtime and Mongo mock')
class RecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import mongomock
        from aiohttp.test_utils import TestClient, TestServer
        from pyrogram.file_id import FileId, FileType
        with patch.dict(os.environ, API_ID='123', API_HASH='offline', BOT_TOKEN='offline', ADMINS='7',
                        LOG_CHANNEL='-1001', BIN_CHANNEL='-1002', DATA_DATABASE_URL='mongodb://localhost',
                        URL='https://example.invalid'), patch.dict(sys.modules), patch('pymongo.MongoClient', mongomock.MongoClient):
            from database import ia_filterdb as ia
            from web import create_app, recycle_routes
            self.bin_routes = recycle_routes
            from utils import temp
            from stream_security import sign_params
            self.http = TestClient(TestServer(create_app()))
            await self.http.start_server()
            self.addAsyncCleanup(self.http.close)
            self.ia = ia
            raw = FileId(file_type=FileType.VIDEO, dc_id=2, media_id=1234, access_hash=555, file_reference=b'new').encode()
            self.fid = ia.unpack_new_file_id(raw)
            self.doc = {'_id':self.fid, 'file_name':'Film <HD>.mp4', 'caption':'saved caption', 'group_id':'group'}
            ia.collection.insert_one(self.doc.copy())
            media = NS(file_id=raw, file_size=120, mime_type='video/mp4', file_name=self.doc['file_name'])
            temp.BOT = NS(get_messages=AsyncMock(return_value=NS(media=NS(value='video'), video=media)))
            temp.USER_SESSIONS.update({key: {'tg_id': uid, 'expiry':time.time()+300} for key, uid in [('admin',7), ('user',8)]})
            self.query = sign_params(24)

    async def test_old_signed_requests_and_bin_authorization(self):
        fid, h = self.fid, self.http
        watch = '/watch/24?' + self.query + '&file_id=a-tampered-query-id'
        download = '/download/24?' + self.query
        self.assertEqual((await h.get(watch)).status, 200)  # also warms the BIN metadata cache
        self.assertTrue(await self.ia.delete_file_by_id(fid))
        self.assertEqual((await h.get(watch)).status, 404)
        self.assertEqual((await h.get(download, headers={'Range':'bytes=2-5'})).status, 404)
        self.assertEqual((await h.head(download)).status, 404)
        self.assertIsNone(await self.ia.get_file_details(fid))
        for cookie in ({}, {'user_session':'user'}):
            self.assertEqual((await h.get('/recycle-bin', cookies=cookie)).status, 403)
            self.assertEqual((await h.post('/api/recycle-bin/restore', json={'id':fid}, cookies=cookie)).status, 403)
        cookie = {'user_session':'admin'}
        page = await h.get('/recycle-bin', cookies=cookie)
        self.assertEqual(page.status, 200)
        self.assertIn('Film &lt;HD&gt;.mp4', await page.text())
        self.assertEqual((await h.post('/api/recycle-bin/restore', json={'id':fid}, cookies=cookie)).status, 200)
        self.assertEqual((await h.post('/api/recycle-bin/restore', json={'id':fid}, cookies=cookie)).status, 404)
        restored = await self.ia.get_file_details(fid)
        self.assertEqual({k:restored[k] for k in self.doc}, self.doc)
        self.assertEqual((await h.head(download)).status, 200)

    async def test_bulk_bin_hides_search_and_duplicate_writes_until_restore(self):
        ia = self.ia
        ia.collection.insert_one({'_id':'second', 'file_name':'Film Two'})
        self.assertEqual((await ia.get_search_results('Film'))[2], 2)
        self.assertEqual(await ia.delete_all_files(), 2)
        self.assertEqual(await ia.delete_all_files(), 0)
        self.assertEqual((await ia.get_search_results('Film'))[2], 0)
        self.assertEqual((await ia.get_recent_files())[0], [])
        self.assertFalse(ia.collection.update_one({'_id':self.fid}, {'$set':{'caption':'overwritten'}}).matched_count)
        self.assertEqual(len(ia.collection.bin_page(0,30)), 2)
        self.assertTrue(await ia.restore_file(self.fid))
        self.assertEqual((await ia.get_search_results('Film'))[2], 1)

    async def test_search_filters_before_paging_and_reuses_view_mode(self):
        admin = {'user_session': 'admin'}
        self.ia.collection.insert_one({'_id':'active', 'file_name':'Clip [x] ACTIVE'})
        for i in range(31):
            fid = f'clip{i:02}'
            self.ia.collection.insert_one({'_id':fid, 'file_name':f'Clip [x] {i}', 'thumb_url':'TG_ID:poster'})
            self.ia.collection.recycle(fid)
        self.ia.collection.recycle(self.fid)
        for page, count in [(0, 30), (1, 1)]:
            r = await self.http.get('/recycle-bin', params={'q':'CLIP [x]', 'page':page}, cookies=admin)
            body = (await r.text()).split('<main class="bin">',1)[1].split('</main>',1)[0]
            self.assertEqual(body.count('class="bin-card vm-card"'), count)
            self.assertIn('data-vm-select="1"', body)
            self.assertNotIn('type="submit"', body)
            self.assertIn('data-src="/api/recycle-bin/poster?', body)
            self.assertNotIn(' src="', body)  # text mode must not fetch thumbnails
            self.assertNotIn('ACTIVE', body)
            self.assertNotIn('Film &lt;HD&gt;', body)
            self.assertIn('q=CLIP+%5Bx%5D&amp;page=', body)
        empty = await self.http.get('/recycle-bin?q=.*', cookies=admin)
        self.assertIn('No deleted files match', await empty.text())  # not a regex search

    async def test_bin_poster_checks_role_and_current_bin_membership(self):
        self.ia.collection.update_one({'_id': self.fid}, {'$set': {'thumb_url':'TG_ID:stored'}})
        url = '/api/recycle-bin/poster?id=' + self.fid
        admin = {'user_session': 'admin'}
        with patch.object(self.bin_routes, 'get_image_bytes', AsyncMock(return_value=b'\xff\xd8\xff'+bytes(20))) as get:
            self.assertEqual((await self.http.get(url, cookies=admin)).status, 404)
            self.ia.collection.recycle(self.fid)
            for cookies in ({}, {'user_session':'user'}):
                self.assertEqual((await self.http.get(url, cookies=cookies)).status, 403)
            get.assert_not_awaited()
            r = await self.http.get(url, cookies=admin)
            self.assertEqual((r.status, r.content_type), (200, 'image/jpeg'))
            self.assertIn('no-store', r.headers['Cache-Control'])
            get.assert_awaited_once_with('stored')
            self.ia.collection.restore(self.fid)
            self.assertEqual((await self.http.get(url, cookies=admin)).status, 404)

    async def test_live_search_returns_only_matching_bin_cards_to_admin(self):
        self.ia.collection.recycle(self.fid)
        h = {'Accept': 'application/json'}
        url = '/recycle-bin?q=Film'
        for cookies in ({}, {'user_session':'user'}):
            self.assertEqual((await self.http.get(url, headers=h, cookies=cookies)).status, 403)
        cookies = {'user_session':'admin'}
        response = await self.http.get(url, headers=h, cookies=cookies)
        data = await response.json()
        self.assertIn('Film &lt;HD&gt;.mp4', data['items'])
        self.assertEqual(data['navigation'], '')
        empty = await self.http.get('/recycle-bin?q=other', headers=h, cookies=cookies)
        self.assertIn('No deleted files match', (await empty.json())['items'])
