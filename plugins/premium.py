import qrcode
import secrets
import asyncio
from io import BytesIO
from datetime import datetime, timedelta

from hydrogram import Client, filters, enums
from hydrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

from info import ADMINS, IS_PREMIUM, PRE_DAY_AMOUNT, UPI_ID, UPI_NAME, RECEIPT_SEND_USERNAME
from database.users_chats_db import db
from utils import is_premium, fmt, get_expiry_datetime


# ======================================================
# ⚙️ CONFIG
# ======================================================

LISTEN_SHORT = 180     # seconds to type the plan number
LISTEN_LONG = 300      # seconds to send the payment screenshot
MAX_PLAN_DAYS = 3650   # sanity cap for /addpremium · /extendpremium

active_sessions = {}   # uid -> current buy-flow step


# ======================================================
# 🧠 PLAN MATH (ONE TABLE, ONE PRICING RULE)
#    unit -> (display label, duration of one unit, billed days per unit)
#    Hours are billed as whole days, so billed days is None for them.
# ======================================================

PLAN_UNITS = {
    "hour":  ("Hours",  timedelta(hours=1),  None),
    "day":   ("Days",   timedelta(days=1),   1),
    "month": ("Months", timedelta(days=30),  30),
    "year":  ("Years",  timedelta(days=365), 365),
}


def plan_quote(unit, num):
    """(plan text, amount, billed days) for one unit + number selection"""
    label, _duration, days_per_unit = PLAN_UNITS[unit]

    if days_per_unit is None:                 # hours → whole days
        days = max(1, (num // 24) or 1)
    else:
        days = days_per_unit * num

    return f"{num} {label}", days * PRE_DAY_AMOUNT, days


def parse_duration(text):
    """'7 days' · '2 months' · '12 hours' → timedelta (None when unparsable)"""
    if not text:
        return None

    text = text.lower().strip()
    num_str = "".join(filter(str.isdigit, text))
    if not num_str:
        return None

    num = int(num_str)
    if num <= 0:
        return None

    for unit, (_label, duration, _days) in PLAN_UNITS.items():
        if unit in text:
            return duration * num

    return timedelta(days=num)     # a bare number means days


def normalise_duration(duration):
    """Plans are stored in days — an hourly purchase becomes 1 day"""
    if duration.days == 0 and duration.seconds > 0:
        return timedelta(days=max(1, (duration.seconds // 3600) // 24 + 1))
    return duration


def gen_invoice_id():
    """Generate unique invoice ID"""
    return "PRM-" + secrets.token_hex(3).upper()


# ======================================================
# 💾 PLAN CORE — the single place that writes a plan
# ======================================================

async def get_plan_data(uid):
    """(plan data, status) with the remaining time already calculated"""
    if uid in ADMINS:
        return None, "admin"

    plan = await db.get_plan(uid)
    if not plan or not plan.get("premium"):
        return None, "none"

    expire = plan.get("expire")
    exp_dt = get_expiry_datetime(expire)
    now = datetime.utcnow()
    remaining = exp_dt - now

    if remaining.total_seconds() <= 0:
        await revoke_premium(uid)      # keep the invoice history
        return None, "expired"

    return {
        "plan": plan,
        "exp_dt": exp_dt,
        "remaining": remaining,
        "days": max(0, remaining.days),
        "hours": remaining.seconds // 3600
    }, "active"


async def apply_premium(uid, plan_text, amount, duration=None, days=None,
                        extend=True, by="admin"):
    """Grant or extend premium and append the invoice.

    Every path (💎 admin command · ✅ payment approval) funnels through here,
    so the expiry rule and the invoice format can never drift apart.

    extend = True  → add `duration` on top of a plan that is still running
    extend = False → start `duration` from now
    Returns (expire_dt, invoice) or None.
    """
    if duration is None:
        if not days:
            return None
        duration = timedelta(days=days)

    now = datetime.utcnow()
    old = await db.get_plan(uid) or {}

    old_expire = old.get("expire")
    old_expire_dt = get_expiry_datetime(old_expire) if old_expire else None

    if extend and old_expire_dt and old_expire_dt > now:
        expire_dt = old_expire_dt + duration
    else:
        expire_dt = now + duration

    invoice = {
        "id": gen_invoice_id(),
        "plan": plan_text,
        "amount": amount,
        "activated": fmt(now),
        "expire": fmt(expire_dt),
        "created_at": now.timestamp(),
        "by": by,
    }

    # NOTE: get_plan() returns a shallow copy of the default plan for a user
    #       without a document — copy the list so the default stays empty.
    invoices = list(old.get("invoices") or [])
    invoices.append(invoice)

    await db.update_plan(uid, {
        "premium": True,
        "plan": plan_text,
        "expire": expire_dt.timestamp(),
        "activated_at": now.timestamp(),
        "invoices": invoices,
    })

    return expire_dt, invoice


async def revoke_premium(uid):
    """Drop premium but keep the invoice history. None when there was no plan."""
    old = await db.get_plan(uid) or {}
    if not old.get("premium"):
        return None

    await db.update_plan(uid, {
        "premium": False,
        "plan": None,
        "expire": None,
        "activated_at": None,
        "invoices": list(old.get("invoices") or []),
    })
    return old


async def notify_user(client, uid, text):
    """Best-effort DM — the user may never have started the bot"""
    try:
        await client.send_message(uid, text, parse_mode=enums.ParseMode.HTML)
        return True
    except Exception:
        return False


# ======================================================
# 🎨 UI HELPERS
# ======================================================

def buy_btn():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("💰 Buy / Renew Premium", callback_data="buy_premium")
    ]])


def cancel_btn():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("❌ Cancel", callback_data="cancel_payment")
    ]])


