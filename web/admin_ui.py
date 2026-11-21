"""Shared presentation for the two library administration pages."""
from html import escape


ADMIN_CSS = '''<style>
.admin-hero{display:flex;align-items:center;gap:clamp(14px,3vw,26px);padding:clamp(18px,3vw,30px);border:1px solid var(--line);border-radius:18px;background:var(--card);background:linear-gradient(115deg,color-mix(in srgb,var(--red) 9%,var(--card)),var(--card) 74%)}
.admin-mark{flex:none;display:grid;place-items:center;width:clamp(58px,10vw,94px);aspect-ratio:1;border-radius:18%;color:white;background:linear-gradient(140deg,#d9555e,#771b36);box-shadow:inset 0 0 0 1px #ffffff24}.admin-mark svg{width:52%}
.admin-hero small{font-size:10px;font-weight:800;letter-spacing:.15em;color:var(--mut)}.admin-hero h1{font-size:clamp(24px,4vw,34px);letter-spacing:-.04em;line-height:1.14;margin:4px 0 6px}.admin-hero p{color:var(--mut);font-size:13px;line-height:1.5;max-width:58ch}
.admin-section-title{font-size:18px;letter-spacing:-.025em;margin:24px 0 12px}.admin-confirm .pp-body{line-height:1.5;overflow-wrap:anywhere}.admin-confirm .pp-foot{justify-content:flex-end}
@media(max-width:480px){.admin-hero{align-items:flex-start}.admin-confirm .pp-foot{flex-wrap:wrap}}
</style>'''


def admin_header(title, description, icon):
    paths = {
        'stats': '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 4 16 4 16 0V5M4 12c0 4 16 4 16 0"/>',
        'bin': '<path d="M4 7h16M9 7V4h6v3M6 7l1 14h10l1-14M10 10v7m4-7v7"/>',
    }
    return (f'<header class="admin-hero"><span class="admin-mark" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">{paths[icon]}</svg></span>'
            f'<div><small>LIBRARY ADMIN</small><h1>{escape(title)}</h1><p>{escape(description)}</p></div></header>')


ADMIN_CONFIRM_JS = '''<script>
function confirmAdminAction(title, message, action){
 return new Promise(resolve=>{
  const dlg=document.createElement('dialog');dlg.className='playlist-picker admin-confirm';dlg.setAttribute('aria-labelledby','adminConfirmTitle');
  dlg.innerHTML='<form method="dialog"><header class="pp-head"><div><small>LIBRARY ADMIN</small><h2 id="adminConfirmTitle"></h2></div></header><div class="pp-body"></div><footer class="pp-foot"><button class="tbtn" value="cancel" autofocus>Cancel</button><button class="pp-save" value="confirm"></button></footer></form>';
  dlg.querySelector('h2').textContent=title;dlg.querySelector('.pp-body').textContent=message;dlg.querySelector('.pp-save').textContent=action;
  dlg.addEventListener('close',()=>{const yes=dlg.returnValue==='confirm';dlg.remove();resolve(yes);},{once:true});document.body.appendChild(dlg);dlg.showModal();
 });
}
</script>'''
