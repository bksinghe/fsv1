"""🎬 Watch page template.

`/watch/<message_id>?e=..&s=..` serves the signed player page. The <video> src
points at `/download/<id>` with the same signed token, so seeking and Range
requests work through that link too. The thumbnail is also shown as the poster.
"""

import html

from web.utils.media_info import get_media_info

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
  <div class="info">
    <div class="name">{file_name}</div>
    <a class="btn" href="{src}" download>⬇ Download</a>
    <a class="btn ghost" href="/search">🔎 Back to Search</a>
  </div>
  <div class="note">This link is valid for a limited time. Seeking uses HTTP Range requests.</div>
</div>
<script>
const v=document.querySelector('video');
v.addEventListener('loadedmetadata',()=>{{v.play().catch(()=>{{}})}});
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


async def media_watch(message_id: int, query: str = "", poster: str = ""):
    info = await get_media_info(message_id)
    if not info:
        return "<h2 style='color:#fff;text-align:center;padding:60px'>❌ File Not Found</h2>"

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
    )
