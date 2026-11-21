"""Private library flows through the real aiohttp routes, with Mongo mocked offline."""

import importlib.util
import os
import sys
import time
import unittest
from unittest.mock import patch


@unittest.skipUnless(
    all(
        importlib.util.find_spec(x)
        for x in ("mongomock", "aiohttp", "pyrogram", "pymongo", "PIL")
    ),
    "runtime dependencies required",
)
class PersonalLibraryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import mongomock
        from aiohttp.test_utils import TestClient, TestServer

        with (
            patch.dict(
                os.environ,
                API_ID="123",
                API_HASH="test",
                BOT_TOKEN="offline",
                ADMINS="7",
                LOG_CHANNEL="-1",
                BIN_CHANNEL="-2",
                DATA_DATABASE_URL="mongodb://localhost",
                URL="https://test.invalid",
            ),
            patch.dict(sys.modules),
            patch("pymongo.MongoClient", mongomock.MongoClient),
        ):
            from web import create_app
            from database.ia_filterdb import collection
            from utils import temp

            self.files = collection
            for i in range(25):
                collection.insert_one({"_id": str(i), "file_name": f"Movie {i} <HD>"})
            for uid in (8, 9):
                temp.USER_SESSIONS[str(uid)] = {
                    "tg_id": uid,
                    "expiry": time.time() + 360,
                }
            self.http = TestClient(TestServer(create_app()))
            await self.http.start_server()
            self.addAsyncCleanup(self.http.close)

    async def post(self, path, data, uid=8, status=200):
        r = await self.http.post(path, json=data, cookies={"user_session": str(uid)})
        self.assertEqual(r.status, status, await r.text())
        return await r.json() if status == 200 else None

    async def body(self, path, uid=8):
        r = await self.http.get(path, cookies={"user_session": str(uid)})
        self.assertEqual(r.status, 200)
        return await r.text()

    async def test_playlists_owner_order_limits_paging_and_restore(self):
        path = "/api/library/playlists"
        await self.post(path, {"action": "create", "name": "guest"}, 99, 401)
        result = await self.post(
            path, {"action": "create", "name": "Private Night", "file_id": "0"}
        )
        pid = result["id"]
        base = "/playlists?list=" + pid
        self.assertNotIn("Private Night", await self.body("/playlists", 9))
        await self.post(path, {"action": "add", "list": pid, "file_id": "1"}, 9, 400)
        for i in range(22):
            await self.post(path, {"action": "add", "list": pid, "file_id": str(i)})
        self.assertEqual(
            (await self.body(base)).count('class="vm-card" data-file='), 21
        )
        self.assertEqual(
            (await self.body(base + "&page=1")).count('class="vm-card" data-file='), 1
        )
        await self.post(path, {"action": "up", "list": pid, "file_id": "1"})
        s = await self.body(base)
        self.assertLess(s.index('data-file="1"'), s.index('data-file="0"'))
        await self.post(path, {"action": "resume", "list": pid, "file_id": "1"})
        self.assertIn('data-last="1"', await self.body(base))
        self.files.recycle("1")
        self.assertNotIn('data-file="1"', await self.body(base))
        await self.post(
            path, {"action": "add", "list": "later", "file_id": "1"}, status=404
        )
        self.files.restore("1")
        self.assertIn('data-file="1"', await self.body(base))
        await self.post(path, {"action": "remove", "list": pid, "file_id": "1"})
        self.assertTrue(self.files.find_one({"_id": "1"}))

    async def test_playlist_moves_across_hidden_files(self):
        path = "/api/library/playlists"
        for fid in ("1", "2", "3"):
            await self.post(path, {"action": "add", "list": "later", "file_id": fid})
        self.files.recycle("2")
        await self.post(path, {"action": "down", "list": "later", "file_id": "1"})
        s = await self.body("/playlists")
        self.assertLess(s.index('data-file="3"'), s.index('data-file="1"'))
        self.assertNotIn('data-file="2"', s)
        self.files.restore("2")
        s = await self.body("/playlists")
        self.assertLess(s.index('data-file="3"'), s.index('data-file="2"'))
        self.assertLess(s.index('data-file="2"'), s.index('data-file="1"'))

    async def test_live_search_in_both_libraries(self):
        for fid in ("1", "21"):
            await self.post(
                "/api/library/playlists",
                {"action": "add", "list": "later", "file_id": fid},
            )
            await self.post(
                "/api/progress",
                {"file_id": fid, "position": 6, "duration": 60, "played": 6},
            )
        for path in ("/playlists", "/watch-history"):
            form = (
                (await self.body(path))
                .split('<form role="search">')[1]
                .split("</form>")[0]
            )
            self.assertIn('id="libMode"', form)
            self.assertNotIn(">Search</button>", form)
            for q, uid, count in (
                ("MOVIE 21", 8, 1),
                ("", 8, 2),
                ("unknown", 8, 0),
                ("", 9, 0),
            ):
                r = await self.http.get(
                    path,
                    params={"q": q},
                    headers={"Accept": "application/json"},
                    cookies={"user_session": str(uid)},
                )
                self.assertIn("no-store", r.headers["Cache-Control"])
                data = await r.json()
                self.assertEqual(data["items"].count('class="vm-card"'), count)
                if count:
                    self.assertIn('data-file="21"', data["items"])
                    self.assertIn("&lt;HD&gt;", data["items"])
                    self.assertIn(
                        'value="1"', data["queue"]
                    )  # playback order stays unfiltered
                self.assertIn("Page 1", data["navigation"])

    async def test_history_threshold_completion_privacy_pause_remove_clear(self):
        path = "/api/library/history"

        async def watch(fid, pos, played):
            await self.post(
                "/api/progress",
                {"file_id": fid, "position": pos, "duration": 100, "played": played},
            )

        await watch("1", 60, 0)
        await watch("1", 64, 4)
        self.assertNotIn('data-file="1"', await self.body("/watch-history"))
        await watch("1", 65, 5)
        await watch("1", 99, 10)
        body = await self.body("/watch-history")
        self.assertEqual(body.count('data-file="1"'), 1)
        self.assertIn("✓ Watched", body)
        self.assertIn("IST", body)
        self.assertNotIn('data-file="1"', await self.body("/watch-history", 9))
        await self.post(path, {"action": "pause"})
        await watch("2", 50, 20)
        self.assertNotIn('data-file="2"', await self.body("/watch-history"))
        await self.post(path, {"action": "unpause"})
        await watch("2", 50, 20)
        self.assertIn('data-file="2"', await self.body("/watch-history"))
        self.files.recycle("1")
        self.assertNotIn('data-file="1"', await self.body("/watch-history"))
        self.files.restore("1")
        await self.post(path, {"action": "remove", "file_id": "2"})
        self.assertNotIn('data-file="2"', await self.body("/watch-history"))
        await self.post(path, {"action": "clear"})
        self.assertNotIn('data-file="1"', await self.body("/watch-history"))
