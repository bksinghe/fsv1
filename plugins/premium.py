import qrcode
import secrets
import asyncio
from io import BytesIO
from datetime import datetime, timedelta

from hydrogram import Client, filters, enums
from hydrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

from info import ADMINS, IS_PREMIUM, PRE_DAY_AMOUNT, UPI_ID, UPI_NAME, RECEIPT_SEND_USERNAME
from database.users_chats_db import db
from utils import is_premium


# ======================================================
# ⚙️ CONFIG
# ======================================================

LISTEN_SHORT = 180
LISTEN_LONG = 300
active_sessions = {}  


# ======================================================
# 🧠 HELPERS
# ======================================================

def fmt(dt):
    """Format datetime to readable string"""
    if isinstance(dt, (int, float)):
        dt = datetime.utcfromtimestamp(dt)
    return dt.strftime("%d %b %Y, %I:%M %p")


def parse_duration(text: str):
    """Parse duration from text like '1 day', '7 days', '1 month'"""
    if not text:
        return None
    text = text.lower().strip()
    
    # Extract number
    num_str = "".join(filter(str.isdigit, text))
    if not num_str:
        return None
    
    num = int(num_str)
    if num <= 0:
        return None
    
    # Convert to days
    if "day" in text:
        return timedelta(days=num)
    if "month" in text:
        return timedelta(days=30 * num)
    if "year" in text:
        return timedelta(days=365 * num)
    if "hour" in text:
        return timedelta(hours=num)
    
    return timedelta(days=num) # Default to days if only number


def gen_invoice_id():
    """Generate unique invoice ID"""
    return "PRM-" + secrets.token_hex(3).upper()


def get_expiry_datetime(expire):
    """Convert expire timestamp/datetime to datetime object"""
    if isinstance(expire, (int, float)):
        return datetime.utcfromtimestamp(expire)
    return expire


async def get_plan_data(uid):
    """Get user plan with calculated remaining time"""
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
        await db.update_plan(uid, {"premium": False, "plan": None, "expire": None})
        return None, "expired"
    
    return {
        "plan": plan,
        "exp_dt": exp_dt,
        "remaining": remaining,
        "days": max(0, remaining.days),
        "hours": remaining.seconds // 3600
    }, "active"


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
    """Generate duration selection buttons based on number"""
    hours_price = max(1, (num // 24) or 1) * PRE_DAY_AMOUNT
    days_price = num * PRE_DAY_AMOUNT
    months_price = num * 30 * PRE_DAY_AMOUNT
    years_price = num * 365 * PRE_DAY_AMOUNT
    
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"⏰ {num} Hours (₹{hours_price})", callback_data=f"dur#{num}#hour")],
        [InlineKeyboardButton(f"📅 {num} Days (₹{days_price})", callback_data=f"dur#{num}#day")],
        [InlineKeyboardButton(f"📆 {num} Months (₹{months_price})", callback_data=f"dur#{num}#month")],
        [InlineKeyboardButton(f"🗓️ {num} Years (₹{years_price})", callback_data=f"dur#{num}#year")],
        [InlineKeyboardButton("🔄 Re-enter Number", callback_data="buy_premium")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_payment")]
    ])


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
    data, status = await get_plan_data(message.from_user.id)
    if status == "admin":
        return await message.reply("👑 You are Admin = Lifetime Premium Access")
    if status in ["none", "expired"]:
        msg = "❌ Your premium plan has expired!" if status == "expired" else "❌ You don't have any active premium plan"
        return await message.reply(msg, reply_markup=buy_btn())
    
    await message.reply(myplan_text(data), reply_markup=myplan_buttons())


@Client.on_message(filters.command("invoice") & filters.private)
async def invoice_cmd(client, message):
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
    if status in ["none", "expired"]:
        msg = "❌ Your premium plan has expired!" if status == "expired" else "❌ You don't have any active premium plan"
        return await query.message.edit(msg, reply_markup=buy_btn())
    await query.message.edit(myplan_text(data), reply_markup=myplan_buttons())


