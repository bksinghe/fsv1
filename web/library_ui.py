"""Logged-in personal library controls. Reuse the site's modal and poster/text mode."""
LIBRARY_CSS = '''<style>.library{max-width:68rem;margin:2rem auto;padding:0 1rem}.library nav,.library form,.library>div,.lib-controls{display:flex;flex-wrap:wrap;align-items:center;gap:.6rem;margin:.8rem 0}
.library form{flex-wrap:nowrap}.library input[type=search]{flex:1;min-width:0;font:inherit;background:var(--bg2);color:var(--txt);padding:.6rem;border:1px solid var(--line);border-radius:8px}.library nav a[aria-current=true]{border-color:var(--red)}
.library section{margin:1rem 0}.library article{padding:.7rem;border:1px solid var(--line);background:var(--card);border-radius:10px;display:grid;gap:.4rem;min-width:0}.library img{width:100%;aspect-ratio:16/9;object-fit:cover}.library small{color:var(--mut)}.lib-name{text-align:left;background:none;color:var(--txt);font:inherit;font-weight:bold;border:0;cursor:pointer;overflow-wrap:anywhere}.lib-day{grid-column:1/-1;font-size:1.1rem}.lib-controls{padding:0 1rem}
/* Playlist collection and queue. Use the same surfaces and accent as the save picker. */
.library[data-kind=playlists]{max-width:64rem;--pl-tint:color-mix(in srgb,var(--red) 8%,var(--card))}
.pl-top,.pl-tools,.pl-row{display:flex;align-items:center}.pl-top{justify-content:space-between;gap:12px}.pl-top h1{font-size:clamp(25px,4vw,35px);letter-spacing:-.045em;line-height:1.15;margin-top:4px}
.library .pl-kicker{font-weight:800;font-size:10px;letter-spacing:.15em;color:var(--mut)}
.pl-top .tbtn,.pl-tools .tbtn,.pl-manage summary{font:inherit;font-size:13px;font-weight:750;padding:9px 13px;min-height:38px;border-radius:9px}
.pl-top .tbtn{background:var(--bg3)}.library .pl-tabs{flex-wrap:nowrap;overflow-x:auto;gap:7px;padding:4px 1px;margin:18px 0;scrollbar-width:thin}
.pl-tabs a{flex:none;max-width:18rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-size:13px;font-weight:700;border:1px solid var(--line);border-radius:24px;padding:8px 14px;color:var(--mut);background:var(--card)}
.pl-tabs a[aria-current=true]{color:var(--txt);background:var(--pl-tint)}
.pl-hero{display:flex;align-items:center;gap:clamp(14px,3vw,30px);border:1px solid var(--line);border-radius:18px;padding:clamp(16px,3vw,30px);background:linear-gradient(115deg,var(--pl-tint),var(--card) 68%)}
.pl-art{position:relative;isolation:isolate;flex:none;width:clamp(80px,16vw,144px);aspect-ratio:1;display:grid;place-items:center;overflow:hidden;border-radius:13px;background:radial-gradient(at 95% 5%,#e65758,transparent 72%),linear-gradient(130deg,#3c1223,#9e273e 65%,#4e1323);box-shadow:inset 0 0 0 1px #ffffff24}
.pl-art:before,.pl-art:after,.pl-art i{content:'';position:absolute;width:52%;height:42%;border:1px solid #ffc5bf99;border-radius:5px}
.pl-art:before{transform:translate(6%,-21%) rotate(8deg);background:#ffaba336}.pl-art:after{transform:translate(2%,-9%) rotate(2deg);background:#e57c83}.pl-art i{z-index:1;display:grid;place-items:center;transform:translate(-4%,6%) rotate(-6deg);background:linear-gradient(145deg,#ab334b,#69203b);color:#fff;font:700 clamp(16px,3vw,24px)/1 system-ui;box-shadow:0 6px 12px #360b1d44}
.pl-info{min-width:0}.pl-info h2{font-size:clamp(22px,4vw,34px);letter-spacing:-.04em;line-height:1.14;margin:5px 0;overflow-wrap:anywhere}.pl-info p{color:var(--mut);font-size:13px}
.pl-tools{flex-wrap:wrap;gap:8px;margin-top:12px}.pl-tools [data-act=continue]{background:var(--red);border-color:var(--red);color:white}
.pl-manage,.pl-options{position:relative}.pl-manage summary,.pl-options summary{list-style:none;cursor:pointer;color:var(--txt);background:var(--bg2);border:1px solid var(--line)}.pl-manage summary::-webkit-details-marker,.pl-options summary::-webkit-details-marker{display:none}
.pl-manage>div,.pl-options>div{position:absolute;z-index:8;right:0;top:calc(100% + 4px);display:grid;min-width:135px;padding:5px;border:1px solid var(--line);border-radius:10px;background:var(--card);box-shadow:0 10px 24px #0003}.pl-manage>div{left:0;right:auto}.pl-options .tbtn,.pl-manage .tbtn{background:none;text-align:left;border:0;border-radius:6px;padding:9px;font-size:13px}.pl-options .tbtn:hover,.pl-manage .tbtn:hover{background:var(--bg3)}
.pl-queue-title{font-size:18px;letter-spacing:-.025em;margin:24px 0 8px}.library[data-kind=playlists] input[type=search]{padding:11px 13px;border-radius:10px;background:var(--card)}
.library[data-kind=playlists] .mode-text{grid-template-columns:minmax(0,1fr)}.library[data-kind=playlists] article{display:block;padding:0;border-radius:12px}.pl-cover{position:relative;display:grid;place-items:center;aspect-ratio:16/9;background:var(--bg3);border-radius:11px 11px 0 0;overflow:hidden;color:var(--mut)}.pl-cover img{position:absolute;inset:0;height:100%}.mode-text .pl-cover{display:none}
.library[data-kind=playlists] article:has(details[open]){position:relative;z-index:2}.pl-row{min-width:0;gap:11px;padding:11px 13px}.pl-number{font:700 12px/1 ui-monospace,monospace;color:var(--mut);background:var(--bg3);border-radius:7px;padding:8px}.pl-row .lib-name{flex:1;min-width:0;font-size:14px;line-height:1.4}.pl-row .lib-name:hover{text-decoration:underline}
.pl-options summary{display:grid;place-items:center;width:36px;height:36px;border-color:transparent;border-radius:8px;font:bold 19px/1 system-ui}.pl-options summary:hover,.pl-options[open] summary{border-color:var(--line);background:var(--bg3)}
.pl-empty{grid-column:1/-1;text-align:center;padding:30px 14px;border:1px dashed var(--line);border-radius:12px;background:var(--card)}.pl-empty p{margin-top:6px;color:var(--mut);font-size:13px}
.library[data-kind=playlists] #libPaging{justify-content:center;color:var(--mut);font-size:13px}.library[data-kind=playlists] #libPaging a{border:1px solid var(--line);padding:7px 12px;border-radius:8px;color:var(--txt)}.library[data-kind=playlists] :focus-visible{outline:2px solid var(--red);outline-offset:2px}
@media(max-width:540px){.pl-manage>div{left:auto;right:0}.pl-top .tbtn,.pl-tools .tbtn,.pl-manage summary{padding:8px 10px}.pl-tools{gap:6px}.pl-hero{align-items:flex-start}.pl-row{padding:9px;gap:8px}}
</style>'''

