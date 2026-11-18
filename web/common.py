"""Shared HTTP helpers for web routes."""
from urllib.parse import quote

from aiohttp import web


def json_response(data, status=200):
    return web.json_response(data, status=status)


async def is_admin(req):
    # Lazy import avoids coupling route helpers to page-asset initialization.
    from web.web_assets import get_auth
    role, _ = await get_auth(req)
    return role == 'admin'


def admin_denied():
    return json_response({'ok': False, 'error': 'Admins only'}, 403)


def redirect(path, **params):
    qs = '&'.join(f'{k}={quote(str(v))}' for k, v in params.items() if v not in (None, ''))
    return web.HTTPFound(path + (f'?{qs}' if qs else ''))
