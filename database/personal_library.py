"""Bounded private playlists and playback history. No media or signed URLs stored."""

import asyncio
import secrets
import time
from pymongo.errors import DuplicateKeyError
from database.ia_filterdb import collection as media_files
from database.users_chats_db import dbase


def defaults(kind):
    return (
        {"lists": [{"id": "later", "name": "Watch Later", "files": [], "last": ""}]}
        if kind == "playlists"
        else {"paused": False, "items": []}
    )


def collection(kind):
    return dbase["personal_" + kind]


async def read(uid, kind):
    return await asyncio.to_thread(collection(kind).find_one, {"_id": uid}) or defaults(
        kind
    )


def _mutate(uid, kind, apply):
    col = collection(kind)
    for _ in range(12):
        doc = col.find_one({"_id": uid}) or dict(_id=uid, revision=0, **defaults(kind))
        old = doc["revision"]
        result = apply(doc)
        if result is False:
            return None
        doc["revision"] += 1
        if not old:
            try:
                col.insert_one(doc)
                return result
            except DuplicateKeyError:
                continue
        if col.replace_one({"_id": uid, "revision": old}, doc).matched_count:
            return result
    raise ValueError("Library changed. Please retry.")


async def edit_playlist(uid, action, pid, fid, name):
    def apply(doc):
        lists = doc["lists"]
        if action in ("create", "rename"):
            if not name or len(name) > 80:
                raise ValueError("Use a playlist name of 1–80 characters.")
            if any(
                p["name"].casefold() == name.casefold()
                and (action == "create" or p["id"] != pid)
                for p in lists
            ):
                raise ValueError("Playlist name already exists.")
        if action == "create":
            if len(lists) >= 25:
                raise ValueError("Playlist limit reached (25).")
            key = secrets.token_hex(8)
            lists.append(
                {"id": key, "name": name, "files": [fid] if fid else [], "last": ""}
            )
            return key
        p = next((p for p in lists if p["id"] == pid), None)
        if p is None:
            raise ValueError("Playlist unavailable.")
        files = p["files"]
        if action == "rename":
            p["name"] = name
        elif action == "delete" and pid != "later":
            lists.remove(p)
        elif action == "add":
            if fid in files:
                return False
            if len(files) >= 200:
                raise ValueError("Playlist is full (200 videos).")
            files.append(fid)
        elif action in ("remove", "up", "down", "resume") and fid in files:
            if action == "remove":
                files.remove(fid)
                if p["last"] == fid:
                    p["last"] = ""
            elif action == "resume":
                p["last"] = fid
            else:
                i = files.index(fid)
                # Match the active-only list on screen. Keep hidden references in
                # their slots so a later restore does not undo the visible move.
                active = {
                    row["_id"]
                    for row in media_files.find({"_id": {"$in": files}}, {"_id": 1})
                }
                if fid not in active:
                    raise ValueError("File unavailable.")
                step = -1 if action == "up" else 1
                stop = -1 if step < 0 else len(files)
                for j in range(i + step, stop, step):
                    if files[j] in active:
                        files[i], files[j] = files[j], files[i]
                        break
        else:
            raise ValueError("Action unavailable.")
        return pid

    return await asyncio.to_thread(_mutate, uid, "playlists", apply)


async def edit_history(uid, action, fid="", position=0, duration=0):
    def apply(doc):
        if action == "record" and doc["paused"]:
            return False
        if action in ("pause", "unpause"):
            doc["paused"] = action == "pause"
        elif action == "clear":
            doc["items"] = []
        elif action in ("record", "remove"):
            items = [x for x in doc["items"] if x["file_id"] != fid]
            if action == "record":
                items.insert(
                    0,
                    {
                        "file_id": fid,
                        "position": round(position, 1),
                        "duration": round(duration, 1),
                        "updated_at": int(time.time()),
                    },
                )
            doc["items"] = items[:200]
        else:
            raise ValueError("Unknown action.")

    return await asyncio.to_thread(_mutate, uid, "history", apply)
