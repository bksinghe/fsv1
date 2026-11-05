"""🎨 Shared web assets: session/auth helper, page shell, CSS and the search UI.

A look like `v5`'s dashboard/mini-app — sidebar (Home / Database Stats /
Profile Settings / Sign Out), stats cards and profile settings — but as one
self-contained page for fsv1 (no extra template engine).

▶ `PLAYER_MODAL_HTML` + `PLAYER_JS` are a **shared player component**: besides
`/search`, the Videos tabs of `/post/<id>` and `/actor/<id>` use the same modal,
the same `/api/stream` flow and the same signed watch/download actions.
The JS exposes `window.play/closePlayer/copyLink` from an IIFE, so there are no
name collisions with a page's own `$` / `esc` / `const`.

✏️ `FILE_EDIT_HTML` + `FILE_EDIT_JS` are the admin-only **file editor** — fsv1's
version of v5's `Edit Title Metadata` (name / caption / poster / delete):
a JSON API, a CDN-free 16:9 canvas crop and card updates without a reload.

🎛️ `FILTER_CSS` + `FILTER_JS` are a **shared filter dropdown component** —
just write `<select class="filter-dd">` and the `FilterDD` engine in `SITE_JS`
upgrades it into a styled button + custom options menu (the MutationObserver
also upgrades selects added later). The native select stays hidden but keeps
`value`/`change`, so existing JS needs no changes. **The entire dropdown UI lives
in this one place** — edit one file and `/search`, `/posts`, `/actors` and the
editor modals all change. **Filter button options/specs live here too** in
`FILTER_OPTIONS` + `SEARCH_FILTERS`/`CATALOG_FILTERS` + `filter_buttons()` — no
page writes its own `<option>`, and setting `sel.value=` syncs the label automatically
(no separate `ddSet()` code on any page). On mobile both toolbars share one
`.filters` row and one `@media` rule: search bar above, two equal buttons below.

🎴 `VCARD_TEMPLATE` + `VCARD_CHIP_SPEC` + `vcard_meta()` — the **single source
for video cards**: markup, chips (size/duration/quality/res/type) and data
normalization all live here. Python `render_vcard()` and JS `vcardHTML()` fill the
same template/spec; `/search`, Post attached videos and Actor tag-results
show exactly the same cards. Changes belong here only.

🎴 `VIDEO_CARD_CSS` is a **shared video card** — the `/search` grid and the
Post/Actor Videos tabs use the same `.vcard`/`.vgrid` markup,
the same 1/2/3 responsive grid and the same compact padding under the name.
"""

import html
import json
import time

from web.group_assets import (
    GROUP_CSS, GROUP_JS, GROUP_ADMIN_HTML, GROUP_ADMIN_JS,
)
from web.mode_assets import VIEW_MODE_OPTIONS, MODE_CSS, MODE_JS
from web.reveal_assets import REVEAL_CSS, REVEAL_JS
from web.welcome_assets import (
    GUEST_BODY_CLASS, GUEST_TOPBAR, GUEST_AMBIENT,
    WELCOME_CSS, WELCOME_JS,
)

from aiohttp import web

from info import ADMINS
from utils import temp, get_size
from database.users_chats_db import web_db


# ─────────────────────────────────────────────────────────────
# 🔐 SESSION / AUTH
# ─────────────────────────────────────────────────────────────
def prune_sessions():
    """Remove expired sessions from RAM and prevent uncontrolled growth."""
    sessions = temp.USER_SESSIONS
    if len(sessions) <= 5000:
        return
    now = time.time()
    for key in [k for k, v in sessions.items() if v.get("expiry", 0) <= now]:
        sessions.pop(key, None)
    while len(sessions) > 5000:
        sessions.pop(next(iter(sessions)), None)


async def get_auth(req):
    """Returns (role, tg_id) — role 'admin' | 'user', ya (None, None)."""
    sid = req.cookies.get("user_session")
    if not sid:
        return None, None

    session = temp.USER_SESSIONS.get(sid)
    if not session:
        # Bot restart / another instance → reload the session from the DB
        try:
            session = await web_db.get_session(sid)
            if session:
                temp.USER_SESSIONS[sid] = session
                prune_sessions()
        except Exception:
            session = None

    if session and session.get("expiry", 0) > time.time():
        tg_id = session.get("tg_id")
        if tg_id:
            return ("admin" if tg_id in ADMINS else "user"), tg_id

    temp.USER_SESSIONS.pop(sid, None)
    return None, None


def is_secure_request(req):
    """Detect the real scheme behind a proxy (Koyeb/Render)."""
    return (
        req.secure
        or req.headers.get("X-Forwarded-Proto", "").split(",")[0].strip().lower() == "https"
    )


# ─────────────────────────────────────────────────────────────
VIDEO_CARD_CSS = r"""
/* ─────────────────────────────────────────────────────────────
   ▶ SHARED VIDEO CARD — /search + /post/<id> + /actor/<id> Videos tabs
    all use the same `.vcard` markup, the same `.vgrid` (📱 1 / 📟 2 / 🖥️ 3) and
    the minimum padding under the name.
   ───────────────────────────────────────────────────────────── */
.vgrid{display:grid;grid-template-columns:minmax(0,1fr);gap:12px}
@media(min-width:620px){.vgrid{grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}}
@media(min-width:1024px){.vgrid{grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}}
.vgrid>.vempty,.vgrid>.state,.vgrid>.cat-vempty{grid-column:1/-1}
.vcard{display:block;position:relative;overflow:hidden;background:var(--card);
border:1px solid var(--line);border-radius:10px;color:var(--txt);cursor:pointer;
text-decoration:none;transition:transform .22s,border-color .22s,box-shadow .28s}
.vcard:focus-visible{outline:2px solid var(--red);outline-offset:2px}
@media(hover:hover){.vcard:hover{transform:translateY(-4px);border-color:rgba(229,9,20,.65);
box-shadow:0 14px 34px rgba(0,0,0,.45)}}
/* ✨ Entrance animation lives in web/reveal_assets.py — cards opt in with `rv-enter`. */
@keyframes sh{0%{background-position:200% 0}100%{background-position:-200% 0}}
.vposter{position:relative;aspect-ratio:16/9;overflow:hidden;
background:linear-gradient(90deg,var(--bg3) 0,#2b2b3a 50%,var(--bg3) 100%);
background-size:200% 100%;animation:sh 1.5s infinite linear}
.vposter.no-thumb{animation:none;background:none}
.vimg{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;opacity:0;
transition:opacity .3s,transform .35s}
.vimg.on{opacity:1}.vimg.hidden{display:none}
.vcard:hover .vimg.on{transform:scale(1.05)}
.vph{position:absolute;inset:0;display:none;align-items:center;justify-content:center;
flex-direction:column;gap:4px;color:var(--mut);font-size:11px;font-weight:800;
letter-spacing:1px;background:linear-gradient(135deg,#1b1b28,#101018)}
.vposter.no-thumb .vph{display:flex}
.vph b{font-size:30px;color:var(--red)}
.vchips{position:absolute;top:0;left:0;right:0;z-index:2;display:flex;gap:5px;
padding:7px;flex-wrap:wrap;pointer-events:none}
.vtag{background:rgba(0,0,0,.78);backdrop-filter:blur(6px);color:#fff;border-radius:5px;
padding:3px 7px;font-size:10px;font-weight:800;border:1px solid rgba(255,255,255,.14)}
.vtag.gold{color:var(--gold);border-color:rgba(255,209,102,.4)}
.vtag.blue{color:#93c5fd;border-color:rgba(147,197,253,.35)}
.vsize{position:absolute;right:7px;bottom:7px;z-index:2;pointer-events:none;
background:rgba(0,0,0,.78);backdrop-filter:blur(6px);color:#fff;border-radius:5px;
padding:3px 7px;font-size:10px;font-weight:800;border:1px solid rgba(255,255,255,.14)}
.vplay{position:absolute;inset:0;z-index:2;display:flex;align-items:center;justify-content:center;
font-size:30px;background:linear-gradient(transparent,rgba(0,0,0,.5));
opacity:0;transition:opacity .2s;pointer-events:none}
.vcard:hover .vplay{opacity:1}
.vposter{cursor:pointer}
/* 📸 Like v5: clicking the thumbnail slides an Edit/Delete bar up inside that poster */
.vadmin{position:absolute;left:0;right:0;bottom:0;z-index:5;display:flex;gap:6px;
padding:9px 8px;background:linear-gradient(transparent,rgba(0,0,0,.9) 45%);
opacity:0;visibility:hidden;transform:translateY(10px);pointer-events:none;
transition:opacity .2s ease,transform .22s ease,visibility .2s}
.vcard.admin-active .vposter::after{content:'';position:absolute;inset:0;z-index:4;
background:rgba(0,0,0,.42);pointer-events:none}
.vcard.admin-active .vadmin{opacity:1;visibility:visible;transform:translateY(0);pointer-events:all}
.vadmin button{flex:1;padding:8px 4px;border-radius:6px;font-size:11px;font-weight:800;
font-family:inherit;cursor:pointer;color:#fff;border:1px solid rgba(255,255,255,.2);
backdrop-filter:blur(8px);transition:background .12s,transform .1s}
.vadmin .va-edit{background:rgba(42,42,48,.9)}
.vadmin .va-edit:hover{background:rgba(80,80,88,.96)}
.vadmin .va-del{background:rgba(160,8,8,.82);border-color:rgba(229,9,20,.5)}
.vadmin .va-del:hover{background:rgba(229,9,20,.95)}
.vadmin button:active{transform:scale(.94)}
/* ✅ Removed the extra space under the name — only the necessary padding remains */
.vbody{padding:8px 11px 9px}
.vtitle{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;
font-size:13px;font-weight:700;line-height:1.35;cursor:pointer;transition:color .18s}
.vcard:hover .vtitle{color:var(--red)}
.state{grid-column:1/-1;text-align:center;padding:70px 20px;color:var(--mut);
font-weight:600;line-height:1.7}
@media(prefers-reduced-motion:reduce){
.vcard,.rv-enter,.rv-enter.in,.vposter{animation:none!important;
transition:none!important;opacity:1!important;transform:none!important}
}
"""


