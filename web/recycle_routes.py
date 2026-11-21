"""Admin-only recycle bin with private video previews."""
import asyncio
import logging
import mimetypes
import time
from collections import OrderedDict
from html import escape
from urllib.parse import urlencode

from aiohttp import web
from pyrogram.file_id import FileId
from info import BIN_CHANNEL, IS_STREAM
from utils import temp
from web.stream_routes import stream_response
from web.utils.media_info import MediaInfo
from database.ia_filterdb import collection, restore_file, unpack_new_file_id
from web.web_assets import app_page, filter_select, get_auth
from web.thumb_engine import get_image_bytes, image_content_type, thumb_id_from_doc
from web.image_validate import is_image_magic

routes = web.RouteTableDef()
PAGE_SIZE = 21


def _card(doc):
    fid = str(doc['_id'])
    image = ''
    if thumb_id_from_doc(doc):
        url = '/api/recycle-bin/poster?' + urlencode({'id': fid})
        image = (f'<img class="vm-img" data-src="{escape(url)}" loading="lazy" alt="" '
                 'onerror="this.hidden=true">')
    name = escape(str(doc.get('file_name') or 'Untitled'))
    return (f'<li class="bin-card vm-card" data-id="{escape(fid)}">'
            f'<button type="button" class="bin-poster vm-overlay" data-options aria-expanded="false" aria-label="File options for {name}">'
            f'<span>No poster available</span>{image}</button><div class="bin-info vm-body">'
            f'<button type="button" class="bin-name" data-preview>{name}</button>'
            f'<small>Deleted {doc["recycled_at"]:%Y-%m-%d %H:%M} UTC</small>'
            '<button type="button" class="tbtn bin-options" data-options aria-expanded="false">Options</button></div>'
            '<div class="bin-actions" role="group" aria-label="File actions" hidden>'
            '<button class="tbtn" data-do="restore">Restore</button>'
            '<button class="tbtn bin-danger" data-do="delete">Delete permanently</button></div></li>')


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


# Cache only Telegram references; never cache bin membership or admin access.
_preview_refs = OrderedDict()
_preview_lock = asyncio.Lock()


async def _preview_info(fid):
    async with _preview_lock:
        cached = _preview_refs.get(fid)
        if cached and cached[0] > time.monotonic():
            return cached[1]
        msg = await temp.BOT.send_cached_media(chat_id=BIN_CHANNEL, file_id=fid, protect_content=True)
        try:
            media = getattr(msg, msg.media.value, None) if msg and msg.media else None
            if not media or unpack_new_file_id(media.file_id) != fid:
                raise ValueError('Telegram returned unexpected media')
            info = MediaInfo(media.file_id, FileId.decode(media.file_id), media.file_size,
                             media.file_name, media.mime_type, bool(msg.video))
        finally:
            if msg:
                try:
                    await msg.delete()
                except Exception:
                    logging.getLogger(__name__).warning('Could not clean up temporary preview message', exc_info=True)
        _preview_refs[fid] = (time.monotonic() + 240, info)
        _preview_refs.move_to_end(fid)
        if len(_preview_refs) > 128:
            _preview_refs.popitem(last=False)
        return info


