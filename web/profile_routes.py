"""⚙️ Profile Settings — a page modelled on JoneySin/v5's `web/profile_routes.py`.

* a "Profile Settings" link in the sidebar (like v5's NAV_MENU).
* the "#5292444428 · ADMIN" identity appears here in the Account Status card —
  in v5 the Telegram ID / admin status also live on the profile only.
* Account Info (Telegram ID, email) + Security (new password), tabs,
  password show/hide and a strength meter — just like v5.
* Email / password changes use fsv1's WebAuthDB + hash_password backend.
"""

import html
import re
from urllib.parse import quote

from aiohttp import web
from web.common import redirect as _redirect

from utils import temp
from database.users_chats_db import (
    db as user_db,
    web_db,
    MIN_PASSWORD_LEN,
)
from web.web_assets import get_auth, app_page, identity_badge

profile_routes = web.RouteTableDef()

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_SVG_EYE_SHOW = ('<svg width="15" height="15" viewBox="0 0 24 24" fill="none" '
                 'stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>'
                 '<circle cx="12" cy="12" r="3"/></svg>')
_SVG_EYE_HIDE = ('<svg width="15" height="15" viewBox="0 0 24 24" fill="none" '
                 'stroke="currentColor" stroke-width="2"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94"/>'
                 '<path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19"/>'
                 '<line x1="1" y1="1" x2="23" y2="23"/></svg>')

# v5-style tab / password-toggle / strength JS (separate string to avoid brace escaping)
_PROFILE_JS = f"""<script>
(function(){{
  var tabs=document.querySelectorAll('.prof-tab'), panels=document.querySelectorAll('.prof-panel');
  tabs.forEach(function(t){{
    t.addEventListener('click',function(){{
      tabs.forEach(function(x){{x.classList.remove('active')}});
      panels.forEach(function(x){{x.classList.remove('active')}});
      t.classList.add('active');
      document.getElementById('panel-'+t.dataset.tab).classList.add('active');
    }});
  }});
  var btn=document.getElementById('passToggle'), inp=document.getElementById('passInput');
  if(btn&&inp){{
    btn.addEventListener('click',function(){{
      var show=inp.type==='password';
      inp.type=show?'text':'password';
      btn.innerHTML=show?'{_SVG_EYE_HIDE}':'{_SVG_EYE_SHOW}';
    }});
    inp.addEventListener('input',function(){{
      var l=inp.value.length, s=l===0?0:l<6?1:l<10?2:l<14?3:4;
      var colors=['var(--bg3)','#ef4444','#f59e0b','#4ade80','#22c55e'],
          labels=['','Weak','Moderate','Strong','Very Strong'];
      document.querySelectorAll('.str-bar').forEach(function(b,i){{
        b.style.background=(i<s)?colors[s]:'var(--bg3)';
      }});
      var lbl=document.getElementById('strLabel');
      if(lbl){{lbl.textContent=labels[s];lbl.style.color=colors[s];lbl.style.display=l?'block':'none';}}
    }});
  }}
}})();
</script>"""