# 🎨 SHARED CSS
# ─────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────
# 🎴 SHARED VIDEO CARD — the **single source** for markup + chips + data
#   `/search`, Post attached videos and Actor tag-results are all built here:
#     Python  → render_vcard() / vcard_chips() / vcard_size()
#     JS      → vcardHTML()    / vcardChips() / vcardSize()  (in SITE_JS below)
#   The template and chip spec are each written once — the same Python values
#   are passed to JS with json.dumps. To add/remove a chip, reorder them or
#   change colours, edit only VCARD_CHIP_SPEC and every surface changes at once.
# ─────────────────────────────────────────────────────────────
# ⚠️ The "VIDEO"/"FILE" type chip was removed — thumbnails now show only
#    quality → res → duration chips. `type` may remain in the payload
#    (used by the API/editor), but it no longer produces a chip on the card.
VCARD_CHIP_SPEC = (
    ("quality",  "vtag blue", ("unknown",)),
    ("res",      "vtag",      ()),
    ("duration", "vtag gold", ()),
)

VCARD_TEMPLATE = (
    '<div class="vcard vm-card{CARD_CLASS}" role="button" tabindex="0"{EXTRA_ATTRS} '
    'data-fid="{FID}" data-name="{NAME}" aria-label="Play {NAME}">'
    '<div class="vposter vm-poster"{POSTER_ID}>'
    '<img class="vimg vm-img" {IMG_ATTRS} alt="" loading="lazy" '
    'onload="this.classList.add(\'on\')" onerror="{IMG_ERROR}">'
    '<div class="vph vm-ph vm-overlay"><b>▶</b><span>NO THUMBNAIL</span></div>'
    '<div class="vchips vm-details">{CHIPS}</div>{SIZE}'
    '<span class="vplay vm-overlay">▶</span>'
    '<div class="vadmin vm-actions"><button class="va-edit" data-fid="{RAW_FID}">✏️ Edit</button>'
    '<button class="va-del" data-fid="{RAW_FID}">🗑️ Delete</button></div>'
    '</div><div class="vbody vm-body"><div class="vtitle vm-title">{NAME}</div></div></div>'
)

_VIDEO_EXT = (".mp4", ".mkv", ".avi", ".mov", ".webm", ".m4v", ".ts",
              ".wmv", ".flv", ".mpeg", ".mpg")


def vcard_is_video(doc) -> bool:
    """Whether a Library doc is a video — every card payload gets `type` here."""
    doc = doc or {}
    name = str(doc.get("file_name") or "").lower()
    mime = str(doc.get("mime_type") or "").lower()
    return (doc.get("file_type") == "video" or mime.startswith("video/")
            or name.endswith(_VIDEO_EXT))