def duration_buttons(num):
    """One row per unit — prices come from plan_quote(), never from magic numbers"""
    rows = []
    for unit in ("hour", "day", "month", "year"):
        plan_text, amount, _days = plan_quote(unit, num)
        rows.append([InlineKeyboardButton(
            f"{plan_text} (₹{amount})", callback_data=f"dur#{num}#{unit}"
        )])

    rows.append([InlineKeyboardButton("🔄 Re-enter Number", callback_data="buy_premium")])
    rows.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel_payment")])
    return InlineKeyboardMarkup(rows)


def myplan_buttons():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🔄 Renew", callback_data="buy_premium"),
        InlineKeyboardButton("🧾 Invoices", callback_data="show_invoices")
    ]])


def back_btn():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🔙 Back", callback_data="back_to_myplan")
    ]])


def myplan_text(data):
    return f"""
🎉 **Premium Active**

💎 Plan     : {data['plan'].get("plan")}
⏰ Expires  : {fmt(data['exp_dt'])}
⏳ Remaining: {data['days']} days {data['hours']} hours
"""


async def _fail(client, message, uid, text):
    """End a buy-flow step with an error and show the buy button again.

    The step message may already be deleted (the QR replaces it), so fall
    back to a fresh PM when editing fails.
    """
    active_sessions.pop(uid, None)
    try:
        await message.edit(text, reply_markup=buy_btn())
    except Exception:
        try:
            await client.send_message(uid, text, reply_markup=buy_btn())
        except Exception:
            pass


def stamp_receipt(caption, verdict, username):
    """Mark the receipt photo in the admin channel as APPROVED / REJECTED"""
    return f"{caption}\n\n{verdict} by @{username}\n⏰ {fmt(datetime.utcnow())}"


# ======================================================
# 👤 USER COMMANDS
# ======================================================