@routes.get('/api/recycle-bin/preview')
async def bin_preview(req):
    role, _ = await get_auth(req)
    if role != 'admin':
        raise web.HTTPForbidden()
    if not IS_STREAM:
        raise web.HTTPForbidden(text='Streaming is disabled')
    fid = req.query.get('id', '')
    if not 0 < len(fid) <= 512:
        raise web.HTTPBadRequest()
    doc = await asyncio.to_thread(collection.bin_entry, fid)
    if not doc:
        raise web.HTTPNotFound()
    mime = doc.get('mime_type') or ''
    if not mime.startswith('video/'):
        mime = mimetypes.guess_type(doc.get('file_name') or '')[0] or ''
    if not mime.startswith('video/') and doc.get('file_type') == 'video':
        mime = 'video/mp4'
    if not mime.startswith('video/'):
        raise web.HTTPUnsupportedMediaType(text='Not a previewable video')

    async def still_allowed():
        return (await get_auth(req))[0] == 'admin' and bool(await asyncio.to_thread(collection.bin_entry, fid))

    try:
        info = await _preview_info(fid)
    except Exception:
        raise web.HTTPServiceUnavailable(text='Preview temporarily unavailable')
    if not await still_allowed():
        raise web.HTTPNotFound()
    return await stream_response(req, info, still_allowed, preview_mime=mime)


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
.bin-info button{align-self:start;width:fit-content}.bin-poster{width:100%;border:0;cursor:pointer}
.bin-name{font:inherit;font-weight:700;text-align:left;color:var(--txt);background:none;border:0;cursor:pointer;overflow-wrap:anywhere}
.bin-name:hover{text-decoration:underline}.bin-options{display:none}.mode-text .bin-options{display:inline-block}
.bin-actions:not([hidden]){display:flex;flex-wrap:wrap;gap:.5rem;padding:.7rem;background:var(--bg2);border-top:1px solid var(--line)}
.bin dialog{margin:auto;border:1px solid var(--line);border-radius:.8rem;padding:1rem;background:var(--card);color:var(--txt);max-width:min(94vw,52rem)}
.bin dialog::backdrop{background:#000a}.bin dialog h2{font-size:1rem;overflow-wrap:anywhere;margin-bottom:1rem}
.bin video{width:min(76vw,48rem);max-height:65vh;background:black}.bin .bin-danger{color:#b52030;background:#ffe1e4}</style>
<main class="bin"><h1>♻️ Recycle Bin</h1><p>Select a file name for a private preview, or its poster for file options.</p>'''
    body += (f'<form action="/recycle-bin" role="search"><input type="search" name="q" maxlength="120" '
             f'aria-label="Search deleted files by name" placeholder="Search deleted files by name…" value="{escape(query)}">'
             f'{mode}</form>'
             f'<ul class="vgrid vm-grid mode-text">{items}</ul>'
             f'<nav>{navigation}</nav><p role="status"></p>'
             '<dialog id="binPlayer" aria-labelledby="binPlayerName"><h2 id="binPlayerName"></h2><video controls playsinline></video>'
             '<p role="alert"></p><button class="tbtn" data-close>Close</button></dialog></main>')
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
const player=bin.querySelector('#binPlayer'),video=player.querySelector('video');
function setOptions(card,open){
  card.querySelector('.bin-actions').hidden=!open;
  card.querySelectorAll('[data-options]').forEach(b=>b.setAttribute('aria-expanded',String(open)));
}
function closeOptions(){
  const open=grid.querySelector('.bin-actions:not([hidden])');if(open)setOptions(open.closest('.bin-card'),false);
}
player.addEventListener('close',()=>{video.pause();video.removeAttribute('src');video.load();});
video.addEventListener('error',()=>{if(player.open)player.querySelector('[role=alert]').textContent='Preview unavailable or unsupported in this browser.';});
bin.addEventListener('click',async e=>{
  const b=e.target.closest('button');if(!b)return;
  if(b.hasAttribute('data-close')){b.closest('dialog').close();return;}
  const card=b.closest('.bin-card');
  if(!card)return;
  const name=card.querySelector('[data-preview]').textContent,actions=card.querySelector('.bin-actions');
  if(b.hasAttribute('data-options')){
    const open=actions.hidden;closeOptions();if(open)setOptions(card,true);return;
  }
  if(b.hasAttribute('data-preview')){
    closeOptions();player.querySelector('h2').textContent=name;player.querySelector('[role=alert]').textContent='';player.showModal();
    video.src='/api/recycle-bin/preview?'+new URLSearchParams({id:card.dataset.id});video.play().catch(()=>{});return;
  }
  const action=b.dataset.do;if(!action||actions.hidden||actions.dataset.busy)return;
  if(action==='delete'&&!confirm('Permanently delete '+name+'? This cannot be undone.'))return;
  const id=card.dataset.id;actions.dataset.busy='1';b.disabled=true;
  try{const r=await fetch('/api/recycle-bin/'+action,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id,confirmed:action==='delete'})});
    if(!r.ok && r.status!==404)throw Error();location.reload();}
  catch(err){status.textContent='Action failed. Please retry.';}
  finally{delete actions.dataset.busy;b.disabled=false;}
});})();</script>'''
    response = app_page('Recycle Bin', body, uid, role, 'bin')
    response.headers.update(headers)
    return response


@routes.post('/api/recycle-bin/restore')
@routes.post('/api/recycle-bin/delete')
async def change_bin_file(req):
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
    if req.path.endswith('/delete'):
        if data.get('confirmed') is not True:
            raise web.HTTPBadRequest(text='Confirm permanent deletion')
        changed = await asyncio.to_thread(collection.purge, fid)
        _preview_refs.pop(fid, None)
    else:
        changed = await restore_file(fid)
    if not changed:
        raise web.HTTPNotFound(text='Not in the recycle bin')
    return web.json_response({'ok': True})