def _vcard_duration(value) -> str:
    try:
        sec = int(value or 0)
    except (TypeError, ValueError):
        return ""
    if sec <= 0:
        return ""
    h, rem = divmod(sec, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def vcard_meta(doc) -> dict:
    """🎴 The only card-data normalizer — `/api/search`, `/api/catalog/{kind}/media`
    and attached-video enrichment all take size/duration/res/quality/type from here,
    so the chip text is identical in all three places."""
    doc = doc or {}
    fid = str(doc.get("_id") or "")
    try:
        w = int(doc.get("width") or 0)
    except (TypeError, ValueError):
        w = 0
    try:
        h = int(doc.get("height") or 0)
    except (TypeError, ValueError):
        h = 0
    return {
        "file_id": fid,
        "name": str(doc.get("file_name") or "Untitled"),
        "size": get_size(doc.get("file_size") or 0),
        "quality": str(doc.get("quality") or ""),
        "type": "VIDEO" if vcard_is_video(doc) else "FILE",
        "duration": _vcard_duration(doc.get("duration")),
        "res": f"{w}×{h}" if w and h else "",
    }


def vcard_chips(data) -> str:
    """Every `.vchips` — order/class/skip rules live only in VCARD_CHIP_SPEC."""
    data = data or {}
    out = []
    for field, cls, skip in VCARD_CHIP_SPEC:
        val = str(data.get(field) or "").strip()
        if not val or val.lower() in skip:
            continue
        out.append(f'<span class="{cls}">{html.escape(val)}</span>')
    return "".join(out)


def vcard_size(data) -> str:
    val = str((data or {}).get("size") or "").strip()
    return f'<span class="vsize vm-size">{html.escape(val)}</span>' if val else ""


def render_vcard(**kw) -> str:
    """Python-side card render — from the same VCARD_TEMPLATE that JS uses."""
    tokens = {k: "" for k in (
        "CARD_CLASS", "EXTRA_ATTRS", "POSTER_ID", "IMG_ATTRS", "IMG_ERROR",
        "CHIPS", "SIZE", "FID", "NAME", "RAW_FID")}
    tokens.update({k: str(v) for k, v in kw.items()})
    return VCARD_TEMPLATE.format(**tokens)


_VCARD_JS_TPL = r"""/* 🎴 SHARED VIDEO CARD — template + chip spec from web_assets.py (Python → JS) */
(function(){
  var TPL=__VCARD_TEMPLATE__, SPEC=__VCARD_CHIP_SPEC__;
  function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){
    return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}
  function chips(f){
    f=f||{};
    return SPEC.map(function(c){
      var v=String(f[c[0]]==null?'':f[c[0]]).trim();
      if(!v||c[2].indexOf(v.toLowerCase())>=0)return '';
      return '<span class="'+c[1]+'">'+esc(v)+'</span>';
    }).join('');
  }
  function vsize(f){
    var s=String((f||{}).size==null?'':f.size).trim();
    return s?'<span class="vsize vm-size">'+esc(s)+'</span>':'';
  }
  function html(t){
    t=t||{};
    return TPL.replace(/\{([A-Z_]+)\}/g,function(m,k){
      return Object.prototype.hasOwnProperty.call(t,k)?String(t[k]):'';
    });
  }
  window.vcardChips=chips;window.vcardSize=vsize;window.vcardHTML=html;
})();
"""
VCARD_JS = (_VCARD_JS_TPL
            .replace("__VCARD_TEMPLATE__", json.dumps(VCARD_TEMPLATE))
            .replace("__VCARD_CHIP_SPEC__",
                     json.dumps([list(x) for x in VCARD_CHIP_SPEC])))

FILE_EDIT_HTML = r"""<style>
/* ✏️ Shared FILE EDITOR — fsv1's take on v5 "Edit Title Metadata" (no CDN) */
.femodal{position:fixed;inset:0;z-index:300;background:rgba(0,0,0,.88);display:none;
align-items:center;justify-content:center;padding:14px}
.femodal.open{display:flex}
.fecard{background:var(--bg2);border:1px solid var(--line);border-radius:14px;width:100%;
max-width:640px;max-height:92vh;display:flex;flex-direction:column;overflow:hidden;
box-shadow:0 24px 70px rgba(0,0,0,.7)}
.fehead{display:flex;align-items:center;gap:10px;padding:13px 16px;border-bottom:1px solid var(--line)}
.fetitle{flex:1;font-weight:900;font-size:15px}
.fex{background:transparent;border:0;color:var(--mut);font-size:22px;cursor:pointer;line-height:1}
.febody{padding:14px 16px;overflow-y:auto}
.feposter{position:relative;width:100%;aspect-ratio:16/9;background:#000;border:1px solid var(--line);
border-radius:9px;overflow:hidden;margin-bottom:10px}
.feposter img,.feposter canvas{width:100%;height:100%;object-fit:contain;display:block}
.feposter canvas{object-fit:cover;cursor:grab;touch-action:none;display:none}
.feposter canvas:active{cursor:grabbing}
.fethumbar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:6px}
.fezoom{display:flex;align-items:center;gap:6px;font-size:11px;font-weight:800;color:var(--mut);flex:1;min-width:130px}
.fezoom input{flex:1;min-width:70px;accent-color:var(--red)}
.febtn{border:1px solid var(--line);border-radius:8px;padding:9px 13px;font-size:12px;font-weight:800;
cursor:pointer;font-family:inherit;background:var(--bg3);color:var(--txt);transition:border-color .15s,transform .1s}
.febtn:hover{border-color:var(--red)}.febtn:active{transform:scale(.96)}
.febtn:disabled{opacity:.5;cursor:not-allowed}
.febtn.save{background:var(--red);border-color:var(--red);color:#fff}
.febtn.danger{background:rgba(160,8,8,.35);border-color:rgba(229,9,20,.5)}
.festate,.festatus{font-size:11px;color:var(--mut);font-weight:700;margin:6px 0 12px;min-height:15px}
.fegrid{display:grid;grid-template-columns:1fr 1fr;gap:10px}
@media(max-width:560px){.fegrid{grid-template-columns:1fr}}
.fegrid label{display:flex;flex-direction:column;gap:5px;font-size:11px;font-weight:800;color:var(--mut)}
.fegrid label.wide{grid-column:1/-1}
.fegrid input,.fegrid select,.fegrid textarea{width:100%;box-sizing:border-box;background:var(--bg3);
border:1px solid var(--line);border-radius:8px;padding:9px 11px;color:var(--txt);font:700 13px inherit;
font-family:inherit;outline:none}
.fegrid textarea{resize:vertical;min-height:58px}
.fegrid input:focus,.fegrid select:focus,.fegrid textarea:focus{border-color:var(--red)}
.fefoot{display:flex;gap:8px;padding:12px 16px;border-top:1px solid var(--line);flex-wrap:wrap}
.fefoot .save{margin-left:auto}
.fetoast{position:fixed;left:50%;bottom:22px;z-index:420;transform:translate(-50%,160%);
opacity:0;background:var(--bg2);border:1px solid var(--line);border-left:4px solid #2ecc71;
color:var(--txt);border-radius:10px;padding:11px 17px;font-size:12px;font-weight:800;
box-shadow:0 12px 34px rgba(0,0,0,.55);transition:transform .3s,opacity .3s;max-width:92vw}
.fetoast.show{transform:translate(-50%,0);opacity:1}
.fetoast.err{border-left-color:var(--red)}
</style>
<div class="femodal" id="feModal" onclick="if(event.target===this)closeFileEdit()">
  <div class="fecard">
    <div class="fehead"><div class="fetitle">✏️ Edit File Metadata</div>
      <button class="fex" onclick="closeFileEdit()" aria-label="Close">✕</button></div>
    <div class="febody">
      <div class="feposter"><img id="fePoster" src="" alt="Current poster">
        <canvas id="feCanvas" width="1280" height="720"></canvas></div>
      <div class="fethumbar">
        <label class="febtn">📂 New poster<input type="file" id="feFile" accept="image/*" hidden></label>
        <label class="fezoom">Zoom <input type="range" id="feZoom" min="1" max="3" step="0.05" value="1"></label>
        <button class="febtn" id="feReset">🔄 Original</button>
      </div>
      <div class="festate" id="feThumbState">🖼️ Telegram original</div>
      <div class="fegrid">
        <label class="wide">📝 File name<input id="feName" type="text" maxlength="300"></label>
        <label class="wide">🏷️ Caption / Search tags<textarea id="feCaption" maxlength="1000"
          placeholder="e.g. Ajay Devgan, 1080p, Comedy…"></textarea></label>
        <label>🎞️ Quality<select class="filter-dd" id="feQuality" data-fdd-full="1" data-fdd-cap="Quality">
          <option value="">Unknown</option><option value="144p">144p</option>
          <option value="240p">240p</option><option value="360p">360p</option>
          <option value="480p">480p</option><option value="720p">720p</option>
          <option value="1080p">1080p</option><option value="1440p">1440p</option>
          <option value="2160p">2160p</option><option value="4K">4K</option>
          <option value="8K">8K</option><option value="HD">HD</option>
          <option value="HDR">HDR</option></select></label>
        <label>⏱️ Duration<input id="feDuration" type="text" placeholder="1:36:22"></label>
        <label>📐 Resolution<input id="feRes" type="text" placeholder="1920×1080"></label>
      </div>
      <div class="festatus" id="feStatus">…</div>
    </div>
    <div class="fefoot">
      <button class="febtn danger" id="feDelete">🗑️ Delete file</button>
      <button class="febtn" onclick="closeFileEdit()">Cancel</button>
      <button class="febtn save" id="feSave">💾 Save Changes</button>
    </div>
  </div>
</div>
<div class="fetoast" id="feToast"></div>"""

FILE_EDIT_JS = r"""<script>
(function(){
  const q = s => document.querySelector(s);
  const esc = s => String(s==null?'':s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let current=null, crop=null, busy=false, toastTimer=null;
  function toast(msg, err){
    const t=q('#feToast'); if(!t) return;
    t.textContent=msg; t.classList.toggle('err',!!err); t.classList.add('show');
    clearTimeout(toastTimer); toastTimer=setTimeout(()=>t.classList.remove('show'),3200);
  }
  function isOpen(){ const m=q('#feModal'); return !!m && m.classList.contains('open'); }
  function cards(fid){
    return Array.prototype.filter.call(document.querySelectorAll('.vcard[data-fid]'),c=>{
      try{ return decodeURIComponent(c.dataset.fid)===fid; }catch(e){ return c.dataset.fid===fid; }
    });
  }
  function syncCard(f){
    const list=cards(f.file_id);
    list.forEach(c=>{
      if(c.dataset.label!=='1'){
        const t=c.querySelector('.vtitle'); if(t) t.textContent=f.name;
        c.dataset.name=f.name; c.setAttribute('aria-label','Play '+f.name);
      }
      // chips + size also come from the same shared spec — the card must not look different after an edit
      const chips=c.querySelector('.vchips');
      if(chips) chips.innerHTML=vcardChips(f);
      const sz=c.querySelector('.vsize');
      if(sz) sz.outerHTML=vcardSize(f);
      const im=c.querySelector('.vimg');
      if(im && f.thumb){ im.src=f.thumb; im.classList.remove('hidden'); }
    });
  }
  function setPoster(f){
    const im=q('#fePoster'); if(!im) return;
    im.src=f.thumb+'&t='+Date.now(); im.style.display='block';
    const cv=q('#feCanvas'); if(cv) cv.style.display='none';
    const st=q('#feThumbState');
    if(st) st.textContent=f.custom_thumb?'📸 Custom poster (web upload)':'🖼️ Telegram original';
  }
  function drawCrop(){
    const cv=q('#feCanvas'); if(!cv) return;
    const ctx=cv.getContext && cv.getContext('2d'); if(!ctx) return;
    ctx.fillStyle='#000'; ctx.fillRect(0,0,1280,720);
    if(!crop||!crop.img) return;
    const im=crop.img, scale=Math.max(1280/im.width,720/im.height)*crop.zoom;
    const w=im.width*scale, h=im.height*scale;
    let x=(1280-w)/2+crop.x, y=(720-h)/2+crop.y;
    x=Math.min(0,Math.max(1280-w,x)); y=Math.min(0,Math.max(720-h,y));
    crop.x=x-(1280-w)/2; crop.y=y-(720-h)/2;
    ctx.drawImage(im,x,y,w,h);
  }
  function loadLocal(input){
    const file=input.files&&input.files[0]; if(!file) return;
    const rd=new FileReader();
    rd.onload=e=>{
      const im=new Image();
      im.onload=()=>{
        crop={img:im,zoom:1,x:0,y:0,dragging:false};
        q('#feZoom').value=1;
        const po=q('#fePoster'); if(po) po.style.display='none';
        const cv=q('#feCanvas'); if(cv) cv.style.display='block';
        drawCrop();
        q('#feStatus').textContent='✂️ 16:9 crop — drag to position, use the slider to zoom';
      };
      im.src=e.target.result;
    };
    rd.readAsDataURL(file);
  }
  function open(fid){
    if(!fid||!q('#feModal')) return;
    current=String(fid); crop=null; busy=false;
    q('#feModal').classList.add('open');
    q('#feStatus').textContent='Loading…';
    q('#feFile').value=''; q('#feZoom').value=1;
    fetch('/api/file/meta?id='+encodeURIComponent(current),{credentials:'same-origin'})
      .then(r=>r.json()).then(d=>{
        if(!d.ok){ q('#feStatus').textContent=d.error||'Load failed'; return; }
        const f=d.file;
        q('#feName').value=f.name; q('#feCaption').value=f.caption;
        q('#feDuration').value=f.duration; q('#feRes').value=f.res;
        const sel=q('#feQuality');
        if(f.quality && !Array.prototype.some.call(sel.options,o=>o.value===f.quality))
          sel.add(new Option(f.quality,f.quality));
        sel.value=f.quality||'';
        q('#feStatus').textContent='✏️ ID: '+esc(f.file_id)+' · '+esc(f.size)+' · '+esc(f.quality||'—');
        setPoster(f);
      }).catch(e=>{ q('#feStatus').textContent='Load error: '+String(e.message||e); });
  }
  function close(){
    const m=q('#feModal'); if(m) m.classList.remove('open');
    current=null; crop=null; busy=false;
  }
  function setBusy(v){
    busy=v;
    const b=q('#feSave'); if(b){ b.disabled=v; b.textContent=v?'Processing…':'💾 Save Changes'; }
  }
  async function save(){
    if(!current||busy) return;
    const payload={file_id:current,name:q('#feName').value,caption:q('#feCaption').value,
      quality:q('#feQuality').value,duration:q('#feDuration').value,
      res:q('#feRes').value};
    setBusy(true);
    try{
      const r=await fetch('/api/file/edit',{method:'POST',credentials:'same-origin',
        headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
      const d=await r.json();
      if(!d.ok){ toast(d.error||'Save failed',true); return; }
      let f=d.file;
      if(crop && crop.img){
        const cv=q('#feCanvas');
        const blob=await new Promise(res=>{
          if(!cv.toBlob){ res(null); return; }
          cv.toBlob(res,'image/jpeg',0.9);
        });
        if(blob){
          const fd=new FormData(); fd.append('file_id',current);
          fd.append('image',blob,'poster.jpg');
          const ur=await fetch('/api/file/thumb',{method:'POST',credentials:'same-origin',body:fd});
          const ud=await ur.json();
          if(ud.ok) f=ud.file; else toast('Poster: '+(ud.error||'upload failed'),true);
        }
      }
      syncCard(f); setPoster(f); toast('✨ File updated — no reload'); close();
    }catch(e){ toast('Network error: '+String(e.message||e),true); }
    finally{ setBusy(false); }
  }
  async function resetThumb(){
    if(!current||busy) return;
    if(!confirm('Remove the custom poster and restore the original Telegram thumbnail?')) return;
    setBusy(true);
    try{
      const r=await fetch('/api/file/thumb_reset',{method:'POST',credentials:'same-origin',
        headers:{'Content-Type':'application/json'},body:JSON.stringify({file_id:current})});
      const d=await r.json();
      if(!d.ok){ toast(d.error||'Reset failed',true); return; }
      syncCard(d.file); setPoster(d.file);
      toast('🔄 Original thumbnail queued for a fresh fetch');
    }catch(e){ toast('Network error: '+String(e.message||e),true); }
    finally{ setBusy(false); }
  }
  async function deleteById(fid){
    if(!fid||busy) return;
    if(!confirm('Permanently delete this file from the database?')) return;
    setBusy(true);
    try{
      const r=await fetch('/api/file/delete',{method:'POST',credentials:'same-origin',
        headers:{'Content-Type':'application/json'},body:JSON.stringify({file_id:fid})});
      const d=await r.json();
      if(!d.ok){ toast(d.error||'Delete failed',true); return; }
      cards(fid).forEach(c=>c.remove());
      toast('🗑️ File deleted');
      if(current===fid) close();
    }catch(e){ toast('Network error: '+String(e.message||e),true); }
    finally{ setBusy(false); }
  }
  function remove(){ if(current) return deleteById(current); }

  /* ── 📸 v5-style: Edit/Delete overlay inside the thumbnail ─────── */
  function closeAdmin(){
    Array.prototype.forEach.call(document.querySelectorAll('.vcard.admin-active'),
      c=>c.classList.remove('admin-active'));
  }
  function toggleAdmin(card){
    const was=card.classList.contains('admin-active');
    closeAdmin();                         /* only one card open at a time */
    if(!was) card.classList.add('admin-active');
  }
  function fidOf(node){
    let fid=node&&node.dataset?node.dataset.fid:'';
    if(!fid){
      const c=node&&node.closest?node.closest('.vcard[data-fid]'):null;
      fid=c?c.dataset.fid:'';
    }
    try{ return decodeURIComponent(fid||''); }catch(err){ return fid||''; }
  }
  window.openFileEdit=open; window.closeFileEdit=close;
  window.closeFileActions=closeAdmin; window.deleteFileById=deleteById;
  document.addEventListener('click',e=>{
    const t=e.target, near=(sel)=>t&&t.closest?t.closest(sel):null;
    const act=near('.vadmin button');
    if(act){                              /* ✏️ Edit / 🗑️ Delete */
      e.preventDefault(); e.stopPropagation();
      const fid=fidOf(act); closeAdmin();
      if(act.classList.contains('va-del')){ if(fid) deleteById(fid); }
      else if(fid) open(fid);
      return;
    }
    const poster=near('.vcard .vposter');
    if(poster){
      const card=poster.closest('.vcard[data-fid]');
      if(card){
        e.preventDefault(); e.stopPropagation();   /* do not open the player — open the overlay */
        toggleAdmin(card);
        return;
      }
    }
    closeAdmin();                         /* outside click → close every overlay */
  },true);
  document.addEventListener('keydown',e=>{
    if(e.key==='Escape'){
      if(document.querySelector('.vcard.admin-active')){ closeAdmin(); return; }
      if(isOpen()){ close(); return; }
      return;
    }
    if(!isOpen()) return;
    if((e.ctrlKey||e.metaKey)&&String(e.key).toLowerCase()==='s'){ e.preventDefault(); save(); }
  });
  q('#feSave').addEventListener('click',save);
  q('#feReset').addEventListener('click',resetThumb);
  q('#feDelete').addEventListener('click',remove);
  q('#feFile').addEventListener('change',e=>loadLocal(e.target));
  q('#feZoom').addEventListener('input',e=>{
    if(crop){ crop.zoom=Number(e.target.value); drawCrop(); }
  });
  const cv=q('#feCanvas');
  if(cv){
    cv.addEventListener('pointerdown',e=>{
      if(!crop) return;
      crop.dragging=true; crop.sx=e.clientX; crop.sy=e.clientY;
    });
    cv.addEventListener('pointermove',e=>{
      if(!crop||!crop.dragging) return;
      const r=cv.getBoundingClientRect();
      crop.x+=(e.clientX-crop.sx)*(1280/(r.width||1280));
      crop.y+=(e.clientY-crop.sy)*(720/(r.height||720));
      crop.sx=e.clientX; crop.sy=e.clientY; drawCrop();
    });
    cv.addEventListener('pointerup',()=>{ if(crop) crop.dragging=false; });
  }
})();
</script>"""


FILTER_CSS = r"""
/* ═══════════════════════════════════════════════════════════════════
   🎛️ SHARED FILTER DROPDOWN — the UI for every filter control lives only here
   Any <select class="filter-dd"> is automatically turned into this component
   (the FilterDD engine in SITE_JS). Changes belong in this CSS + the JS below.
   ═══════════════════════════════════════════════════════════════════ */
.fdd{position:relative;display:inline-flex;min-width:132px;flex:0 0 auto;vertical-align:middle}
.fdd.full{display:flex;width:100%;min-width:0}
.fdd-btn{display:flex;align-items:center;gap:8px;width:100%;min-height:42px;
box-sizing:border-box;padding:10px 12px;background:var(--bg3);border:1.5px solid var(--line);
border-radius:10px;color:var(--txt);font:800 12px 'DM Sans',sans-serif;
font-family:'DM Sans',sans-serif;cursor:pointer;text-align:left;
transition:border-color .18s,background .18s,box-shadow .18s,transform .1s}
.fdd-btn:hover{border-color:var(--red);background:var(--bg2)}
.fdd.open .fdd-btn{border-color:var(--red);background:var(--bg2);
box-shadow:0 0 0 3px rgba(229,9,20,.13)}
.fdd-btn:active{transform:scale(.98)}
.fdd-ico{font-size:15px;line-height:1;flex:0 0 auto}
.fdd-label{flex:1;min-width:0;overflow:hidden;white-space:nowrap;text-overflow:ellipsis}
.fdd-arrow{flex:0 0 auto;font-size:10px;color:var(--mut);transition:transform .2s}
.fdd.open .fdd-arrow{transform:rotate(180deg)}
.fdd-menu{position:absolute;top:calc(100% + 8px);left:0;z-index:150;
min-width:100%;max-width:min(320px,90vw);max-height:300px;overflow-y:auto;
box-sizing:border-box;padding:6px;background:var(--bg2);border:1.5px solid var(--line);
border-radius:12px;box-shadow:0 18px 48px rgba(0,0,0,.62);display:none;
animation:fddIn .16s ease-out}
.fdd.open .fdd-menu{display:block}
.fdd.up .fdd-menu{top:auto;bottom:calc(100% + 8px)}
@keyframes fddIn{from{opacity:0;transform:translateY(-6px) scale(.98)}to{opacity:1;transform:none}}
.fdd-cap{padding:6px 10px 9px;font-size:10px;font-weight:900;letter-spacing:1px;
text-transform:uppercase;color:var(--mut);border-bottom:1px solid var(--line);margin-bottom:4px}
.fdd-item{display:flex;align-items:center;gap:10px;width:100%;box-sizing:border-box;
padding:10px 11px;border:0;border-radius:8px;background:transparent;color:var(--txt);
font:700 12px 'DM Sans',sans-serif;font-family:'DM Sans',sans-serif;
cursor:pointer;text-align:left;transition:background .12s,color .12s}
.fdd-item:hover,.fdd-item:focus-visible{background:var(--bg3);outline:none}
.fdd-item[aria-selected=true]{background:rgba(229,9,20,.14);color:var(--red)}
.fdd-opt-ico{font-size:15px;width:18px;flex:0 0 18px;text-align:center}
.fdd-opt-text{flex:1;min-width:0;overflow:hidden;white-space:nowrap;text-overflow:ellipsis}
.fdd-tick{flex:0 0 auto;color:var(--red);font-weight:900;opacity:0}
.fdd-item[aria-selected=true] .fdd-tick{opacity:1}
.fdd > select.fdd-native{position:absolute!important;left:0!important;top:0!important;
width:1px!important;height:1px!important;padding:0!important;border:0!important;
opacity:0!important;pointer-events:none!important;clip:rect(0,0,0,0)!important;
overflow:hidden!important}
/* container layout lives here too — base + mobile CSS for the filter row in one block */
.filters{display:flex;gap:10px;align-items:center;flex:0 0 auto}
.filters .fdd{min-width:132px}
/* 📱 mobile: /search and /posts–/actors share **one rule** — the search bar on its own line,
   filter buttons directly below in the same `.filters` row, equally wide. */
@media(max-width:760px){
.qwrap,.cat-toolbar .cat-search{flex:1 1 100%}
.filters{flex:1 1 100%}
.filters .fdd{flex:1 1 0;min-width:0}
/* ✅ Like v5 `.search-box`: mobile keeps **one box** (card + border + padding)
   too — only the controls inside split into three lines, the chrome is not removed. */
/* ✨ New Post / New Profile: a full-width line directly below the filter buttons.
   (0,3,0) ⇒ the later CATALOG_CSS `.cat-toolbar .cat-create` rule cannot override it. */
.cat-toolbar.cat-toolbar .cat-create{flex:1 1 100%;width:100%}
/* the count sits at the bottom of the same box, very light (no separate heading) */
.cat-toolbar.cat-toolbar .cat-count{flex:1 1 100%;text-align:right;
background:none;border:0;padding:2px 0 0}
}
@media(prefers-reduced-motion:reduce){.fdd-menu{animation:none}.fdd-btn,.fdd-arrow{transition:none}}
"""

FILTER_JS = r"""
/* 🎛️ SHARED FILTER DROPDOWN ENGINE — every <select class="filter-dd"> is upgraded here.
   The native <select> stays hidden in the DOM (value + change events = old code unchanged),
   while a styled button + custom options menu are shown. Add a new select at any time —
   the MutationObserver upgrades it automatically, with no changes in another file. */
(function(){
  var ALL=[];
  function el(tag,cls,txt){var e=document.createElement(tag);if(cls)e.className=cls;
    if(txt!=null)e.textContent=txt;return e;}
  function split(t){
    var v=String(t==null?'':t).trim(), m=v.match(/^(\S+)\s+(.+)$/);
    if(m&&/[^\x00-\x7F]/.test(m[1])) return {ico:m[1],text:m[2].trim()};
    return {ico:'',text:v};
  }
  function capOf(sel){return sel.getAttribute('data-fdd-cap')||
    sel.getAttribute('aria-label')||sel.title||'Options';}
  function render(d){
    var o=d.sel.options[d.sel.selectedIndex], p=o?split(o.text):{ico:'',text:'—'};
    d.btn.querySelector('.fdd-ico').textContent=p.ico;
    d.btn.querySelector('.fdd-label').textContent=p.text||'—';
    Array.prototype.forEach.call(d.menu.querySelectorAll('.fdd-item'),function(it){
      it.setAttribute('aria-selected',
        it.getAttribute('data-value')===String(d.sel.value)?'true':'false');
    });
  }
  function buildMenu(d){
    d.menu.innerHTML='';
    d.menu.appendChild(el('div','fdd-cap',capOf(d.sel)));
    Array.prototype.forEach.call(d.sel.options,function(o){
      var p=split(o.text), it=el('button','fdd-item');
      it.type='button';it.setAttribute('role','option');
      it.setAttribute('data-value',o.value);it.setAttribute('aria-selected','false');
      it.appendChild(el('span','fdd-opt-ico',p.ico));
      it.appendChild(el('span','fdd-opt-text',p.text||o.value));
      it.appendChild(el('span','fdd-tick','✓'));
      it.addEventListener('click',function(ev){ev.stopPropagation();choose(d,o.value);});
      it.addEventListener('keydown',function(ev){
        if(ev.key==='Enter'||ev.key===' '){ev.preventDefault();choose(d,o.value);return;}
        var all=Array.prototype.slice.call(d.menu.querySelectorAll('.fdd-item')),
            i=all.indexOf(ev.currentTarget);
        if(ev.key==='ArrowDown'){ev.preventDefault();(all[i+1]||all[0]).focus();}
        else if(ev.key==='ArrowUp'){ev.preventDefault();(all[i-1]||all[all.length-1]).focus();}
        else if(ev.key==='Escape'){ev.preventDefault();close(d);d.btn.focus();}
      });
      d.menu.appendChild(it);
    });
    render(d);
  }
  function close(d){d.wrap.classList.remove('open','up');
    d.btn.setAttribute('aria-expanded','false');}
  function closeAll(){ALL.forEach(close);}
  function open(d){
    closeAll();render(d);
    d.wrap.classList.add('open');d.btn.setAttribute('aria-expanded','true');
    var r=d.wrap.getBoundingClientRect(), h=d.menu.offsetHeight||220;
    if(r.bottom+h+10>window.innerHeight&&r.top>h) d.wrap.classList.add('up');
  }
  function choose(d,v){
    d.sel.value=v;
    d.sel.dispatchEvent(new Event('change',{bubbles:true}));
    render(d);close(d);d.btn.focus();
  }
  /* Any page writing `sel.value = x` syncs the button label automatically.
     That is why no page needs its own ddSet()/refresh() call. */
  function watchValue(sel,d){
    var desc=null,pObj=Object.getPrototypeOf(sel);
    while(pObj&&!desc){
      var x=Object.getOwnPropertyDescriptor(pObj,'value');
      if(x&&x.get&&x.set){desc=x;break;}
      pObj=Object.getPrototypeOf(pObj);
    }
    if(!desc)return;
    try{
      Object.defineProperty(sel,'value',{configurable:true,enumerable:true,
        get:function(){return desc.get.call(this);},
        set:function(v){desc.set.call(this,v);if(d.menu)buildMenu(d);}});
    }catch(err){}
  }
  function build(sel){
    if(sel.getAttribute('data-fdd')) return null;
    sel.setAttribute('data-fdd','1');
    var wrap=el('div','fdd'),btn=el('button','fdd-btn'),menu=el('div','fdd-menu');
    if(sel.getAttribute('data-fdd-full'))wrap.classList.add('full');
    btn.type='button';btn.setAttribute('aria-haspopup','listbox');
    btn.setAttribute('aria-expanded','false');
    btn.appendChild(el('span','fdd-ico',''));
    btn.appendChild(el('span','fdd-label','—'));
    btn.appendChild(el('span','fdd-arrow','▾'));
    menu.setAttribute('role','listbox');
    sel.parentNode.insertBefore(wrap,sel);
    wrap.appendChild(btn);wrap.appendChild(menu);wrap.appendChild(sel);
    sel.classList.add('fdd-native');
    var d={sel:sel,wrap:wrap,btn:btn,menu:menu};
    ALL.push(d);
    watchValue(sel,d);
    btn.addEventListener('click',function(ev){ev.stopPropagation();
      if(wrap.classList.contains('open'))close(d);else open(d);});
    btn.addEventListener('keydown',function(ev){
      if(ev.key==='ArrowDown'||ev.key==='Enter'||ev.key===' '){
        ev.preventDefault();if(!wrap.classList.contains('open'))open(d);
        var f=d.menu.querySelector('.fdd-item[aria-selected=true]')||
              d.menu.querySelector('.fdd-item');if(f)f.focus();
      }else if(ev.key==='Escape'){close(d);}
    });
    buildMenu(d);
    return d;
  }
  function find(id){
    var s=typeof id==='string'?document.getElementById(id):id;
    if(!s)return null;
    for(var i=0;i<ALL.length;i++)if(ALL[i].sel===s)return ALL[i];
    return build(s);
  }
  function init(root){
    var scope=root&&root.querySelectorAll?root:document;
    Array.prototype.forEach.call(
      scope.querySelectorAll('select.filter-dd:not([data-fdd])'),build);
  }
  function set(id,value,fire){
    var d=find(id);if(!d)return;
    d.sel.value=value;buildMenu(d);
    if(fire)d.sel.dispatchEvent(new Event('change',{bubbles:true}));
  }
  function ensure(id,value,label){
    var d=find(id);if(!d)return;
    var has=Array.prototype.some.call(d.sel.options,function(o){return o.value===value;});
    if(value&&!has)d.sel.add(new Option(label||value,value));
    buildMenu(d);set(id,value||'');
  }
  function refresh(id){var d=find(id);if(d)buildMenu(d);}
  window.FilterDD={init:init,set:set,ensure:ensure,refresh:refresh,
                   closeAll:closeAll,find:find};
  window.ddSet=set;
  document.addEventListener('click',function(ev){
    if(!ev.target||!ev.target.closest||!ev.target.closest('.fdd'))closeAll();
  },true);
  document.addEventListener('keydown',function(ev){
    if(ev.key==='Escape')closeAll();
  });
  document.addEventListener('change',function(ev){
    if(ev.target&&ev.target.matches&&ev.target.matches('select.filter-dd')){
      var d=find(ev.target);if(d)render(d);
    }
  },true);
  var pending=false;
  function schedule(){if(pending)return;pending=true;
    setTimeout(function(){pending=false;init(document);},0);}
  function start(){
    init(document);
    if(window.MutationObserver&&document.body)
      new MutationObserver(schedule).observe(document.body,{childList:true,subtree:true});
  }
  if(document.readyState==='loading')
    document.addEventListener('DOMContentLoaded',start);
  else start();
})();
"""


# ─────────────────────────────────────────────────────────────
# 🎛️ FILTER BUTTONS — the only definition (options, labels, markup)
#   Options like "Poster/Text" are not written separately on both pages.
#   To add a button or change a label, edit only this place.
# ─────────────────────────────────────────────────────────────
FILTER_OPTIONS = {
    "view":  VIEW_MODE_OPTIONS,
    "group": (("all", "All"), ("group", "Group"), ("ungroup", "UnGroup")),
}

# (id, options, caption, aria/title label, onchange)
SEARCH_FILTERS = (
    {"id": "modeSel",  "options": "view",  "cap": "View mode",     "label": "Mode",   "vm": True},
    {"id": "groupSel", "options": "group", "cap": "Result filter", "label": "Filter", "onchange": "setGroup(this.value)"},
)
CATALOG_FILTERS = (
    {"id": "catCategory", "options": None,   "cap": "Category",  "label": "Category"},  # options = dynamic per kind
    {"id": "catMode",     "options": "view", "cap": "View mode", "label": "Mode", "vm": True},
)


def filter_select(sel_id, *, options, cap, label, onchange="", full=False, vm=False):
    """Markup for one filter button. `options` = a FILTER_OPTIONS key | (value,label)
    pairs | pre-built `<option>` HTML (such as the catalog's dynamic categories)."""
    if options is None:
        options = ()
    if isinstance(options, str) and options in FILTER_OPTIONS:
        options = FILTER_OPTIONS[options]
    if isinstance(options, str):
        opts = options
    else:
        opts = "".join(
            '<option value="%s">%s</option>'
            % (html.escape(str(v), quote=True), html.escape(str(l)))
            for v, l in options)
    e = lambda x: html.escape(str(x), quote=True)
    extra = (' data-fdd-full="1"' if full else "") + \
            (' data-vm-select="1"' if vm else "")
    cb = ' onchange="%s"' % e(onchange) if onchange else ""
    return (f'<select class="filter-dd" id="{e(sel_id)}" data-fdd-cap="{e(cap)}"'
            f' aria-label="{e(label)}" title="{e(label)}"{extra}{cb}>{opts}</select>')


def filter_buttons(specs, dynamic=None):
    """The whole `.filters` row — shared by `/search` and `/posts`–`/actors`.
    `dynamic` = {select_id: `<option>` HTML} (catalog categories)."""
    dynamic = dynamic or {}
    out = ["      " + filter_select(
        sp["id"], options=dynamic.get(sp["id"], sp.get("options")),
        cap=sp.get("cap", sp["id"]), label=sp.get("label", sp["id"]),
        onchange=sp.get("onchange", ""), full=sp.get("full", False),
        vm=sp.get("vm", False))
        for sp in specs]
    return '<div class="filters">\n' + "\n".join(out) + "\n    </div>"


SITE_CSS = """
*{box-sizing:border-box;margin:0;padding:0}
:root{--bg:#0b0b0f;--bg2:#14141c;--bg3:#1e1e2a;--card:#16161f;--line:#2a2a38;
--txt:#f5f5f7;--mut:#9a9aad;--red:#e50914;--red2:#b30710;--gold:#ffd166}
html.light{--bg:#f4f5f8;--bg2:#fff;--bg3:#eceef4;--card:#fff;--line:#d8dbe5;
--txt:#101018;--mut:#5c5c70}
body{font-family:'DM Sans',system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
background:var(--bg);color:var(--txt);min-height:100vh;transition:background .2s,color .2s}
a{color:inherit;text-decoration:none}
.top{position:sticky;top:0;z-index:50;display:flex;align-items:center;gap:14px;
height:62px;padding:0 4%;background:var(--bg2);border-bottom:1px solid var(--line);
box-shadow:0 4px 20px rgba(0,0,0,.35)}
.logo{font-size:19px;font-weight:900;letter-spacing:1px;color:var(--red);display:flex;
align-items:center;gap:8px;flex:1}
.nfi{background:var(--red);color:#fff;border-radius:4px;padding:2px 8px;font-size:17px}
.tbtn{background:transparent;border:1px solid var(--line);color:var(--txt);border-radius:6px;
padding:7px 13px;font-weight:700;font-size:12px;cursor:pointer;font-family:inherit}
.tbtn:hover{border-color:var(--red)}
.search-zone{padding:18px 4% 14px;background:var(--bg);border-bottom:1px solid var(--line)}
/* 🖥️ desktop: search input + both filter dropdowns on the same line */
.srow{display:flex;gap:10px;max-width:1100px;align-items:center;flex-wrap:wrap}
.qwrap{position:relative;flex:1 1 320px;min-width:0}
.sinput{display:block;width:100%;min-width:0;box-sizing:border-box;background:var(--bg2);
border:1.5px solid var(--line);border-radius:10px;padding:13px 16px;color:var(--txt);
font-size:15px;font-weight:600;font-family:inherit;outline:none;transition:border-color .18s}
.sinput:focus{border-color:var(--red)}
.spin{display:none;position:absolute;right:16px;top:50%;transform:translateY(-50%);
width:17px;height:17px;border:2px solid var(--line);border-top-color:var(--red);
border-radius:50%;animation:spin .6s linear infinite}
.srow.loading .spin{display:block}
@keyframes spin{to{transform:translateY(-50%) rotate(360deg)}}
.main{padding:18px 4% 60px;max-width:1700px;margin:0 auto}
.more{display:none;margin:28px auto 0;padding:11px 30px;border-radius:8px;
background:var(--bg3);border:1px solid var(--line);color:var(--txt);font-weight:800;
cursor:pointer;font-family:inherit}
.more.show{display:block}
/* ── player modal ── */
.modal{position:fixed;inset:0;z-index:200;background:rgba(0,0,0,.88);
display:none;align-items:center;justify-content:center;padding:16px}
.modal.open{display:flex}
.mcard{background:var(--bg2);border:1px solid var(--line);border-radius:14px;
width:100%;max-width:940px;overflow:hidden;box-shadow:0 20px 70px rgba(0,0,0,.7)}
.mhead{display:flex;align-items:center;gap:10px;padding:12px 16px;
border-bottom:1px solid var(--line)}
.mtitle{flex:1;font-weight:800;font-size:14px;overflow:hidden;
text-overflow:ellipsis;white-space:nowrap}
.xbtn{background:transparent;border:0;color:var(--mut);font-size:22px;cursor:pointer;
line-height:1}
.video-wrap{background:#000;aspect-ratio:16/9}
video{width:100%;height:100%;display:block;background:#000}
.mactions{display:flex;gap:8px;flex-wrap:wrap;padding:13px 16px}
.mactions a,.mactions button{background:var(--bg3);border:1px solid var(--line);
color:var(--txt);border-radius:7px;padding:9px 14px;font-size:12px;font-weight:800;
cursor:pointer;font-family:inherit}
.mactions a.red{background:var(--red);border-color:var(--red);color:#fff}
.mnote{padding:0 16px 15px;font-size:11px;color:var(--mut)}
/* ── auth form base (guest composition lives in web/welcome_assets.py) ── */
.auth-wrap{min-height:calc(100vh - 62px);display:flex;align-items:center;
justify-content:center;padding:24px}
.auth-card{width:100%;max-width:430px;background:var(--card);border:1px solid var(--line);
border-radius:16px;padding:34px;box-shadow:0 18px 60px rgba(0,0,0,.45)}
.auth-card h2{font-size:27px;margin-bottom:6px}
.auth-card .lead{font-size:13px;color:var(--mut);margin-bottom:24px;line-height:1.5}
.auth-card input{width:100%;background:var(--bg);border:1.5px solid var(--line);
border-radius:9px;padding:14px;color:var(--txt);font-size:14px;margin-bottom:13px;
font-family:inherit;outline:none}
.auth-card input:focus{border-color:var(--red)}
.submit{width:100%;background:var(--red);color:#fff;border:0;border-radius:9px;
padding:15px;font-weight:800;font-size:14px;cursor:pointer;font-family:inherit;margin-top:8px}
.submit:hover{background:var(--red2)}
.err,.ok{border-radius:8px;padding:11px 14px;font-size:13px;font-weight:700;margin-bottom:16px}
.err{background:rgba(229,9,20,.16);color:#ff8c92;border:1px solid rgba(229,9,20,.4)}
.ok{background:rgba(40,167,69,.15);color:#6ee7a0;border:1px solid rgba(40,167,69,.4)}
.links{display:flex;justify-content:space-between;margin-top:20px;font-size:13px;
font-weight:700;color:var(--mut);gap:10px;flex-wrap:wrap}
.links a:hover{color:var(--red)}
.hr{border:0;border-top:1px solid var(--line);margin:24px 0}
/* 📱 mobile filter row (search + both buttons) → one rule in FILTER_CSS */
@media(max-width:520px){.spin{display:none!important}
.auth-card{padding:24px}.vgrid{gap:8px}}

"""

SITE_CSS += VIDEO_CARD_CSS
SITE_CSS += FILTER_CSS
SITE_CSS += GROUP_CSS
# 🌐 Guest landing/auth design system (scoped to body.guest)
SITE_CSS += WELCOME_CSS
# ✨ One shared staggered result entrance, before the Poster/Text rules
SITE_CSS += REVEAL_CSS
# ⚠️ MODE_CSS comes last — the only rule-set for Poster/Text; everything above is base only
SITE_CSS += MODE_CSS




# ─────────────────────────────────────────────────────────────
# 🧭 APP SHELL — a sidebar like JoneySin/v5 (web/web_assets.py)
#    Home · Database Stats · Profile Settings + Sign Out in the footer.
#    The identity badge now lives only in Profile Settings — the desktop topbar/
#    sidebar does not show "#<tg_id> · ADMIN".
# ─────────────────────────────────────────────────────────────
APP_CSS = """
/* ── v5-style sidebar / app shell ── */
.ham-btn{background:transparent;border:0;cursor:pointer;color:var(--txt);display:flex;
flex-direction:column;gap:4px;padding:6px}
.ham-line{width:21px;height:2px;background:currentColor;border-radius:2px}
.topbar-right{display:flex;align-items:center;gap:8px}
.sidebar-overlay{position:fixed;inset:0;background:rgba(0,0,0,.68);z-index:150;
opacity:0;pointer-events:none;transition:opacity .2s}
.sidebar-overlay.open{opacity:1;pointer-events:all}
.sidebar{position:fixed;top:0;left:0;height:100%;width:260px;max-width:82vw;
background:var(--bg2);border-right:1px solid var(--line);z-index:160;display:flex;
flex-direction:column;transform:translateX(-100%);transition:transform .3s}
.sidebar.open{transform:translateX(0)}
.sb-header{padding:18px 18px 14px;border-bottom:1px solid var(--line);display:flex;
align-items:center;justify-content:space-between}
.sb-logo{font-size:14px;font-weight:900;color:var(--red);display:flex;align-items:center;
gap:8px;letter-spacing:.6px}
.sb-close{background:none;border:0;color:var(--mut);font-size:20px;cursor:pointer;line-height:1}
.sb-user{margin:14px 14px 0;padding:10px 12px;background:var(--bg3);border:1px solid var(--line);
border-radius:8px;display:flex;align-items:center;justify-content:space-between;gap:8px}
.sb-uid{font-size:12px;font-weight:800;color:var(--txt);white-space:nowrap;overflow:hidden;
text-overflow:ellipsis}
.sb-role{font-size:9px;font-weight:900;letter-spacing:.8px;color:#fff;background:var(--red);
border-radius:20px;padding:3px 8px;flex-shrink:0}
.sb-nav{padding:14px 10px;flex:1;overflow-y:auto}
.sb-section{font-size:10px;font-weight:900;color:var(--mut);padding:8px 12px;
letter-spacing:1.4px;text-transform:uppercase}
.sb-link{display:block;padding:12px 15px;border-radius:8px;color:var(--mut);font-size:14px;
font-weight:700;margin-bottom:4px;transition:background .15s,color .15s}
.sb-link:hover{background:var(--bg3);color:var(--txt)}
.sb-link.active{background:var(--red);color:#fff}
.sb-footer{padding:14px 10px;border-top:1px solid var(--line)}
.sb-logout{display:block;padding:12px;border-radius:8px;text-align:center;color:var(--txt);
font-weight:800;font-size:13px;border:1px solid var(--line);background:var(--bg3)}
.sb-logout:hover{border-color:var(--red);color:var(--red)}
/* ── Database Stats: compact, restrained motion, responsive ── */
@keyframes ffFade{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:translateY(0)}}
.anim-card{animation:ffFade .22s ease both}
.stat-hero{background:var(--card);border:1px solid var(--line);border-radius:12px;
padding:18px 20px;margin-bottom:14px;position:relative;overflow:hidden}
.stat-hero::before{content:'';position:absolute;top:0;left:0;right:0;height:2px;background:var(--red)}
.stat-hero-label{font-size:10px;font-weight:800;color:var(--mut);text-transform:uppercase;
letter-spacing:1px;margin-bottom:7px}
.stat-hero-num{font-size:40px;font-weight:850;letter-spacing:-1.5px;line-height:1;color:var(--red)}
.stat-hero-sub{font-size:11px;color:var(--mut);margin-top:7px;line-height:1.5}
.stat-title{font-size:21px;font-weight:850;margin-bottom:4px}
.stat-lead{font-size:12px;color:var(--mut);margin-bottom:15px;line-height:1.5}
.stat-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-bottom:16px}
.st-card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px;
position:relative;overflow:hidden;transition:border-color .15s}
.st-card:hover{border-color:rgba(229,9,20,.45)}
.st-bar{position:absolute;top:0;left:0;right:0;height:2px}
.st-label{font-size:9px;font-weight:850;color:var(--mut);text-transform:uppercase;
letter-spacing:.55px;margin:4px 0 9px}
.st-val{font-size:27px;font-weight:850;letter-spacing:-.8px;line-height:1;margin-bottom:7px}
.st-sub{font-size:11px;color:var(--mut);line-height:1.45}
.st-link{display:inline-block;margin-top:12px;font-size:12px;font-weight:800;color:var(--red)}
@media(max-width:950px){.stat-grid{grid-template-columns:repeat(3,minmax(0,1fr))}}
@media(max-width:680px){.stat-grid{grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}.st-card{padding:12px}}
/* ── Profile Settings (v5-style) ── */
.scard{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:28px}
.scard-label{font-size:11px;font-weight:900;color:var(--mut);text-transform:uppercase;
letter-spacing:.9px;margin-bottom:9px}
.prof-status{background:var(--bg3);padding:18px;border-radius:10px;margin-bottom:22px}
.prof-badge{display:inline-flex;align-items:center;gap:8px;background:rgba(229,9,20,.14);
border:1px solid rgba(229,9,20,.38);color:var(--red);font-size:12px;font-weight:900;
padding:6px 12px;border-radius:20px;margin-bottom:14px}
.prof-tab-bar{display:flex;gap:4px;background:var(--bg3);border:1px solid var(--line);
border-radius:9px;padding:4px;margin-bottom:20px}
.prof-tab{flex:1;padding:9px 0;border-radius:6px;border:0;cursor:pointer;font-size:13px;
font-weight:800;font-family:inherit;background:transparent;color:var(--mut)}
.prof-tab.active{background:var(--bg2);color:var(--txt);box-shadow:0 2px 8px rgba(0,0,0,.2)}
.prof-panel{display:none}.prof-panel.active{display:block}
.prof-field{margin-bottom:18px}
.prof-input{width:100%;background:var(--bg3);border:1.5px solid var(--line);border-radius:8px;
padding:11px 14px;font-size:14px;color:var(--txt);font-family:inherit;outline:none;
box-sizing:border-box;transition:border-color .15s}
.prof-input:focus{border-color:var(--red)}.prof-input:disabled{opacity:.6;cursor:default}
.prof-input.pass-input{padding-right:46px}.pass-wrap{position:relative}
.pass-toggle{position:absolute;right:12px;top:50%;transform:translateY(-50%);background:none;
border:0;cursor:pointer;color:var(--mut);padding:0;display:flex;align-items:center}
.str-row{display:flex;gap:4px;margin-top:8px}
.str-bar{flex:1;height:3px;border-radius:2px;background:var(--bg3)}
.info-row{display:flex;align-items:center;gap:12px;background:var(--bg3);
border:1px solid var(--line);border-radius:8px;padding:12px 14px}
.info-row-lbl{font-size:11px;color:var(--mut);margin-bottom:2px}
.info-row-val{font-size:13px;font-weight:800;color:var(--txt)}
.prof-divider{border:0;border-top:1px solid var(--line);margin:18px 0}
.prof-save-row{display:flex;justify-content:flex-end;margin-top:22px}
.prof-save{background:var(--red);color:#fff;border:0;border-radius:8px;padding:12px 24px;
font-weight:800;font-size:13px;cursor:pointer;font-family:inherit}
.prof-save:hover{background:var(--red2)}
@media(max-width:520px){.stat-grid{grid-template-columns:1fr}.stat-hero-num{font-size:38px}
.scard{padding:20px}}
"""

# Theme + sidebar — one shared script on every logged-in page (like v5's shared head)
SITE_JS = """
(function(){if(localStorage.getItem('ff_theme')==='light')document.documentElement.classList.add('light')})();
function toggleTheme(){var l=document.documentElement.classList.toggle('light');localStorage.setItem('ff_theme',l?'light':'dark')}
function openSidebar(){var s=document.getElementById('sidebar'),o=document.getElementById('sbOverlay');if(s)s.classList.add('open');if(o)o.classList.add('open')}
function closeSidebar(){var s=document.getElementById('sidebar'),o=document.getElementById('sbOverlay');if(s)s.classList.remove('open');if(o)o.classList.remove('open')}
document.addEventListener('keydown',function(e){if(e.key==='Escape')closeSidebar()});
"""
SITE_JS += FILTER_JS
SITE_JS += VCARD_JS
SITE_JS += GROUP_JS
SITE_JS += WELCOME_JS
SITE_JS += REVEAL_JS
SITE_JS += MODE_JS

# Like v5's NAV_MENU — Database Stats is admin-only
NAV_MENU = (
    ("dash",    "/search",  "🏠 Home"),
    ("posts",   "/posts",   "📝 Posts"),
    ("actors",  "/actors",  "🎭 Actors"),
    ("stats",   "/stats",   "📊 Database Stats"),
    ("profile", "/profile", "⚙️ Profile Settings"),
)


def identity_badge(tg_id: int, role: str) -> str:
    """'#5292444428 · ADMIN' — in v5 this identity appears in Profile Settings."""
    return f"#{html.escape(str(tg_id))}" + (" · ADMIN" if role == "admin" else "")


def nav_shell(tg_id: int, role: str, active_tab: str = "") -> str:
    """Sidebar + topbar like v5. Sign Out appears only in the sidebar footer —
    never again in the main area/topbar."""
    links = "".join(
        f'<a href="{href}" class="sb-link {"active" if active_tab == tab else ""}">{label}</a>'
        for tab, href, label in NAV_MENU
        if role == "admin" or tab != "stats"      # Database Stats admin-only (v5)
    )
    # ℹ️ The "#<tg_id> · ADMIN" badge was removed from the desktop topbar — identity
    #    now appears only on Profile Settings (no ID in the sidebar either).
    role_txt = "ADMIN" if role == "admin" else "USER"
    return (
        '<div class="sidebar-overlay" id="sbOverlay" onclick="closeSidebar()"></div>'
        '<div class="sidebar" id="sidebar">'
          '<div class="sb-header"><div class="sb-logo"><span class="nfi">F</span> FAST FINDER</div>'
          '<button class="sb-close" onclick="closeSidebar()" aria-label="Close menu">&#10005;</button></div>'
          f'<div class="sb-user"><span class="sb-uid">Account</span>'
          f'<span class="sb-role">{role_txt}</span></div>'
          f'<nav class="sb-nav"><div class="sb-section">Menu</div>{links}</nav>'
          '<div class="sb-footer"><a href="/logout" class="sb-logout">Sign Out</a></div>'
        '</div>'
        '<div class="top">'
          '<button class="ham-btn" id="hamBtn" onclick="openSidebar()" aria-label="Open menu">'
            '<span class="ham-line"></span><span class="ham-line"></span><span class="ham-line"></span>'
          '</button>'
          '<a class="logo" href="/search"><span class="nfi">F</span> FAST FINDER</a>'
          '<div class="topbar-right">'
            '<button class="tbtn" onclick="toggleTheme()">Theme</button>'
          '</div>'
        '</div>'
    )


def app_page(title: str, body: str, tg_id: int, role: str,
             active_tab: str = "", body_class: str = ""):
    """Common shell for logged-in pages (Search / Database Stats / Profile Settings)."""
    return html_response(
        "<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{html.escape(title)}</title>"
        "<link rel='preconnect' href='https://fonts.googleapis.com'>"
        "<link href='https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;700;900&display=swap' rel='stylesheet'>"
        f"<style>{SITE_CSS}{APP_CSS}</style>"
        f"<script>{SITE_JS}</script></head>"
        f"<body class='{body_class}'>{nav_shell(tg_id, role, active_tab)}{body}</body></html>"
    )


def html_response(body: str, status: int = 200):
    return web.Response(text=body, content_type="text/html", charset="utf-8", status=status)


def page(title: str, body: str, body_class: str = "", topbar: str = ""):
    """Guest shell: CSS + one shared topbar + ambient backdrop + body."""
    ambient = GUEST_AMBIENT if GUEST_BODY_CLASS in body_class else ""
    nav = topbar or GUEST_TOPBAR
    return html_response(
        "<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<meta name='theme-color' content='#0b0b0f'>"
        f"<title>{html.escape(title)}</title>"
        "<link rel='preconnect' href='https://fonts.googleapis.com'>"
        "<link href='https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;700;900&display=swap' rel='stylesheet'>"
        f"<style>{SITE_CSS}{APP_CSS}</style>"
        f"<script>{SITE_JS}</script></head>"
        f"<body class='{body_class}'>{ambient}{nav}{body}</body></html>"
    )


# Kept as an alias: every guest page uses the same nav from welcome_assets.py.
DEFAULT_TOPBAR = GUEST_TOPBAR


def form_page(title: str, inner: str, err: str = "", msg: str = "", heading: str = ""):
    """One split-layout auth page for /login, /register, OTP and password reset."""
    e = f"<div class='err'>{html.escape(err)}</div>" if err else ""
    m = f"<div class='ok'>{html.escape(msg)}</div>" if msg else ""
    body = (
        "<div class='wc-auth'>"
          "<div class='wc-story'>"
            "<div class='wc-eyebrow'><span class='wc-pulse'></span> FAST FINDER · WEB FILE SEARCH</div>"
            "<h2>Everything you saved,<br><span>one search away.</span></h2>"
            "<p>Sign in to browse your library with real posters, quality chips and "
              "private signed streaming links — all in one place.</p>"
            "<ul class='wc-points'>"
              "<li><span>🔍</span> Instant search as you type</li>"
              "<li><span>🖼️</span> Real thumbnails, never placeholders</li>"
              "<li><span>🔐</span> Private, expiring watch links</li>"
            "</ul>"
            "<div class='wc-story-foot'>🤖 POWERED BY YOUR TELEGRAM BOT</div>"
          "</div>"
          "<div class='auth-wrap'><div class='auth-card'>"
            "<span class='wc-kicker-card'>SECURE ACCESS</span>"
            f"<h2>{html.escape(heading or title)}</h2>{e}{m}{inner}"
            "<div class='wc-card-foot'>🔒 Protected by an HttpOnly session cookie</div>"
          "</div></div>"
        "</div>"
    )
    return page(title, body, GUEST_BODY_CLASS)


# ─────────────────────────────────────────────────────────────
# ▶ SHARED PLAYER MODAL — /search + /post/<id> + /actor/<id> all use the same
# modal and the same `/api/stream` flow (no duplicate JS).
# PLAYER_JS exposes `window.play/closePlayer/copyLink` from an IIFE,
# so there are no name collisions with a page's own `$` / `esc` / `const`.
# ─────────────────────────────────────────────────────────────
PLAYER_MODAL_HTML = """<div class="modal" id="modal" onclick="if(event.target===this)closePlayer()">
  <div class="mcard">
    <div class="mhead"><div class="mtitle" id="pTitle">Loading stream…</div>
      <button class="xbtn" onclick="closePlayer()">✕</button></div>
    <div class="video-wrap"><video id="player" controls playsinline></video></div>
    <div class="mactions">
      <a class="red" id="pWatch" href="#" target="_blank" rel="noopener">▶ Player page</a>
      <a id="pDl" href="#">⬇ Download</a>
      <button onclick="copyLink()">🔗 Copy stream link</button>
      <button onclick="closePlayer()">Close</button>
    </div>
    <div class="mnote" id="pNote">Signed streaming link — valid for a limited time.</div>
  </div>
</div>"""

PLAYER_JS = r"""<script>
(function(){
  const q = s => document.querySelector(s);
  let currentWatch = '';
  window.play = async function(fid, name){
    const modal=q('#modal'), v=q('#player');
    if(!modal || !v) return;
    q('#pTitle').textContent='⏳ '+name;
    q('#pNote').textContent='Preparing the streaming link…';
    modal.classList.add('open');
    v.pause(); v.removeAttribute('src');
    try{
      const r=await fetch('/api/stream',{method:'POST',credentials:'same-origin',
        headers:{'Content-Type':'application/json'},body:JSON.stringify({file_id:fid})});
      if(r.status===401){location.href='/login?err='+encodeURIComponent('Session expired. Please sign in again.');return}
      const d=await r.json();
      if(!d.stream){q('#pTitle').textContent='❌ '+(d.error||'Stream unavailable');
        q('#pNote').textContent='This file could not be streamed right now.';return}
      currentWatch=location.origin+d.watch;
      q('#pTitle').textContent='▶ '+name;
      q('#pNote').textContent='Signed link · '+(d.expires_in||0)+' seconds valid · Range/seek supported';
      q('#pWatch').href=d.watch;
      q('#pDl').href=d.download;
      v.poster=d.poster||'';
      v.src=d.stream;
      v.load();
      const pr=v.play(); if(pr && typeof pr.catch==='function') pr.catch(()=>{});
    }catch(e){q('#pTitle').textContent='❌ Stream error';
      q('#pNote').textContent=String(e.message||e)}
  };
  window.closePlayer = function(){
    const v=q('#player'); if(!v) return;
    v.pause(); v.removeAttribute('src'); v.load();
    const m=q('#modal'); if(m) m.classList.remove('open');
  };
  window.copyLink = function(){
    if(!currentWatch) return;
    const note=q('#pNote'), clip=navigator.clipboard;
    if(!clip || !clip.writeText){ if(note) note.textContent=currentWatch; return; }
    clip.writeText(currentWatch).then(()=>{
      if(note) note.textContent='🔗 Link copied: '+currentWatch;
    }).catch(()=>{ if(note) note.textContent=currentWatch; });
  };
  document.addEventListener('keydown',e=>{ if(e.key==='Escape') window.closePlayer(); });
})();
</script>"""


# ─────────────────────────────────────────────────────────────
# 🔍 SEARCH PAGE (after login)
# ─────────────────────────────────────────────────────────────
SEARCH_BODY = """<div class="search-zone">
  <div class="srow" id="srow">
    <div class="qwrap">
      <input class="sinput" id="q" type="search" placeholder="Search movies, series or file names..." autocomplete="off">
      <div class="spin"></div>
    </div>
    __FILTER_BUTTONS__
  </div>
</div>

<div class="main">
  <div class="vgrid vm-grid" id="grid"></div>
  <button class="more" id="more" onclick="load(false)">Show more ⬇</button>
</div>

__PLAYER_MODAL__
__FILE_EDIT_HTML__
__GROUP_ADMIN_HTML__

<script>
const $=s=>document.querySelector(s);
const esc=s=>String(s==null?'':s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let curQ='',offset=0,loading=false,hasMore=false,seenGroups={};
let debounce=null,searchController=null,searchSeq=0;
/* 🖼️📄 Poster/Text comes entirely from `web/mode_assets.py` (SITE_JS → window.ViewMode) —
   there is no mode logic here, just one init call. The group filter is a separate feature. */
let groupMode=localStorage.getItem('ff_group_mode')||'all';
if(!['all','group','ungroup'].includes(groupMode))groupMode='all';
ViewMode.init({storage:ViewMode.storageFor()});
$('#groupSel').value=groupMode;
function setGroup(v){groupMode=['all','group','ungroup'].includes(v)?v:'all';
  localStorage.setItem('ff_group_mode',groupMode);
  $('#groupSel').value=groupMode;doSearch()}
function doSearch(){curQ=$('#q').value.trim();load(true)}
$('#q').addEventListener('keydown',e=>{if(e.key==='Enter'){clearTimeout(debounce);doSearch()}});
$('#q').addEventListener('input',()=>{clearTimeout(debounce);debounce=setTimeout(()=>{
  const v=$('#q').value.trim();if(v.length>=2||v==='')doSearch()},420)});

/* 🎴 Card markup/chips/size come from web_assets.VCARD_TEMPLATE + VCARD_CHIP_SPEC —
   the Post/Actor Videos tabs run the exact same vcardHTML()/vcardChips()/vcardSize(). */
function imgAttrs(f){
  // only ViewMode (web/mode_assets.py) decides between src ⇄ data-src
  return ViewMode.imgAttrs(f.thumb?encodeURI(f.thumb):'');
}
function cardTokens(f,topLevel){
  const fid=encodeURIComponent(f.file_id);
  return {
    FID:fid, RAW_FID:esc(f.file_id), NAME:esc(f.name), POSTER_ID:` id="pb-${fid}"`,
    CARD_CLASS:topLevel?' rv-enter':'', IMG_ATTRS:imgAttrs(f),
    IMG_ERROR:'thumbFail(this)', CHIPS:vcardChips(f), SIZE:vcardSize(f)
  };
}
/* 🎴 One entry point: a group card (`web/group_assets.py`) or the shared vcard.
   Every variant inside a group is also built by this cardHTML() → vcardHTML(),
   so cards look identical on /search, Post and Actor. Only top-level results opt
   into the entrance animation; nested variants must be visible on expand. */
function cardHTML(f,topLevel){
  if(f.group)return groupHTML(f,imgAttrs(f),'thumbFail(this)',topLevel);
  return vcardHTML(cardTokens(f,topLevel));
}
window.cardHTML=cardHTML;
function card(f){return cardHTML(f,true)}
/* Shimmer placeholders while a fresh result batch is being fetched — the GitHub
   reference shows a shimmering poster box, then reveals the real cards in a wave. */
function skeletons(){
  return Array.from({length:6},()=>'<div class="vcard rv-skel vm-card">'
    +'<div class="vposter vm-poster"></div><div class="vbody vm-body">'
    +'<div class="rv-line"></div><div class="rv-line short"></div></div></div>').join('');
}
// Like v5's reloadThumb(fileId): first-time posters come from a serial warmup queue
// one at a time, so on a 404 we retry gradually with `retry=true&t=...` —
// as ids are locked into the DB, the posters appear automatically.
function thumbFail(img){
  const delays=[1500,2500,4000,6000,9000,12000,16000,20000];
  const n=Number(img.dataset.retry||0);
  if(n<delays.length&&!img.classList.contains('hidden')){
    img.dataset.retry=String(n+1);
    setTimeout(()=>{
      if(!img.isConnected||img.classList.contains('on'))return;
      const base=img.dataset.thumb||img.getAttribute('src')||'';
      if(!base)return;
      img.src=base+(base.includes('?')?'&':'?')+'retry=true&t='+Date.now();
    },delays[n]);
    return;
  }
  img.classList.add('hidden');
  const p=img.closest('.vposter,.gposter');if(p)p.classList.add('no-thumb');
}

async function load(reset){
  // A new search supersedes the old request immediately; stale responses must
  // never overwrite newer results. Pagination remains single-flight.
  if(reset){
    if(searchController)searchController.abort();
    searchController=new AbortController();searchSeq++;loading=false;
    offset=0;hasMore=false;seenGroups={};$('#grid').innerHTML=skeletons();
  }else if(loading||!hasMore)return;
  const seq=searchSeq,controller=searchController||new AbortController();
  const requestedOffset=offset,query=curQ,mode=groupMode;
  loading=true;$('#srow').classList.add('loading');
  try{
    const r=await fetch(`/api/search?q=${encodeURIComponent(query)}&offset=${requestedOffset}&group=${mode}`,{
      credentials:'same-origin',signal:controller.signal
    });
    if(seq!==searchSeq)return;
    if(r.status===401){location.href='/login?err='+encodeURIComponent('Session expired. Please sign in again.');return}
    if(!r.ok)throw new Error(`HTTP ${r.status}`);
    const d=await r.json();if(seq!==searchSeq)return;
    const list=(d.results||[]).filter(f=>{
      if(!f.group)return true;
      const k=String(f.key||f.gid||'');
      if(seenGroups[k])return false;
      seenGroups[k]=1;return true;
    });
    const html=list.map(card).join('');
    if(reset)$('#grid').innerHTML=html;
    else $('#grid').insertAdjacentHTML('beforeend',html);
    RevealCards.reveal($('#grid'));
    hasMore=!!d.next_offset;offset=hasMore?Number(d.next_offset):0;
    $('#more').classList.toggle('show',hasMore);
    if(!$('#grid').children.length)
      $('#grid').innerHTML=`<div class="state">🔍 No files found.<br>Try another name or keyword.</div>`;
  }catch(e){
    if(e.name==='AbortError'||seq!==searchSeq)return;
    $('#grid').innerHTML=`<div class="state">⚠️ Search could not be loaded.<br>${esc(e.message||e)}</div>`;
  }finally{
    if(seq===searchSeq){loading=false;$('#srow').classList.remove('loading')}
  }
}
$('#grid').addEventListener('click',e=>{
  const el=e.target.closest('.vcard[data-fid]');if(!el)return;
  play(decodeURIComponent(el.dataset.fid),el.dataset.name);
});
document.addEventListener('keydown',e=>{
  if(e.key!=='Enter'&&e.key!==' ')return;
  const a=document.activeElement;
  const el=a&&a.closest?a.closest('.vcard[data-fid]'):null;
  if(!el)return;
  e.preventDefault();play(decodeURIComponent(el.dataset.fid),el.dataset.name);
});

ViewMode.apply();
load(true);
</script>
__PLAYER_JS__
__FILE_EDIT_JS__
__GROUP_ADMIN_JS__"""


def search_page(tg_id: int, role: str):
    """The app shell + search body with a v5-style sidebar.

    * Sign Out only in the sidebar footer (not the topbar).
    * Mode/Filter dropdowns share the search line on desktop,
      and sit on one line directly below it on mobile.
    * The "Recently Added / Database Stats" meta line was removed —
      the count lives only on the `/stats` (Database Stats) page.
    """
    admin = role == "admin"
    body = (SEARCH_BODY
            .replace("__FILTER_BUTTONS__", filter_buttons(SEARCH_FILTERS))
            .replace("__PLAYER_MODAL__", PLAYER_MODAL_HTML)
            .replace("__PLAYER_JS__", PLAYER_JS)
            .replace("__FILE_EDIT_HTML__", FILE_EDIT_HTML if admin else "")
            .replace("__FILE_EDIT_JS__", FILE_EDIT_JS if admin else "")
            .replace("__GROUP_ADMIN_HTML__", GROUP_ADMIN_HTML if admin else "")
            .replace("__GROUP_ADMIN_JS__", GROUP_ADMIN_JS if admin else ""))
    # GROUP_JS (head) receives the admin flag in the first body script —
    # so group cards created by load(true) get their admin overlay.
    if admin:
        body = '<script>window.IS_GROUP_ADMIN=true;</script>' + body
    return app_page(
        "FAST FINDER — Search Files", body,
        tg_id=tg_id, role=role, active_tab="dash",
    )
