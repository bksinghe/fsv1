"""Admin-only, metadata-only recycle bin. No play, download or purge actions."""
import asyncio
from html import escape
from urllib.parse import urlencode

from aiohttp import web
from database.ia_filterdb import collection, restore_file
from web.web_assets import app_page, filter_select, get_auth
from web.thumb_engine import get_image_bytes, image_content_type, thumb_id_from_doc
from web.image_validate import is_image_magic

routes = web.RouteTableDef()
PAGE_SIZE = 30


def _card(doc):
    fid = str(doc['_id'])
    image = ''
    if thumb_id_from_doc(doc):
        url = '/api/recycle-bin/poster?' + urlencode({'id': fid})
        image = (f'<img class="vm-img" data-src="{escape(url)}" loading="lazy" alt="" '
                 'onerror="this.hidden=true">')
    return (f'<li class="bin-card vm-card"><div class="bin-poster vm-overlay">'
            f'<span>No poster available</span>{image}</div><div class="bin-info vm-body">'
            f'<strong>{escape(str(doc.get("file_name") or "Untitled"))}</strong>'
            f'<small>Deleted {doc["recycled_at"]:%Y-%m-%d %H:%M} UTC</small>'
            f'<button class="tbtn" data-id="{escape(fid)}">Restore</button></div></li>')


@routes.get('/api/recycle-bin/poster')
async def bin_poster(req):
    role, _ = await get_auth(req)
    if role != 'admin':
        raise web.HTTPForbidden()
    fid = req.query.get('id', '')
    if not 0 < len(fid) <= 512:
        raise web.HTTPBadRequest(text='Invalid file ID')
    # Only return the saved thumbnail, never probe or copy the deleted media.
    doc = await asyncio.to_thread(collection.bin_poster, fid)
    thumb = thumb_id_from_doc(doc)
    data = await get_image_bytes(thumb) if thumb else None
    if not is_image_magic(data):
        raise web.HTTPNotFound()
    return web.Response(body=data, content_type=image_content_type(data),
                        headers={'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'})


@routes.get('/recycle-bin')
async def recycle_bin(req):
    role, uid = await get_auth(req)
    if role != 'admin':
        raise web.HTTPForbidden()
    try:
        page = max(0, min(100000, int(req.query.get('page', '0'))))
    except ValueError:
        raise web.HTTPBadRequest(text='Invalid page')
    query = req.query.get('q', '').strip()
    if len(query) > 120:
        raise web.HTTPBadRequest(text='Search is limited to 120 characters')
    docs = await asyncio.to_thread(collection.bin_page, page, PAGE_SIZE, query)
    cards = ''.join(_card(d) for d in docs[:PAGE_SIZE])
    empty = 'No deleted files match this search.' if query else 'No deleted files on this page.'
    def page_url(n):
        return '?' + escape(urlencode({'q': query, 'page': n}))
    prev = f'<a href="{page_url(page-1)}">← Previous</a>' if page else ''
    nxt = f'<a href="{page_url(page+1)}">Next →</a>' if len(docs) > PAGE_SIZE else ''
    items = cards or f'<li>{empty}</li>'
    navigation = prev + nxt
    headers = {'Cache-Control': 'private, no-store', 'Vary': 'Accept'}
    if req.headers.get('Accept') == 'application/json':
        return web.json_response({'items': items, 'navigation': navigation}, headers=headers)
    mode = filter_select('binMode', options='view', cap='View mode', label='View mode', vm=True)
    body = '''<style>.bin{margin:2rem auto;padding:0 1rem;max-width:68rem}.bin ul{list-style:none;margin:1rem 0}
.bin form,.bin nav{display:flex;align-items:center;gap:.6rem;flex-wrap:wrap;margin:1rem 0}
.bin form{flex-wrap:nowrap}.bin input{flex:1;min-width:0;background:var(--bg2);color:var(--txt);border:1px solid var(--line);border-radius:8px;padding:.7rem}
.bin-card{overflow:hidden;border:1px solid var(--line);border-radius:10px;background:var(--card)}
.bin-poster{position:relative;display:grid;place-items:center;aspect-ratio:16/9;background:var(--bg3);color:var(--mut)}
.bin-poster img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}
.bin-info{display:grid;gap:.4rem;padding:.8rem}.bin-info strong{overflow-wrap:anywhere}.bin-info small{color:var(--mut)}
.bin-info button{align-self:start;width:fit-content}</style>
<main class="bin"><h1>♻️ Recycle Bin</h1><p>Files here are hidden from the library and cannot be streamed.</p>'''
    body += (f'<form action="/recycle-bin" role="search"><input type="search" name="q" maxlength="120" '
             f'aria-label="Search deleted files by name" placeholder="Search deleted files by name…" value="{escape(query)}">'
             f'{mode}</form>'
             f'<ul class="vgrid vm-grid mode-text">{items}</ul>'
             f'<nav>{navigation}</nav><p role="status"></p></main>')
    body += '''<script>(()=>{ViewMode.init({storage:ViewMode.storageFor()});
const bin=document.querySelector('.bin'),form=bin.querySelector('form'),input=form.elements.q;
const grid=bin.querySelector('.vm-grid'),nav=bin.querySelector('nav'),status=bin.querySelector('[role=status]');
let timer,request;
function cancelSearch(){clearTimeout(timer);if(request)request.abort();}
async function search(){
  cancelSearch();const current=request=new AbortController();
  const url=new URL(form.action),q=input.value.trim();if(q)url.searchParams.set('q',q);
  grid.setAttribute('aria-busy','true');status.textContent='Searching…';
  try{
    const r=await fetch(url,{headers:{Accept:'application/json'},signal:current.signal});
    if(r.status===403&&!current.signal.aborted){location.replace(url);return;}
    if(!r.ok)throw Error();const result=await r.json();if(current.signal.aborted)return;
    grid.innerHTML=result.items;nav.innerHTML=result.navigation;ViewMode.apply();
    history.replaceState(null,'',url);status.textContent='';
  }catch(err){if(!current.signal.aborted)status.textContent='Search failed. Press Enter to retry.';}
  finally{if(request===current)grid.removeAttribute('aria-busy');}
}
function scheduleSearch(){cancelSearch();timer=setTimeout(search,250);}
input.addEventListener('input',e=>{if(!e.isComposing)scheduleSearch();});
input.addEventListener('compositionstart',cancelSearch);input.addEventListener('compositionend',scheduleSearch);
form.addEventListener('submit',e=>{e.preventDefault();search();});
bin.addEventListener('click',async e=>{
const b=e.target.closest('button[data-id]');if(!b)return;b.disabled=true;
try{const r=await fetch('/api/recycle-bin/restore',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:b.dataset.id})});
if(!r.ok && r.status!==404)throw Error();location.reload();}
catch(err){b.disabled=false;document.querySelector('.bin [role=status]').textContent='Restore failed. Please retry.';}});})();</script>'''
    response = app_page('Recycle Bin', body, uid, role, 'bin')
    response.headers.update(headers)
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
