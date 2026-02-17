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

CHANNEL_ID = -1003833257976  # admin notification channel
CRYPTO_WALLET = "LTC1qv4u6vr0gzp9g4lq0g3qev939vdnwxghn5gtnfc"

ADMINS = set()  # auto-filled on first /admin
# ==========================================

# In-memory storage
orders = {}
user_sessions = {}

# Products & pricing
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

# ============== MAIN MENU =================
def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🍋 Lemon Cherry Gelato", callback_data="prod_lcg")],
        [InlineKeyboardButton("🐕 Dawg", callback_data="prod_dawg")],
        [InlineKeyboardButton("🍒 Cherry Punch", callback_data="prod_cherry")],
    ])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome to Donny’s Shop\n\nSelect a product to begin:",
        reply_markup=main_menu()
    )

# ============== PRODUCT FLOW ==============
async def product_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    product_key = query.data.replace("prod_", "")
    user_sessions[query.from_user.id] = {"product": PRODUCTS[product_key]}

    buttons = [[InlineKeyboardButton(f"{q}g (£{PRICES[q]})", callback_data=f"qty_{q}")]
               for q in PRICES]
    buttons.append([InlineKeyboardButton("⬅ Back", callback_data="back_main")])

    await query.edit_message_text(
        f"🛒 {PRODUCTS[product_key]}\n\nChoose quantity:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def quantity_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    qty = query.data.replace("qty_", "")
    session = user_sessions[query.from_user.id]
    session["quantity"] = qty
    session["price"] = PRICES[qty]

    await query.edit_message_text("✍️ Send your FULL NAME:")
    session["step"] = "name"

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    session = user_sessions.get(user_id)

    if not session:
        return

    if session.get("step") == "name":
        session["name"] = update.message.text
        session["step"] = "address"
        await update.message.reply_text("📍 Send your FULL ADDRESS:")
        return

    if session.get("step") == "address":
        session["address"] = update.message.text

        order_id = random.randint(100000, 999999)
        session["order_id"] = order_id
        session["status"] = "Pending"

        orders[order_id] = {
            "user_id": user_id,
            **session
        }

        summary = (
            f"✅ *ORDER SUMMARY*\n\n"
            f"Order #: {order_id}\n"
            f"Product: {session['product']}\n"
            f"Qty: {session['quantity']}g\n"
            f"Name: {session['name']}\n"
            f"Address: {session['address']}\n\n"
            f"💰 Amount: £{session['price']}\n"
            f"⏳ Pay within 3 hours\n\n"
            f"💳 *LTC ONLY*\n`{CRYPTO_WALLET}`"
        )

        buttons = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ I HAVE PAID", callback_data=f"paid_{order_id}")],
            [InlineKeyboardButton("⬅ Back to Menu", callback_data="back_main")]
        ])

        await update.message.reply_text(summary, parse_mode="Markdown", reply_markup=buttons)

        await context.bot.send_message(
            CHANNEL_ID,
            f"🆕 *NEW ORDER*\n\nOrder #{order_id}\n{session['product']} {session['quantity']}g\n£{session['price']}",
            parse_mode="Markdown"
        )

        user_sessions.pop(user_id)

# ============== USER CONFIRM ===============
async def paid_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    order_id = int(query.data.replace("paid_", ""))
    orders[order_id]["status"] = "Paid – awaiting dispatch"

    await query.edit_message_text(
        "✅ Payment noted.\nStatus: *Paid – awaiting dispatch*",
        parse_mode="Markdown"
    )

# ============== ADMIN PANEL =================
async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if not ADMINS:
        ADMINS.add(user_id)
        await update.message.reply_text(f"✅ You are now the main admin.\nYour ID: `{user_id}`", parse_mode="Markdown")

    if user_id not in ADMINS:
        await update.message.reply_text(f"❌ Not authorised.\nYour ID: `{user_id}`", parse_mode="Markdown")
        return

    buttons = []
    for oid, data in orders.items():
        buttons.append([
            InlineKeyboardButton(
                f"#{oid} – {data['status']}",
                callback_data=f"admin_{oid}"
            )
        ])

    await update.message.reply_text(
        "🛠 *ADMIN PANEL*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def admin_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    oid = int(query.data.replace("admin_", ""))
    order = orders[oid]

    text = (
        f"📦 *ORDER #{oid}*\n\n"
        f"{order['product']} {order['quantity']}g\n"
        f"£{order['price']}\n\n"
        f"{order['name']}\n{order['address']}\n\n"
        f"Status: {order['status']}"
    )

    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 Mark Paid", callback_data=f"mark_paid_{oid}")],
        [InlineKeyboardButton("🚚 Mark Dispatched", callback_data=f"mark_sent_{oid}")]
    ])

    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=buttons)

async def admin_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    action, oid = query.data.split("_", 1)
    oid = int(oid)

    if action == "mark_paid":
        orders[oid]["status"] = "Paid"
    elif action == "mark_sent":
        orders[oid]["status"] = "Dispatched"

    user_id = orders[oid]["user_id"]
    await context.bot.send_message(
        user_id,
        f"📦 Order #{oid} update:\nStatus: *{orders[oid]['status']}*",
        parse_mode="Markdown"
    )

    await query.edit_message_text("✅ Updated.")

# ============== BACK BUTTON =================
async def back_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Main menu:", reply_markup=main_menu())

# ============== APP =========================
app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("admin", admin))

app.add_handler(CallbackQueryHandler(product_handler, pattern="^prod_"))
app.add_handler(CallbackQueryHandler(quantity_handler, pattern="^qty_"))
app.add_handler(CallbackQueryHandler(paid_handler, pattern="^paid_"))
app.add_handler(CallbackQueryHandler(admin_order, pattern="^admin_"))
app.add_handler(CallbackQueryHandler(admin_update, pattern="^mark_"))
app.add_handler(CallbackQueryHandler(back_main, pattern="^back_main$"))

app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

print("✅ BOT RUNNING")
app.run_polling()
