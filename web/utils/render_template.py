"""🎬 Watch page template.

`/watch/<message_id>?e=..&s=..` serves the signed player page. The <video> src
points at `/download/<id>` with the same signed token, so seeking and Range
requests work through that link too. The thumbnail is also shown as the poster.
"""

import html
from urllib.parse import quote

from web.web_assets import PLAYER_ACTIONS_HTML, PLAYER_CHOICES_HTML, PLAYER_JS, SITE_CSS, THEME_JS, html_response

from web.utils.media_info import get_media_info
from database.ia_filterdb import unpack_new_file_id

UNSUPPORTED_HTML = """<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Download File</title><meta name="viewport" content="width=device-width,initial-scale=1">
<script>{theme}</script><style>{css}body{{padding:16px;display:flex;
align-items:center;justify-content:center;min-height:100vh;text-align:center}}
.box{{background:var(--card);border:1px solid var(--line);overflow-wrap:anywhere;padding:36px;border-radius:14px;max-width:440px}}
a{{display:inline-block;margin-top:18px;background:var(--red);color:#fff;padding:12px 24px;
border-radius:8px;text-decoration:none;font-weight:800}}</style></head>
<body><div class="box"><h2>📦 {file_name}</h2>
<p style="color:var(--mut);margin-top:10px">This file cannot be played in the browser. Download it instead.</p>
<a href="{src}" download>⬇ Direct Download</a></div></body></html>"""


async def media_watch(message_id: int, query: str = "", poster: str = "", file_id: str = "", *, signed_in=False, bot_username=""):
    info = await get_media_info(message_id)
    if not info:
        return html_response("<h2>❌ File Not Found</h2>", status=404)

    # Attribute playback history to the signed media, never a query-string hint.
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
    if not is_video:
        return html_response(UNSUPPORTED_HTML.format(file_name=name, src=src, theme=THEME_JS, css=SITE_CSS))

    # The signed message authorizes this video, not other catalog entries.
    # Account-only thumbnails, group choices and progress require a web session.
    safe_poster = ""
    if signed_in and file_id:
        safe_poster = poster if poster.startswith("/api/thumb?") else f"/api/thumb?file_id={quote(file_id, safe='')}"
    # Close is a real link: it also works if scripts or autoplay are disabled.
    return_url = "https://t.me/" + quote(bot_username or "", safe="")
    actions = PLAYER_ACTIONS_HTML.format(download=src, close=f'<a id="pReturn" href="{return_url}" rel="noreferrer">Close</a>')
    return html_response(f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="referrer" content="no-referrer">
<title>Watch {name}</title><script>{THEME_JS}</script><style>{SITE_CSS}
#signedPlayer{{max-width:1000px;margin:22px auto;padding:0 16px 40px}}
#signedPlayer .video-wrap{{overflow:hidden;border:1px solid var(--line);border-radius:12px}}
#signedPlayer .pchoices{{margin-top:14px;background:var(--card);border:1px solid var(--line);border-radius:12px}}
#signedPlayer .mtitle{{margin:16px 0 0;white-space:normal;overflow-wrap:anywhere}}
#signedPlayer .mactions,#signedPlayer .mnote{{padding-inline:0}}
</style></head><body><header class="top"><div class="logo"><span class="nfi">F</span>
<span class="brand-txt">FAST FINDER<small>WEB FILE SEARCH</small></span></div></header>
<main id="signedPlayer" data-file-id="{html.escape(file_id[:512], quote=True)}" data-name="{name}"
 data-stream="{src}" data-poster="{html.escape(safe_poster, quote=True)}" data-account="{int(signed_in)}">
<div class="video-wrap"><video id="player" controls playsinline preload="metadata" src="{src}" poster="{html.escape(safe_poster, quote=True)}"></video></div>
{PLAYER_CHOICES_HTML}<h1 class="mtitle" id="pTitle">{name}</h1>{actions}</main>{PLAYER_JS}</body></html>""")
