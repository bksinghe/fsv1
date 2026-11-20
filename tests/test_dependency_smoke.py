"""Offline smoke tests when runtime dependencies are installed."""
import importlib.util
import io
import unittest


@unittest.skipUnless(all(importlib.util.find_spec(name) for name in (
    'pyrogram', 'tgcrypto', 'uvloop', 'aiohttp', 'pymongo', 'PIL', 'qrcode', 'pytz'
)), 'runtime dependencies not installed')
class DependencySmokeTests(unittest.TestCase):
    def test_runtime_imports_crypto_and_qr(self):
        import aiohttp
        import pymongo
        import pytz
        import qrcode
        import uvloop
        from PIL import Image
        from pyrogram import Client
        from pyrogram.crypto import aes
        from pyrogram.file_id import FileId, FileType, ThumbnailSource
        from pyrogram.session import Auth, Session

        self.assertTrue(callable(Client))
        self.assertIsNotNone(aiohttp.web if hasattr(aiohttp, 'web') else aiohttp.ClientSession)
        self.assertTrue(callable(pymongo.MongoClient))
        self.assertTrue(callable(uvloop.install))
        self.assertEqual(str(pytz.timezone('Asia/Kolkata')), 'Asia/Kolkata')
        self.assertEqual(aes._crypto_backend.__name__.lower(), 'tgcrypto')
        data, key, iv = bytes(16), bytes(32), bytes(32)
        self.assertEqual(aes.ige256_decrypt(aes.ige256_encrypt(data, key, iv), key, iv), data)
        image = io.BytesIO()
        qrcode.make('upi://pay?pa=test').save(image, format='PNG')
        image.seek(0)
        Image.open(image).verify()
