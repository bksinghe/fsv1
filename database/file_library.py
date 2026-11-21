"""Default file collection view. Only the recycle-bin operations see hidden rows."""
import re
import time
from datetime import datetime, timezone


class FileLibrary:
    def __init__(self, collection):
        self._raw = collection

    @staticmethod
    def _active(query):
        return {**query, 'recycled_at': {'$exists': False}}

    def find(self, query, *args, **kwargs):
        return self._raw.find(self._active(query), *args, **kwargs)

    def find_one(self, query, *args, **kwargs):
        return self._raw.find_one(self._active(query), *args, **kwargs)

    def count_documents(self, query, **kwargs):
        return self._raw.count_documents(self._active(query), **kwargs)

    def update_one(self, query, update):
        return self._raw.update_one(self._active(query), update)

    def mark_group(self, ids, gid, only_if=None):
        # Keep membership in sync even when a group is merged/deleted while a file is hidden.
        query = {'_id': {'$in': ids}}
        if only_if is not None:
            query['group_id'] = str(only_if)
        update = {'$set': {'group_id': str(gid)}} if gid else {'$unset': {'group_id': ''}}
        return self._raw.update_many(query, update).modified_count

    def insert_one(self, doc):
        # A hidden file retains its unique _id. Re-indexing cannot resurrect it.
        return self._raw.insert_one(doc)

    def recycle(self, fid=None):
        query = {} if fid is None else {'_id': fid}
        update = {'$set': {'recycled_at': datetime.now(timezone.utc), 'bin_revision': time.time_ns()}}
        return self._raw.update_many(self._active(query), update).modified_count

    @staticmethod
    def _in_bin():
        return {'recycled_at': {'$exists': True}, 'purged': {'$ne': True}}

    def bin_entry(self, fid):
        return self._raw.find_one({'_id': fid, **self._in_bin()}, {'file_name': 1, 'mime_type': 1, 'file_type': 1})

    def purge(self, fid):
        # Keep only a denial marker: removing the ID would unblock old signed links.
        return self._raw.replace_one({'_id': fid, **self._in_bin()},
                                     {'_id': fid, 'purged': True, 'recycled_at': datetime.now(timezone.utc),
                                      'bin_revision': time.time_ns()}).modified_count

    def restore(self, fid):
        return self._raw.update_one({'_id': fid, **self._in_bin()},
                                    {'$unset': {'recycled_at': ''}, '$set': {'bin_revision': time.time_ns()}}).modified_count

    def revision(self):
        row = self._raw.find_one({'bin_revision': {'$exists': True}}, {'bin_revision': 1}, sort=[('bin_revision', -1)])
        return row['bin_revision'] if row else 0

    def recycled_ids(self, ids):
        return {row['_id'] for row in self._raw.find({'_id': {'$in': list(ids)}, 'recycled_at': {'$exists': True}}, {'_id': 1})}

    def bin_poster(self, fid):
        return self._raw.find_one({'_id': fid, **self._in_bin()},
                                  {'thumb_url': 1, 'thumb_file_id': 1})

    def bin_page(self, page, limit, query=''):
        match = self._in_bin()
        if query:
            match['file_name'] = re.compile(re.escape(query), re.IGNORECASE)
        fields = {'file_name': 1, 'recycled_at': 1, 'thumb_url': 1, 'thumb_file_id': 1}
        return list(self._raw.find(match, fields).sort([('recycled_at', -1), ('_id', 1)])
                    .skip(page * limit).limit(limit + 1))
