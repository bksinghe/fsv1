"""🗂️ PERMANENT GROUP UI — group card, master thumbnail, admin modal, Group Mode.

Like `web/web_assets.py`, this is the **single source** for CSS, `GROUP_CARD_TEMPLATE`,
`GROUP_JS` (the renderer, included in `SITE_JS` on every page) and the admin-only
`GROUP_ADMIN_HTML` / `GROUP_ADMIN_JS` (only for admins on `/search`).

Standing constraints stay in force:
  * `.vcard`/`.vgrid`/`vcardHTML()` is the shared single-source video card — every
    variant inside a group is exactly that card (via `window.cardHTML`).
  * The shared `FILTER_CSS`/`FILTER_JS` dropdown owns the Group Scan action;
    Group Mode keeps its separate FAB for selecting cards.
  * The Edit/Delete overlay inside the thumbnail (`.vadmin`) stays the same on file cards;
    a group card has its own `.gadmin` overlay inside that same poster.
  * No primary/cloud/archive/section pill and no new player tab.
"""

import json

GROUP_CSS = r"""
/* ═══════════════════════════════════════════════════════════════════
   🗂️ SHARED GROUP CARD — master thumbnail + quality chips + variants
   ═══════════════════════════════════════════════════════════════════ */
.gcard{display:block;position:relative;overflow:hidden;background:var(--card);
border:1px solid var(--line);border-radius:10px;color:var(--txt);cursor:pointer;
transition:transform .22s,border-color .22s,box-shadow .28s}
.gcard:focus-visible{outline:2px solid var(--red);outline-offset:2px}
@media(hover:hover){.gcard:not(.open):hover{transform:translateY(-4px);
border-color:rgba(229,9,20,.65);box-shadow:0 14px 34px rgba(0,0,0,.45)}}
.gcard.open{grid-column:1/-1;box-shadow:0 8px 28px rgba(0,0,0,.45);cursor:default}
.gposter{position:relative;aspect-ratio:16/9;overflow:hidden;
background:linear-gradient(90deg,var(--bg3) 0,#2b2b3a 50%,var(--bg3) 100%);
background-size:200% 100%;animation:sh 1.5s infinite linear}
.gposter.no-thumb{animation:none;background:none}
.gposter.no-thumb .vph{display:flex}
.gcard:hover .gposter .vimg.on{transform:scale(1.05)}
/* 🗂️ Like the GitHub reference (v5 `.grp-card.open .grp-master{display:none}`):
   `.gcard.open` used to span the full grid width, so its 16:9 master thumbnail looked
   huge on desktop. On expand the thumbnail is hidden and only a compact header remains —
   name + #N GROUP / QUALITIES|EPISODES / duration / kind / quality-episode chips
   + Edit/Delete. The chips stay in the DOM ⇒ Text mode keeps every detail,
   and collapsing restores the same master poster. */
.gcard.open .gmaster{display:flex;flex-direction:column;align-items:stretch}
.gcard.open .gbody{order:-1;padding:8px 11px 0}
.gcard.open .gbody .gopenbtn{align-self:flex-start}
.gcard.open .gposter{position:static;display:flex;flex-wrap:wrap;align-items:center;
gap:6px;aspect-ratio:auto;height:auto;min-height:0;width:100%;padding:8px 11px;
overflow:visible;background:none;animation:none}
.gcard.open .gposter .vm-img,
.gcard.open .gposter .vm-ph{display:none!important}
.gcard.open .gposter .vm-details{position:static;top:auto;left:auto;right:auto;
bottom:auto;display:flex;flex-wrap:wrap;gap:5px;padding:0;background:none;
pointer-events:none}
.gcard.open .gposter .vm-actions{position:static;top:auto;left:auto;right:auto;
bottom:auto;gap:5px;padding:0;background:none;flex:0 0 auto;opacity:1;
visibility:visible;transform:none;pointer-events:all}
.gcard.open .gposter::after{display:none}
.gbottom{position:absolute;left:0;right:0;bottom:0;z-index:3;display:flex;
flex-wrap:wrap;gap:5px;padding:24px 8px 8px;
background:linear-gradient(transparent,rgba(0,0,0,.88));pointer-events:none}
.gqchip{background:#082f49;color:#7dd3fc;border:1px solid #0ea5e9;border-radius:5px;
font-size:10px;font-weight:800;padding:2px 8px;line-height:1.5}
.gqchip i{font-style:normal;color:#e0f2fe;margin-left:2px}
.gqchip.more{background:#3f3f46;color:#e4e4e7;border-color:#71717a}
/* 🎞️ qualities of one file  ⇄  📺 episodes of a series */
.vtag.gdur{background:rgba(20,83,45,.85);color:#bbf7d0;border-color:rgba(187,247,208,.4)}
.gkind{background:rgba(0,0,0,.78);backdrop-filter:blur(6px);border-radius:5px;
padding:3px 7px;font-size:10px;font-weight:800;border:1px solid rgba(255,255,255,.14)}
.gkind.quality{color:#fde68a;border-color:rgba(253,230,138,.45)}
.gkind.series{color:#c4b5fd;border-color:rgba(196,181,253,.5)}
.gqchip.ep{background:#3b0764;color:#e9d5ff;border-color:#a855f7}
.gmkind{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.gmkind button{border:1.5px solid var(--line);background:var(--bg3);color:var(--txt);
border-radius:9px;padding:10px 8px;font-size:12px;font-weight:800;cursor:pointer;
font-family:inherit;line-height:1.45;text-align:center}
.gmkind button small{display:block;font-size:10px;font-weight:600;color:var(--mut);margin-top:3px}
.gmkind button.on{border-color:var(--red);background:rgba(229,9,20,.13);color:var(--txt)}
.gmkind button:hover{border-color:var(--red)}
.gmep{width:96px;flex:0 0 auto;background:var(--bg);border:1px solid var(--line);
color:var(--txt);border-radius:6px;padding:4px 7px;font-size:11px;font-weight:800;
font-family:inherit;outline:none;text-align:center}
.gmep:focus{border-color:var(--red)}
.gmcount{font-size:11px;font-weight:800;color:#c4b5fd;margin-top:6px}
.gbody{padding:11px 13px 13px;display:flex;align-items:flex-start;gap:8px}
.gtitle{flex:1;min-width:0;color:var(--txt);font-size:13px;font-weight:700;
line-height:1.45;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;
cursor:pointer;transition:color .15s}
.gcard.open .gtitle{-webkit-line-clamp:unset;color:var(--red)}
.gtitle:hover{color:var(--red)}
.gvariants{display:grid;grid-template-columns:1fr;gap:12px;max-height:0;overflow:hidden;
padding:0 10px;opacity:0;transform:translateY(-4px);border-top:1px solid transparent;
transition:max-height .24s ease,opacity .16s ease,transform .2s ease,padding .2s ease,border-color .2s ease}
.gvariants-inner{min-height:0;display:grid;grid-template-columns:1fr;gap:12px}
.gcard.open .gvariants{max-height:5000px;padding:10px;opacity:1;transform:translateY(0);border-top-color:var(--line)}
@media(min-width:620px){.gcard.open .gvariants-inner{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(min-width:1024px){.gcard.open .gvariants-inner{grid-template-columns:repeat(3,minmax(0,1fr))}}
.gvariants .vcard:hover{transform:none}
/* Admin controls: a light, distinct toolbar instead of a black poster overlay. */
.gadmin{position:absolute;left:8px;right:8px;bottom:8px;z-index:6;display:flex;gap:6px;
flex-wrap:wrap;padding:8px;border:1px solid rgba(255,255,255,.18);border-radius:12px;
background:rgba(38,39,51,.94);box-shadow:0 8px 24px rgba(0,0,0,.32);
opacity:0;visibility:hidden;transform:translateY(8px);
transition:opacity .18s,transform .18s,visibility .18s;pointer-events:none}
.gcard.gactive .gadmin{opacity:1;visibility:visible;transform:translateY(0);pointer-events:all}
.gcard.gactive:not(.open) .gbottom{display:none}
.gadmin button{flex:1 1 42%;min-width:0;padding:9px 10px;border-radius:8px;
font-size:11px;font-weight:800;line-height:1.3;color:#f5f6ff;border:1px solid rgba(255,255,255,.15);
background:#45495c;cursor:pointer;font-family:inherit;transition:background .15s,border-color .15s,transform .15s}
.gadmin button:hover{background:#5b6078;border-color:rgba(255,255,255,.35)}
.gadmin button:focus-visible{outline:2px solid #a5b4fc;outline-offset:2px}
.gadmin .ga-edit{background:#394e80;border-color:#5774b2}
.gadmin .ga-edit:hover{background:#48639f}
.gadmin .ga-merge{background:#51466f;border-color:#76669b}
.gadmin .ga-merge:hover{background:#695a8d}
.gadmin .ga-del{background:#693940;border-color:#a65b63;color:#fff1f2}
.gadmin .ga-del:hover{background:#98434c;border-color:#d2707b}
.gadmin button:active{transform:scale(.97)}
/* Expanded groups have no poster: never paint an overlay over the whole card. */
.gcard.open.gactive .gposter::after{display:none}
.gcard.open .gposter .gadmin{flex:1 1 100%;width:100%;margin-top:4px;
box-shadow:none;border:0;border-radius:0}
.gcard.open .gadmin button{flex:0 1 auto;min-width:0}
@media(max-width:520px){.gcard.open .gadmin button{flex:1 1 calc(50% - 6px)}}
/* Light theme: legible toolbar and chips on both opened and text-mode cards. */
html.light .gcard.open{box-shadow:0 8px 26px rgba(31,41,55,.12)}
html.light .gadmin{background:rgba(255,255,255,.96);border-color:#d8dce6;
box-shadow:0 8px 24px rgba(31,41,55,.2)}
html.light .gadmin button{background:#f1f3f8;color:#273144;border-color:#d5dbe6}
html.light .gadmin button:hover{background:#e2e7f1;border-color:#aab6cb}
html.light .gadmin .ga-edit{background:#e7efff;color:#244b87;border-color:#b8ccef}
html.light .gadmin .ga-edit:hover{background:#d4e3ff}
html.light .gadmin .ga-merge{background:#f0eafa;color:#62428b;border-color:#d7c8eb}
html.light .gadmin .ga-merge:hover{background:#e4d9f5}
html.light .gadmin .ga-del{background:#fff0f1;color:#a82838;border-color:#f0c4c9}
html.light .gadmin .ga-del:hover{background:#ffdee1}
html.light .gcard.open .gposter .gadmin{background:none;box-shadow:none}
html.light .gcard.open .gposter .vtag{background:#f0f2f7;color:#334155;border-color:#d5dbe6;backdrop-filter:none}
html.light .gcard.open .gposter .vtag.blue{background:#e8f0ff;color:#24589c;border-color:#c1d4f4}
html.light .gcard.open .gposter .vtag.gold{background:#fff4d8;color:#805400;border-color:#edd9a4}
html.light .gcard.open .gposter .vtag.gdur{background:#e6f6ec;color:#17663a;border-color:#bee2ca}
html.light .gcard.open .gposter .gkind{background:#f2edfb;color:#61448e;border-color:#d8cbea;backdrop-filter:none}
html.light .gcard.open .gposter .gqchip{background:#e8f5ff;color:#075985;border-color:#9bd1ef}
html.light .gcard.open .gposter .gqchip.ep{background:#f3e8ff;color:#6b21a8;border-color:#d5b9ee}
html.light .gcard.open .gposter .gqchip.more{background:#f1f3f6;color:#475569;border-color:#d7dce3}
html.light .gcard.open .gposter .gqchip i{color:inherit}
/* Shared destination preview in file and group editors. */
.gpreview{display:flex;align-items:center;gap:11px;padding:10px;margin-top:9px;
background:var(--bg3);border:1px solid var(--line);border-radius:10px;min-width:0}
.gpreview[hidden]{display:none}.gpreview-poster{position:relative;width:108px;aspect-ratio:16/9;flex:none;
overflow:hidden;border-radius:7px;background:var(--bg);border:1px solid var(--line)}
.gpreview-placeholder{position:absolute;inset:0;display:grid;place-items:center;padding:4px;
text-align:center;color:var(--mut);font-size:10px;line-height:1.2}
.gpreview-img{position:absolute;inset:0;display:block;width:100%;height:100%;object-fit:cover}
.gpreview-img[hidden],.gpreview-placeholder[hidden]{display:none}
.gpreview-info{min-width:0;display:flex;flex-direction:column;gap:3px}.gpreview-caption{font-size:10px;text-transform:uppercase;letter-spacing:.04em;color:var(--mut);font-weight:800}
.gpreview-name{font-size:13px;color:var(--txt);font-weight:800;overflow-wrap:anywhere}.gpreview-meta{font-size:11px;color:var(--mut)}
.gpreview-message{font-size:12px;color:var(--mut);line-height:1.4}.gpreview.error .gpreview-message{color:var(--red)}
.fegrid .gpreview{grid-column:1/-1;margin-top:0}
/* ☑️ Group Mode: select files → permanent group */
.gfab{position:fixed;right:16px;bottom:18px;z-index:140;background:var(--red);color:#fff;
border:0;border-radius:999px;padding:11px 16px;font-size:12px;font-weight:800;
cursor:pointer;box-shadow:0 6px 20px rgba(229,9,20,.45);font-family:inherit}
.gselbar{position:fixed;left:50%;bottom:18px;transform:translateX(-50%);z-index:150;
background:var(--bg2);border:1.5px solid var(--line);border-radius:14px;padding:9px 12px;
display:flex;align-items:center;gap:8px;box-shadow:0 8px 30px rgba(0,0,0,.55);max-width:96vw}
.gselbar span{font-size:12px;font-weight:700;color:var(--txt);white-space:nowrap}
.gselbar button{border:0;border-radius:8px;padding:8px 12px;font-size:12px;font-weight:800;
cursor:pointer;color:#fff;background:var(--red);font-family:inherit}
.gselbar button.alt{background:var(--bg3);color:var(--txt)}
.gselbar button:disabled{opacity:.5}
.gsel-mode .vcard{cursor:pointer}
.gsel-mode .vcard::after{content:'';position:absolute;top:8px;right:8px;width:22px;height:22px;
border-radius:50%;border:2px solid #fff;background:rgba(0,0,0,.55);z-index:7;display:flex;
align-items:center;justify-content:center;color:#fff;font-size:13px;font-weight:900}
.gsel-mode .vcard.gsel::after{content:'✓';background:#22c55e;border-color:#22c55e}
.vcard.gsel{outline:2px solid #22c55e;outline-offset:-2px}
/* 🛠️ Group modal */
.gmodal{position:fixed;inset:0;z-index:300;background:rgba(0,0,0,.88);display:none;
align-items:center;justify-content:center;padding:14px}
.gmodal.open{display:flex}
.gmcard{background:var(--bg2);border:1px solid var(--line);border-radius:14px;width:100%;
max-width:560px;max-height:92vh;overflow-y:auto;padding:18px;box-sizing:border-box}
.gmhead{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:14px}
.gmhead h3{margin:0;font-size:16px;font-weight:900;color:var(--txt)}
.gmclose{background:none;border:0;color:var(--mut);font-size:22px;cursor:pointer;line-height:1}
.gmlabel{font-size:11px;font-weight:800;color:var(--mut);letter-spacing:.5px;margin:14px 0 6px}
.gminput{width:100%;background:var(--bg3);border:1.5px solid var(--line);color:var(--txt);
padding:10px 12px;border-radius:8px;font-size:13px;font-family:inherit;outline:none;box-sizing:border-box}
.gminput:focus{border-color:var(--red)}
.gmresults{max-height:150px;overflow-y:auto;border:1px solid var(--line);border-radius:8px;margin-top:6px}
.gmres{display:flex;align-items:center;gap:8px;padding:9px 11px;font-size:12px;color:var(--txt);
cursor:pointer;border-bottom:1px solid var(--line)}
.gmres:last-child{border-bottom:0}
.gmres:hover,.gmres.on{background:var(--bg3);color:var(--red)}
.gmres b{color:#38bdf8;font-size:11px;min-width:40px}
.gmchosen{margin-top:8px;font-size:12px;font-weight:800;color:#22c55e}
.gmthumbs{display:grid;grid-template-columns:repeat(auto-fill,minmax(104px,1fr));gap:8px}
.gmth{position:relative;border:2px solid var(--line);border-radius:8px;overflow:hidden;
cursor:pointer;background:var(--bg3);aspect-ratio:16/9}
.gmth.on{border-color:#22c55e}
.gmth img{width:100%;height:100%;object-fit:cover;display:block}
.gmth em{position:absolute;left:0;right:0;bottom:0;font-style:normal;font-size:10px;
font-weight:800;color:#7dd3fc;background:rgba(0,0,0,.78);padding:2px 5px;text-align:center}
.gmauto{display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:800;color:var(--mut)}
.gmmem{display:flex;align-items:center;gap:8px;padding:7px 0;border-bottom:1px solid var(--line);
font-size:12px;color:var(--txt)}
.gmmem span{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.gmmem button{border:0;background:none;color:var(--mut);font-size:14px;cursor:pointer}
.gmmem button:hover{color:var(--red)}
.gmeprow{display:flex;align-items:center;gap:8px;padding:7px 0;
border-bottom:1px solid var(--line);font-size:12px;color:var(--txt)}
.gmeprow span{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.gmrow{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-top:12px}
.gmbtn{border:0;border-radius:8px;padding:10px 14px;font-size:12px;font-weight:800;cursor:pointer;
color:#fff;background:var(--red);font-family:inherit}
.gmbtn.alt{background:var(--bg3);color:var(--txt);border:1px solid var(--line)}
.gmbtn.danger{background:#a00808}
.gmbtn:disabled{opacity:.5}
.gmnote{font-size:11px;color:var(--mut);line-height:1.5;margin-top:10px}
/* Group editor: structured, responsive sections without changing other modals. */
.gmcard.is-edit{--gm-surface:var(--bg2);--gm-section:rgba(255,255,255,.025);
--gm-section-border:rgba(255,255,255,.08);--gm-input:rgba(8,9,15,.48);
--gm-label:#c6c8d4;--gm-muted-action:#ff9fa5;--gm-shadow:rgba(0,0,0,.55);
padding:0;max-width:620px;border-color:var(--line);
background:var(--gm-surface);box-shadow:0 24px 70px var(--gm-shadow)}
html.light .gmcard.is-edit{--gm-surface:#fff;--gm-section:#f7f8fb;
--gm-section-border:#e3e6ee;--gm-input:#fff;--gm-label:#50596a;
--gm-muted-action:#b42332;--gm-shadow:rgba(32,39,57,.2)}
.gmcard.is-edit .gmhead{position:sticky;top:0;z-index:4;margin:0;padding:18px 20px;
background:var(--gm-surface);border-bottom:1px solid var(--line)}
.gmcard.is-edit .gmclose{display:grid;place-items:center;width:34px;height:34px;
border-radius:9px;background:var(--bg3);border:1px solid var(--line);font-size:18px}
.gmcard.is-edit .gmclose:hover{color:var(--txt);border-color:#73798a}
.gmedit{padding:16px 20px 0}.gmedit-section{background:var(--gm-section);
border:1px solid var(--gm-section-border);border-radius:12px;padding:14px;margin-bottom:12px}
.gmedit .gmlabel{display:block;margin:0 0 9px;font-size:11px;letter-spacing:.06em;color:var(--gm-label)}
.gmedit .gminput{background:var(--gm-input);border-radius:9px;padding:11px 12px}
.gmedit .gminput:focus,.gmedit .gmep:focus{outline:2px solid rgba(229,9,20,.3);outline-offset:1px}
.gmedit #gmEpisodes{margin-top:16px}.gmedit .gmkind{gap:10px}.gmedit .gmkind button{padding:12px 8px;border-radius:10px;background:var(--bg3)}
.gmedit .gmkind button.on{background:rgba(229,9,20,.15);box-shadow:inset 0 0 0 1px rgba(229,9,20,.25)}
.gmedit .gmkind button:focus-visible,.gmedit button:focus-visible,.gmedit summary:focus-visible{outline:2px solid #ff737c;outline-offset:2px}
.gmedit .gmresults{background:var(--gm-input)}.gmedit .gmchosen:empty{display:none}
.gmedit .gmth{border-radius:9px}.gmedit .gmth.on{border-color:#4ade80;box-shadow:0 0 0 2px rgba(74,222,128,.18)}
.gmedit .gmrow{margin-top:12px}.gmedit .gmmem,.gmedit .gmeprow{padding:9px 2px}
.gmedit .gmmem button{width:30px;height:30px;border-radius:7px;background:rgba(229,9,20,.1);color:var(--gm-muted-action)}
.gmedit .gmmem button:hover{background:rgba(229,9,20,.2);color:var(--gm-muted-action)}
.gmedit .gmlist{max-height:210px;overflow-y:auto;overscroll-behavior:contain}
.gmedit details summary{cursor:pointer;color:var(--txt);font-size:12px;font-weight:800;list-style:none}
.gmedit details summary::-webkit-details-marker{display:none}.gmedit details summary::after{content:'+';float:right;color:var(--mut);font-size:17px;line-height:1}
.gmedit details[open] summary::after{content:'−'}.gmedit details[open] summary{margin-bottom:12px}
.gmedit-actions{position:sticky;bottom:0;z-index:3;display:flex;gap:8px;flex-wrap:wrap;
margin:4px -20px 0;padding:14px 20px;background:var(--gm-surface);border-top:1px solid var(--line)}
.gmedit-actions .gmbtn{min-height:40px}.gmedit-actions .gmbtn:first-child{flex:1}
.gmedit-actions .danger{background:#693940;border:1px solid #a65b63}
html.light .gmodal{background:rgba(28,34,47,.46)}
html.light .gmedit-actions .danger{background:#fff0f1;color:#a82838;border-color:#f0c4c9}
html.light .gmedit-actions .danger:hover{background:#ffdee1}
html.light .gmedit .gmchosen{color:#15803d}
html.light .gmedit .gmcount{color:#6941a1}
@media(max-width:520px){.gmodal{padding:8px}.gmcard.is-edit{max-height:94vh}
.gmcard.is-edit .gmhead{padding:14px}.gmedit{padding:12px 12px 0}
.gmedit-section{padding:12px}.gmedit-actions{margin:4px -12px 0;padding:12px}
.gmedit-actions .gmbtn{padding:9px 10px}.gmedit-actions .gmbtn:first-child{flex:1 1 100%}}
.gmtoast{position:fixed;top:16px;left:50%;transform:translateX(-50%);z-index:400;
background:var(--bg2);border:1.5px solid var(--line);border-radius:10px;padding:10px 16px;
font-size:12px;font-weight:800;color:var(--txt);opacity:0;pointer-events:none;
transition:opacity .2s;box-shadow:0 8px 24px rgba(0,0,0,.5)}
.gmtoast.show{opacity:1}
.gmtoast.err{border-color:var(--red);color:#fca5a5}
.gmprogress{font-size:11px;color:var(--mut);margin-top:8px;line-height:1.5}
@media(max-width:520px){.gselbar{left:8px;right:8px;transform:none;justify-content:center;flex-wrap:wrap}
.gfab{right:10px;bottom:76px}}
"""