@Client.on_message(filters.command("plan") & filters.private)
async def plan_cmd(client, message):
    if not IS_PREMIUM:
        return await message.reply("⚠️ Premium system disabled")

    uid = message.from_user.id
    if uid in ADMINS:
        return await message.reply("👑 You are Admin = Lifetime Premium Access")

    premium = await is_premium(uid, client)

    text = f"""
💎 **Premium Benefits**

🚀 Faster search & downloads
📩 PM Search access
🔕 No advertisements
⚡ Instant file delivery
🎯 Priority support
🌟 Exclusive features

💰 **Pricing:** ₹{PRE_DAY_AMOUNT}/day

📌 **Example Plans:**
• 7 days = ₹{7 * PRE_DAY_AMOUNT}
• 30 days = ₹{30 * PRE_DAY_AMOUNT}
• 365 days = ₹{365 * PRE_DAY_AMOUNT}
"""
    if premium:
        text += "\n✅ **You already have Premium!**\nYou can renew or extend your current plan."

    await message.reply(text, reply_markup=buy_btn())


@Client.on_message(filters.command("myplan") & filters.private)
async def myplan_cmd(client, message):
    if not IS_PREMIUM:
        return await message.reply("⚠️ Premium system disabled")

    data, status = await get_plan_data(message.from_user.id)
    if status == "admin":
        return await message.reply("👑 You are Admin = Lifetime Premium Access")
    if status in ("none", "expired"):
        msg = ("❌ Your premium plan has expired!" if status == "expired"
               else "❌ You don't have any active premium plan")
        return await message.reply(msg, reply_markup=buy_btn())

    await message.reply(myplan_text(data), reply_markup=myplan_buttons())


@Client.on_message(filters.command("invoice") & filters.private)
async def invoice_cmd(client, message):
    if not IS_PREMIUM:
        return await message.reply("⚠️ Premium system disabled")

    plan = await db.get_plan(message.from_user.id)
    invoices = plan.get("invoices", []) if plan else []
    if not invoices:
        return await message.reply("❌ No invoices found")

    inv = invoices[-1]
    await message.reply(
        f"""
🧾 **Latest Invoice**

🆔 **ID:** `{inv.get('id')}`
💎 **Plan:** {inv.get('plan')}
💰 **Amount:** ₹{inv.get('amount')}
📅 **Activated:** {inv.get('activated')}
⏰ **Expires:** {inv.get('expire')}
""",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("📜 View All Invoices", callback_data="show_invoices")
        ]])
    )


@Client.on_callback_query(filters.regex("^show_invoices$"))
async def show_invoice_cb(client, query: CallbackQuery):
    plan = await db.get_plan(query.from_user.id)
    invoices = plan.get("invoices", []) if plan else []
    if not invoices:
        return await query.answer("❌ No invoices found", show_alert=True)

    text = "🧾 **Invoice History**\n\n"
    for inv in invoices[-10:][::-1]:
        text += f"• `{inv.get('id')}` | ₹{inv.get('amount')} | {inv.get('plan')}\n"
        text += f"  📅 {inv.get('activated')} → {inv.get('expire')}\n\n"

    await query.message.edit(text, reply_markup=back_btn())


@Client.on_callback_query(filters.regex("^back_to_myplan$"))
async def back_to_myplan_cb(client, query: CallbackQuery):
    data, status = await get_plan_data(query.from_user.id)
    if status == "admin":
        return await query.message.edit("👑 You are Admin = Lifetime Premium Access")
    if status in ("none", "expired"):
        msg = ("❌ Your premium plan has expired!" if status == "expired"
               else "❌ You don't have any active premium plan")
        return await query.message.edit(msg, reply_markup=buy_btn())
    await query.message.edit(myplan_text(data), reply_markup=myplan_buttons())


# ======================================================
# 🛠 ADMIN PREMIUM COMMANDS (PM)
#    /stats lists these commands, so keep the two in sync.
# ======================================================

def _usage(cmd, args, example):
    return (
        f"❌ <b>Usage:</b> <code>/{cmd} {args}</code>\n\n"
        f"Example: <code>/{cmd} {example}</code>"
    )