# ======================================================
# 🛠 ADMIN PREMIUM COMMANDS (PM)
#    The buttons of /admin → 💎 Premium point at these
#    commands, so they must stay in sync with that panel.
# ======================================================

def _admin_usage(cmd: str) -> str:
    return (
        f"❌ <b>Usage:</b> <code>/{cmd} user_id days</code>\n\n"
        f"Example: <code>/{cmd} 123456789 30</code>"
    )


@Client.on_message(
    filters.command(["addpremium", "extendpremium"]) & filters.private & filters.user(ADMINS)
)
async def admin_add_premium(client, message):
    """💎 /addpremium <user_id> <days> · /extendpremium <user_id> <days>"""
    cmd = message.command[0].lower()

    if len(message.command) < 3:
        return await message.reply(_admin_usage(cmd), parse_mode=enums.ParseMode.HTML)

    try:
        uid = int(message.command[1])
        days = int(message.command[2])
    except ValueError:
        return await message.reply("❌ <code>user_id</code> and <code>days</code> must be numbers.",
                                   parse_mode=enums.ParseMode.HTML)

    if days <= 0 or days > 3650:
        return await message.reply("❌ Days must be between <code>1</code> and <code>3650</code>.",
                                   parse_mode=enums.ParseMode.HTML)

    now = datetime.utcnow()
    old = await db.get_plan(uid) or {}

    old_expire = old.get("expire")
    old_expire_dt = get_expiry_datetime(old_expire) if old_expire else None

    # extend = add on top of a plan that is still running, add = start from now
    if cmd == "extendpremium" and old_expire_dt and old_expire_dt > now:
        expire_dt = old_expire_dt + timedelta(days=days)
        action = "Extended"
    else:
        expire_dt = now + timedelta(days=days)
        action = "Granted"

    plan_text = f"{days} Days (Admin)"
    invoice = {
        "id": gen_invoice_id(),
        "plan": plan_text,
        "amount": 0,
        "activated": fmt(now),
        "expire": fmt(expire_dt),
        "created_at": now.timestamp(),
        "by": "admin",
    }

    # NOTE: db.get_plan() returns a shallow copy of the default plan for a user
    #       without a document, so the list must be copied before appending.
    invoices = list(old.get("invoices") or [])
    invoices.append(invoice)

    await db.update_plan(uid, {
        "premium": True,
        "plan": plan_text,
        "expire": expire_dt.timestamp(),
        "activated_at": now.timestamp(),
        "invoices": invoices,
    })

    # Best-effort notice to the user (they may never have started the bot)
    try:
        await client.send_message(
            uid,
            f"🎉 <b>Premium {action}!</b>\n\n"
            f"💎 Plan: <b>{plan_text}</b>\n"
            f"⏰ Expires: <code>{fmt(expire_dt)}</code>\n\n"
            "Use /myplan to check your subscription.",
            parse_mode=enums.ParseMode.HTML,
        )
    except Exception:
        pass

    await message.reply(
        f"✅ <b>Premium {action}</b>\n\n"
        f"👤 User: <code>{uid}</code>\n"
        f"💎 Plan: <b>{plan_text}</b>\n"
        f"⏰ Expires: <code>{fmt(expire_dt)}</code>",
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.command("removepremium") & filters.private & filters.user(ADMINS))
async def admin_remove_premium(client, message):
    """🗑 /removepremium <user_id> — drop premium, keep the invoice history"""
    if len(message.command) < 2:
        return await message.reply(
            "❌ <b>Usage:</b> <code>/removepremium user_id</code>\n\n"
            "Example: <code>/removepremium 123456789</code>",
            parse_mode=enums.ParseMode.HTML,
        )

    try:
        uid = int(message.command[1])
    except ValueError:
        return await message.reply("❌ <code>user_id</code> must be a number.",
                                   parse_mode=enums.ParseMode.HTML)

    old = await db.get_plan(uid) or {}
    if not old.get("premium"):
        return await message.reply(
            f"ℹ️ <code>{uid}</code> has no active premium plan.",
            parse_mode=enums.ParseMode.HTML,
        )

    await db.update_plan(uid, {
        "premium": False,
        "plan": None,
        "expire": None,
        "activated_at": None,
        "invoices": list(old.get("invoices") or []),
    })

    try:
        await client.send_message(
            uid,
            "⚠️ <b>Premium Removed</b>\n\n"
            "Your premium subscription has been removed by an admin.\n"
            "Use /plan to buy a new plan.",
            parse_mode=enums.ParseMode.HTML,
        )
    except Exception:
        pass

    await message.reply(
        f"✅ <b>Premium removed</b>\n\n👤 User: <code>{uid}</code>",
        parse_mode=enums.ParseMode.HTML,
    )


