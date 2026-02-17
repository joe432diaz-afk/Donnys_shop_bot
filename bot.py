import logging
import uuid
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)

# =======================
# 🔧 CONFIG – EDIT THESE
# =======================
BOT_TOKEN = "8383232415:AAGDzTvKSird6CCg4NyXHnwpim4KN6q24WQ "

ADMIN_IDS = {
    1003833257976,   # main admin
    # add more admin IDs here
}

LTC_ADDRESS = "ltc1qv4u6vr0gzp9g4lq0g3qev939vdnwxghn5gtnfc"

# =======================
logging.basicConfig(level=logging.INFO)

# In‑memory storage (phase‑1 stable)
USERS = {}
ORDERS = {}
REVIEWS = []
PRODUCTS = {
    "lemon_cherry_gelato": {
        "name": "Lemon Cherry Gelato",
        "desc": "Premium herbal flower – calming, aromatic, wellness focused.",
        "prices": {3.5: 30, 7: 50, 14: 80, 28: 150, 56: 270},
        "photo": None
    },
    "dawg": {
        "name": "Dawg",
        "desc": "Earthy herbal blend used traditionally for relaxation.",
        "prices": {3.5: 30, 7: 50, 14: 80},
        "photo": None
    },
    "cherry_punch": {
        "name": "Cherry Punch",
        "desc": "Sweet botanical infusion with spiritual grounding effects.",
        "prices": {3.5: 30, 7: 50, 14: 80},
        "photo": None
    }
}

# =======================
# 🏁 START / MAIN MENU
# =======================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    USERS.setdefault(uid, {"basket": {}, "state": None})

    text = (
        "🌿 **Welcome to Donny’s Herbal Wellness Store** 🌿\n\n"
        "We specialise in ethically sourced herbal teas, botanical supplements "
        "and spiritual wellness essentials.\n\n"
        "✨ Natural • Discreet • Trusted ✨"
    )

    keyboard = [
        [InlineKeyboardButton("🛍 Browse Products", callback_data="browse")],
        [InlineKeyboardButton("🧺 Basket", callback_data="basket")],
        [InlineKeyboardButton("⭐ Reviews", callback_data="reviews")],
        [InlineKeyboardButton("📞 Contact Support", callback_data="contact")]
    ]

    await update.message.reply_text(
        text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
    )

# =======================
# 🛍 PRODUCTS
# =======================
async def browse(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    buttons = [
        [InlineKeyboardButton(p["name"], callback_data=f"product:{k}")]
        for k, p in PRODUCTS.items()
    ]
    buttons.append([InlineKeyboardButton("⬅ Back", callback_data="main")])

    await q.edit_message_text(
        "🛍 **Our Herbal Products**",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown"
    )

async def product_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    pid = q.data.split(":")[1]
    p = PRODUCTS[pid]

    text = f"*{p['name']}*\n\n{p['desc']}\n\nSelect weight:"

    buttons = [
        [InlineKeyboardButton(f"{w}g – £{price}", callback_data=f"add:{pid}:{w}")]
        for w, price in p["prices"].items()
    ]
    buttons.append([InlineKeyboardButton("⬅ Back", callback_data="browse")])

    await q.edit_message_text(
        text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown"
    )

# =======================
# 🧺 BASKET
# =======================
async def add_to_basket(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    _, pid, weight = q.data.split(":")
    weight = float(weight)

    basket = USERS[uid]["basket"]
    basket.setdefault((pid, weight), 0)
    basket[(pid, weight)] += 1

    await q.edit_message_text("✅ Added to basket.", reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("🧺 View Basket", callback_data="basket")],
        [InlineKeyboardButton("⬅ Back", callback_data="browse")]
    ]))

async def basket(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    basket = USERS[uid]["basket"]

    if not basket:
        await q.edit_message_text("🧺 Your basket is empty.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅ Back", callback_data="main")]]))
        return

    total = 0
    lines = []
    for (pid, w), qty in basket.items():
        price = PRODUCTS[pid]["prices"][w] * qty
        total += price
        lines.append(f"{PRODUCTS[pid]['name']} {w}g × {qty} = £{price}")

    text = "🧺 **Your Basket**\n\n" + "\n".join(lines) + f"\n\n**Total: £{total}**"

    await q.edit_message_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Checkout", callback_data="checkout")],
            [InlineKeyboardButton("⬅ Back", callback_data="main")]
        ])
    )