def _read_args(message, count):
    """(values, error) — parse `<user_id> [days]` out of an admin command"""
    values = []
    for raw in message.command[1:1 + count]:
        try:
            values.append(int(raw))
        except ValueError:
            return None, "❌ <code>user_id</code> and <code>days</code> must be numbers."
    return values, None


@Client.on_message(
    filters.command(["addpremium", "extendpremium"]) & filters.private & filters.user(ADMINS)
)
async def admin_add_premium(client, message):
    """💎 /addpremium <user_id> <days> · /extendpremium <user_id> <days>"""
    cmd = message.command[0].lower()

    if len(message.command) < 3:
        return await message.reply(
            _usage(cmd, "user_id days", "123456789 30"), parse_mode=enums.ParseMode.HTML
        )

    values, error = _read_args(message, 2)
    if error:
        return await message.reply(error, parse_mode=enums.ParseMode.HTML)

    uid, days = values
    if days <= 0 or days > MAX_PLAN_DAYS:
        return await message.reply(
            f"❌ Days must be between <code>1</code> and <code>{MAX_PLAN_DAYS}</code>.",
            parse_mode=enums.ParseMode.HTML,
        )

    plan_text = f"{days} Days (Admin)"

    # extend adds on top of a running plan, add restarts the clock from now
    result = await apply_premium(
        uid, plan_text, amount=0, days=days,
        extend=(cmd == "extendpremium"), by="admin",
    )
    if not result:
        return await message.reply("❌ Could not update that plan.")

    expire_dt, _invoice = result
    action = "Extended" if cmd == "extendpremium" else "Granted"

    notified = await notify_user(
        client, uid,
        f"🎉 <b>Premium {action}!</b>\n\n"
        f"💎 Plan: <b>{plan_text}</b>\n"
        f"⏰ Expires: <code>{fmt(expire_dt)}</code>\n\n"
        "Use /myplan to check your subscription.",
    )

    await message.reply(
        f"✅ <b>Premium {action}</b>\n\n"
        f"👤 User: <code>{uid}</code>\n"
        f"💎 Plan: <b>{plan_text}</b>\n"
        f"⏰ Expires: <code>{fmt(expire_dt)}</code>\n\n"
        f"{'📩 User notified' if notified else '⚠️ Granted, but the user could not be notified'}",
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.command("removepremium") & filters.private & filters.user(ADMINS))
async def admin_remove_premium(client, message):
    """🗑 /removepremium <user_id> — drop premium, keep the invoice history"""
    if len(message.command) < 2:
        return await message.reply(
            _usage("removepremium", "user_id", "123456789"),
            parse_mode=enums.ParseMode.HTML,
        )

    values, error = _read_args(message, 1)
    if error:
        return await message.reply(
            "❌ <code>user_id</code> must be a number.", parse_mode=enums.ParseMode.HTML
        )

    uid = values[0]
    if not await revoke_premium(uid):
        return await message.reply(
            f"ℹ️ <code>{uid}</code> has no active premium plan.",
            parse_mode=enums.ParseMode.HTML,
        )

    notified = await notify_user(
        client, uid,
        "⚠️ <b>Premium Removed</b>\n\n"
        "Your premium subscription has been removed by an admin.\n"
        "Use /plan to buy a new plan.",
    )

    await message.reply(
        f"✅ <b>Premium removed</b>\n\n"
        f"👤 User: <code>{uid}</code>\n\n"
        f"{'📩 User notified' if notified else '⚠️ Removed, but the user could not be notified'}",
        parse_mode=enums.ParseMode.HTML,
    )


# ======================================================
# 💰 BUY FLOW
# ======================================================

