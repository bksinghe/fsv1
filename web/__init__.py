# web/__init__.py
#
# 🌐 WEB APP
#   stream_routes  → /, /watch/<id>, /download/<id> (signed + Range streaming)
#   auth_routes    → /login, /register, OTP, /logout (cookie sessions)
#   search_routes  → /search, /api/search, /api/thumb, /api/stream
#   file_edit_routes → /api/file/{meta,edit,thumb,thumb_reset,delete} (admin)
#   group_routes   → /api/group/* (permanent quality groups, admin CRUD/merge/scan)
#   catalog_routes → /posts, /actors, /post/<id>, /actor/<id> + generic JSON API
#   stats_routes   → /stats, /api/db_stats ("Database Stats", as in v5)
#   profile_routes → /profile, /api/update_profile ("Profile Settings", as in v5)
#
# The v5-style web experience — sidebar (Home / Posts / Actors / Database Stats /
# Profile Settings / Sign Out) — adapted to fsv1's existing bot links.
# Posts + Actors use one shared catalog engine instead of v5's two 1,400-line pages.

from aiohttp import web

# ⚠️ Names are `_`-prefixed: otherwise `web.search_routes` would be overwritten
# as a package attribute by RouteTableDef and `import web.search_routes` would break.
from web.stream_routes import routes as _stream_routes
from web.auth_routes import auth_routes as _auth_routes
from web.search_routes import search_routes as _search_routes
from web.catalog_routes import catalog_routes as _catalog_routes
from web.stats_routes import stats_routes as _stats_routes
from web.profile_routes import profile_routes as _profile_routes
from web.file_edit_routes import file_edit_routes as _file_edit_routes
from web.group_routes import group_routes as _group_routes
from web.recycle_routes import routes as _recycle_routes
from web.library_routes import routes as _library_routes
from web.progress_routes import progress_routes as _progress_routes


def create_app():
    app = web.Application(client_max_size=100 * 1024 * 1024)

    app.add_routes(_stream_routes)
    app.add_routes(_auth_routes)
    app.add_routes(_search_routes)
    app.add_routes(_catalog_routes)
    app.add_routes(_stats_routes)
    app.add_routes(_profile_routes)
    app.add_routes(_file_edit_routes)
    app.add_routes(_group_routes)
    app.add_routes(_progress_routes)
    app.add_routes(_library_routes)
    app.add_routes(_recycle_routes)

    return app


web_app = create_app()