# ======================================================
# 💰 BUY FLOW (HYDROGRAM COMPATIBLE - FIXED)
# ======================================================

@Client.on_callback_query(filters.regex("^buy_premium$"))
async def buy_premium(client, query: CallbackQuery):
    """Start premium purchase flow"""
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
        # ✅ FIXED: Hydrogram compatible listen() syntax
        msg = await client.listen(query.message.chat.id, timeout=LISTEN_SHORT)
        
        # ✅ FIXED: Manual user verification
        if msg.from_user.id != uid:
            active_sessions.pop(uid, None)
            await query.message.edit(
                "❌ Invalid response. Please try again.",
                reply_markup=buy_btn()
            )
            return
        
        if not msg.text:
            active_sessions.pop(uid, None)
            await query.message.edit(
                "❌ Please send a number\n\n💡 Example: `7` or `30`",
                reply_markup=buy_btn()
            )
            return
        
        num_str = "".join(filter(str.isdigit, msg.text))
        if not num_str:
            active_sessions.pop(uid, None)
            await query.message.edit(
                "❌ Invalid number\n\nPlease send only numbers like: `7` or `30`",
                reply_markup=buy_btn()
            )
            return
        
        num = int(num_str)
        if num <= 0 or num > 9999:
            active_sessions.pop(uid, None)
            await query.message.edit(
                "❌ Invalid number (1-9999)\n\nPlease send a number between 1 and 9999",
                reply_markup=buy_btn()
            )
            return
        
        active_sessions[uid] = {"step": "waiting_duration", "number": num}
        
        await query.message.edit(
            f"""
✅ Number: **{num}**

Now select your duration:
""",
            reply_markup=duration_buttons(num)
        )
    
    except asyncio.TimeoutError:
        active_sessions.pop(uid, None)
        return await query.message.edit("⏱️ Timeout! Payment cancelled.", reply_markup=buy_btn())
    except Exception as e:
        active_sessions.pop(uid, None)
        return await query.message.edit(
            f"❌ Error: {str(e)}\n\nPlease try again",
            reply_markup=buy_btn()
        )