@Client.on_callback_query(filters.regex("^buy_premium$"))
async def buy_premium(client, query: CallbackQuery):
    """Step 1 — ask for a number, then let the user pick a unit"""
    uid = query.from_user.id

    if uid in active_sessions:
        return await query.answer("⚠️ You already have an active payment session", show_alert=True)

    active_sessions[uid] = {"step": "waiting_number"}

    await query.message.edit(
        """
🔢 **Enter a Number**

Just send a number (e.g., 7, 30, 365)

Then you can choose:
• Hours
• Days
• Months
• Years

💡 Example: `7` or `30` or `365`
""",
        reply_markup=cancel_btn()
    )

    try:
        msg = await client.listen(query.message.chat.id, timeout=LISTEN_SHORT)

        if msg.from_user.id != uid:
            return await _fail(client, query.message, uid, "❌ Invalid response. Please try again.")

        if not msg.text:
            return await _fail(
                client, query.message, uid, "❌ Please send a number\n\n💡 Example: `7` or `30`"
            )

        num_str = "".join(filter(str.isdigit, msg.text))
        if not num_str:
            return await _fail(
                client, query.message, uid,
                "❌ Invalid number\n\nPlease send only numbers like: `7` or `30`"
            )

        num = int(num_str)
        if num <= 0 or num > 9999:
            return await _fail(
                client, query.message, uid,
                "❌ Invalid number (1-9999)\n\nPlease send a number between 1 and 9999"
            )

        active_sessions[uid] = {"step": "waiting_duration", "number": num}

        await query.message.edit(
            f"""
✅ Number: **{num}**

Now select your duration:
""",
            reply_markup=duration_buttons(num)
        )

    except asyncio.TimeoutError:
        return await _fail(client, query.message, uid, "⏱️ Timeout! Payment cancelled.")
    except Exception as e:
        return await _fail(client, query.message, uid, f"❌ Error: {str(e)}\n\nPlease try again")


@Client.on_callback_query(filters.regex("^dur#"))
async def duration_selected(client, query: CallbackQuery):
    """Step 2 — show the UPI QR, then wait for the payment screenshot"""
    uid = query.from_user.id

    if uid not in active_sessions:
        return await query.answer("⚠️ Session expired. Please start again.", show_alert=True)

    try:
        _, num_str, unit = query.data.split("#")
        num = int(num_str)
        plan_text, amount, days = plan_quote(unit, num)
    except Exception:
        return await query.answer("❌ Invalid data", show_alert=True)

    active_sessions[uid] = {
        "step": "waiting_screenshot",
        "plan_text": plan_text,
        "amount": amount,
        "days": days
    }

    # ---- UPI QR ----
    try:
        upi_url = f"upi://pay?pa={UPI_ID}&pn={UPI_NAME}&am={amount}&cu=INR"
        qr = qrcode.make(upi_url)
        bio = BytesIO()
        qr.save(bio, "PNG")
        bio.seek(0)
        bio.name = "qr_code.png"

        await query.message.reply_photo(
            bio,
            caption=f"""
💰 **Payment Details**

📦 **Plan:** {plan_text}
💵 **Amount:** ₹{amount}
⏰ **Duration:** {days} days

📱 **UPI ID:** `{UPI_ID}`

📸 **Next Step:** Send payment screenshot after completing payment
""",
            reply_markup=cancel_btn()
        )

        try:
            await query.message.delete()
        except:
            pass

    except Exception as e:
        return await _fail(client, query.message, uid, f"❌ Error: {str(e)}")

    # ---- Screenshot ----
    try:
        receipt = await client.listen(query.message.chat.id, timeout=LISTEN_LONG)

        if receipt.from_user.id != uid:
            return await _fail(
                client, query.message, uid, "❌ Invalid response. Please try again."
            )

        if not receipt.photo:
            return await _fail(
                client, query.message, uid, "❌ Screenshot not received. Please send a photo."
            )

    except asyncio.TimeoutError:
        return await _fail(
            client, query.message, uid,
            "⏱️ Timeout! Screenshot not received. Payment cancelled."
        )
    except Exception as e:
        return await _fail(client, query.message, uid, f"❌ Error: {str(e)}")

    buttons = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Approve", callback_data=f"pay_ok#{uid}#{plan_text}#{amount}"),
        InlineKeyboardButton("❌ Reject", callback_data=f"pay_no#{uid}")
    ]])

    try:
        await client.send_photo(
            RECEIPT_SEND_USERNAME,
            receipt.photo.file_id,
            caption=f"""
🔔 **#PremiumPayment**

👤 **User ID:** `{uid}`
👤 **Username:** @{receipt.from_user.username or 'N/A'}
👤 **Name:** {receipt.from_user.first_name}

📦 **Plan:** {plan_text}
💰 **Amount:** ₹{amount}
⏰ **Duration:** {days} days

⏰ **Time:** {datetime.utcnow().strftime("%d %b %Y, %I:%M %p UTC")}
""",
            reply_markup=buttons
        )
    except Exception as e:
        return await _fail(client, query.message, uid, f"❌ Error sending to admin: {str(e)}")

    await receipt.reply(
        "✅ **Screenshot received!**\n\n"
        "⏳ Your payment is being reviewed by admin.\n"
        "You'll be notified once approved."
    )
    active_sessions.pop(uid, None)


