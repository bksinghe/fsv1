"""🌐 Guest pages — the single source for the landing page and every sign-in form.

Studied the GitHub reference (`JoneySin/v5`'s Netflix-style `login-bg` hero and
`login-card`) and rebuilt it for fsv1 **in its own way**: no external background
image, no CDN, just CSS gradients, a decorative app preview and the shared
`rv-enter` wave already used by result cards. Everything a guest sees lives here:

    WELCOME_CSS   all `wc-*` styling, light-mode + reduced-motion variants
    WELCOME_JS    password visibility, context-aware topbar, feature wave
    GUEST_TOPBAR  one nav for `/`, `/login`, `/register`, `/forgot_password`, …
    GUEST_AMBIENT the fixed ambient backdrop injected by `page()`
    landing_body() the hero + features + footer of `/`

`web/web_assets.py` only imports and appends these, so editing one file changes
every guest page. Auth form markup, field names, endpoints, error/message query
parameters and the logged-in shell are deliberately untouched.
"""
GUEST_BODY_CLASS = "guest"

GUEST_TOPBAR = (
    '<header class="wc-top">'
      '<a class="wc-brand" href="/">'
        '<span class="wc-mark">F</span>'
        '<span class="wc-brand-txt">FAST FINDER<small>WEB FILE SEARCH</small></span>'
      '</a>'
      '<nav class="wc-nav" aria-label="Guest navigation">'
        '<a class="wc-nav-link" href="/#features">Features</a>'
        '<a class="wc-nav-link" href="/login" title="Sign in to browse your library">Browse library</a>'
      '</nav>'
      '<div class="wc-actions">'
        '<button class="wc-theme" type="button" onclick="toggleTheme()" '
          'aria-label="Toggle colour theme" title="Toggle colour theme">'
          '<span aria-hidden="true">◐</span><span class="wc-theme-txt">Theme</span></button>'
        '<a class="wc-sign" href="/login">'
          '<span class="wc-sign-txt">Sign In</span><span aria-hidden="true">→</span></a>'
      '</div>'
    '</header>'
)

GUEST_AMBIENT = (
    '<div class="wc-ambient" aria-hidden="true">'
      '<div class="wc-grid"></div>'
      '<span class="wc-orb wc-orb-a"></span>'
      '<span class="wc-orb wc-orb-b"></span>'
      '<span class="wc-orb wc-orb-c"></span>'
    '</div>'
)


def landing_body(bot_username: str) -> str:
    """Hero, feature strip and footer for the unauthenticated `/` page."""
    chips = "".join(
        f'<a class="wc-chip" href="/login">{label}</a>'
        for label in ("Movies", "Web Series", "4K UHD", "Anime", "Apps")
    )
    minis = "".join(
        '<div class="wc-mini">'
          '<div class="wc-mini-poster"></div>'
          '<div class="wc-mini-name"></div><div class="wc-mini-name short"></div>'
          '<div class="wc-mini-chips"><i>1080p</i><i>1:36:22</i></div>'
        '</div>'
        for _ in range(3)
    )
    features = "".join(
        f'<article class="wc-feature rv-enter">'
        f'<div class="wc-feature-ico">{icon}</div>'
        f'<h4>{title}</h4><p>{copy}</p></article>'
        for icon, title, copy in (
            ("🔍", "Instant search", "Find any indexed file as you type — no reloads, no hunting through chat history."),
            ("🖼️", "Real thumbnails", "Genuine Telegram posters and quality, resolution and duration chips on every result."),
            ("▶️", "Signed streaming", "Play or download from a private, expiring link. Range/seek works in the built-in player."),
        )
    )
    return (
        '<main class="wc-hero">'
          '<div class="wc-hero-copy">'
            '<div class="wc-eyebrow"><span class="wc-pulse"></span> YOUR TELEGRAM LIBRARY, ON THE WEB</div>'
            '<h1 class="wc-title">Find anything.<br><span>Watch it instantly.</span></h1>'
            '<p class="wc-sub">Every file your bot has indexed, one clean page. Search by name, '
              'browse real posters and stream with a private signed link — no chat scrolling.</p>'
            '<div class="wc-cta">'
              '<a class="wc-primary" href="/login">Sign In to Search <span aria-hidden="true">→</span></a>'
              '<a class="wc-secondary" href="/register">Create Account</a>'
            '</div>'
            '<div class="wc-chips"><span class="wc-chips-label">Popular collections</span>' + chips + '</div>'
            '<div class="wc-trust">🔐 Private signed links <b>·</b> ⚡ Instant streaming <b>·</b> 🤖 Telegram-powered</div>'
          '</div>'
          '<div class="wc-preview" aria-hidden="true">'
            '<div class="wc-win">'
              '<div class="wc-win-bar"><span class="wc-dots"><i></i><i></i><i></i></span>'
                '<span class="wc-win-title">FAST FINDER · Search</span></div>'
              '<div class="wc-win-search">🔍 <span>Search movies, series or file names...</span><em>↵</em></div>'
              '<div class="wc-win-label">RECENTLY ADDED <span>21 files</span></div>'
              '<div class="wc-win-grid">' + minis + '</div>'
            '</div>'
            '<div class="wc-float wc-float-a">▶️ Signed stream ready</div>'
            '<div class="wc-float wc-float-b">🖼️ Real thumbnail</div>'
          '</div>'
        '</main>'
        '<section class="wc-features" id="features">'
          '<div class="wc-features-head"><span class="wc-kicker">WHY FAST FINDER</span>'
            '<h3>Built for a big library</h3></div>'
          '<div class="wc-feature-grid">' + features + '</div>'
        '</section>'
        '<footer class="wc-foot"><span>© FAST FINDER · Web File Search</span>'
          '<div class="wc-foot-links">'
            '<a href="/login">Sign In</a>'
            '<a href="/register">Create Account</a>'
          '</div></footer>'
    )