@Client.on_callback_query(filters.regex("^dur#"))
async def duration_selected(client, query: CallbackQuery):
    """Handle duration selection"""
    uid = query.from_user.id
    
    if uid not in active_sessions:
        return await query.answer("⚠️ Session expired. Please start again.", show_alert=True)
    
    try:
        _, num_str, unit = query.data.split("#")
        num = int(num_str)
    except:
        return await query.answer("❌ Invalid data", show_alert=True)
    
    unit_map = {
        "hour": "Hours",
        "day": "Days",
        "month": "Months",
        "year": "Years"
    }
    
    unit_display = unit_map.get(unit, unit)
    plan_text = f"{num} {unit_display}"
    
    # Calculate the duration in days (price and plan both come from here)
    if unit == "hour":
        days = max(1, (num // 24) or 1)
    elif unit == "day":
        days = num
    elif unit == "month":
        days = 30 * num
    elif unit == "year":
        days = 365 * num
    else:
        return await query.answer("❌ Invalid unit", show_alert=True)
    
    amount = days * PRE_DAY_AMOUNT
    
    active_sessions[uid] = {
        "step": "waiting_screenshot",
        "plan_text": plan_text,
        "amount": amount,
        "days": days
    }
    
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
        active_sessions.pop(uid, None)
        return await query.answer(f"❌ Error: {str(e)}", show_alert=True)
    
    # ✅ FIXED: Hydrogram compatible listen() for screenshot
    try:
        # ✅ FIXED: Correct syntax without filters parameter
        receipt = await client.listen(
            query.message.chat.id, 
            timeout=LISTEN_LONG
        )
        
        # ✅ FIXED: Manual verification for user and photo
        if receipt.from_user.id != uid:
            active_sessions.pop(uid, None)
            await query.message.reply(
                "❌ Invalid response. Please try again.",
                reply_markup=buy_btn()
            )
            return
        
        if not receipt.photo:
            active_sessions.pop(uid, None)
            await query.message.reply(
                "❌ Screenshot not received. Please send a photo.",
                reply_markup=buy_btn()
            )
            return
    
    except asyncio.TimeoutError:
        active_sessions.pop(uid, None)
        return await query.message.reply(
            "⏱️ Timeout! Screenshot not received. Payment cancelled.",
            reply_markup=buy_btn()
        )
    except Exception as e:
        active_sessions.pop(uid, None)
        return await query.message.reply(
            f"❌ Error: {str(e)}",
            reply_markup=buy_btn()
        )
    
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
        active_sessions.pop(uid, None)
        return await receipt.reply(
            f"❌ Error sending to admin: {str(e)}",
            reply_markup=buy_btn()
        )
    
    await receipt.reply("✅ **Screenshot received!**\n\n⏳ Your payment is being reviewed by admin.\nYou'll be notified once approved.")
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
    duration = parse_duration(plan_txt)
    if not duration:
        return False
    
    now = datetime.utcnow()
    old = await db.get_plan(uid) or {}
    
    if duration.days == 0 and duration.seconds > 0:
        days = max(1, (duration.seconds // 3600) // 24 + 1)
        duration = timedelta(days=days)
    
    expire = old.get("expire")
    if expire:
        expire_dt = get_expiry_datetime(expire)
        expire_dt = expire_dt + duration if expire_dt > now else now + duration
    else:
        expire_dt = now + duration
    
    invoice = {
        "id": gen_invoice_id(),
        "plan": plan_txt,
        "amount": amount,
        "activated": fmt(now),
        "expire": fmt(expire_dt),
        "created_at": now.timestamp()
    }
    
    # NOTE: get_plan() returns a shallow copy of the default plan for a user
    #       without a document — copy the list so the default stays empty.
    invoices = list(old.get("invoices") or [])
    invoices.append(invoice)
    
    await db.update_plan(uid, {
        "premium": True,
        "plan": plan_txt,
        "expire": expire_dt.timestamp(),
        "activated_at": now.timestamp(),
        "invoices": invoices
    })
    
    return expire_dt, invoice


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
    
    try:
        await client.send_message(
            uid,
            f"""
🎉 **Premium Activated Successfully!**

💎 **Plan:** {plan_txt}
⏰ **Valid Till:** {fmt(expire_dt)}
🧾 **Invoice ID:** `{invoice['id']}`

Thank you for your purchase! 🙏
Enjoy your premium benefits! ✨
"""
        )
    except:
        pass
    
    await query.message.edit_caption(
        query.message.caption + f"\n\n✅ **APPROVED** by @{query.from_user.username}\n⏰ {fmt(datetime.utcnow())}"
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
    
    try:
        await client.send_message(
            uid,
            """
❌ **Payment Rejected**

Your payment screenshot was rejected by admin.
Please contact support or try again with correct details.
"""
        )
    except:
        pass
    
    await query.message.edit_caption(
        query.message.caption + f"\n\n❌ **REJECTED** by @{query.from_user.username}\n⏰ {fmt(datetime.utcnow())}"
    )
    await query.answer("❌ Payment Rejected", show_alert=True)
