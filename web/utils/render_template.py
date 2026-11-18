"""🎬 Watch page template.

`/watch/<message_id>?e=..&s=..` serves the signed player page. The <video> src
points at `/download/<id>` with the same signed token, so seeking and Range
requests work through that link too. The thumbnail is also shown as the poster.
"""

import html

from web.utils.media_info import get_media_info
from database.ia_filterdb import unpack_new_file_id

WATCH_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
:root{{--bg:#0b0b0f;--card:#16161f;--line:#2a2a38;--txt:#f5f5f7;--mut:#9a9aad;--red:#e50914}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:var(--bg);
color:var(--txt);min-height:100vh}}
header{{display:flex;align-items:center;gap:10px;padding:14px 5%;border-bottom:1px solid var(--line)}}
.logo{{display:flex;align-items:center;gap:10px;font-weight:900;color:var(--txt);font-size:15px;letter-spacing:1px;text-decoration:none;flex:1}}
.logo-mark{{display:grid;place-items:center;width:34px;height:34px;border-radius:9px;background:linear-gradient(140deg,#ff2733,#b30710);color:#fff;font-size:19px;box-shadow:0 6px 20px rgba(229,9,20,.3)}}
.logo-title{{display:flex;flex-direction:column;font-size:15px;line-height:1.1;letter-spacing:1.4px}}
.logo-title small{{font-size:8px;letter-spacing:2px;color:var(--mut);margin-top:3px}}
.badge{{font-size:11px;color:var(--mut);border:1px solid var(--line);border-radius:20px;padding:5px 10px}}
.wrap{{max-width:1000px;margin:22px auto;padding:0 16px 40px}}
.player{{background:#000;border:1px solid var(--line);border-radius:12px;overflow:hidden}}
video{{display:block;width:100%;aspect-ratio:16/9;background:#000}}
 .choices{{margin-top:14px;padding:16px;background:linear-gradient(180deg,#1d1d27,var(--card));border:1px solid var(--line);border-radius:12px}}
.choices[hidden]{{display:none}}.choices-head{{display:flex;align-items:center;gap:10px;margin-bottom:12px}}
.choices-icon{{display:grid;place-items:center;width:34px;height:34px;border-radius:10px;background:rgba(229,9,20,.13);color:#ff5260;font-size:16px;flex:none}}
.choices h2{{font-size:13px;color:var(--txt)}}.choices-sub{{font-size:11px;color:var(--mut);margin-top:2px}}
.choices-list{{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:8px;max-height:220px;overflow-y:auto;overscroll-behavior:contain;padding:2px}}
.choices button{{min-width:0;background:#242430;color:var(--txt);border:1px solid var(--line);border-radius:10px;padding:10px 11px;cursor:pointer;text-align:left;font:inherit;transition:border-color .16s,background .16s}}
.choices button:hover{{border-color:#a74c55;background:#292731}}.choices button:focus-visible{{outline:2px solid #ff6670;outline-offset:2px}}
.choices button.active{{border-color:#e50914;background:linear-gradient(135deg,rgba(229,9,20,.18),rgba(229,9,20,.04));box-shadow:inset 3px 0 #e50914}}
.choices .choice-top{{display:flex;align-items:center;gap:6px;min-width:0}}.choices .choice-label{{font-size:12px;font-weight:800;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.choices .choice-state{{margin-left:auto;flex:none;font-size:9px;font-weight:800;text-transform:uppercase;letter-spacing:.04em;color:#ff7b84}}
.choices .choice-name{{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--mut);font-size:11px;margin-top:5px}}
.choices .choice-meta{{display:block;margin-top:5px;color:var(--mut);font-size:11px}}
@media(max-width:480px){{.choices{{padding:12px}}.choices-list{{grid-template-columns:repeat(2,minmax(0,1fr));max-height:190px}}.choices button{{padding:9px}}}}
.info{{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-top:16px}}
.name{{font-size:17px;font-weight:700;flex:1;min-width:200px;word-break:break-word}}
.btn{{display:inline-block;background:var(--red);color:#fff;font-weight:800;font-size:13px;
padding:11px 20px;border-radius:8px;text-decoration:none}}
.btn.ghost{{background:var(--card);border:1px solid var(--line);color:var(--txt)}}
.note{{margin-top:18px;color:var(--mut);font-size:12px;line-height:1.6}}
</style>
</head>
<body>
<header><a class="logo" href="/search"><span class="logo-mark">F</span><span class="logo-title">FAST FINDER<small>WEB FILE SEARCH</small></span></a><span class="badge">SIGNED STREAM</span></header>
<div class="wrap">
  <div class="player">
    <video controls playsinline preload="metadata" poster="{poster}">
      <source src="{src}" type="{mime}">
      Your browser does not support HTML5 video.
    </video>
  </div>
  <section class="choices" id="choices" data-file-id="{file_id}" hidden aria-label="Episodes and qualities"><div class="choices-head"><span class="choices-icon" aria-hidden="true">▤</span><div><h2>Episodes &amp; qualities</h2><div class="choices-sub">Choose a version to play</div></div></div><div class="choices-list"></div></section>
  <div class="info">
    <div class="name" id="name">{file_name}</div>
    <a class="btn" id="download" href="{src}" download>⬇ Download</a>
    <a class="btn ghost" href="/search">🔎 Back to Search</a>
  </div>
  <div class="note" id="note">This link is valid for a limited time. Seeking uses HTTP Range requests.</div>
</div>
<script>
const v=document.querySelector('video');
v.addEventListener('loadedmetadata',()=>{{v.play().catch(()=>{{}})}});
const box=document.querySelector('#choices'), list=box.querySelector('.choices-list');
let fid=box.dataset.fileId, request=0, items=[];
function render(){{
  list.replaceChildren(); box.hidden=items.length<2;
  items.forEach(item=>{{
    const b=document.createElement('button'); b.type='button';
    const top=document.createElement('span');top.className='choice-top';
    const label=document.createElement('span');label.className='choice-label';
    label.textContent=[item.episode,item.quality].filter(Boolean).join(' · ') || 'Video';top.appendChild(label);
    if(item.file_id===fid){{const state=document.createElement('span');state.className='choice-state';state.textContent='Selected';top.appendChild(state)}}
    b.appendChild(top);
    const name=document.createElement('span');name.className='choice-name';name.textContent=item.name;b.appendChild(name);
    const meta=[item.duration ? '⏱ '+item.duration : '', item.size && !/^0(?:\.0+)?\s*B$/i.test(item.size) ? item.size : ''].filter(Boolean);
    if(meta.length){{const detail=document.createElement('span');detail.className='choice-meta';detail.textContent=meta.join(' · ');b.appendChild(detail)}}
    b.title=item.name; b.className=item.file_id===fid?'active':'';
    b.setAttribute('aria-pressed',item.file_id===fid?'true':'false');
    b.addEventListener('click',()=>select(item)); list.appendChild(b);
  }});
}}
async function select(item){{
  const seq=++request; fid=item.file_id; render();
  v.pause(); v.removeAttribute('src'); v.querySelectorAll('source').forEach(s=>s.remove()); v.load();
  document.querySelector('#name').textContent='Preparing '+item.name+'…';
  document.querySelector('#download').removeAttribute('href');
  try{{
    const r=await fetch('/api/stream',{{method:'POST',credentials:'same-origin',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{file_id:fid}})}});
    const d=await r.json(); if(seq!==request)return;
    if(!r.ok || !d.stream)throw Error(d.error||'Stream unavailable');
    document.querySelector('#name').textContent=item.name;
    document.querySelector('#download').href=d.download;
    document.querySelector('#note').textContent='Signed link · '+d.expires_in+' seconds valid · Range/seek supported';
    v.poster=d.poster||''; v.src=d.stream; v.load();
    history.replaceState(null,'',d.watch);
  }}catch(e){{if(seq===request)document.querySelector('#note').textContent=String(e.message||e)}}
}}
if(fid)fetch('/api/player/group?file_id='+encodeURIComponent(fid),{{credentials:'same-origin'}})
  .then(r=>r.ok?r.json():null).then(d=>{{if(d&&Array.isArray(d.items)){{items=d.items;render()}}}}).catch(()=>{{}});
</script>
</body>
</html>"""

UNSUPPORTED_HTML = """<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Download File</title><meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{{background:#0b0b0f;color:#fff;font-family:system-ui,sans-serif;display:flex;
align-items:center;justify-content:center;min-height:100vh;text-align:center}}
.box{{background:#16161f;border:1px solid #2a2a38;padding:36px;border-radius:14px;max-width:440px}}
a{{display:inline-block;margin-top:18px;background:#e50914;color:#fff;padding:12px 24px;
border-radius:8px;text-decoration:none;font-weight:800}}</style></head>
<body><div class="box"><h2>📦 {file_name}</h2>
<p style="color:#9a9aad;margin-top:10px">This file cannot be played in the browser. Download it instead.</p>
<a href="{src}" download>⬇ Direct Download</a></div></body></html>"""


async def media_watch(message_id: int, query: str = "", poster: str = "", file_id: str = ""):
    info = await get_media_info(message_id)
    if not info:
        return "<h2 style='color:#fff;text-align:center;padding:60px'>❌ File Not Found</h2>"

    if not file_id:
        file_id = unpack_new_file_id(info.file_id)

    src = f"/download/{message_id}"
    if query:
        src += "?" + html.escape(query, quote=True)

    raw_name = str(info.file_name or "Fast Finder Media")
    name = html.escape(raw_name)
    # Many Telegram videos are indexed as "document" (mime is None or
    # octet-stream), so also check the extension — otherwise MKV files get no player.
    looks_video = raw_name.lower().endswith(
        (".mp4", ".mkv", ".avi", ".mov", ".webm", ".m4v", ".ts", ".wmv", ".flv", ".mpeg", ".mpg")
    )
    is_video = info.is_video or str(info.mime_type or "").startswith("video/") or looks_video
    mime = html.escape(info.mime_type or ("video/mp4" if is_video else "application/octet-stream"))

    # Only allow our own /api/thumb URL as the poster (prevents open redirect / XSS)
    safe_poster = poster if poster.startswith("/api/thumb") else ""
    safe_poster = html.escape(safe_poster, quote=True)

    if not is_video:
        return UNSUPPORTED_HTML.format(file_name=name, src=src)

    return WATCH_HTML.format(
        title=f"Watch {name}",
        file_name=name,
        src=src,
        mime=mime,
        poster=safe_poster,
        file_id=html.escape(file_id[:512], quote=True),
    )