@Client.on_callback_query(filters.regex("^cancel_payment$"))
async def cancel_payment(_, query: CallbackQuery):
    active_sessions.pop(query.from_user.id, None)
    await query.message.edit("❌ Payment process cancelled", reply_markup=buy_btn())
    await query.answer("Cancelled", show_alert=False)


# ======================================================
# 🛂 ADMIN APPROVAL
# ======================================================

async def update_user_premium(uid, plan_txt, amount):
    """Approve a purchase: the plan text (e.g. "7 Days") carries the duration"""
    duration = parse_duration(plan_txt)
    if not duration:
        return False

    return await apply_premium(
        uid, plan_txt, amount,
        duration=normalise_duration(duration),
        extend=True, by="purchase",
    )


@Client.on_callback_query(filters.regex("^pay_ok#"))
async def approve_payment(client, query: CallbackQuery):
    if query.from_user.id not in ADMINS:
        return await query.answer("⛔ Not authorized", show_alert=True)

    try:
        _, uid, plan_txt, amount = query.data.split("#", 3)
        uid = int(uid)
        amount = int(amount)
    except Exception as e:
        return await query.answer(f"❌ Invalid data: {e}", show_alert=True)

    result = await update_user_premium(uid, plan_txt, amount)
    if not result:
        return await query.message.edit_caption(
            query.message.caption + "\n\n❌ **FAILED** - Invalid plan duration"
        )

    expire_dt, invoice = result

    await notify_user(
        client, uid,
        f"""
🎉 **Premium Activated Successfully!**

💎 **Plan:** {plan_txt}
⏰ **Valid Till:** {fmt(expire_dt)}
🧾 **Invoice ID:** `{invoice['id']}`

Thank you for your purchase! 🙏
Enjoy your premium benefits! ✨
"""
    )

    await query.message.edit_caption(
        stamp_receipt(query.message.caption, "✅ **APPROVED**", query.from_user.username)
    )
    await query.answer("✅ Payment Approved Successfully!", show_alert=True)


@Client.on_callback_query(filters.regex("^pay_no#"))
async def reject_payment(client, query: CallbackQuery):
    if query.from_user.id not in ADMINS:
        return await query.answer("⛔ Not authorized", show_alert=True)

    try:
        uid = int(query.data.split("#")[1])
    except:
        return await query.answer("❌ Invalid data", show_alert=True)

    await notify_user(
        client, uid,
        """
❌ **Payment Rejected**

Your payment screenshot was rejected by admin.
Please contact support or try again with correct details.
"""
    )

    await query.message.edit_caption(
        stamp_receipt(query.message.caption, "❌ **REJECTED**", query.from_user.username)
    )
    await query.answer("❌ Payment Rejected", show_alert=True)