LIBRARY_JS = '''<script>(()=>{
ViewMode.init({storage:ViewMode.storageFor()});
const root=document.querySelector('.library'),kind=root.dataset.kind,pid=root.dataset.list;
const queueSelect=root.querySelector('#libQueue');
const readQueue=()=>Array.from(queueSelect.options,o=>({id:o.value,name:o.text,position:o.dataset.resume===''?null:Number(o.dataset.resume)}));
let queue=readQueue();
const form=root.querySelector('form'),input=form.elements.q,grid=root.querySelector('.vm-grid');
const paging=root.querySelector('#libPaging'),status=root.querySelector('[role=status]');
let timer,request;
function cancelSearch(){clearTimeout(timer);request?.abort();}
async function search(){
 cancelSearch();const current=request=new AbortController(),url=new URL(location.href);
 url.searchParams.delete('page');const q=input.value.trim();
 if(q)url.searchParams.set('q',q);else url.searchParams.delete('q');
 grid.setAttribute('aria-busy','true');status.textContent='Searching…';
 try{
  const r=await fetch(url,{headers:{Accept:'application/json'},signal:current.signal});
  if(r.redirected&&!current.signal.aborted){location.assign(r.url);return;}
  if(!r.ok)throw Error();const data=await r.json();if(current.signal.aborted)return;
  grid.innerHTML=data.items;paging.innerHTML=data.navigation;
  queueSelect.innerHTML=data.queue;queue=readQueue();ViewMode.apply();
  history.replaceState(null,'',url);status.textContent='';
 }catch(err){if(!current.signal.aborted)status.textContent='Search failed. Press Enter to retry.';}
 finally{if(request===current)grid.removeAttribute('aria-busy');}
}
function schedule(){cancelSearch();timer=setTimeout(search,250);}
input.addEventListener('input',e=>{if(!e.isComposing)schedule();});
input.addEventListener('compositionstart',cancelSearch);input.addEventListener('compositionend',schedule);
form.addEventListener('submit',e=>{e.preventDefault();search();});
async function edit(action,fields={}){
 const r=await fetch('/api/library/'+kind,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({list:pid,action,...fields})});
 if(!r.ok)throw Error((await r.json().catch(()=>({}))).error||'Request failed. Please retry.');return r.json();
}
function run(id){const item=queue.find(x=>x.id===id);if(item)window.play(item.id,item.name,[],null,{playlist:kind==='playlists',position:item.position});}
root.addEventListener('click',async e=>{const b=e.target.closest('[data-act]');if(!b)return;
 const id=b.closest('[data-file]')?.dataset.file||'',action=b.dataset.act;
 if(action==='save')return window.saveToPlaylist(id);
 if(action==='play'||action==='continue')return run(id||(queue.some(x=>x.id===root.dataset.last)?root.dataset.last:queue[0]?.id));
 if(kind==='playlists'&&['create','rename','delete'].includes(action))return playlistDialog(action);
 if(action==='clear'&&!confirm('Clear your entire watch history?'))return;
 b.disabled=true;try{await edit(action,{file_id:id});location.reload();}
 catch(err){alert(err.message);b.disabled=false;}
});
function playlistDialog(action){
 const removing=action==='delete',dlg=document.createElement('dialog');dlg.className='playlist-picker';dlg.setAttribute('aria-labelledby','plEditTitle');
 const title=action==='create'?'New playlist':removing?'Delete playlist':'Rename playlist';
 dlg.innerHTML=`<form><header class="pp-head"><div><small>YOUR LIBRARY</small><h2 id="plEditTitle">${title}</h2></div><button class="pp-close" type="button" aria-label="Close">×</button></header><div class="pp-body"></div><footer class="pp-foot"><p role="status">Only visible to you.</p><button class="pp-save" type="submit">${removing?'Delete playlist':'Save'}</button></footer></form>`;
 const form=dlg.querySelector('form'),body=form.querySelector('.pp-body'),save=form.querySelector('.pp-save');let field;
 if(removing){body.textContent='Delete this playlist? The videos will stay in the library.';}
 else{body.innerHTML='<label class="pp-name"><span>Playlist name</span><input name="name" maxlength="80" required placeholder="Name your playlist"></label>';field=body.querySelector('input');
 if(action==='rename')field.value=root.querySelector('.pl-info h2').textContent;
 field.oninput=()=>{save.disabled=!field.value.trim();};field.oninput();}
 form.querySelector('.pp-close').onclick=()=>dlg.close();dlg.addEventListener('close',()=>dlg.remove(),{once:true});
 form.onsubmit=async e=>{e.preventDefault();if(save.disabled)return;save.disabled=true;
 try{const d=await edit(action,{name:field?.value.trim()||''});if(action==='create')location.assign('/playlists?list='+encodeURIComponent(d.id));else if(removing)location.assign('/playlists');else location.reload();}
 catch(err){form.querySelector('[role=status]').textContent=err.message;save.disabled=false;}};
 document.body.appendChild(dlg);dlg.showModal();if(field){field.focus();field.select();}
}
if(kind==='playlists'){
 // Keep only one actions menu open; clicking elsewhere or pressing Escape closes it.
 const menus=()=>root.querySelectorAll('.pl-manage[open],.pl-options[open]');
 document.addEventListener('click',e=>{menus().forEach(m=>{if(!m.contains(e.target))m.open=false;});});
 root.addEventListener('keydown',e=>{if(e.key==='Escape')menus().forEach(m=>{m.open=false;m.querySelector('summary').focus();});});
 const v=document.querySelector('#player'),bar=document.createElement('div');bar.className='lib-controls';
 bar.innerHTML='<button class="tbtn" data-step="-1">← Previous</button><button class="tbtn" data-step="1">Next →</button><label><input type="checkbox"> Auto-next</label>';
 document.querySelector('#modal .mcard').appendChild(bar);const auto=bar.querySelector('input');
 const index=()=>queue.findIndex(x=>x.id===window.libraryActiveFile());
 function step(n){const i=index();if(i>=0&&queue[i+n])run(queue[i+n].id);}
 bar.addEventListener('click',e=>{if(e.target.dataset.step)step(Number(e.target.dataset.step));});
 v.addEventListener('ended',()=>{if(auto.checked)step(1);});
 let cursor=Promise.resolve();v.addEventListener('playing',()=>{const i=index();if(i<0)return;const id=queue[i].id;
 bar.querySelector('[data-step="-1"]').disabled=i===0;bar.querySelector('[data-step="1"]').disabled=i===queue.length-1;
 if(root.dataset.last!==id){root.dataset.last=id;cursor=cursor.then(()=>edit('resume',{file_id:id})).catch(()=>{});}});
}
})();</script>'''