# Group card markup — from the JS `GROUP_CARD_TEMPLATE`, just like VCARD_TEMPLATE.
GROUP_CARD_TEMPLATE = (
    '<div class="gcard vm-card{CARD_CLASS}" role="button" tabindex="0" '
    'data-gkey="{GKEY}" data-gid="{GID}" aria-label="{NAME} — {COUNT} files">'
    '<div class="gmaster vm-master">'
    '<div class="gposter vm-poster" onclick="gPoster(this,event)">'
    '<img class="vimg vm-img" {IMG_ATTRS} alt="" loading="lazy" '
    'onload="this.classList.add(\'on\')" onerror="{IMG_ERROR}">'
    '<div class="vph vm-ph vm-overlay"><b>▶</b><span>NO THUMBNAIL</span></div>'
    '<div class="vchips vm-details">{TOPCHIPS}</div>'
    '<div class="gbottom vm-details">{QCHIPS}</div>{ADMIN}'
    '</div>'
    '<div class="gbody vm-body"><div class="gtitle vm-title" onclick="event.stopPropagation();gToggle(this)">{NAME}</div></div>'
    '</div>'
    '<div class="gvariants"><div class="gvariants-inner">{VARIANTS}</div></div></div>'
)

_GROUP_JS_TPL = r"""/* 🗂️ SHARED GROUP CARD — template from web/group_assets.py (Python → JS) */
(function(){
  var TPL=__GROUP_CARD_TEMPLATE__, GD={};
  var esc=window.escapeHTML;
  /* For inline onclick="...'VALUE'...": escape HTML entities + JS quotes/backslashes */
  function js1(s){return String(s==null?'':s)
    .replace(/\\/g,'\\\\').replace(/'/g,"\\'")
    .replace(/&/g,'&amp;').replace(/"/g,'&quot;')
    .replace(/</g,'&lt;').replace(/>/g,'&gt;');}
  function fill(t){return TPL.replace(/\{([A-Z_]+)\}/g,function(m,k){
    return Object.prototype.hasOwnProperty.call(t,k)?String(t[k]):'';});}
  /* html(g, imgAttrs, imgError, topLevel) — only top-level result cards opt into
     the shared `rv-enter` entrance; variants inside an open group stay visible. */
  function html(g,imgAttrs,imgError,topLevel){
    if(!g||!g.group)return '';
    GD[String(g.key)]=g;
    var isEp=g.kind==='episodes';
    var n=isEp?(g.episodes||g.count||0):(g.qualities||g.count||0);
    var list=g.chips||[], MAX=6;
    var chips=list.slice(0,MAX).map(function(c){
      return '<span class="gqchip'+(isEp?' ep':'')+'">'+esc(c.label)+
        (c.count>1?' <i>x'+c.count+'</i>':'')+'</span>';
    }).join('');
    if(list.length>MAX)chips+='<span class="gqchip more">+'+esc(list.length-MAX)+'</span>';
    /* 🎞️ Qualities of one file → showing a shared DURATION is correct.
       📺 For a series/episode-marked group every episode has its own duration, so
       the group shows no duration at all (even if the payload has a stale value).
       SIZE is never shown on a group — members have different sizes;
       on expand each variant gets size/duration from its own shared `.vcard`. */
    var showDur=!isEp&&g.duration;
    var top='<span class="vtag blue">'+(g.manual?'#'+esc(g.num)+' GROUP':'GROUP')+'</span>'+
            '<span class="vtag gold">'+esc(n)+(isEp?' EPISODES':' QUALITIES')+'</span>'+
            (showDur?'<span class="vtag gdur">⏱ '+esc(g.duration)+'</span>':'')+
            '<span class="gkind '+(isEp?'series':'quality')+'">'+
              (isEp?'📺 SERIES':'🎞️ SINGLE TITLE')+'</span>';
    /* ⚠️ No "VIDEO"/"FILE" type chip — like the shared `.vcard`, group
       thumbnails only show quality / res / duration / group-meta chips. */
    var adm='';
    if(window.IS_GROUP_ADMIN){
      var k=js1(g.key), gd=js1(g.gid||'');
      adm='<div class="gadmin vm-actions">'+
        '<button class="ga-edit" onclick="event.stopPropagation();gEdit(\''+k+'\')">'+
          (g.manual?'✏️ Edit Group #'+esc(g.num):'💾 Save as Group')+'</button>'+
        '<button onclick="event.stopPropagation();gSelectGroup(\''+k+'\')">☑️ Select files</button>'+
        (g.manual?'<button class="ga-merge" onclick="event.stopPropagation();gMerge(\''+k+'\')">🔀 Merge</button>'+
                  '<button class="ga-del" onclick="event.stopPropagation();gUngroup(\''+gd+'\')">🗑️ Ungroup</button>':'')+
      '</div>';
    }
    var variants=(g.variants||[]).map(function(v){
      return window.cardHTML?window.cardHTML(v,false,true):'';
    }).join('');
    return fill({
      CARD_CLASS:topLevel?' rv-enter':'', GKEY:esc(g.key), GID:esc(g.gid||''),
      NAME:esc(g.name), COUNT:esc(g.count||0),
      IMG_ATTRS:imgAttrs||'', IMG_ERROR:imgError||'thumbFail(this)',
      TOPCHIPS:top, QCHIPS:chips,
      ADMIN:adm, VARIANTS:variants
    });
  }
  // One exact-ID preview implementation for all transfer/merge surfaces.
  window.GroupPreview=function(input,box,onChange){
    var seq=0,timer=null,resolved=null;
    function message(text,error){box.replaceChildren();box.hidden=false;box.classList.toggle('error',!!error);
      var el=document.createElement('span');el.className='gpreview-message';el.textContent=text;box.appendChild(el);}
    function update(){
      var id=String(input.value||'').trim().replace(/^#/, '').trim(), request=++seq;
      clearTimeout(timer);resolved=null;if(onChange)onChange(null);
      box.classList.remove('error');
      if(!id){box.hidden=true;box.replaceChildren();return;}
      message('Checking group…',false);
      timer=setTimeout(function(){
        fetch('/api/group/preview?id='+encodeURIComponent(id),{credentials:'same-origin'})
          .then(function(r){return r.json().then(function(d){if(!r.ok||!d.ok)throw new Error(d.error||'Group not found');return d.group;});})
          .then(function(g){if(request!==seq)return;resolved=g;box.replaceChildren();box.classList.remove('error');box.hidden=false;
            var poster=document.createElement('div');poster.className='gpreview-poster';
            var placeholder=document.createElement('span');placeholder.className='gpreview-placeholder';
            placeholder.textContent=g.thumb?'Loading thumbnail…':'Thumbnail unavailable';poster.appendChild(placeholder);
            var img=document.createElement('img');img.className='gpreview-img';img.alt='Group thumbnail';img.hidden=true;
            var delays=[1500,2500,4000,6000,9000,12000,16000,20000],attempt=0;
            img.onload=function(){if(request!==seq)return;img.hidden=false;placeholder.hidden=true;};
            img.onerror=function(){
              if(request!==seq)return;
              img.hidden=true;
              if(attempt>=delays.length){placeholder.textContent='Thumbnail unavailable';return;}
              var delay=delays[attempt++];
              setTimeout(function(){
                if(request!==seq||!img.isConnected)return;
                img.src=g.thumb+(g.thumb.indexOf('?')>=0?'&':'?')+'retry=true&t='+Date.now();
              },delay);
            };
            poster.appendChild(img);if(g.thumb)img.src=g.thumb;
            var info=document.createElement('div');info.className='gpreview-info';
            var caption=document.createElement('span');caption.className='gpreview-caption';caption.textContent='Destination group';
            var name=document.createElement('strong');name.className='gpreview-name';name.textContent=g.name;
            var meta=document.createElement('span');meta.className='gpreview-meta';meta.textContent='#'+g.num+' · '+g.count+' files';
            info.appendChild(caption);info.appendChild(name);info.appendChild(meta);box.appendChild(poster);box.appendChild(info);
            if(onChange)onChange(g);
          }).catch(function(e){if(request!==seq)return;message(e.message||'Could not check group',true);});
      },250);
    }
    input.addEventListener('input',update);
    return {update:update,get:function(){return resolved;},dispose:function(){++seq;clearTimeout(timer);input.removeEventListener('input',update);}};
  };
  window.groupHTML=html;
  window.gJs=js1;
  window.groupGet=function(k){return GD[String(k)];};
  window.gToggle=function(node){
    var c=node&&node.closest?node.closest('.gcard'):null;if(!c)return;
    c.classList.toggle('open');
  };
  window.gPoster=function(el,e){
    if(e)e.stopPropagation();
    var c=el.closest('.gcard');if(!c)return;
    if(!window.IS_GROUP_ADMIN){c.classList.toggle('open');return;}
    var was=c.classList.contains('gactive');
    Array.prototype.forEach.call(document.querySelectorAll('.gcard.gactive'),
      function(x){x.classList.remove('gactive');});
    if(!was)c.classList.add('gactive');
  };
  document.addEventListener('click',function(e){
    if(e.target&&e.target.closest&&e.target.closest('.gadmin'))return;
    Array.prototype.forEach.call(document.querySelectorAll('.gcard.gactive'),
      function(x){x.classList.remove('gactive');});
  });
  document.addEventListener('keydown',function(e){
    if(e.key==='Escape')Array.prototype.forEach.call(
      document.querySelectorAll('.gcard.gactive'),function(x){x.classList.remove('gactive');});
    if((e.key==='Enter'||e.key===' ')&&document.activeElement){
      var c=document.activeElement.closest&&document.activeElement.closest('.gcard');
      if(c&&document.activeElement===c){e.preventDefault();c.classList.toggle('open');}
    }
  });
})();
"""
GROUP_JS = _GROUP_JS_TPL.replace("__GROUP_CARD_TEMPLATE__",
                                 json.dumps(GROUP_CARD_TEMPLATE))


