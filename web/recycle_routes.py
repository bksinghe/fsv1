"""Admin-only, metadata-only recycle bin. No play, download or purge actions."""
import asyncio
from html import escape

from aiohttp import web
from database.ia_filterdb import collection, restore_file
from web.web_assets import app_page, get_auth

routes = web.RouteTableDef()
PAGE_SIZE = 30


@routes.get('/recycle-bin')
async def recycle_bin(req):
    role, uid = await get_auth(req)
    if role != 'admin':
        raise web.HTTPForbidden()
    try:
        page = max(0, min(100000, int(req.query.get('page', '0'))))
    except ValueError:
        raise web.HTTPBadRequest(text='Invalid page')
    docs = await asyncio.to_thread(collection.bin_page, page, PAGE_SIZE)
    rows = ''.join(
        f'<li><div><strong>{escape(str(d.get("file_name") or "Untitled"))}</strong><br>'
        f'<small>Deleted {d["recycled_at"]:%Y-%m-%d %H:%M} UTC</small></div>'
        f'<button class="tbtn" data-id="{escape(str(d["_id"]))}">Restore</button></li>'
        for d in docs[:PAGE_SIZE])
    prev = f'<a href="?page={page-1}">← Previous</a>' if page else ''
    nxt = f'<a href="?page={page+1}">Next →</a>' if len(docs) > PAGE_SIZE else ''
    body = '''<style>.bin{margin:2rem auto;padding:0 1rem;max-width:54rem}.bin ul{list-style:none;margin:1rem 0}
.bin li,.bin nav{display:flex;align-items:center;justify-content:space-between;gap:1rem;padding:.8rem 0}
.bin li{border-bottom:1px solid var(--line)}.bin strong{overflow-wrap:anywhere}.bin small{color:var(--mut)}</style>
<main class="bin"><h1>♻️ Recycle Bin</h1><p>Files here are hidden from the library and cannot be streamed.</p>'''
    body += f'<ul>{rows or "<li>No deleted files on this page.</li>"}</ul><nav>{prev}{nxt}</nav><p role="status"></p></main>'
    body += '''<script>document.querySelector('.bin').addEventListener('click',async e=>{
const b=e.target.closest('button[data-id]');if(!b)return;b.disabled=true;
try{const r=await fetch('/api/recycle-bin/restore',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:b.dataset.id})});
if(!r.ok && r.status!==404)throw Error();location.reload();}
catch(err){b.disabled=false;document.querySelector('.bin [role=status]').textContent='Restore failed. Please retry.';}});</script>'''
    response = app_page('Recycle Bin', body, uid, role, 'bin')
    response.headers['Cache-Control'] = 'private, no-store'
    return response


@routes.post('/api/recycle-bin/restore')
async def restore(req):
    role, _ = await get_auth(req)
    if role != 'admin':
        raise web.HTTPForbidden()
    if req.content_type != 'application/json':
        raise web.HTTPUnsupportedMediaType()
    try:
        data = await req.json()
    except ValueError:
        raise web.HTTPBadRequest(text='Invalid JSON')
    fid = data.get('id') if isinstance(data, dict) else None
    if not isinstance(fid, str) or not 0 < len(fid) <= 512:
        raise web.HTTPBadRequest(text='Invalid file ID')
    if not await restore_file(fid):
        raise web.HTTPNotFound(text='Not in the recycle bin')
    return web.json_response({'ok': True})