WELCOME_CSS = r"""
/* ─────────────────────────────────────────────────────────────
   🌐 GUEST SHELL — landing page + every auth form (web/welcome_assets.py)
   All rules are `wc-*` or scoped to `body.guest`, so /search, /posts,
   /actors and the detail pages are completely unaffected.
   ───────────────────────────────────────────────────────────── */
body.guest{position:relative;overflow-x:hidden;background:var(--bg)}
.wc-ambient{position:fixed;inset:0;z-index:0;pointer-events:none;overflow:hidden}
.wc-grid{position:absolute;inset:0;opacity:.35;
background-image:linear-gradient(to right,rgba(255,255,255,.045) 1px,transparent 1px),
linear-gradient(to bottom,rgba(255,255,255,.045) 1px,transparent 1px);
background-size:68px 68px;
-webkit-mask-image:linear-gradient(to bottom,rgba(0,0,0,.95),transparent 82%);
mask-image:linear-gradient(to bottom,rgba(0,0,0,.95),transparent 82%)}
.wc-orb{position:absolute;border-radius:50%;filter:blur(90px);opacity:.55;
animation:wcDrift 20s ease-in-out infinite alternate}
.wc-orb-a{width:520px;height:520px;top:-170px;left:-120px;background:rgba(229,9,20,.34)}
.wc-orb-b{width:480px;height:480px;bottom:-190px;right:-110px;background:rgba(88,80,235,.26);
animation-delay:-7s}
.wc-orb-c{width:300px;height:300px;top:45%;left:55%;background:rgba(229,9,20,.10);
animation-delay:-12s}
@keyframes wcDrift{from{transform:translate3d(0,0,0) scale(1)}to{transform:translate3d(36px,-28px,0) scale(1.12)}}
html.light body.guest{--wc-soft:rgba(16,16,24,.045)}
html.light .wc-grid{opacity:.7;
background-image:linear-gradient(to right,rgba(16,16,24,.07) 1px,transparent 1px),
linear-gradient(to bottom,rgba(16,16,24,.07) 1px,transparent 1px)}
html.light .wc-orb{opacity:.26}

/* ── guest topbar ── */
.wc-top{position:sticky;top:0;z-index:40;display:flex;align-items:center;gap:22px;
height:70px;padding:0 5%;background:rgba(11,11,15,.62);
border-bottom:1px solid rgba(255,255,255,.07);backdrop-filter:blur(18px)}
html.light .wc-top{background:rgba(255,255,255,.7);border-bottom-color:rgba(16,16,24,.09)}
.wc-brand{display:flex;align-items:center;gap:11px;flex:1;min-width:0}
.wc-mark{display:grid;place-items:center;width:34px;height:34px;flex:0 0 auto;
border-radius:9px;background:linear-gradient(140deg,#ff2733,#b30710);color:#fff;
font-size:20px;font-weight:900;box-shadow:0 6px 20px rgba(229,9,20,.38)}
.wc-brand-txt{display:flex;flex-direction:column;font-size:16px;font-weight:900;
letter-spacing:1.6px;line-height:1.1;white-space:nowrap}
.wc-brand-txt small{margin-top:3px;font-size:8px;font-weight:800;letter-spacing:2.2px;
color:var(--mut)}
.wc-nav{display:flex;gap:26px;align-items:center}
.wc-nav-link{font-size:13px;font-weight:700;color:var(--mut);transition:color .18s}
.wc-nav-link:hover{color:var(--txt)}
.wc-actions{display:flex;align-items:center;gap:10px}
.wc-theme{display:flex;align-items:center;gap:7px;padding:9px 13px;border-radius:9px;
background:transparent;border:1px solid var(--line);color:var(--txt);
font-size:12px;font-weight:700;line-height:1;font-family:inherit;
cursor:pointer;transition:border-color .18s,background .18s}
.wc-theme:hover{border-color:var(--red);background:rgba(229,9,20,.08)}
.wc-theme>span:first-child{font-size:15px}
.wc-sign{display:flex;align-items:center;gap:8px;padding:10px 17px;border-radius:9px;
background:var(--red);color:#fff;font-size:12px;font-weight:800;white-space:nowrap;
box-shadow:0 8px 22px rgba(229,9,20,.3);transition:transform .18s,box-shadow .18s}
.wc-sign:hover{transform:translateY(-2px);box-shadow:0 12px 28px rgba(229,9,20,.46)}

/* ── landing hero ── */
.wc-hero,.wc-features,.wc-foot,.wc-auth{position:relative;z-index:1}
.wc-hero{display:grid;grid-template-columns:1.05fr .95fr;gap:60px;align-items:center;
max-width:1260px;margin:0 auto;padding:64px 5% 56px;min-height:calc(100vh - 70px)}
.wc-hero-copy>*{animation:wcRise .7s cubic-bezier(.22,1,.36,1) both}
.wc-hero-copy>*:nth-child(1){animation-delay:.04s}
.wc-hero-copy>*:nth-child(2){animation-delay:.11s}
.wc-hero-copy>*:nth-child(3){animation-delay:.18s}
.wc-hero-copy>*:nth-child(4){animation-delay:.25s}
.wc-hero-copy>*:nth-child(5){animation-delay:.32s}
.wc-hero-copy>*:nth-child(6){animation-delay:.39s}
@keyframes wcRise{from{opacity:0;transform:translateY(22px)}to{opacity:1;transform:none}}
.wc-eyebrow,.wc-kicker{display:inline-flex;align-items:center;gap:9px;font-size:10px;
font-weight:900;letter-spacing:2.2px;color:#ff8c92;text-transform:uppercase}
.wc-eyebrow{padding:8px 14px;border:1px solid rgba(229,9,20,.35);border-radius:999px;
background:rgba(229,9,20,.09)}
.wc-pulse{width:7px;height:7px;border-radius:50%;background:var(--red);
box-shadow:0 0 0 0 rgba(229,9,20,.7);animation:wcPulse 2s infinite}
@keyframes wcPulse{70%{box-shadow:0 0 0 9px rgba(229,9,20,0)}100%{box-shadow:0 0 0 0 rgba(229,9,20,0)}}
.wc-title{margin:22px 0 18px;font-size:clamp(38px,5.1vw,66px);line-height:1.06;
letter-spacing:-2.4px;font-weight:900}
.wc-title span{background:linear-gradient(100deg,#ff8a90,#e50914 48%,#ff5b63);
-webkit-background-clip:text;background-clip:text;color:transparent}
.wc-sub{max-width:520px;font-size:16px;line-height:1.7;color:var(--mut);font-weight:500}
.wc-cta{display:flex;flex-wrap:wrap;gap:12px;margin:30px 0 26px}
.wc-primary,.wc-secondary{display:inline-flex;align-items:center;justify-content:center;gap:10px;
padding:15px 24px;border-radius:11px;font-size:14px;font-weight:800;transition:transform .18s,box-shadow .18s,border-color .18s}
.wc-primary{background:linear-gradient(135deg,#f6121e,#b30710);color:#fff;
box-shadow:0 12px 30px rgba(229,9,20,.34)}
.wc-primary:hover{transform:translateY(-3px);box-shadow:0 18px 38px rgba(229,9,20,.48)}
.wc-secondary{border:1px solid var(--line);color:var(--txt);background:rgba(255,255,255,.04)}
.wc-secondary:hover{border-color:var(--red);transform:translateY(-2px)}
.wc-chips{display:flex;flex-wrap:wrap;align-items:center;gap:8px}
.wc-chips-label{margin-right:4px;font-size:11px;font-weight:800;letter-spacing:1px;
text-transform:uppercase;color:var(--mut)}
.wc-chip{padding:7px 13px;border-radius:999px;border:1px solid var(--line);
background:rgba(255,255,255,.035);color:var(--txt);font-size:11px;font-weight:700;
transition:border-color .18s,background .18s,transform .18s}
.wc-chip:hover{border-color:var(--red);background:rgba(229,9,20,.1);transform:translateY(-2px)}
.wc-trust{margin-top:30px;font-size:12px;font-weight:600;color:var(--mut)}
.wc-trust b{margin:0 8px;opacity:.5}

/* ── decorative app preview (pure CSS, no images or network) ── */
.wc-preview{position:relative;max-width:540px;margin:0 auto;width:100%}
.wc-win{border:1px solid var(--line);border-radius:16px;overflow:hidden;
background:var(--bg2);box-shadow:0 34px 90px rgba(0,0,0,.6),0 0 0 1px rgba(255,255,255,.03) inset;
transform:perspective(1200px) rotateY(-7deg) rotateX(3deg);
animation:wcWin 1s cubic-bezier(.22,1,.36,1) both}
@keyframes wcWin{from{opacity:0;transform:perspective(1200px) rotateY(-7deg) rotateX(3deg) translateY(30px)}
to{opacity:1;transform:perspective(1200px) rotateY(-7deg) rotateX(3deg) translateY(0)}}
.wc-win-bar{display:flex;align-items:center;gap:12px;padding:11px 14px;
background:rgba(255,255,255,.035);border-bottom:1px solid var(--line)}
.wc-dots{display:flex;gap:5px}.wc-dots i{width:8px;height:8px;border-radius:50%;background:#4a4a5c}
.wc-dots i:first-child{background:#e50914}
.wc-win-title{font-size:10px;font-weight:800;letter-spacing:1.2px;color:var(--mut)}
.wc-win-search{display:flex;align-items:center;gap:10px;margin:14px;padding:11px 13px;
border:1px solid var(--line);border-radius:9px;background:var(--bg);font-size:12px}
.wc-win-search span{flex:1;color:var(--mut)}
.wc-win-search em{font-style:normal;color:var(--red);font-weight:900}
.wc-win-label{display:flex;justify-content:space-between;margin:0 14px 10px;
font-size:9px;font-weight:900;letter-spacing:1.6px;color:var(--mut)}
.wc-win-label span{letter-spacing:0;font-weight:700}
.wc-win-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;padding:0 14px 16px}
.wc-mini{border:1px solid var(--line);border-radius:8px;overflow:hidden;background:var(--card);padding-bottom:9px}
.wc-mini-poster{aspect-ratio:16/9;
background:linear-gradient(135deg,var(--bg3),#30303f 52%,var(--bg3));
/* Static preview placeholders: avoid an endless shimmer competing with real posters. */}
.wc-mini-name{height:7px;margin:9px 9px 0;border-radius:4px;background:var(--bg3)}
.wc-mini-name.short{width:58%;margin-top:5px}
.wc-mini-chips{display:flex;gap:4px;margin:9px 9px 0}
.wc-mini-chips i{font-style:normal;font-size:8px;font-weight:800;padding:3px 5px;border-radius:4px;
background:rgba(229,9,20,.16);color:#ff8c92}
.wc-mini-chips i+ i{background:var(--bg3);color:var(--mut)}
.wc-float{position:absolute;padding:9px 14px;border-radius:10px;font-size:11px;font-weight:800;
border:1px solid var(--line);background:var(--card);box-shadow:0 14px 34px rgba(0,0,0,.45);
animation:wcFloat 5s ease-in-out infinite alternate}
.wc-float-a{top:-16px;right:-18px}.wc-float-b{bottom:-18px;left:-20px;animation-delay:-2.5s}
@keyframes wcFloat{from{transform:translateY(0)}to{transform:translateY(-11px)}}

/* ── features ── */
.wc-features{max-width:1260px;margin:0 auto;padding:44px 5% 70px;scroll-margin-top:90px}
.wc-features-head{margin-bottom:24px}
.wc-kicker{color:var(--mut)}
.wc-features-head h3{margin-top:10px;font-size:26px;font-weight:900;letter-spacing:-.6px}
.wc-feature-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}
.wc-feature{padding:24px;border:1px solid var(--line);border-radius:16px;
background:linear-gradient(160deg,rgba(255,255,255,.05),transparent 60%),var(--card);
transition:transform .22s,border-color .22s}
.wc-feature:hover{transform:translateY(-5px);border-color:rgba(229,9,20,.5)}
.wc-feature-ico{display:grid;place-items:center;width:42px;height:42px;border-radius:11px;
background:rgba(229,9,20,.12);font-size:20px;margin-bottom:16px}
.wc-feature h4{font-size:15px;font-weight:800;margin-bottom:8px}
.wc-feature p{font-size:12.5px;line-height:1.65;color:var(--mut)}
.wc-foot{display:flex;justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap;
max-width:1260px;margin:0 auto;padding:22px 5% 34px;
border-top:1px solid var(--line);font-size:11px;font-weight:700;color:var(--mut)}
.wc-foot-links{display:flex;gap:20px;flex-wrap:wrap}
.wc-foot a:hover{color:var(--red)}

/* ── auth pages: split story + polished card ── */
.wc-auth{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.05fr);gap:60px;
align-items:center;max-width:1180px;margin:0 auto;padding:56px 5% 80px;
min-height:calc(100vh - 70px)}
.wc-story h2{margin:18px 0 14px;font-size:clamp(30px,3.6vw,46px);line-height:1.12;
letter-spacing:-1.6px;font-weight:900}
.wc-story h2 span{color:var(--red)}
.wc-story>p{max-width:420px;font-size:14px;line-height:1.7;color:var(--mut)}
.wc-points{list-style:none;margin:28px 0 26px;display:grid;gap:14px}
.wc-points li{display:flex;align-items:center;gap:12px;font-size:13px;font-weight:600}
.wc-points li>span{display:grid;place-items:center;width:30px;height:30px;flex:0 0 auto;
border-radius:9px;background:rgba(229,9,20,.11);font-size:14px}
.wc-story-foot{font-size:11px;font-weight:800;letter-spacing:1px;color:var(--mut)}
body.guest .auth-wrap{min-height:0;display:flex;align-items:center;justify-content:center;padding:0}
body.guest .auth-card{position:relative;max-width:440px;padding:36px;border-radius:22px;
background:linear-gradient(160deg,rgba(255,255,255,.055),transparent 55%),var(--card);
border:1px solid var(--line);
box-shadow:0 30px 80px rgba(0,0,0,.5),0 0 0 1px rgba(255,255,255,.025) inset;
backdrop-filter:blur(16px)}
html.light body.guest .auth-card{background:var(--card);box-shadow:0 24px 60px rgba(16,16,24,.14)}
.wc-kicker-card{display:block;margin-bottom:10px;font-size:9px;font-weight:900;
letter-spacing:2.2px;color:var(--red);text-transform:uppercase}
body.guest .auth-card h2{font-size:30px;letter-spacing:-.8px;margin-bottom:8px}
body.guest .auth-card .lead{font-size:13px;line-height:1.65;margin-bottom:22px}
body.guest .auth-card input{transition:border-color .18s,box-shadow .18s,background .18s}
body.guest .auth-card input:focus{border-color:var(--red);
box-shadow:0 0 0 4px rgba(229,9,20,.13)}
.wc-field{position:relative}
.wc-field input{padding-right:70px!important}
.wc-eye{position:absolute;right:9px;top:11px;border:0;background:transparent;
color:var(--mut);font-size:11px;font-weight:800;line-height:1;font-family:inherit;
cursor:pointer;padding:8px 9px;border-radius:6px}
.wc-eye:hover{color:var(--red);background:rgba(229,9,20,.08)}
body.guest .submit{background:linear-gradient(135deg,#f6121e,#b30710);border-radius:11px;
box-shadow:0 10px 26px rgba(229,9,20,.28);transition:transform .18s,box-shadow .18s}
body.guest .submit:hover{transform:translateY(-2px);box-shadow:0 15px 32px rgba(229,9,20,.44)}
body.guest .err,body.guest .ok{border-radius:10px}
body.guest .links{padding-top:4px;border-top:1px solid var(--line);margin-top:22px}
.wc-card-foot{margin-top:18px;text-align:center;font-size:11px;color:var(--mut)}

/* ── responsive + reduced motion ── */
@media(max-width:980px){
.wc-nav{display:none}
.wc-hero{grid-template-columns:1fr;gap:44px;padding:48px 5% 44px;min-height:0}
.wc-preview{max-width:480px}
.wc-auth{grid-template-columns:1fr;gap:0;padding:36px 5% 60px;min-height:0}
.wc-story{display:none}
.wc-feature-grid{grid-template-columns:1fr}
}
@media(max-width:560px){
.wc-top{height:62px;gap:10px;padding:0 4%}
.wc-brand-txt{font-size:13px;letter-spacing:1px}
.wc-brand-txt small{font-size:7px;letter-spacing:1.4px}
.wc-theme-txt{display:none}
.wc-theme{padding:9px 11px}
.wc-sign{padding:9px 12px}
.wc-title{letter-spacing:-1.4px}
.wc-hero{padding:36px 4% 36px}
.wc-float{font-size:9px;padding:7px 10px}
.wc-float-a{right:-6px}.wc-float-b{left:-6px}
body.guest .auth-card{padding:26px 22px}
.wc-foot{flex-direction:column;align-items:flex-start}
}
@media(prefers-reduced-motion:reduce){
.wc-orb,.wc-pulse,.wc-float,.wc-win,.wc-mini-poster,.wc-hero-copy>*{animation:none!important}
.wc-hero-copy>*{opacity:1!important;transform:none!important}
.wc-primary,.wc-secondary,.wc-sign,.wc-chip,.wc-feature,body.guest .submit{transition:none!important}
}
"""

