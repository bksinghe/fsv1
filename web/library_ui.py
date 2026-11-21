"""Logged-in personal library controls. Reuse the site's modal and poster/text mode."""
LIBRARY_CSS = '''<style>.library{max-width:68rem;margin:2rem auto;padding:0 1rem}.library nav,.library form,.library>div,.lib-controls{display:flex;flex-wrap:wrap;align-items:center;gap:.6rem;margin:.8rem 0}
.library form{flex-wrap:nowrap}.library input[type=search]{flex:1;min-width:0;font:inherit;background:var(--bg2);color:var(--txt);padding:.6rem;border:1px solid var(--line);border-radius:8px}.library nav a[aria-current=true]{border-color:var(--red)}
.library section{margin:1rem 0}.library article{padding:.7rem;border:1px solid var(--line);background:var(--card);border-radius:10px;display:grid;gap:.4rem;min-width:0}.library img{width:100%;aspect-ratio:16/9;object-fit:cover}.library small{color:var(--mut)}.lib-name{text-align:left;background:none;color:var(--txt);font:inherit;font-weight:bold;border:0;cursor:pointer;overflow-wrap:anywhere}.lib-day{grid-column:1/-1;font-size:1.1rem}.lib-controls{padding:0 1rem}</style>'''

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
 if((action==='delete'||action==='clear')&&!confirm(action==='clear'?'Clear your entire watch history?':'Delete this playlist? Library files are not deleted.'))return;
 let name='';if(action==='create'||action==='rename'){name=prompt('Playlist name');if(!name?.trim())return;}
 b.disabled=true;try{const d=await edit(action,{file_id:id,name});
 if(action==='create')location.assign('/playlists?list='+encodeURIComponent(d.id));else if(action==='delete')location.assign('/playlists');else location.reload();}
 catch(err){alert(err.message);b.disabled=false;}
});
if(kind==='playlists'){
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
