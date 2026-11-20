"""🎬 Watch page template.

`/watch/<message_id>?e=..&s=..` serves the signed player page. The <video> src
points at `/download/<id>` with the same signed token, so seeking and Range
requests work through that link too. The thumbnail is also shown as the poster.
"""

import html
from urllib.parse import quote

from web.web_assets import PLAYER_JS, PLAYER_MODAL_HTML, html_response, page

from web.utils.media_info import get_media_info
from database.ia_filterdb import unpack_new_file_id

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


async def media_watch(message_id: int, query: str = "", poster: str = "", file_id: str = "", *, signed_in=False):
    info = await get_media_info(message_id)
    if not info:
        return html_response("<h2>❌ File Not Found</h2>", status=404)

    if not file_id:
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
        return html_response(UNSUPPORTED_HTML.format(file_name=name, src=src))

    # The signed message authorizes this video, not other catalog entries.
    # Account-only thumbnails, group choices and progress require a web session.
    safe_poster = ""
    if signed_in and file_id:
        safe_poster = poster if poster.startswith("/api/thumb?") else f"/api/thumb?file_id={quote(file_id, safe='')}"
    body = (
        f'<main id="signedPlayer" data-file-id="{html.escape(file_id[:512], quote=True)}" '
        f'data-name="{name}" data-stream="{src}" data-poster="{html.escape(safe_poster, quote=True)}" '
        f'data-account="{int(signed_in)}">{PLAYER_MODAL_HTML}</main>'
        f'<noscript><a href="{src}">Download {name}</a></noscript>{PLAYER_JS}'
    )
    return page(f"Watch {raw_name}", body, topbar='<a class="top" href="/search">← Back to Search</a>')
