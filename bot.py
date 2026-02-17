import os
import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ================= CONFIG =================
TOKEN = os.environ.get("TOKEN")
CHANNEL_ID = -1003833257976
CRYPTO_WALLET = "LTC1qv4u6vr0gzp9g4lq0g3qev939vdnwxghn5gtnfc"

ADMINS = set()
orders = {}
sessions = {}

PRODUCTS = {
    "lcg": "Lemon Cherry Gelato",
    "dawg": "Dawg",
    "cherry": "Cherry Punch",
}

PRICES = {
    "3.5": 30,
    "7": 50,
    "14": 80,
    "28": 150,
    "56": 270,
}

# ============== MENUS =================
def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🍋 Lemon Cherry Gelato", callback_data="prod_lcg")],
        [InlineKeyboardButton("🐕 Dawg", callback_data="prod_dawg")],
        [InlineKeyboardButton("🍒 Cherry Punch", callback_data="prod_cherry")],
    ])

# ============== START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome to Donny’s Shop\n\nSelect a product:",
        reply_markup=main_menu()
    )

# ============== CANCEL (SAFETY) =================
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sessions.pop(update.effective_user.id, None)
    await update.message.reply_text(
        "❌ Action cancelled.\nBack to main menu:",
        reply_markup=main_menu()
    )

# ============== PRODUCT =================
async def product_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    key = q.data.replace("prod_", "")
    sessions[q.from_user.id] = {
        "product": PRODUCTS[key],
        "step": "qty"
    }

    buttons = [[InlineKeyboardButton(f"{g}g (£{PRICES[g]})", callback_data=f"qty_{g}")]
               for g in PRICES]
    buttons.append([InlineKeyboardButton("⬅ Back", callback_data="back")])

    await q.edit_message_text(
        f"🛒 {PRODUCTS[key]}\nChoose quantity:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def quantity_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    qty = q.data.replace("qty_", "")
    s = sessions[q.from_user.id]
    s["qty"] = qty
    s["price"] = PRICES[qty]
    s["step"] = "name"

    await q.edit_message_text("✍️ Send your FULL NAME:")

# ============== TEXT FLOW =================
async def text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    s = sessions.get(uid)
    if not s:
        return

    if s["step"] == "name":
        s["name"] = update.message.text
        s["step"] = "address"
        await update.message.reply_text("📍 Send your FULL ADDRESS:")
        return

    if s["step"] == "address":
        s["address"] = update.message.text
        order_id = random.randint(100000, 999999)

        orders[order_id] = {
            "user_id": uid,
            "status": "Pending",
            **s
        }

        print("ORDER CREATED:", order_id)

        summary = (
            f"✅ *ORDER SUMMARY*\n\n"
            f"Order #: {order_id}\n"
            f"Product: {s['product']}\n"
            f"Qty: {s['qty']}g\n"
            f"Name: {s['name']}\n"
            f"Address: {s['address']}\n\n"
            f"💰 Amount: £{s['price']}\n"
            f"⏳ Pay within 3 hours\n\n"
            f"💳 *LTC ONLY*\n`{CRYPTO_WALLET}`"
        )

        buttons = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ I HAVE PAID", callback_data=f"paid_{order_id}")],
            [InlineKeyboardButton("⬅ Back to Menu", callback_data="back")]
        ])

        await update.message.reply_text(summary, parse_mode="Markdown", reply_markup=buttons)

        await context.bot.send_message(
            CHANNEL_ID,
            f"🆕 NEW ORDER #{order_id}\n{s['product']} {s['qty']}g\n£{s['price']}"
        )

        sessions.pop(uid)

# ============== USER PAID =================
async def user_paid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    oid = int(q.data.replace("paid_", ""))
    orders[oid]["status"] = "Paid – awaiting dispatch"

    await q.edit_message_text(
        "✅ Payment noted.\nStatus: *Paid – awaiting dispatch*",
        parse_mode="Markdown"
    )

# ============== ADMIN =================
async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id

    if not ADMINS:
        ADMINS.add(uid)
        await update.message.reply_text(
            f"✅ You are now the main admin.\nYour ID: `{uid}`",
            parse_mode="Markdown"
        )

    if uid not in ADMINS:
        await update.message.reply_text("❌ Not authorised.")
        return

    if not orders:
        await update.message.reply_text("🛠 Admin Panel\n\nNo orders yet.")
        return

    buttons = [[InlineKeyboardButton(f"#{oid} – {o['status']}", callback_data=f"admin_{oid}")]
               for oid, o in orders.items()]

    await update.message.reply_text(
        "🛠 *ADMIN PANEL*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def admin_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    oid = int(q.data.replace("admin_", ""))
    o = orders[oid]

    text = (
        f"📦 *ORDER #{oid}*\n\n"
        f"{o['product']} {o['qty']}g\n"
        f"£{o['price']}\n\n"
        f"{o['name']}\n{o['address']}\n\n"
        f"Status: {o['status']}"
    )

    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 Mark Paid", callback_data=f"mark_paid_{oid}")],
        [InlineKeyboardButton("🚚 Mark Dispatched", callback_data=f"mark_sent_{oid}")]
    ])

    await q.edit_message_text(text, parse_mode="Markdown", reply_markup=buttons)

async def admin_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    action, oid = q.data.rsplit("_", 1)
    oid = int(oid)

    if action == "mark_paid":
        orders[oid]["status"] = "Paid"
    elif action == "mark_sent":
        orders[oid]["status"] = "Dispatched"

    print("ADMIN UPDATE:", action, oid)

    await context.bot.send_message(
        orders[oid]["user_id"],
        f"📦 Order #{oid} status update:\n*{orders[oid]['status']}*",
        parse_mode="Markdown"
    )

    await context.bot.send_message(
        CHANNEL_ID,
        f"✅ Order #{oid} marked as {orders[oid]['status']}"
    )

    await q.edit_message_text("✅ Status updated.")

# ============== BACK =================
async def back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text("Main menu:", reply_markup=main_menu())

# ============== APP =================
app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("admin", admin))
app.add_handler(CommandHandler("cancel", cancel))

app.add_handler(CallbackQueryHandler(product_select, pattern="^prod_"))
app.add_handler(CallbackQueryHandler(quantity_select, pattern="^qty_"))
app.add_handler(CallbackQueryHandler(user_paid, pattern="^paid_"))
app.add_handler(CallbackQueryHandler(admin_order, pattern="^admin_"))
app.add_handler(CallbackQueryHandler(admin_update, pattern="^mark_"))
app.add_handler(CallbackQueryHandler(back, pattern="^back$"))

app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_input))

print("✅ BOT RUNNING")
app.run_polling()