@profile_routes.get("/profile")
async def profile_page(req):
    role, tg_id = await get_auth(req)
    if not role:
        return web.HTTPFound("/login")

    prof = await web_db.get_profile(tg_id)
    email = str(prof.get("email") or "")

    # v5-style status: admin / premium / free (the plan comes from the real DB)
    try:
        mp = await user_db.get_plan(tg_id)
    except Exception:
        mp = {}
    if role == "admin":
        st_txt, exp_txt, st_clr = "👑 Admin (Lifetime Access)", "Never (Lifetime)", "var(--red)"
    elif mp.get("premium"):
        st_txt, exp_txt, st_clr = "💎 Premium User", (mp.get("expire") or "Unknown"), "#3399ff"
    else:
        st_txt, exp_txt, st_clr = "🆓 Free Account (No Active Plan)", "Use /plan in Bot PM to activate", "var(--mut)"

    err_h = f'<div class="err">{html.escape(req.query.get("err", ""))}</div>' if req.query.get("err") else ""
    msg_h = f'<div class="ok">{html.escape(req.query.get("msg", ""))}</div>' if req.query.get("msg") else ""
    badge = identity_badge(tg_id, role)

    body = f'''<div class="main" style="padding-top:36px;max-width:720px;">
  <div class="scard">{err_h}{msg_h}
    <h2 style="margin-bottom:22px;font-size:24px">⚙️ Account Settings</h2>

    <div class="prof-status" style="border-left:4px solid {st_clr};">
      <div class="prof-badge">{badge}</div>
      <div class="scard-label">Account Status</div>
      <div style="font-size:18px;font-weight:800;color:{st_clr};margin-bottom:10px">{st_txt}</div>
      <div class="scard-label" style="margin-bottom:2px">Subscription expires:</div>
      <div style="font-size:14px;font-weight:600">{html.escape(str(exp_txt))}</div>
    </div>

    <div class="prof-tab-bar">
      <button class="prof-tab active" data-tab="account" type="button">Account Info</button>
      <button class="prof-tab" data-tab="security" type="button">Security</button>
    </div>

    <form action="/api/update_profile" method="post">
      <div class="prof-panel active" id="panel-account">
        <div class="prof-field"><div class="scard-label">Telegram ID (Non-changeable)</div>
          <input class="prof-input" type="text" value="{tg_id}" disabled></div>
        <div class="prof-field"><div class="scard-label">Current Email</div>
          <input class="prof-input" type="text" value="{html.escape(email)}" disabled></div>
        <div class="prof-field"><div class="scard-label">New Email Address *</div>
          <input class="prof-input" type="email" name="new_email" value="{html.escape(email)}"
                 placeholder="Enter new email..." required></div>
        <hr class="prof-divider">
        <div class="info-row">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="#3399ff"><path d="M11.944 0A12 12 0 0 0 0 12a12 12 0 0 0 12 12 12 12 0 0 0 12-12A12 12 0 0 0 12 0a12 12 0 0 0-.056 0zm4.962 7.224c.1-.002.321.023.465.14a.506.506 0 0 1 .171.325c.016.093.036.306.02.472-.18 1.898-.962 6.502-1.36 8.627-.168.9-.499 1.201-.82 1.23-.696.065-1.225-.46-1.9-.902-1.056-.693-1.653-1.124-2.678-1.8-1.185-.78-.417-1.21.258-1.91.177-.184 3.247-2.977 3.307-3.23.007-.032.014-.15-.056-.212s-.174-.041-.249-.024c-.106.024-1.793 1.14-5.061 3.345-.48.33-.913.49-1.302.48-.428-.008-1.252-.241-1.865-.44-.752-.245-1.349-.374-1.297-.789.027-.216.325-.437.893-.663 3.498-1.524 5.83-2.529 6.998-3.014 3.332-1.386 4.025-1.627 4.476-1.635z"/></svg>
          <div><div class="info-row-lbl">Linked Telegram Account</div>
               <div class="info-row-val">ID: {tg_id} · {("ADMIN" if role == "admin" else "USER")}</div></div>
        </div>
      </div>

      <div class="prof-panel" id="panel-security">
        <div class="prof-field">
          <div class="scard-label">New Password <span style="color:var(--mut);font-weight:400;text-transform:none;letter-spacing:0;font-size:11px">(leave blank to keep current)</span></div>
          <div class="pass-wrap"><input class="prof-input pass-input" type="password" id="passInput"
               name="new_pass" minlength="{MIN_PASSWORD_LEN}" placeholder="Enter new password...">
            <button type="button" class="pass-toggle" id="passToggle">{_SVG_EYE_SHOW}</button></div>
          <div class="str-row"><div class="str-bar"></div><div class="str-bar"></div><div class="str-bar"></div><div class="str-bar"></div></div>
          <div id="strLabel" style="font-size:11px;margin-top:5px;display:none"></div>
        </div>
        <div class="info-row">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--mut)" stroke-width="2"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
          <div><div class="info-row-lbl">Password protection</div><div class="info-row-val">Active</div></div>
        </div>
        <div class="st-sub" style="margin-top:12px">Changing your password signs you out of all existing sessions. You will need to sign in again.</div>
      </div>

      <div class="prof-save-row"><button class="prof-save" type="submit">💾 Save Changes</button></div>
    </form>
  </div>
</div>{_PROFILE_JS}'''

    return app_page(
        "Profile - Fast Finder", body,
        tg_id=tg_id, role=role, active_tab="profile",
    )


@profile_routes.post("/api/update_profile")
async def api_update_profile(req):
    role, tg_id = await get_auth(req)
    if not role:
        return web.HTTPFound("/login")

    d = await req.post()
    new_email = (d.get("new_email") or "").strip().lower()
    new_pass = d.get("new_pass") or ""

    if not EMAIL_RE.match(new_email):
        return _redirect("/profile", err="Enter a valid Email Address")
    if new_pass and len(new_pass) < MIN_PASSWORD_LEN:
        return _redirect("/profile", err=f"Password must be at least {MIN_PASSWORD_LEN} characters")
    if await web_db.email_taken(new_email, tg_id):
        return _redirect("/profile", err="This email is already in use by another account!")

    try:
        await web_db.update_profile(tg_id, new_email, new_pass)
    except Exception as e:
        return _redirect("/profile", err=f"Update failed: {e}")

    # Password changed → close every session in RAM + DB (fsv1's reset flow)
    if new_pass:
        for key in [k for k, v in temp.USER_SESSIONS.items() if v.get("tg_id") == tg_id]:
            temp.USER_SESSIONS.pop(key, None)
        try:
            await web_db.delete_user_sessions(tg_id)
        except Exception:
            pass
        res = web.HTTPFound("/login?msg=" + quote("Password updated! Please sign in again."))
        res.del_cookie("user_session", path="/")
        return res

    return _redirect("/profile", msg="Profile updated successfully!")