WELCOME_JS = r"""
/* 🌐 Guest-page behaviour — all logic lives in web/welcome_assets.py.
   Every step is defensive so the same SITE_JS is harmless on logged-in pages. */
(function(){
  function init(){
    var body=document.body;
    if(!body || !body.classList.contains('guest')) return;

    /* The topbar's main button changes to the action the guest still needs. */
    var sign=document.querySelector('.wc-sign'), txt=sign&&sign.querySelector('.wc-sign-txt');
    if(sign && txt && location.pathname!=='/'){
      var isLogin=location.pathname==='/login';
      sign.setAttribute('href',isLogin?'/register':'/login');
      txt.textContent=isLogin?'Create Account':'Sign In';
    }

    /* Show/Hide for any password field on any auth form — markup is untouched,
       the wrapper is added at runtime so field names/attributes stay identical. */
    Array.prototype.forEach.call(
      document.querySelectorAll('.auth-card input[type=password]'),function(inp){
        if(inp.getAttribute('data-wc-pw')) return;
        inp.setAttribute('data-wc-pw','1');
        var wrap=document.createElement('div'); wrap.className='wc-field';
        inp.parentNode.insertBefore(wrap,inp);
        wrap.appendChild(inp);
        var b=document.createElement('button');
        b.type='button'; b.className='wc-eye'; b.textContent='Show';
        b.setAttribute('aria-label','Show password');
        b.addEventListener('click',function(){
          var show=inp.type==='password';
          inp.type=show?'text':'password';
          b.textContent=show?'Hide':'Show';
          b.setAttribute('aria-label',show?'Hide password':'Show password');
          inp.focus();
        });
        wrap.appendChild(b);
      });

    /* Feature cards use the same staggered spring as result grids. */
    var cards=document.querySelectorAll('.wc-feature.rv-enter');
    if(window.RevealCards) window.RevealCards.stagger('.wc-feature.rv-enter');
    else Array.prototype.forEach.call(cards,function(c){c.classList.remove('rv-enter');});
  }
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',init);
  else init();
})();
"""
