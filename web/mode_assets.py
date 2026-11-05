"""🖼️/📄 POSTER ↔ TEXT VIEW MODE — the **single source** (this file only).

All Poster/Text behaviour is defined here once; `/search`, `/posts`,
`/actors`, group cards and group variants all use it.
**Both modes share exactly the same markup and code**; Text mode only hides
 the thumbnail image (`vm-img`) and image-only decoration (`vm-ph`/`vm-overlay`)
 through CSS. There is no separate HTML branch or render path.
The Text-mode grid also lives here: like the GitHub reference (v5 `.res-grid`)
📱 1 / 📟 2 / 🖥️ 3 cards per row, each card compact (name + chips + actions).

┌── CHANGE IN ONE PLACE → EVERYWHERE ──────────────────────────────────┐
│ • to change a mode label/chip/option   → `VIEW_MODE_OPTIONS`          │
│ • to change Text mode layout/colours   → `MODE_CSS`                    │
│ • mode state / persistence / img src    → `MODE_JS` (`window.ViewMode`)│
│ • to change the default mode (Text)    → `DEFAULT` in `MODE_JS`       │
│ • to make a new page/card mode-aware   → add the `VM_*` classes below  │
│   to its markup (`vm-grid`, `vm-card`, `vm-img`, …); no new CSS/JS     │
│   rules need to be written anywhere else.                              │
└──────────────────────────────────────────────────────────────────────┘

📐 CLASS CONTRACT (mode-agnostic — any surface can opt in)::

    vm-grid      grid the Poster/Text mode applies to (.vgrid, .cat-grid)
    vm-card      one card                          (.vcard, .gcard, .cat-card)
    vm-master    inner wrapper, if any             (.gmaster)
    vm-poster    box holding image + details      (.vposter, .gposter, .cat-poster-wrap)
    vm-img       thumbnail `<img>`                (.vimg, .cat-poster)
    vm-ph        "NO THUMBNAIL" placeholder       (.vph, .cat-ph)
    vm-overlay   decoration that only shows on an image (.vplay, .cat-grad)
    vm-details   container of chips/badges        (.vchips, .gbottom)
    vm-chip      a single badge/chip              (.cat-badge)
    vm-size      size badge                      (.vsize)
    vm-actions   admin Edit/Delete box           (.vadmin, .gadmin, .cat-actions)
    vm-always    (with vm-actions) always visible in Text mode — apply only
                 to actions that are rendered for admins
    vm-body      section holding the name / meta  (.vbody, .gbody, .cat-meta)
    vm-title     the name                         (.vtitle, .gtitle, .cat-meta-main)

`ViewMode.imgAttrs(url)` in `MODE_JS` only chooses between `src` ⇄ `data-src`,
so Text mode never requests a thumbnail; switching back to Poster mode
restores `src` from `data-src`. Add `data-vm-select="1"` to a select and its
state, localStorage and styled dropdown label stay in sync automatically.
"""

# ── 🎛️ Dropdown options — labels/captions live here too (filter specs read them)
VIEW_MODE_OPTIONS = (("poster", "🖼️ Poster"), ("text", "📄 Text"))


# ── 🎨 CSS — the only rule-set for `mode-text` ─────────────────────────────
# ⚠️ This is appended last to SITE_CSS, so it beats page-specific base rules
#    such as `.vgrid`, `.cat-grid`, `.vposter` and `.cat-poster-wrap` on both
#    specificity and order. For a new page just add the `vm-*` classes;
#    nothing needs to change here.
MODE_CSS = r"""
/* ═══════════════ 🖼️📄 POSTER / TEXT — web/mode_assets.py ═══════════════
   Text mode: only the thumbnail and image-only decoration are hidden.
   Everything else (name, chips, size, duration, group meta, admin actions)
   stays exactly as in Poster mode, just in a compact card.
   📐 Responsive grid like the GitHub reference (v5 `.res-grid`) — 📱 1 card/row,
   📟 2, 🖥️ 3 (matching the `.vgrid` breakpoints used by Poster mode). */
.vm-grid.mode-text{display:grid;grid-template-columns:minmax(0,1fr);gap:8px;
align-items:start}
@media(min-width:620px){.vm-grid.mode-text{grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}}
@media(min-width:1024px){.vm-grid.mode-text{grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}}
.vm-grid.mode-text>.state,.vm-grid.mode-text>.vempty,
.vm-grid.mode-text>.cat-vempty{grid-column:1/-1}
.vm-grid.mode-text .vm-card{display:flex;flex-direction:column;align-items:stretch;
gap:6px;padding:10px 11px;margin:0;border-radius:8px;min-width:0;max-width:100%}
.vm-grid.mode-text > .vm-card > .vm-master{display:flex;flex-direction:column;
align-items:stretch;gap:6px;padding:0}
.vm-grid.mode-text .vm-body{order:-1;display:flex;flex-direction:column;
align-items:stretch;gap:3px;padding:0;flex:0 0 auto;width:100%;min-width:0}
.vm-grid.mode-text .vm-title{display:block;flex:1;min-width:0;white-space:nowrap;
overflow:hidden;text-overflow:ellipsis;-webkit-line-clamp:1}
/* ⚠️ In Text mode only these are hidden — things tied to the thumbnail */
.vm-grid.mode-text .vm-img,
.vm-grid.mode-text .vm-ph,
.vm-grid.mode-text .vm-overlay{display:none!important}
/* poster box → compact inline details strip (chips/size live inside it) */
.vm-grid.mode-text .vm-poster{position:static;display:flex;flex-wrap:wrap;
align-items:center;gap:5px;aspect-ratio:auto;width:100%;flex:0 0 auto;
min-width:0;padding:0;overflow:visible;background:none;animation:none;cursor:pointer}
.vm-grid.mode-text .vm-details{position:static;top:auto;left:auto;right:auto;
bottom:auto;display:flex;flex-wrap:wrap;gap:5px;padding:0;background:none;
pointer-events:none}
.vm-grid.mode-text .vm-chip{position:static;top:auto;left:auto;display:inline-flex;
align-items:center}
.vm-grid.mode-text .vm-size{position:static;right:auto;bottom:auto;
display:inline-block;pointer-events:none}
.vm-grid.mode-text .vm-actions{position:static;top:auto;left:auto;right:auto;
bottom:auto;gap:5px;padding:0;background:none;flex:0 0 auto;flex-wrap:wrap}
.vm-grid.mode-text .vm-actions button{flex:0 0 auto;min-width:0;padding:6px 9px}
/* catalog admin actions are rendered only for admins ⇒ always show them;
   `.vadmin`/`.gadmin` still open on poster click only. */
.vm-grid.mode-text .vm-actions.vm-always{opacity:1;visibility:visible;
transform:none;pointer-events:all}
/* disable the dim pseudo-overlay on images; detail chips always remain */
.vm-grid.mode-text .vm-card.admin-active .vm-poster::after,
.vm-grid.mode-text .vm-card.gactive .vm-poster::after{display:none}
.vm-grid.mode-text .vm-card.gactive .vm-details{display:flex}
@media(hover:hover){.vm-grid.mode-text .vm-card:hover{transform:translateX(3px)}}
"""


