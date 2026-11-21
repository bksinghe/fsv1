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
            from web import create_app
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
