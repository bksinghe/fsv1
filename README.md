# 🚀 FAST FINDER — Web File Search, Real Thumbnails and Streaming

The Telegram Auto-Filter Bot (`fsv1`) now lets you **sign in on the web**, search your files, see a **real Telegram thumbnail** for each result and **play a video from a signed streaming link by clicking the file name**. The same flow exists in `JoneySin/v5`; here it has been adapted to fsv1's existing PyMongo + aiohttp architecture.

---

## ✨ What's new

| Feature | Detail |
|---|---|
| 🌐 **Guest Pages — one source** | `/` and `/login` were plain centred cards; after studying the GitHub reference's cinematic `login-bg` hero they are now **one shared design system** in `web/welcome_assets.py`. `/` has a gradient headline, ambient CSS-only glow + grid backdrop (no external image/CDN), popular-collection chips, a decorative tilted app preview with shimmer posters, three feature cards that rise in the shared `RevealCards` wave and a footer. `/login`, `/register`, `/verify_registration` and `/forgot_password` share a **split layout**: a brand story panel + a glass auth card with a Show/Hide password toggle, focus glow and a context-aware topbar button. Everything is `wc-*`/`body.guest`-scoped, so `/search`, `/posts`, `/actors` and the detail pages are untouched; light mode, mobile breakpoints and `prefers-reduced-motion` are built in. Form actions, field names, autocomplete values, error/message query parameters and the `/` → `/search` redirect for signed-in users are unchanged. Guarded by `tests/test_welcome.py` and a jsdom runtime suite |
| 🔐 Login / Register | Email + password, **OTP in the Telegram bot PM** for registration, OTP-based password reset, HttpOnly cookie sessions (RAM + MongoDB, so a login survives restarts) |
| 🔍 Web Search | `/search` → `/api/search` → MongoDB text search + regex fallback, **search as you type** (no Search button), **21 results per page** (3 columns × 7 rows on desktop), "Show more" pagination and a **Recently Added** grid for an empty query. The "Recently Added / Database Stats" text line is gone — the count lives on the **Database Stats** page |
| 🧭 Sidebar | A hamburger sidebar on every logged-in page — **Home · 📝 Posts · 🎭 Actors · Database Stats (admin-only) · Profile Settings**, with **Sign Out** in the footer. The **`#ID · ADMIN` badge was removed** from the desktop topbar/sidebar; identity appears only on `/profile`, and Sign Out is not repeated in the main area |
| 📊 Database Stats | `/stats` — animated stat cards like v5, including the **"🆕 Recently Added Files"** count that used to sit in the search meta line |
| ⚙️ Profile Settings | `/profile` — v5-style Account Settings: `#ID · ADMIN` identity, Account Status (👑 Admin / 💎 Premium / 🆓 Free), Telegram ID, and email/password changes with tabs, show/hide and a strength meter |
| 📝 Posts + 🎭 Actors | `/posts` (Movies / Web Series / App Video / Other) and `/actors` (Actor / App / Website) are both served by **one shared catalog engine**. Poster/Text view, category filter, live search, pagination and detail pages (`/post/<id>`, `/actor/<id>`) |
| 🗂️ Tabs | Actor: `ℹ️ Overview · 🎬 Videos · 🖼️ Gallery` · Post: `ℹ️ Overview · 🎬 Videos · 📸 Screenshots` — **Posts use a Screenshots tab instead of Gallery**, where screenshots are shown. Count badges, `?tab=` deep links (Post `?tab=screenshots`), arrow-key navigation, staggered entrance and a lightbox |
| 🏷️ Tag-driven Videos (Actors only) | The Actor Videos tab finds videos in the Library using **Search Tags** (`tags[]`), like v5's `get_actor_search_results(name\|tags)`. Tag pills, `🏷️ N tags → M videos` info, a "Search inside this profile…" box above (typing ignores tags) and pagination; the title is used when there are no tags. **Posts do not have this search block** — their Videos tab shows attached videos only and the `/media` API returns `disabled` |
| 📐 Responsive grids | 🎬 **All video grids** (`/search` + `#catVideos` + `#catMediaResults`): 📱 **1/row** · tablet 2 · 🖥️ **3/row** via the shared `.vgrid`. 📝🎭 **Post/Actor listing** (`.cat-grid`): 📱 **2/row** · tablet 3–4 · 🖥️ **5/row** |
| 🎬 Multiple Videos | `videos[]` in the editor — **as many as 50**: the Library picker adds several files from one search and stays open, `➕ Add Video`, ▲▼ reorder, per-row ✕, duplicate guard and a live count. Episodes stored in `links` on older posts are **auto-migrated** |
| 🖼️ Photos / 📸 Screenshots | **Direct photo upload on the Actor Gallery tab** (`multiple`, like v5) and direct screenshot upload on the Post Screenshots tab. The editor also has a visual thumbnail grid, URL add and per-image remove. Telegram uploads run **one at a time** (rate-limit safe) and add/delete from the detail tab happens **without a page reload** |
| ✏️ Inline Edit + Animations | Admins get a **modal editor** on the listing: create / edit / delete without a reload, live cover preview + Telegram image upload, a linked-media Library picker, an unsaved-changes guard, `Ctrl/Cmd+S`, `Esc` and a delete toast with **Undo** (old deep links keep working). Animations: staggered card entrance (IntersectionObserver), 3D hover, poster zoom, shimmer skeleton, modal spring, button ripple, save-flash, toast slide and lightbox zoom — all respecting `prefers-reduced-motion`, with no CDN |
| ✨ **One Result Entrance — single source** | Rebuilt after studying the GitHub reference's `staggerCards()` / `cardEnter`: `web/reveal_assets.py` holds **the only** spring keyframes (`@keyframes rvEnter`), the `.rv-enter` / `.rv-enter.in` contract, the shimmer placeholder rules and the `window.RevealCards` engine (IntersectionObserver at `threshold:.08`, a 75 ms stagger capped at 10 cards, a 0.58 s rise → slight overshoot → settle, plus a reduced-motion fallback). A fresh `/search` batch shows shimmer cards, then results **rise in a wave**; `/posts` / `/actors` listings, their detail Videos / Screenshots / Gallery tabs and tag-driven results use the **same** wave. Cards are cleaned up after the animation so hover/press transforms keep working, and **nested group variants never wait for an off-screen intersection** — they are visible the moment a group expands. `REVEAL_CSS` / `REVEAL_JS` are appended to `SITE_CSS` / `SITE_JS` (before the Poster/Text rules), so editing the timing, curve or distance in **one file changes every result grid**. Guarded by `tests/test_reveal.py` and the jsdom runtime suite |
| 📐 Responsive Grid | **Poster and Text share the same responsive grid** (like `JoneySin/v5`'s `.res-grid`): 🖥️ Desktop ≥1024px **3 cards / row** · 📟 Tablet ≥620px 2 · 📱 Mobile **1 card / row**. Text mode is no longer a full-width list; compact cards keep the name in a single-line ellipsis above quality/res/duration chips + size + wrapping admin actions, so no detail is hidden |
| 🎛️ View / Filter | The main page has **only 2 filter buttons/dropdowns** — no `Mode` / `Filter` text labels (only `aria-label`/`title` for accessibility). **Poster / Text** mode defaults to **📄 Text everywhere** (`DEFAULT='text'` in `web/mode_assets.py`; an old saved Poster preference is reset once, then the new choice is remembered). **Text mode hides only the thumbnail image; everything else looks like Poster mode**: name + `quality / res / duration` chips (**no `VIDEO` type chip**) + `size` + a group card's `#number`, `N QUALITIES` / `N EPISODES`, duration, kind and quality/episode chips (also on each expanded variant) — `img` receives `data-src` instead of `src`, so **no thumbnail request is made**, and switching back to Poster restores `src` (all from `web/mode_assets.py`). The second filter is **All / Group / UnGroup**. 🖥️ **Desktop:** both buttons share the search line · 📱 **Mobile:** both sit on one line directly below it. **✨ New Post / ✨ New Profile** also live in `.cat-toolbar`: 🖥️ on the search line after the filters, 📱 on a **full-width line directly below the filter row**. Choices are remembered in the browser. **🎛️ The Category filter's default label is just `All`** (`CATEGORY_ALL_LABEL = "📂 All"` in `web/catalog.py` — the listing filter and the inline editor both use this one constant; the longer label is gone). **🧩 `/posts` / `/actors` have no `Content Posts` / `Directory Profiles` heading** — like the GitHub reference (v5 `.search-box`), there is **one card-box** (`var(--card)` background + border + `16px` padding + shadow) holding the search bar, Category/Mode filter buttons, ✨ New Post/Profile and the small `#catCount`, on desktop and mobile alike; on mobile the controls inside split into three lines while the box stays intact |
| 📏 Size Chip | **File size sits inside the thumbnail** (bottom-right badge); the old size/Stream line under the file name was removed |
| 📸 Real Thumbnails | **Only the Telegram thumbnail file_id is stored in the DB** — a `thumb_url: "TG_ID:<file_id>"` string, as in v5. **No image bytes in the DB or server RAM** (Koyeb's free tier has limited memory). `/api/thumb` serves already-locked ids immediately and uses `ETag` + `Cache-Control` so the **browser's own memory/disk cache** holds the poster (`If-None-Match` → 304, no repeat server/Telegram call); first-time files come from the serial warmup below |
| 🖼️ First-time Thumbnail Warmup (v5 logic) | Opening 21 new files at once can trigger **FLOOD_WAIT**, so `send_cached_media` runs **one file at a time** (global lock + a random 1.2–3.0s anti-flood gap), sleeping `wait + extra` and retrying up to 5 times on **FLOOD_WAIT/420**. The id is locked as `TG_ID:` in the DB; files without a poster are marked `NO_THUMB`. On the first request `/api/thumb` enqueues the file and returns 404 + `Retry-After`, and the browser's `retry=true&t=…` reveals posters automatically (like v5's `reloadThumb`). Admins can warm the whole library with **`/warmup_thumbs`** |
| 🛡️ **`/warmup_thumbs` = real thumbnails + accurate metadata** | Built for fsv1 after **studying** the GitHub reference (`JoneySin/v5`'s `media_probe.py` + `plugins/warmup.py` + `web/search_api.py`) — not a verbatim copy. Every serial probe writes not just a poster but **duration, quality, width×height, mime, file_size and file_type** to the DB (`$set` with `meta_v` + `probed_at`). `media_probe.py` reads the **real bytes** of MP4/MKV/AVI files (only ~2 MB head, plus ~4 MB tail when needed) for dimensions/duration instead of trusting the uploader's often **wrong `1280×720` / default duration** attributes; on failure it falls back to attributes/filename and never fails hard. `quality` comes from the true height (`2160p…240p`). **A fake "NO IMAGE" poster is never saved**: `web/image_validate.py` checks every candidate's bytes (JPEG/PNG/WEBP magic, ≥`THUMB_MIN_BYTES`, ≥`THUMB_MIN_DIM`, RGB variance, `NO IMAGE`/`NO_THUMB` markers, Pillow `verify()`), then permanently re-uploads a genuine image with `send_photo` to `CATALOG_STORAGE_CHANNEL` (like v5) and writes `thumb_url`/`thumb_verified`/`is_thumb_permanent`. Fake/blank/tiny images are marked **`NO_THUMB`** — no bogus id in the DB, and `/api/thumb` will not serve one (it forces a re-probe). The query selects only documents whose thumbnail is not **verified** or whose `meta_v` is stale, so unverified index-time `TG_ID:` ids are validated in the same run; an admin's `thumb_source:"web"` custom poster is never overwritten. The report breaks out real posters / metadata saved / fakes rejected / NO_THUMB separately |
| ✏️ File Editor (v5 `Edit Title Metadata`) | **One click on the thumbnail** (`/search` + Post/Actor Videos tabs) slides an admin-only **✏️ Edit / 🗑️ Delete** bar up **inside that thumbnail** (like v5's `.poster-admin`; no floating menu outside). Edit opens one shared inline modal: **📝 File name, 🏷️ Caption / Search tags, 🎞️ Quality, ⏱️ Duration, 📐 Resolution, 📸 Custom poster (16:9 crop), 🔄 Original thumbnail, 🗑️ Delete**. Rebuilt for fsv1 after studying v5's `/api/edit_name` + `/api/upload_thumb` + `/api/delete` — **not a verbatim copy**: v5's `target_collection` (primary/cloud/archive) was **not ported** because fsv1 has no such concept, the Cropper.js CDN is replaced by a **dependency-free canvas crop** (drag + zoom), `window.location.reload()` by a **JSON in-place card update**, and quality/duration/resolution chips are editable too. Custom posters go to `CATALOG_STORAGE_CHANNEL`, only `TG_ID:` reaches the DB, `thumb_version()` busts the browser cache and reset uses the serial probe queue. Every endpoint is admin-only with a `$set` whitelist |
| 🖱️ Card Clicks | **A single click on the thumbnail opens the `.vadmin` overlay inside that poster** (v5's `toggleAdminBtns` pattern): the ✏️ Edit / 🗑️ Delete bar slides up, the poster dims slightly and only one card is active at a time; **clicking the file name / `.vbody` plays the video in the same small shared player**. The overlay closes on a second thumbnail click, an outside click or `Esc`. Non-admins play the video directly (the overlay is hidden). The **"▶ Click to play" line under the name was removed** — only the name and compact padding remain |
| 🎛️ Shared Filter Dropdown | **The UI for every filter control lives in one place** — `FILTER_CSS` + `FILTER_JS` (`window.FilterDD`) in `web/web_assets.py`. Any `<select class="filter-dd">` is upgraded automatically into a styled button + custom options menu (the native OS dropdown never opens): caption, icon, hover/selected state, ✓ tick, keyboard `↑↓/Enter/Esc`, drop-up, outside-click close, and a `MutationObserver` for selects added later. `/search` (Mode/Filter), `/posts`–`/actors` (Category/Mode) and editor modals (Category/Quality) all use this one component; **options, labels, captions and markup also live here** in `FILTER_OPTIONS` + `SEARCH_FILTERS`/`CATALOG_FILTERS` + `filter_buttons()` — no page writes its own `<option>` or `.filters` div, so adding a button or renaming one means editing only these specs. Setting `sel.value = …` syncs the label automatically (`watchValue`), so no page needs its own `ddSet()` code. **On mobile `/search` and `/posts`–`/actors` share one `.filters` row**: the search bar on its own line, both filter buttons directly below at equal width (the catalog `.cat-box` keeps its background/border/padding on mobile too) — all changes live in **one** `@media(max-width:760px)` rule in `FILTER_CSS`; **edit `FILTER_CSS` once to change colours, spacing or animation everywhere**. The native `<select>` stays hidden but keeps `value`/`change`, so filter logic is unchanged |
| 🎴 **One Video Card — single source** | **All card markup + chips + data are written once in `web/web_assets.py`**: `VCARD_TEMPLATE`, `VCARD_CHIP_SPEC` (`quality → res → duration` — the `VIDEO`/`FILE` type chip was removed; `type` remains in the payload for the API/editor only), `vcard_meta()`, `vcard_chips()`, `vcard_size()` and `render_vcard()`. `json.dumps` feeds the same template/spec to `vcardHTML()/vcardChips()/vcardSize()` in `SITE_JS`. `/search`'s `card(f)`, Post attached videos' `video_card_html()` and Actor tag-results' `mediaCard(f)` therefore show **exactly the same** size / duration / quality / res / type chips and `.vsize`; attached videos get the same metadata from their Library doc. **To add/remove a chip, reorder them or change colours, edit only `VCARD_CHIP_SPEC`** — `syncCard()` after an edit uses the same spec. `VIDEO_CARD_CSS` gives `/search`, Post attached videos and Actor tag-results **the same `.vcard`**: 16:9 poster, quality/res/duration chips, size chip, hover play overlay, a 2-line name and only **3px gap + 9px padding** below it (the old empty space is gone). All three open the same `/api/stream` modal |
| 🖼️📄 **One View Mode — single source** | **Poster and Text share exactly the same code and markup** — `web/mode_assets.py` is the only file: `VIEW_MODE_OPTIONS` (dropdown labels), `MODE_CSS` (every `.mode-text` rule) and `MODE_JS` (`window.ViewMode` — state, localStorage keys, `data-vm-select` auto-binding, `src ⇄ data-src`). `/search`, `/posts`, `/actors`, group cards and group variants all run on that **one** engine + one CSS; catalog's separate Text HTML branch was removed, so `cardHTML()` returns one markup for both modes. **Class contract**: semantic `vm-*` classes (`vm-grid`, `vm-card`, `vm-master`, `vm-poster`, `vm-img`, `vm-ph`, `vm-overlay`, `vm-details`, `vm-chip`, `vm-size`, `vm-actions`, `vm-always`, `vm-body`, `vm-title`) — in Text mode CSS hides **only** `vm-img`/`vm-ph`/`vm-overlay`; everything else becomes static/inline and looks the same. To make a new page/card mode-aware, just add these classes; no new rules belong in another CSS/JS file. **Change one place → change everywhere**: colour/spacing/layout = `MODE_CSS`, option labels = `VIEW_MODE_OPTIONS`, state/persistence/image behaviour = `MODE_JS`. `MODE_CSS` is appended last to `SITE_CSS`, `MODE_JS` to `SITE_JS`, and both are present on every logged-in page. **To change the default mode, edit the single `DEFAULT='text'` line in `MODE_JS`** (the one-time old-preference reset `resetOnce()` lives in the same module) |
| 🗂️ **Permanent Quality Groups** | Built for fsv1 after **studying** the GitHub reference (`JoneySin/v5`'s `QualityGroups`/`QualityGroupSeq` + `/api/group/*`) — not a verbatim copy, and **no primary/cloud/archive/`section`** (fsv1 has a single `collection`). Each group is **permanent in the DB**: its own **`group_id` / `#number`** (`quality_group_seq` counter), `name`, `members` (file ids), `auto_keys`, `excluded`, master thumbnail and timestamps; each member file doc carries a **sparse `group_id`** mark. `/api/search` shows **group-first** cards: a large master poster, `#N GROUP` + quality chips (720p/1080p/2160p…), expanding into **the exact same shared `.vcard`** variants (1/2/3 responsive grid), even for members not on that page — all members come from the DB. Admins can use the **☑️ Group Mode** FAB to select several cards and create a group, **find an existing group (#number/name) and add files to it**, **🔀 Merge** (source → target number), **✏️ Rename**, **🖇️ Remove file** (blacklisted so auto-join cannot restore it), **🗑️ Ungroup** (files are not deleted), **📸 master thumbnail** (AUTO = highest quality / a member's poster / custom upload) and **⚙️ Scan all & build groups** (whole library, progress, idempotent, skips common names with 30+ files, repairs broken `group_id` marks). **New qualities join automatically**: `auto_keys`/title-key at both index time and search time add them to the same permanent group; title-key, filter, scan and auto-join come from **one** `database/group_db.py`. The Group/UnGroup filter also recognises saved groups (it used to look at names only). **🎞️/📺 Group Type:** every group stores `kind: qualities \| episodes` + `episode_map`; **GROUP TYPE** in the Edit modal changes it, and episode labels `S01E01`/`1x03`/`Ep 4`/custom are edited there too. A group card **never shows one file's `size`** (members have different sizes). **⏱ DURATION appears only on 🎞️ qualities groups** — one file's qualities share the same duration; **📺 series/episode groups show none** (each episode differs). Badges: **`3 QUALITIES`** or **`12 EPISODES`** + 🎞️ `SINGLE TITLE` / 📺 `SERIES` chip; on expand each variant keeps its own size/duration on the shared `.vcard`. The **"▾ Files" label next to the group name was removed** — now only a small `▾` chevron remains (clicking the name or chevron expands/collapses; the arrow rotates when open). `/stats` shows the **🗂️ Permanent Groups** count. **🗂️ Compact head on expand** (like v5 `.grp-card.open .grp-master{display:none}`): the open `.gcard.open` used to span the whole grid width and its 16:9 master thumbnail looked huge on desktop — now the thumbnail is hidden and a thin header remains (name + `#N GROUP` / `N QUALITIES` / duration / kind / quality-episode chips + Edit/Delete), while the variants keep their 1/2/3 grid; collapsing restores the same 16:9 master poster |
| ▶ Click-to-Stream (Shared) | **`/search` + both Post/Actor Videos tabs use one small player modal.** **Clicking a file name** → `POST /api/stream` → cached media in BIN_CHANNEL → **HMAC-signed** `/watch/<id>` + `/download/<id>` → `<video>` player (Range/seek supported), Download, Player page, Copy link, closed with `Esc`/✕. `PLAYER_MODAL_HTML` + `PLAYER_JS` from `web/web_assets.py` are the shared component; cards carry `data-fid`/`data-name` (keyboard `Enter`/`Space` too) and no new tab is opened |
| 🔗 Signed Links | `e` (expiry) + `s` (signature) — guessing a message id cannot retrieve a file without the correct signature. The Telegram bot's Watch/Download buttons also produce signed links |
| ⚡ Seek Performance | A 5-minute `media_info` cache avoids `get_messages()` on every Range request; the Range parser and `StreamResponse` are hardened and the final chunk is trimmed correctly |

---

## 🤖 Telegram Commands

The help menu (`/start` → 👨‍🚒 Help) is the **only** place commands are documented, and it is generated from two constants — `USER_COMMAND_TXT` and `ADMIN_COMMAND_TXT` in `Script.py`. `tests/test_commands.py` parses `plugins/` with `ast` and fails if a listed command has no `filters.command(...)` handler, if a `/cmd` written inside any reply is dead, if a block grows past Telegram's 1024-character caption limit, or if a removed feature ever comes back. **Commands that do not exist are no longer advertised** (`/index`, `/premium`, `/broadcast`, `/stats`, `/restart`, `/go`, `/trans`, `/uptime`, `/health`, `/softban`, `/tempban` were all dead entries and were removed).

| Where | Command | What it does |
|---|---|---|
| 👤 PM + groups | `/start` | Welcome card with the 👨‍🚒 Help button |
| 👤 PM + groups | `/id` | User / chat / sticker ID (reply to inspect someone else) |
| 👤 PM | _(plain text)_ | Search — **PM search is 💎 premium only**, group search is free |
| 👤 PM | `/plan` · `/myplan` · `/invoice` | Premium plans, your plan/expiry/renew, latest invoice |
| 👤 PM 💎 | `/upload` · `/cancel_upload` | Reply to a file (**max 200 MB**) → 🟢 GoFile or 🔵 TmpFiles, with per-site limits and an automatic fallback if the chosen host fails (`plugins/tools.py`) |
| 🛡️ PM | `/admin` (or `/dashboard`) | Live stats, 💎 Premium panel, 🗑 Delete Files, 🔄 Restart |
| 🛡️ PM | `/addpremium <user_id> <days>` · `/extendpremium <user_id> <days>` · `/removepremium <user_id>` | Grant / extend / revoke premium (invoices are kept) |
| 🛡️ PM | `/delete <keyword>` · `/deleteall` | Delete matching files · delete everything (asks `CONFIRM DELETE ALL`) |
| 🛡️ PM | `/warmup_thumbs` | Sequential scan → real posters + duration / quality / size metadata |
| 🛡️ PM | _(forward a channel post or send a `t.me` link)_ | Indexing — there is **no** `/index` command, the bot replies with ✅ START INDEXING |
| 👥 Groups only | `/search on\|off` | Toggle group search (group admins) |
| 👥 Groups only | `/help` | Group admin help (`plugins/group_mgmt.py`) — search toggle + anti-bot |

**Removed features (no longer part of the bot):** 📢 broadcast (`/broadcast_all`, `/broadcast_premium`, `/broadcast_free`, `/pin_broadcast`, `/grp_broadcast`, `/pin_grp_broadcast` — `plugins/broadcast.py` and the `utils.py` helpers are gone; `/grp_broadcast` called a `db.get_all_chats()` that never existed), 👮 group moderation (`/mute` `/unmute` `/ban` `/warn` `/resetwarn` — `/warn` used `db.get_warn()`/`set_warn()`/`clear_warn()`, which were never defined, so it always raised), 🚫 blacklist (`/addblacklist` `/removeblacklist` `/blacklist` `/blacklistwarn`), ⏱ delayed delete (`/dlink` `/removedlink` `/dlinklist`) and the ⚙️ `/ping` · `/botinfo` utilities. Group `/help` now documents only what still exists.

**📦 Plugin layout:** `plugins/misc.py` held a single command (`/id`) after the `/ping` and `/botinfo` clean-up, so it was merged into `plugins/start.py` and deleted — `start.py` is now the home of the plain-user commands (`/start`, `/id`).

**📤 `/upload` hosts:** 🟠 Catbox and 🟡 File.io were removed — every upload to them ended in `❌ Upload to … failed`. Only 🟢 **GoFile** (≤ 200 MB) and 🔵 **TmpFiles** (≤ 100 MB) remain, each with its own size limit: a host that cannot take the file is never offered (the picker shows `🚫 Too big for …` instead), the hard cap is **200 MB**, and if the chosen host still fails the bot silently tries the other one before reporting a failure.

---

## 🧭 Routes

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | Logged-in users → `/search`; otherwise the landing page (uptime-safe 200) |
| GET | `/login`, `/register`, `/verify_registration`, `/forgot_password` | Auth pages |
| POST | `/api/login`, `/api/register_step1`, `/api/register_step2`, `/api/forgot_password`, `/api/reset_password` | Auth APIs |
| GET | `/logout` | Ends the session (RAM + DB) |
| GET | `/search` | Login-walled search UI with the v5-style sidebar |
| GET | `/api/search?q=&offset=&group=` | Results JSON — text/regex search, Recently Added, Group/UnGroup filter |
| GET | `/stats` | **Database Stats** (admin-only) — v5-style counters, including "Recently Added Files" |
| GET | `/api/db_stats` | The same counters as JSON (admin-only) |
| GET | `/api/file/meta?id=` | ✏️ Editor prefill — a safe projection of a file (admin-only) |
| POST | `/api/file/edit` | Save name / caption / quality / duration / resolution — whitelisted `$set` + search cache clear (admin-only) |
| POST | `/api/file/thumb` | 📸 16:9 cropped custom poster → Telegram → `TG_ID:` + cache bust (admin-only, ≤5 MB, JPG/PNG/WEBP) |
| POST | `/api/file/thumb_reset` | 🔄 Remove the custom poster and requeue the original thumbnail (admin-only) |
| POST | `/api/file/delete` | 🗑️ Delete a file by exact `_id` (admin-only; also removes it from groups) |
| POST | `/api/group/save` | 🆕 New group (new `#number`) or add files to `{group_id}` — `{items:[{id,name}], name?, kind?, episode_map?}`; **a `name` sent with `group_id` renames that existing group** (the #number stays), so renaming in the Edit modal appears in the DB and on the card immediately. Without `kind`, qualities/episodes are detected from file names (admin-only) |
| POST | `/api/group/update` | ✏️ Name / `thumb_file_id` master poster / `clear_custom` / **`kind: qualities\|episodes`** / **`episode_map: {file_id: "E05"}`**; an invalid `kind` returns `400` (admin-only) |
| GET | `/api/group/list?q=&limit=` | 🔎 Each group with `kind`, `qualities`, `episodes`, `episode_map` — which groups hold qualities and how many episodes each has |
| POST | `/api/group/remove_file` | 🖇️ Remove a file from a group + `excluded` blacklist (admin-only) |
| POST | `/api/group/delete` | 🗑️ Ungroup — files are kept, `group_id` is unset (admin-only) |
| POST | `/api/group/merge` | 🔀 `{source, target}` — all files/keys of the source move into the target `#number`, then the source is deleted (admin-only) |
| POST | `/api/group/scan_all` · GET `/api/group/scan_status` | ⚙️ Whole-library scan → permanent groups + progress (admin-only) |
| POST | `/api/group/upload_thumb` · GET `/api/group/thumb?gid=` | 📸 Custom master poster (multipart ≤5 MB) and serving it (admin / login) |
| GET | `/profile` | **Profile Settings** — v5-style Account Settings (`#ID · ADMIN`, status, email, password) |
| GET | `/posts`, `/actors` | Shared catalog UI (search, `All` category filter, Poster/Text, pagination) — no page heading, everything in one `.cat-box` |
| GET | `/post/<id>`, `/actor/<id>` | Detail page — hero, description, tags, gallery lightbox, links, admin Edit/Delete |
| GET | `/api/catalog/{kind}?q=&category=&offset=&limit=&id=` | Unified JSON list / single item (login required) |
| POST | `/api/catalog/{kind}/save` | **Create + Edit in one endpoint** (admin); `restore:true` = Undo-delete with the same id |
| POST | `/api/catalog/{kind}/delete` | Delete (admin) |
| GET | `/api/catalog/{kind}/media?id=&q=&offset=&limit=` | 🏷️ **Actors only**: Library videos from **Search Tags** (custom `q` overrides tags), JSON cards + pagination; Posts → `source: disabled` |
| POST | `/api/catalog/{kind}/gallery_upload` | Multiple photos/screenshots straight from the detail tab → `TG_ID:` (admin, serial upload) |
| POST | `/api/catalog/{kind}/gallery_delete` | `{id, index}` — remove one gallery image without a reload (admin) |
| POST | `/api/catalog/upload` | Cover/avatar image → Telegram → permanent `TG_ID:` (admin, ≤5 MB) |
| GET | `/api/catalog/photo?id=` | `TG_ID:` image bytes via the same serial-safe, FloodWait-aware download engine |
| POST | `/api/update_profile` | Email / password update (changing the password closes every session) |
| GET | `/api/search?q=&offset=&limit=&group=` | JSON results (`file_id`, `name`, `size`, `quality`, `duration`, `res`, `thumb`); `group=all\|group\|ungroup` |
| GET | `/api/thumb?file_id=&v=` | Real thumbnail image (login required) |
| POST | `/api/stream` `{file_id}` | `{watch, download, stream, poster, expires_in}` |
| GET | `/setup_stream?file_id=&mode=` | GET shortcut that redirects to signed watch/download |
| GET | `/watch/<id>?e=&s=&poster=` | Signed player page |
| GET | `/download/<id>?e=&s=` | Signed Range streaming (206/416/HEAD) |

> **Stream links are shareable:** once issued, a signed link keeps working after logout until `WEB_STREAM_TTL` expires (as in v5). Signing in is required to create a new link.

---

## ⚙️ Environment Variables

Variables that are actually used in code (`API_ID`, `API_HASH`, `BOT_TOKEN`, `ADMINS`, `DATA_DATABASE_URL`, `DATABASE_NAME`, `COLLECTION_NAME`, `BIN_CHANNEL`, `URL`, `MAX_BTN`, `PM_FILE_DELETE_TIME`, `IS_STREAM`, `USE_CAPTION_FILTER`, `PROTECT_CONTENT`, …) remain unchanged. **Unused legacy variables** (`SUPPORT_GROUP`, `SUPPORT_LINK`, `TUTORIAL`, `QUALITY`, `LANGUAGES`, `CACHE_TIME`, `DELETE_TIME`, `TIME_ZONE`, `IS_VERIFY`, `AUTO_DELETE`, `LINK_MODE`, `VERIFY_EXPIRE`, hot/cold collection names, …) were removed from `info.py` — they no longer need to be set, and `SUPPORT_GROUP` is no longer mandatory. New optional variables:

| Var | Default | Meaning |
|---|---|---|
| `MAX_WEB_RESULTS` | `21` | Results per page (3×7 on desktop); configurable via env |
| `WEB_SESSION_TTL` | `604800` | Login cookie lifetime in seconds (7 days) |
| `WEB_STREAM_TTL` | `21600` | Web stream link lifetime (6 hours) |
| `CATALOG_STORAGE_CHANNEL` | `BIN_CHANNEL` | Telegram channel for Post/Actor cover images. If `BIN_CHANNEL` is also in `INDEX_CHANNELS`, use a separate private channel so covers do not appear in file search |
| `THUMB_BROWSER_CACHE` | `604800` | How long the browser caches a poster in seconds (7 days) |
| `THUMB_FETCH_CONCURRENCY` | `6` | Download concurrency for files that **already have a `TG_ID:`** (first-time probing is always 1) |
| `THUMB_CACHE_BYTES` | `16777216` | Maximum process-RAM thumbnail hot cache (16 MiB, LRU; set `0` to disable). Speeds up repeat loads of saved `TG_ID:` posters without storing image bytes in MongoDB |
| `THUMB_PROBE_GAP_MIN` / `THUMB_PROBE_GAP_MAX` | `1.2` / `3.0` | Random anti-flood gap between first-time probes in seconds, like the v5 warmup |
| `THUMB_PROBE_ATTEMPTS` | `5` | Maximum `send_cached_media` attempts per file |
| `THUMB_FLOOD_EXTRA` | `10` | Extra buffer added to the seconds Telegram reports on FLOOD_WAIT |
| `THUMB_MIN_BYTES` | `512` | Smaller images are rejected as fake/placeholder (`NO_THUMB`) |
| `THUMB_MIN_DIM` | `48` | Minimum poster width **and** height in px (blocks 1×1 / 16×16 tracking pixels) |
| `THUMB_MIN_STDDEV` | `6.0` | RGB channel variance — a blank solid-colour "NO IMAGE" card ≈ 0, a real video frame ≫ 6 |
| `STREAM_SECRET` | Derived from `BOT_TOKEN` | HMAC secret — **set it in production**; changing it expires old links |
| `ALLOW_UNSIGNED_LINKS` | `False` | Set to `True` to keep old unsigned `/watch/<id>` links that were shared before deployment working |

---

## 🧑‍💻 Getting started

1. Send `/start` to the bot on Telegram (the OTP arrives there).
2. Open `https://<your-domain>/register` → enter **Telegram ID + Email + Password** → click "Send OTP via Telegram" → enter the 6-digit OTP from the bot PM → your account is created.
3. Sign in at `/login` with your email + password → `/search`.
4. Type a name in the search box (or pick a chip) → cards show **real thumbnails**, size, quality, resolution and duration.
5. **Click a file name** → a streaming link is prepared → the video plays in the modal. You can also use "Player page" / "Download" / "Copy stream link". The same modal opens on the **🎬 Videos tab** of `/posts` / `/actors` detail pages (for attached videos and Actor tag-driven results alike).

> When no thumbnail exists, the card shows a graceful placeholder (never a fake poster).
>
> **🖼️ First-time files:** opening the web UI does not request all posters at once — the single-worker queue in `web/thumb_engine.py` fetches them from Telegram **one at a time** and locks a `TG_ID:` in the DB; the browser's `retry=true` shows each poster automatically within a few seconds. To prepare the whole library in advance, send **`/warmup_thumbs`** to the bot on Telegram (a sequential scan with progress, like the v5 warmup engine). This command now also **saves duration / quality / resolution / mime / size / type** alongside the thumbnail, probed from the file's real bytes instead of trusting Telegram's often-wrong `1280×720` attributes. **Only genuine images become `TG_ID:`**: a "NO IMAGE" card, blank solid frame, 1×1 pixel or error body is rejected and marked `NO_THUMB`, so a fake poster never appears on the web. Remaining files are visible under "⏳ Thumb Warmup Queue" on the Database Stats page.

> **🗂️ Permanent Groups / Group–UnGroup:** fsv1 now has genuinely **permanent groups** — a `quality_groups` collection + `quality_group_seq` counter and a sparse `group_id` on every grouped file (`database/group_db.py`). The title key (with `quality`/language/codec/extension stripped) comes from **one place** and drives the search filter, auto-join and scan-all: groups an admin created stay in the DB with their `#number`, a **new quality of the same title automatically joins the same group** (`auto_keys`), and a file an admin removed stays in `excluded` and never returns. In `/api/search`, every bucket of 2+ files is a **group card** (master poster + quality chips + the same shared `.vcard` variants on expand); **Group** = group cards only, **UnGroup** = single files only, **All** = both. Group cards hold **no image bytes in the DB or RAM** — only a `TG_ID:`/`/api/thumb` reference, with the existing browser ETag cache unchanged.

> **📸 Thumbnail storage:** a `files` document holds `thumb_url: "TG_ID:<telegram_thumb_file_id>"` — just a short string in the DB. The real JPEG/PNG/WEBP bytes live **neither in MongoDB nor in a server RAM cache**; `/api/thumb` uses `ETag` + `Cache-Control: private, max-age=...` so they stay in **that browser's own memory/disk cache**. The server only holds a ~10–60 KB transient buffer for the in-flight request, released with the response. Changing `v` (the thumb_url hash) changes the ETag/URL, so a new poster appears automatically.

---

## 🧠 Restructuring permanent groups

In `JoneySin/v5`, groups were spread across `QualityGroups`/`QualityGroupSeq`, `/api/group/*` in `web/search_api.py` and admin JS in `web/dashboard_routes.py`, and every file was looked up in three collections (`primary`/`cloud`/`archive`, with `source_col`, `thumb_col`, `COLLECTIONS`). Here **only the features were studied**; the structure is fsv1's own:

* **One** `collection` — no `section` / `target_collection` / 3-collection lookup and no PRIMARY/CLOUD/ARCHIVE pill on group cards.
* **One** store, `database/group_db.py`: sync PyMongo → `asyncio.to_thread`, with a transparent in-memory fallback when MongoDB is unavailable (like `catalog_db.py`). High-level methods (`get` / `by_members` / `by_keys` / `add_members` / `merge` / `mark_files`, …) mean no raw `$addToSet`/`$pull` queries in the routes; operator logic lives in one place.
* **Numbers** come from the `quality_group_seq` counter; a sparse `group_id` index; `auto_keys` auto-joins new qualities at both index time and search time; `excluded` is a blacklist; `scan_all` is idempotent (safe to rerun) with a progress endpoint.
* **One UI source**, `web/group_assets.py`: `GROUP_CSS`, `GROUP_CARD_TEMPLATE`, `GROUP_JS` (in `SITE_JS`) and the admin-only `GROUP_ADMIN_HTML`/`GROUP_ADMIN_JS`. Every variant inside a group is built by the same `window.cardHTML()` → `VCARD_TEMPLATE`, so cards/chips look alike on `/search`, Post and Actor; the filter dropdown (`FILTER_CSS`/`FILTER_JS`) and in-poster `.vadmin` overlay are unchanged.
* **Group metadata:** `kind` (`qualities`/`episodes`), `episode_map` and `episode_label()`/`detect_episodes()`/`guess_kind()`/`episode_chips()` exist only in `database/group_db.py` — cards, `/api/group/*` and the admin modal read from that one source. The card payload has **no `size` key at all**; `duration` is filled only for qualities groups (the most common/shared duration) and is `""` for episode groups — the JS `!isEp && g.duration` guard also prevents a duration on series. Group-level chips read `N QUALITIES` / `N EPISODES` while each variant's `.vcard` stays unchanged. Episode numbers are extracted from names like `S01E02`, `2x03`, `Ep 4` or `4 of 12`, and an admin can override any label in the Edit modal. New groups guess their type from the names; a saved group always keeps the admin's choice in the DB.
* Deleting a file in the file editor cleans up groups; renaming refreshes `files[].name` + auto_keys; `/stats` and `/api/db_stats` include a `groups` count; a custom master poster uses the same `CATALOG_STORAGE_CHANNEL` + `get_image_bytes()` path (no new channel).
* Every write endpoint is **admin-only**, ids pass through the `file_edit_routes._file_id()` whitelist, field lengths are capped and DB errors are fail-soft; ungrouping never deletes files.

---

## 🧠 Restructuring Posts + Actors

In `JoneySin/v5`, these features were split between `post_routes.py` (~790 lines) and `actor_routes.py` (~590 lines) — directory CSS/JS/search/pagination copy-pasted in both, separate full-page multipart wizards for create/edit (a reload on every save), raw HTML strings from the server and a Cropper.js CDN dependency. Here **only the features were studied**; the structure is new:

* **One** `CATALOGS` config + **one** CSS/JS engine for both pages; adding a catalog means adding one config entry.
* **JSON API + client-side render** (`textContent`-safe escaping) → the server never returns an HTML string, markup lives in one place and XSS is closed off.
* **One** `/save` endpoint handles create + edit + Undo-restore (v5 had separate APIs).
* **Tabs + multi-video**: v5 had `Info / Linked Media / Gallery` tabs only on the actor detail page, with videos inside the post wizard. Here both kinds have tabs, but Post's third tab is **Screenshots**; `videos[]` is a proper array (up to 50) and the picker adds several files from one search.
* **🏷️ Tags → videos**: v5's `/api/actor/search` ran `get_actor_search_results(actor_name, tags)` as one raw regex-OR `(tag1\|tag2\|…)` and forgot the name. Here the same semantics run fsv1's **own** `get_search_results()` (`$text` index + regex fallback) per tag, then merge/dedupe/paginate — the index is used, with no new query layer. A custom `q` ignores tags, exactly like v5.
* **Gallery upload**: v5's `/api/actor/gallery_upload` submitted a form and called `window.location.reload()`; here a `multiple` input on the detail tab returns JSON that is rendered in place, with serial (anti-flood) uploads. v5's `gallery_idx` deletion is replaced by index-based in-place delete + Undo.
* **Inline modal** editing needs no page reload and adds a dirty guard, keyboard shortcuts, live preview, upload and a media picker — none of which existed in the v5 wizards.
* **Validation**: URL/scheme sanitization, media `file_id` pattern checks, field length caps, short-hex ids, admin-only writes and `prefers-reduced-motion` support.
* Images go to Telegram as `TG_ID:` so no bytes enter the DB; serving uses the same rate-limit-safe download path in `web/thumb_engine.py`, with no separate burst.

---

### ✅ Single-source regression test

A stdlib-only regression test keeps Poster/Text code from splitting across files again (no MongoDB / Telegram / aiohttp required):

```bash
python3 -m unittest discover -s tests -v
```

`tests/test_view_mode.py` checks that mode options/CSS/JS live only in `web/mode_assets.py`, that no other file has `.mode-text` CSS, a separate mode state, a different storage key or a Text-only HTML branch, that all surfaces opt in through the `vm-*` contract, and that Text mode hides only the photo. `tests/test_listing_ui.py` guards the group toggle label, create-button placement, the single search box and the `All` category label.

## 🗂️ Where things changed

```
stream_security.py               → HMAC sign/verify (new)
database/users_chats_db.py       → WebAuthDB: web_users + web_sessions + PBKDF2 + OTP (new)
database/ia_filterdb.py          → save_file stores `thumb_url` (just an id) + metadata fields,
                                   + WEB_EDITABLE_FIELDS / get_file_meta / update_file_fields / delete_file_by_id,
                                   search projection, get_recent_files(),
                                   update_file_meta() (id-only backfill)
utils.py                         → temp.USER_SESSIONS / REG_PENDING
web/mode_assets.py               → 🖼️📄 The only Poster/Text source: VIEW_MODE_OPTIONS +
                                   MODE_CSS + MODE_JS (window.ViewMode, DEFAULT='text'),
                                   and the vm-* class contract (new)
web/web_assets.py                → get_auth(), CSS, login shell, search UI; auto-search,
                                   All/Group/UnGroup dropdowns (without labels); mode wiring is
                                   only `ViewMode.init()` — no local mode logic;
                                   VIDEO_CARD_CSS (shared video card/grid), PLAYER_MODAL_HTML +
                                   PLAYER_JS (shared /search + catalog player); no #ID badge
web/auth_routes.py               → login/register/OTP/logout routes (new)
web/thumb_engine.py              → Telegram fetch (no cache), id-only DB backfill
web/search_routes.py             → /search, /api/search (group-first cards + Group/UnGroup), /api/thumb, /api/stream (new)
database/group_db.py             → 🗂️ permanent group store + title_key/quality_label/scan helpers (new)
web/group_routes.py              → 🗂️ /api/group/* CRUD/merge/scan/thumb + group_cards() (new)
web/group_assets.py              → GROUP_CSS + GROUP_CARD_TEMPLATE/GROUP_JS + admin modal/Group Mode (new)
web/file_edit_routes.py          → ✏️ admin file editor JSON/multipart API (name, caption, poster, delete) (new)
web/utils/media_info.py          → media metadata cache (new)
web/utils/render_template.py     → signed player page + poster
web/utils/custom_dl.py           → FileId support + final Range chunk fix
web/stream_routes.py             → landing, signed watch/download, hardened Range
database/catalog_db.py           → one CatalogStore: catalog_posts + catalog_actors,
                                   short-hex ids, PyMongo→to_thread, in-memory fallback (new)
web/catalog.py                   → one CATALOGS config + shared CSS/JS/detail/editor engine,
                                   video_card_html() + .vgrid (listing 2/5, videos 1/3), shared player modal
web/catalog_routes.py            → pages + generic JSON API + upload/photo (new)
web/thumb_engine.py              → Telegram fetch (no cache), id-only DB backfill,
                                   get_image_bytes() for catalog images
web/__init__.py                  → registers every route table
web/web_assets.py                → + FILTER_CSS / FILTER_JS (the only UI source for all filter dropdowns),
                                    + FILE_EDIT_HTML / FILE_EDIT_JS shared admin modal (canvas crop)
plugins/callbacks.py             → the bot's Watch/Download links are now signed
```

### 🧹 Dead-code cleanup

`info.py` now keeps only the config that is actually read by the code (unused env vars, `import os` and old link/collection/template constants were removed). Unused message templates in `Script.py`, DB helpers and methods that were never called (`run_sync`, `update_file_quality`, `database_health_check`, `delete_file_by_id`, ban/add-user API, `update_profile`, `download_as_bytesio`, `drop_media_info`, `last_online`), unused imports/locals and pointless `f`-strings/`global` statements were removed too. `pyflakes` is clean across the repo; web/auth/stream/thumbnail behaviour is unchanged.

**🤖 Telegram command audit (this pass):** every entry of `Script.py`'s `USER_COMMAND_TXT` / `ADMIN_COMMAND_TXT` was checked against the handlers registered in `plugins/`. Dead entries (`/index`, `/premium`, `/broadcast`, `/stats`, `/restart`, `/go`, `/trans`, `/uptime`, `/health`, `/softban`, `/tempban`) were dropped and the real commands were filled in. The unreachable `stats_callback` branch of `plugins/callbacks.py` was removed, the admin panel's `Use /premium` hint now points at `/admin`, and the 💎 Premium buttons that printed `/addpremium` · `/extendpremium` · `/removepremium` without a handler are now real PM commands (`plugins/premium.py`), with 🔍 Check User listening for the user ID it asks for. The 📢 broadcast, 👮 moderation, 🚫 blacklist and ⏱ dlink features (and the PM `/help` · `/commands` shortcuts) were then **removed on request** — `plugins/broadcast.py`, the broadcast helpers in `utils.py`, the unused `db.get_all_users()` and the moderation/blacklist/dlink handlers in `plugins/group_mgmt.py` are gone. `tests/test_commands.py` keeps the lists honest from now on, including a guard that a removed command can never be registered or advertised again.

---

## 🚢 Deploy

`Procfile` / `Dockerfile` / `render.yaml` still run `python bot.py`; the web app comes up on `0.0.0.0:PORT` as soon as the bot starts. No extra service or dependency was added (everything is stdlib plus the existing `aiohttp`/`pymongo`/`hydrogram`).

> ⚠️ Old unsigned watch/download links are disabled by default for security. If such links are still in circulation, set `ALLOW_UNSIGNED_LINKS=True` temporarily.