# ── ⚙️ JS — the only engine for mode state ────────────────────────────────
MODE_JS = r"""/* 🖼️📄 POSTER / TEXT — single source web/mode_assets.py (inside SITE_JS) */
window.ViewMode=(function(){
  /* ⭐ DEFAULT_VIEW_MODE — change this one line to change the default.
     Every page (/search, /posts, /actors) starts here on an empty localStorage. */
  var DEFAULT='text', RESET_FLAG='ff_mode_default_v2';
  var VALID=['poster','text'], cur=DEFAULT, cfg={}, bound=[];
  function norm(v){return VALID.indexOf(v)>=0?v:DEFAULT;}
  /* Storage keys live here too — search / posts / actors are remembered separately */
  /* One preference across search, posts, actors and every shared video grid. */
  function storageFor(kind){return 'ff_view_mode_shared';}
  /* Older browsers may have saved 'poster' ⇒ apply the new default once:
     only the old mode keys are removed; afterwards the user's choice is remembered. */
  function resetOnce(){
    /* Preserve the previous per-page choice when upgrading to shared mode. */
    try{
      if(localStorage.getItem('ff_view_mode_shared'))return;
      var old=localStorage.getItem(key());
      if(!old)old=localStorage.getItem('ff_view_mode');
      if(!old&&cfg.kind)old=localStorage.getItem('ff_cat_mode_'+cfg.kind);
      if(!old)old=localStorage.getItem('ff_cat_mode_posts')||localStorage.getItem('ff_cat_mode_actors');
      if(old)localStorage.setItem('ff_view_mode_shared',norm(old));
      localStorage.setItem(RESET_FLAG,'1');
    }catch(e){}
  }
  function key(){return cfg.storage||storageFor(cfg.kind);}
  function get(){return cur;}
  function isText(){return cur==='text';}
  /* The URL is already HTML-safe; we only choose between src ⇄ data-src.
     In Text mode no thumbnail network request is made. */
  function imgAttrs(url){
    var u=String(url==null?'':url);
    return (isText()?'data-src="'+u+'"':'src="'+u+'"')+
           ' data-thumb="'+u+'" data-retry="0"';
  }
  function apply(){
    Array.prototype.forEach.call(document.querySelectorAll('.vm-grid'),function(g){
      g.classList.toggle('mode-text',isText());
    });
  /* Sync the styled dropdown's label/value — do not dispatch change,
     otherwise the listener below would run itself again. */
    Array.prototype.forEach.call(
      document.querySelectorAll('select[data-vm-select]'),function(s){
        s.value=cur;
        if(window.ddSet)window.ddSet(s,cur,false);
      });
    if(!isText()){
      Array.prototype.forEach.call(
        document.querySelectorAll('.vm-grid img.vm-img[data-src]'),function(img){
          if(!img.getAttribute('src'))img.src=img.dataset.src;
        });
    }
  }
  function set(v){
    cur=norm(v);
    try{localStorage.setItem(key(),cur);}catch(e){}
    apply();                       /* CSS-only toggle — no re-render */
  }
  function bind(){
    Array.prototype.forEach.call(
      document.querySelectorAll('select[data-vm-select]'),function(s){
        if(bound.indexOf(s)>=0)return;bound.push(s);
        s.addEventListener('change',function(){set(s.value);});
      });
  }
  window.addEventListener('storage',function(e){
    if(e.key==='ff_view_mode_shared'){
      cur=norm(e.newValue||DEFAULT);apply();
    }
  });
  function init(o){
    cfg=o||{};
    resetOnce();                 /* first visit only — clears the old Poster preference */
    var v=null;try{v=localStorage.getItem(key());}catch(e){}
    cur=norm(v||DEFAULT);       /* no saved preference ⇒ Text mode */
    bind();apply();
  }
  return {init:init,set:set,get:get,isText:isText,apply:apply,
          imgAttrs:imgAttrs,storageFor:storageFor,options:VALID.slice(),
          defaultMode:DEFAULT};
})();
/* Small alias for older inline handlers / tests — logic stays inside ViewMode */
window.setMode=function(v){window.ViewMode.set(v);};
"""