# =======================
# 💳 CHECKOUT
# =======================
async def checkout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    USERS[q.from_user.id]["state"] = "name"
    await q.edit_message_text("Please enter your **full name**:")

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    state = USERS.get(uid, {}).get("state")

    if state == "name":
        USERS[uid]["name"] = update.message.text
        USERS[uid]["state"] = "address"
        await update.message.reply_text("Enter your **delivery address**:")
        return

    if state == "address":
        USERS[uid]["address"] = update.message.text
        USERS[uid]["state"] = None
        await create_order(update, context)

async def create_order(update, context):
    uid = update.effective_user.id
    order_id = str(uuid.uuid4())[:8]
    basket = USERS[uid]["basket"]

    total = sum(PRODUCTS[p]["prices"][w] * q for (p, w), q in basket.items())

    ORDERS[order_id] = {
        "user": uid,
        "name": USERS[uid]["name"],
        "address": USERS[uid]["address"],
        "basket": basket.copy(),
        "total": total,
        "status": "Pending"
    }

    USERS[uid]["basket"] = {}

    text = (
        f"🧾 **Order #{order_id}**\n\n"
        f"Amount to pay: **£{total}**\n\n"
        f"💳 **LTC ONLY**\n"
        f"`{LTC_ADDRESS}`\n\n"
        "⏳ Processing time: ~3 hours\n\n"
        "After payment, wait for admin confirmation."
    )

    await update.message.reply_text(text, parse_mode="Markdown")

    # Notify admins
    for admin in ADMIN_IDS:
        await context.bot.send_message(
            admin,
            f"🆕 New Order #{order_id}\nName: {ORDERS[order_id]['name']}\n"
            f"Address: {ORDERS[order_id]['address']}\nTotal: £{total}"
        )

# =======================
# 🛠 ADMIN PANEL
# =======================
async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in ADMIN_IDS:
        return

    buttons = [
        [InlineKeyboardButton("📦 View Orders", callback_data="admin_orders")],
    ]

    await update.message.reply_text(
        "🛠 **Admin Panel**",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown"
    )

async def admin_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    buttons = [
        [InlineKeyboardButton(
            f"{oid} – {o['status']}",
            callback_data=f"admin_order:{oid}"
        )] for oid, o in ORDERS.items()
    ]

    await q.edit_message_text(
        "📦 Orders",
        reply_markup=InlineKeyboardMarkup(buttons or [[InlineKeyboardButton("No orders", callback_data="noop")]])
    )

async def admin_order_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    oid = q.data.split(":")[1]
    o = ORDERS[oid]

    text = (
        f"🧾 Order #{oid}\n\n"
        f"Name: {o['name']}\n"
        f"Address: {o['address']}\n"
        f"Total: £{o['total']}\n"
        f"Status: {o['status']}"
    )

    await q.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Mark Paid", callback_data=f"paid:{oid}")],
            [InlineKeyboardButton("📦 Mark Dispatched", callback_data=f"sent:{oid}")]
        ])
    )

async def set_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    action, oid = q.data.split(":")
    o = ORDERS[oid]

    if action == "paid":
        o["status"] = "Paid"
        await context.bot.send_message(o["user"], f"✅ Order #{oid} marked as PAID.")
    else:
        o["status"] = "Dispatched"
        await context.bot.send_message(o["user"], f"📦 Order #{oid} has been DISPATCHED.")

    await admin_orders(update, context)

# =======================
# 🚀 RUN
# =======================
app = ApplicationBuilder().token(BOT_TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("admin", admin))
app.add_handler(CallbackQueryHandler(browse, pattern="^browse$"))
app.add_handler(CallbackQueryHandler(product_view, pattern="^product:"))
app.add_handler(CallbackQueryHandler(add_to_basket, pattern="^add:"))
app.add_handler(CallbackQueryHandler(basket, pattern="^basket$"))
app.add_handler(CallbackQueryHandler(checkout, pattern="^checkout$"))
app.add_handler(CallbackQueryHandler(admin_orders, pattern="^admin_orders$"))
app.add_handler(CallbackQueryHandler(admin_order_view, pattern="^admin_order:"))
app.add_handler(CallbackQueryHandler(set_status, pattern="^(paid|sent):"))
app.add_handler(CallbackQueryHandler(start, pattern="^main$"))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

app.run_polling()