GROUP_ADMIN_HTML = r"""<div class="gmtoast" id="gmToast"></div>
<div class="gmodal" id="gmModal">
  <div class="gmcard">
    <div class="gmhead"><h3 id="gmTitle">🗂️ Permanent Group</h3>
      <button class="gmclose" onclick="gClose()" aria-label="Close">✕</button></div>
    <div id="gmBody"></div>
  </div>
</div>
<button class="gfab" id="gFab" onclick="gSelectMode()">☑️ Group Mode</button>
"""


GROUP_ADMIN_JS = r"""<script>
/* 🛠️ ADMIN GROUP ACTIONS — permanent groups, merge, scan, master thumbnail */
(function(){
  var SEL={}, selMode=false, mode='save', current=null, targetGid='',
      thumbFid='', currentKind='qualities', scanTimer=null, targetPreview=null;
  function q(s){return document.querySelector(s);}
  var esc=window.escapeHTML;
  var jse=window.gJs||function(s){return String(s==null?'':s).replace(/'/g,"\\'");};
  var LIST=[];
  function toast(msg,err){window.showSimpleToast(q('#gmToast'),msg,err);}
  function post(url,body){
    return fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify(body||{}),credentials:'same-origin'}).then(function(r){
        return r.json().then(function(d){if(!r.ok||d.ok===false)
          throw new Error(d.error||('HTTP '+r.status));return d;});});
  }
  function refresh(){if(window.load)window.load(true);}
  function open(title,body){if(targetPreview)targetPreview.dispose();targetPreview=null;
    q('#gmTitle').textContent=title;q('#gmBody').innerHTML=body;
    q('#gmModal .gmcard').classList.toggle('is-edit',!!q('#gmBody .gmedit'));
    q('#gmModal').classList.add('open');}
  window.gClose=function(){if(targetPreview)targetPreview.dispose();targetPreview=null;var m=q('#gmModal');if(m)m.classList.remove('open');
    current=null;targetGid='';thumbFid='';};
  function itemsFrom(g){
    return (g.variants||[]).map(function(v){return {id:v.file_id,name:v.name};});
  }
  function thumbnailFromCard(card){
    var img=card&&card.querySelector?card.querySelector('.vm-img'):null;
    if(!img)return '';
    return String(img.getAttribute('data-thumb')||img.getAttribute('data-src')||
      img.getAttribute('src')||'');
  }
  function qualityFromCard(card){
    var chip=card&&card.querySelector?card.querySelector('.vtag.blue'):null;
    return chip?String(chip.textContent||'').trim():'';
  }
  var EPISODE_MARKERS=[
    /\bS\d{1,2}\s*[._ -]?\s*E\d{1,3}\b/i,
    /\b\d{1,2}\s*x\s*\d{2,3}\b/i,
    /\b(?:Ep|Episode|Part|Pt|Chapter|Ch)\s*[._ -]?\s*\d{1,3}\b/i,
    /\bE(?:pisode)?\s*[._ -]?\s*\d{1,3}\b/i,
    /\b\d{1,3}\s*(?:of|\/)\s*\d{1,3}\b/i
  ];
  function episodeMarker(name){
    var best=null,text=String(name||'');
    EPISODE_MARKERS.forEach(function(re){
      var m=re.exec(text);if(m&&(!best||m.index<best.index))best=m;
    });
    return best;
  }
  function cleanSuggestedTitle(name){
    var s=String(name||'').trim();
    s=s.replace(/\.(?:mp4|mkv|avi|mov|webm|m4v|ts|wmv|flv|mpg|mpeg)$/i,'');
    s=s.replace(/\b(?:240|360|480|540|576|720|1080|1440|2160|4320)\s*p\b|\b(?:4k|8k|uhd)\b/gi,' ');
    s=s.replace(/\b(?:hdr10plus|hdr10|hdr|sdr|10bit|8bit|hevc|x264|x265|h264|h265|avc|xvid|divx|bl[u]?ray|brrip|bdrip|bdremux|remux|web[\s._-]?dl|webrip|hdtv|dvdrip|dvd|cam|hdcam|predvd|hdrip|dvdscr|r5)\b/gi,' ');
    s=s.replace(/\[\s*\]|\(\s*\)/g,' ')
      .replace(/[._-]+/g,' ').replace(/\s+/g,' ');
    return s.replace(/^[\s|–]+|[\s|–]+$/g,'').trim().slice(0,200);
  }
  function seriesNameSuggestion(name){
    var text=String(name||''),marker=episodeMarker(text),prefix='';
    if(marker){
      prefix=text.slice(0,marker.index);
      [['[',']'],['(',')']].forEach(function(pair){
        var open=prefix.lastIndexOf(pair[0]),close=prefix.lastIndexOf(pair[1]);
        if(open>close)prefix=prefix.slice(0,open);
      });
      var title=cleanSuggestedTitle(prefix);if(title)return title;
    }
    var fallback=text.replace(/\[[^\]]*\]|\([^)]*\)/g,' ');
    EPISODE_MARKERS.forEach(function(re){
      fallback=fallback.replace(new RegExp(re.source,'gi'),' ');
    });
    return cleanSuggestedTitle(fallback);
  }
  function suggestGroupName(items){
    var names=(items||[]).map(function(it){return String(it.name||'').trim();})
      .filter(function(name){return !!name;});
    if(!names.length)return '';
    for(var i=0;i<names.length;i++){
      if(episodeMarker(names[i])){
        var series=seriesNameSuggestion(names[i]);if(series)return series;
      }
    }
    return cleanSuggestedTitle(names[0]);
  }
  function membersHtml(items,gid){
    return items.map(function(it){
      return '<div class="gmmem"><span>'+esc(it.name||it.id)+'</span>'+
        (gid?'<button title="Remove from group" onclick="gRemove(\''+jse(gid)+'\',\''+jse(it.id)+'\')">✕</button>':'')+
        '</div>';
    }).join('');
  }
  function kindHtml(g){
    var isQ=currentKind!=='episodes';
    return '<div class="gmlabel">GROUP TYPE</div>'+
      '<div class="gmkind">'+
        '<button type="button" data-kind="qualities" class="'+(isQ?'on':'')+'" '+
          'aria-pressed="'+(isQ?'true':'false')+'" onclick="gPickKind(\'qualities\')">🎞️ Qualities'+
          '<small>Different qualities of one file / movie</small></button>'+
        '<button type="button" data-kind="episodes" class="'+(isQ?'':'on')+'" '+
          'aria-pressed="'+(isQ?'false':'true')+'" onclick="gPickKind(\'episodes\')">📺 Episodes'+
          '<small>Different episodes of a series</small></button>'+
      '</div>';
  }
  function episodesHtml(g){
    var rows=(g.variants||[]).map(function(v){
      return '<div class="gmeprow"><span>'+esc(v.name||v.file_id)+'</span>'+
        '<input class="gmep" data-fid="'+esc(v.file_id)+'" maxlength="24" '+
        'value="'+esc(v.el||'')+'" aria-label="Episode label" title="Change episode label"></div>';
    }).join('');
    return '<div id="gmEpisodes" style="display:'+(currentKind==='episodes'?'block':'none')+'">'+
      '<div class="gmlabel">EPISODE LABELS</div>'+
      '<div class="gmlist">'+rows+'</div><div class="gmcount">This group has '+(g.episodes||(g.variants||[]).length)+
      ' episodes / '+(g.variants||[]).length+' files</div></div>';
  }
  window.gPickKind=function(k){
    currentKind=(k==='episodes')?'episodes':'qualities';
    Array.prototype.forEach.call(document.querySelectorAll('.gmkind button'),function(b){
      var selected=b.getAttribute('data-kind')===currentKind;
      b.classList.toggle('on',selected);b.setAttribute('aria-pressed',selected?'true':'false');});
    var ep=q('#gmEpisodes');if(ep)ep.style.display=(currentKind==='episodes'?'block':'none');
  };
  function groupMetric(x){
    x=x||{};
    if(x.kind==='episodes')return (x.episodes||x.count||0)+' episodes';
    return (x.qualities||x.count||0)+' qualities';
  }
  function collectEpisodes(){
    /* Custom labels must survive switching the type and coming back — so inputs are
       always read, even when the episode editor is currently hidden. */
    var out={};
    Array.prototype.forEach.call(document.querySelectorAll('#gmEpisodes .gmep'),function(inp){
      var v=String(inp.value||'').trim();
      if(v)out[inp.getAttribute('data-fid')]=v.slice(0,24);
    });
    return out;
  }
  function thumbsHtml(g){
    var out='<div class="gmth'+(thumbFid?'':' on')+'" onclick="gPickThumb(\'\')">'+
      '<div class="gmauto" style="height:100%">⚡ AUTO<br>(highest quality)</div><em>AUTO</em></div>';
    (g.variants||[]).forEach(function(v){
      out+='<div class="gmth'+(thumbFid===v.file_id?' on':'')+'" onclick="gPickThumb(\''+esc(v.file_id)+'\')">'+
        (v.thumb?'<img src="'+esc(v.thumb)+'" alt="">':'<div class="gmauto" style="height:100%">no thumb</div>')+
        '<em>'+esc(v.ql||v.quality||'?')+'</em></div>';
    });
    return out;
  }

  /* ── Save / Edit modal ─────────────────────────────────────── */
  window.gEdit=function(k){
    var g=window.groupGet(k);if(!g)return;
    current=g;mode='save';targetGid=g.manual?String(g.gid):'';
    thumbFid=g.manual&&g.thumb_fid?String(g.thumb_fid):'';
    currentKind=(g.kind==='episodes')?'episodes':'qualities';
    var items=itemsFrom(g);
    open(g.manual?'✏️ Edit Group #'+g.num:'💾 Save as Permanent Group',
      '<div class="gmedit">'+
      '<section class="gmedit-section"><label class="gmlabel" for="gmName">GROUP NAME</label>'+
      '<input class="gminput" id="gmName" value="'+esc(g.name)+'" placeholder="Movie / series name"></section>'+
      '<section class="gmedit-section">'+kindHtml(g)+episodesHtml(g)+'</section>'+
      '<section class="gmedit-section"><div class="gmlabel">MASTER THUMBNAIL</div><div class="gmthumbs" id="gmThumbs">'+thumbsHtml(g)+'</div>'+
      '<div class="gmrow"><button type="button" class="gmbtn alt" onclick="document.getElementById(\'gmFile\').click()">📸 Custom upload</button>'+
      '<input type="file" accept="image/*" id="gmFile" hidden onchange="gUpload(this)">'+
      (g.manual?'<button class="gmbtn alt" onclick="gClearCustom()">↩️ Remove custom</button>':'')+'</div></section>'+
      '<section class="gmedit-section"><div class="gmlabel">FILES ('+items.length+')</div><div class="gmlist">'+membersHtml(items,g.manual?String(g.gid):'')+'</div></section>'+
      '<details class="gmedit-section"><summary>Add to an existing group</summary>'+
      '<label class="gmlabel" for="gmFind">SEARCH BY NAME OR #NUMBER</label>'+
      '<input class="gminput" id="gmFind" placeholder="Search… e.g. #12 or a name" oninput="gFind(this.value)">'+
      '<div class="gmresults" id="gmResults"></div>'+
      '<div class="gpreview" id="gmChosen" hidden aria-live="polite"></div></details>'+
      '<div class="gmedit-actions"><button class="gmbtn" id="gmSave" onclick="gSave()">'+
        (g.manual?'💾 Save Changes':'💾 Save Group')+'</button>'+
      (g.manual?'<button class="gmbtn danger" onclick="gUngroup(\''+jse(g.gid)+'\')">🗑️ Ungroup</button>':'')+
      '<button class="gmbtn alt" onclick="gClose()">Cancel</button></div></div>');
    targetPreview=window.GroupPreview(q('#gmFind'),q('#gmChosen'),function(dest){
      var value=q('#gmFind').value.trim();
      targetGid=dest?dest.id:(!value&&g.manual?String(g.gid):'');
    });
    if(targetGid)gFind('#'+targetGid);
  };
  window.gFind=function(v){
    var box=q('#gmResults');if(!box)return;
    fetch('/api/group/list?q='+encodeURIComponent(v||''),{credentials:'same-origin'})
      .then(function(r){return r.json();}).then(function(d){
        LIST=d.groups||[];
        box.innerHTML=LIST.map(function(x){
          return '<div class="gmres'+(String(x.id)===targetGid?' on':'')+'" onclick="gChoose(\''+jse(x.id)+'\')">'+
            '<b>#'+esc(x.num)+'</b><span>'+esc(x.name)+' · '+groupMetric(x)+'</span></div>';
        }).join('')||'<div class="gmres" style="color:var(--mut)">No groups found</div>';
      }).catch(function(){});
  };
  window.gChoose=function(gid){
    targetGid=String(gid);
    q('#gmFind').value=targetGid;targetPreview.update();
    gFind('#'+gid);
  };
  window.gPickThumb=function(fid){thumbFid=String(fid||'');
    var g=current;if(!g)return;var box=q('#gmThumbs');if(box)box.innerHTML=thumbsHtml(g);};
  window.gClearCustom=function(){
    if(!current||!current.gid){toast('Save the group first',true);return;}
    post('/api/group/update',{group_id:current.gid,clear_custom:true})
      .then(function(){toast('↩️ Custom thumbnail removed');window.gClose();refresh();})
      .catch(function(e){toast(e.message,true);});
  };
  window.gUpload=function(input){
    var f=input.files&&input.files[0];if(!f)return;
    if(!current||!current.gid){toast('Save the group first',true);return;}
    var fd=new FormData();fd.append('group_id',current.gid);fd.append('image',f);
    fetch('/api/group/upload_thumb',{method:'POST',body:fd,credentials:'same-origin'})
      .then(function(r){return r.json();}).then(function(d){
        if(d.ok===false)throw new Error(d.error||'upload fail');
        toast('📸 Custom master thumbnail save');window.gClose();refresh();
      }).catch(function(e){toast(e.message,true);});
  };
  window.gSave=function(){
    var g=current;if(!g)return;
    if(q('#gmFind').value.trim() && !(targetPreview&&targetPreview.get())){toast('Select a valid destination group first',true);return;}
    var name=String((q('#gmName')||{}).value||'').trim();
    if(!targetGid&&!name){toast('Enter a group name',true);return;}
    if(targetGid && (!g.manual || targetGid!==String(g.gid))){
      var dest=targetPreview&&targetPreview.get();
      if(!dest||dest.id!==targetGid){toast('Please wait for a valid destination group preview',true);return;}
      if(!confirm('Add these files to group #'+dest.num+' — '+dest.name+'?'))return;
    }
    var btn=q('#gmSave');if(btn)btn.disabled=true;
    var emap=collectEpisodes();
    var transferring=!!targetGid&&(!g.manual||targetGid!==String(g.gid));
    var body=transferring?{items:itemsFrom(g)}:{items:itemsFrom(g),name:name,kind:currentKind,episode_map:emap};
    if(targetGid)body.group_id=targetGid;
    post('/api/group/save',body).then(function(d){
      var gid=d.group_id||targetGid||'';
      if(transferring)return d; // Never overwrite the destination group's name/type/thumbnail.
      /* ✏️ Renaming is separate from saving members — send it explicitly to
         `/api/group/update` (along with the master thumbnail in the same call). */
      var upd={group_id:gid,kind:currentKind,episode_map:emap};
      if(name)upd.name=name;
      if(thumbFid)upd.thumb_file_id=thumbFid;
      if(!gid)return d;
      return post('/api/group/update',upd).then(function(){return d;});
    }).then(function(d){
      /* Rename the card immediately — do not wait for a reload, and show the new
         name even if the fetch fails. If another target group was selected, do not
         rename here; refresh will bring the correct state. */
      var sameGroup=!targetGid||String(targetGid)===String(g.gid||'');
      if(name&&sameGroup){
        Array.prototype.forEach.call(document.querySelectorAll('.gcard'),function(c){
          if(c.getAttribute('data-gid')===String(d.group_id||targetGid||'')||
             c.getAttribute('data-gkey')===String(g.key||'')){
            var t=c.querySelector('.gtitle');if(t)t.textContent=name;
          }
        });
        var gd=window.groupGet(g.key);if(gd)gd.name=name;
      }
      /* Show the group type / episode labels on the card immediately (before refresh) */
      var gd2=window.groupGet(g.key);
      if(gd2&&sameGroup){gd2.kind=currentKind;gd2.episode_map=emap;}
      toast('🗂️ Group #'+d.num+' saved · '+
        (currentKind==='episodes'?'📺 episodes':'🎞️ qualities'));
      window.gClose();refresh();
    }).catch(function(e){toast(e.message,true);if(btn)btn.disabled=false;});
  };
  window.gRemove=function(gid,fid){
    if(!confirm('Remove this file from the group?'))return;
    post('/api/group/remove_file',{group_id:gid,file_id:fid})
      .then(function(){toast('File removed from group');window.gClose();refresh();})
      .catch(function(e){toast(e.message,true);});
  };
  window.gUngroup=function(gid){
    if(!gid||!confirm('Delete this group? Files are NOT deleted — they are only ungrouped.'))return;
    post('/api/group/delete',{group_id:gid})
      .then(function(){toast('🗑️ Group removed');window.gClose();refresh();})
      .catch(function(e){toast(e.message,true);});
  };

  /* ── Merge modal ───────────────────────────────────────────── */
  window.gMerge=function(k){
    var g=window.groupGet(k);if(!g||!g.manual)return;
    current=g;
    open('🔀 Merge Group #'+g.num,
      '<div class="gmlabel">TARGET GROUP NUMBER</div>'+
      '<input class="gminput" id="gmTarget" placeholder="e.g. 12 or #12" autocomplete="off">'+
      '<div class="gmnote">Source group #'+esc(g.num)+'  — all its files and auto_keys will move into the target '+
      'group, and the source group will be deleted. No files are deleted.</div>'+
      '<div class="gpreview" id="gmMergePreview" hidden aria-live="polite"></div>'+
      '<div class="gmlabel">FILES ('+(g.variants||[]).length+')</div>'+membersHtml(itemsFrom(g),'')+
      '<div class="gmrow"><button class="gmbtn" onclick="gDoMerge()">🔀 Merge</button>'+
      '<button class="gmbtn alt" onclick="gClose()">Cancel</button></div>');
    targetPreview=window.GroupPreview(q('#gmTarget'),q('#gmMergePreview'));
  };
  window.gDoMerge=function(){
    var t=(q('#gmTarget')||{}).value||'';
    if(!t.trim()){toast('Enter the target group number',true);return;}
    var dest=targetPreview&&targetPreview.get();
    if(!dest||dest.id!==t.trim().replace(/^#/,'').trim()){toast('Please wait for a valid destination group preview',true);return;}
    if(dest.id===String(current.gid)){toast('Cannot merge a group into itself',true);return;}
    if(!confirm('Merge group #'+current.num+' into group #'+dest.num+' — '+dest.name+'?'))return;
    post('/api/group/merge',{source:String(current.gid),target:t.trim()})
      .then(function(d){toast('🔀 Group #'+d.num+' — merged');window.gClose();refresh();})
      .catch(function(e){toast(e.message,true);});
  };

  /* ── ☑️ Group Mode — select individual cards to build a group ─────────── */
  function renderBar(){
    var fab=q('#gFab');if(fab)fab.style.display=selMode?'none':'block';
    var bar=q('#gSelBar');
    if(!selMode){if(bar)bar.remove();return;}
    if(!bar){bar=document.createElement('div');bar.id='gSelBar';bar.className='gselbar';
      document.body.appendChild(bar);}
    var keys=Object.keys(SEL),n=keys.length;
    bar.innerHTML='<span>'+n+' selected</span>'+
      '<button onclick="gOpenSelected()"'+(n>=2?'':' disabled')+'>🗂️ Group</button>'+
      '<button class="alt" onclick="gSelectMode()">Cancel</button>';
  }
  window.gSelectMode=function(){
    selMode=!selMode;SEL={};
    var grid=q('#grid');if(grid)grid.classList.toggle('gsel-mode',selMode);
    Array.prototype.forEach.call(document.querySelectorAll('.vcard.gsel'),
      function(c){c.classList.remove('gsel');});
    renderBar();
  };
  document.addEventListener('click',function(e){
    if(!selMode)return;
    var c=e.target&&e.target.closest&&e.target.closest('.vcard[data-fid]');
    if(!c)return;
    e.preventDefault();e.stopPropagation();
    var fid=c.dataset.fid;if(!fid)return;
    try{fid=decodeURIComponent(fid);}catch(x){}
    if(SEL[fid])delete SEL[fid];else SEL[fid]={id:fid,name:c.dataset.name||fid,
      thumb:thumbnailFromCard(c),quality:qualityFromCard(c)};
    c.classList.toggle('gsel',!!SEL[fid]);renderBar();
  },true);
  window.gSelectGroup=function(k){
    var g=window.groupGet(k);if(!g)return;
    SEL={};(g.variants||[]).forEach(function(v){SEL[v.file_id]={id:v.file_id,name:v.name,
      thumb:v.thumb||'',quality:v.quality||v.ql||''};});
    selMode=true;var grid=q('#grid');if(grid)grid.classList.add('gsel-mode');
    renderBar();toast('☑️ '+Object.keys(SEL).length+' files selected — click cards to add more');
  };
  window.gOpenSelected=function(){
    var items=Object.keys(SEL).map(function(k){return SEL[k];});
    if(items.length<2){toast('Select at least 2 files',true);return;}
    var fake={group:true,manual:false,gid:'',num:'',name:suggestGroupName(items),count:items.length,
      key:'sel:'+Date.now(),variants:items.map(function(it){
        return {file_id:it.id,name:it.name,thumb:it.thumb||'',size:'',
          quality:it.quality||'',ql:it.quality||'',duration:''};
      }),chips:[],duration:'',size:''};
    window.groupHTML(fake,'');                 /* register it in GD */
    selMode=false;SEL={};var grid=q('#grid');if(grid)grid.classList.remove('gsel-mode');renderBar();
    window.gEdit(fake.key);
  };

  /* ── ⚙️ Scan all + progress ────────────────────────────────── */
  window.gScanAll=function(){
    if(!confirm('Scan the whole library and build permanent groups? This can take a few minutes on a large library.'))return;
    post('/api/group/scan_all',{}).then(function(d){
      toast(d.started?'⚙️ Scan started…':'⚙️ A scan is already running');
      clearInterval(scanTimer);
      scanTimer=setInterval(function(){
        fetch('/api/group/scan_status',{credentials:'same-origin'}).then(function(r){return r.json();})
          .then(function(s){
            if(s.running){toast('⚙️ '+s.phase+' ('+s.scanned+'/'+s.total+')');}
            else{clearInterval(scanTimer);
              if(s.error)toast('Scan error: '+s.error,true);
              else{toast('✅ Scan complete: '+s.created+' new groups, '+s.added+' files added');refresh();}}
          }).catch(function(){});
      },3000);
    }).catch(function(e){toast(e.message,true);});
  };
  q('#gmModal').addEventListener('click',function(e){if(e.target===this)window.gClose();});
  document.addEventListener('keydown',function(e){
    if(e.key==='Escape'&&q('#gmModal').classList.contains('open'))window.gClose();
  });
  renderBar();
})();
</script>"""
