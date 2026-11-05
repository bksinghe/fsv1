class script(object):

    # ================= START =================
    # ℹ️ {0} = user mention · {1} = bot mention
    #    Rendered with enums.ParseMode.HTML, so keep the tags balanced
    #    and escape < > & inside the text (&lt; &gt; &amp;).
    START_TXT = (
        "<b>👋 Hey {}</b>\n"
        "<i>Welcome to {}</i>\n\n"
        "🤖 I am an <b>Ultra Advanced Auto Filter Bot</b>\n"
        "⚡ Fast • 🔍 Smart • 🧠 Fuzzy Search\n\n"
        "📌 Just send any movie / series name\n"
        "📌 Works in Groups &amp; PM (PM search = 💎 premium)\n"
        "📌 Premium unlocks extra power 💎\n\n"
        "👇 Tap 👨‍🚒 Help for every command."
    )

    # ================= HELP =================
    # ℹ️ {} = user mention
    HELP_TXT = (
        "<b>ℹ️ Help Menu</b>\n\n"
        "Hey {} 👋\n\n"
        "🔍 Send a movie / series name in a group\n"
        "📂 Get instant results with quality buttons\n"
        "💎 Premium unlocks PM search &amp; PM file delivery\n\n"
        "👇 Use the buttons below for the full command list."
    )

    # ================= USER COMMANDS =================
    # ⚠️ Single source of truth for the 👤 User Commands button.
    #    tests/test_commands.py fails if a command listed here has no
    #    registered handler in plugins/, so never list a dead command.
    USER_COMMAND_TXT = (
        "<b>👤 USER COMMANDS</b>\n\n"

        "🚀 <b>Basic</b>\n"
        "• /start – Welcome + 👨‍🚒 Help menu\n\n"

        "🔍 <b>Search</b>\n"
        "• Just send a movie / series name\n"
        "• Group – free for everyone\n"
        "• PM – 💎 premium only\n\n"

        "📩 <b>File Delivery</b> <i>(💎 premium)</i>\n"
        "• Tap a file button in a group → the bot\n"
        "  sends it here with ▶️ Watch / Download\n\n"

        "💎 <b>Premium</b>\n"
        "• /plan – Plans &amp; pricing\n"
        "• /myplan – Your plan, expiry &amp; renew\n"
        "• /invoice – Your latest invoice\n\n"

        "📤 <b>Upload Tools</b> <i>(PM · 💎 premium or admin)</i>\n"
        "• /upload – Reply to a file (max 200 MB),\n"
        "  then pick 🟢 GoFile or 🔵 TmpFiles\n"
        "• /cancel_upload – Cancel a pending upload\n\n"

        "⚙️ <b>Utilities</b>\n"
        "• /id – User / chat / sticker ID"
    )

    # ================= ADMIN COMMANDS =================
    # ⚠️ Single source of truth for the 🛡️ Admin Commands button.
    #    tests/test_commands.py checks every command below against the
    #    handlers registered in plugins/ — dead commands break the test.
    # ⚠️ Telegram allows only 1024 characters in a photo caption, and these
    #    lists are shown as the caption of the help photo — keep them short
    #    (tests/test_commands.py enforces the limit).
    ADMIN_COMMAND_TXT = (
        "<b>🛡️ ADMIN COMMANDS</b>\n\n"

        "🎛 <b>Panel</b>\n"
        "• /admin (or /dashboard) – stats,\n"
        "  premium, delete files, restart\n\n"

        "📁 <b>Indexing</b> <i>(PM · no command)</i>\n"
        "• Forward a channel post or a t.me link\n\n"

        "💎 <b>Premium</b>\n"
        "• /addpremium &lt;user_id&gt; &lt;days&gt;\n"
        "• /extendpremium &lt;user_id&gt; &lt;days&gt;\n"
        "• /removepremium &lt;user_id&gt;\n\n"

        "🗑 <b>Delete Files</b>\n"
        "• /delete &lt;keyword&gt; – matching files\n"
        "• /deleteall – ALL files (confirmation)\n\n"

        "🖼 /warmup_thumbs – posters + metadata\n\n"

        "👥 <b>Group Only</b> <i>(not in PM)</i>\n"
        "• /search on|off – group file search\n"
        "• /help – group admin help"
    )
