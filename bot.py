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
TOKEN = os.environ.get("TOKEN")  # or "PASTE_YOUR_TOKEN_HERE"
CHANNEL_ID = -1003833257976
CRYPTO_WALLET = "LTC1qv4u6vr0gzp9g4lq0g3qev939vdnwxghn5gtnfc"

ADMINS = set()
orders = {}
sessions = {}
REVIEWS = []  # stores dicts: {"user_id":..., "product_key":..., "stars":..., "text":...}
CONTACT_SESSIONS = {}  # for handling user/admin contact/review sessions

# ===== PRODUCTS AND PRICES =====
PRODUCTS = {
    "lcg": "Lemon Cherry Gelato",
    "dawg": "Dawg",
    "cherry": "Cherry Punch",
}

PRICES = {
    "lcg": {"3.5": 30, "7": 50, "14": 80, "28": 150, "56": 270},
    "dawg": {"3.5": 30, "7": 50, "14": 80, "28": 150, "56": 270},
    "cherry": {"3.5": 30, "7": 50, "14": 80, "28": 150, "56": 270},
}

# ================= MENU =================
def main_menu():
    buttons = [
        [InlineKeyboardButton(f"{name}", callback_data=f"prod_{key}")]
        for key, name in PRODUCTS.items()
    ]
    buttons.append([InlineKeyboardButton("⭐ Reviews", callback_data="view_reviews")])
    buttons.append([InlineKeyboardButton("📞 Contact Support", callback_data="contact_support")])
    return InlineKeyboardMarkup(buttons)

# ================= START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🌿 Welcome to Donny’s Herbal & Wellness Shop\n\nSelect a product:",
        reply_markup=main_menu()
    )

# ================= CANCEL =================
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sessions.pop(update.effective_user.id, None)
    await update.message.reply_text(
        "❌ Action cancelled.\nBack to main menu:",
        reply_markup=main_menu()
    )

# ================= PRODUCT FLOW =================
async def product_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    key = q.data.replace("prod_", "")
    if key not in PRODUCTS:
        await q.edit_message_text("❌ Product not found.")
        return

    sessions[q.from_user.id] = {"product_key": key, "product": PRODUCTS[key], "step": "qty"}
    buttons = [
        [InlineKeyboardButton(f"{g}g (£{PRICES[key][g]})", callback_data=f"qty_{g}")]
        for g in PRICES[key]
    ]
    buttons.append([InlineKeyboardButton("⬅ Back", callback_data="back")])
    await q.edit_message_text(f"🛒 {PRODUCTS[key]}\nChoose quantity:", reply_markup=InlineKeyboardMarkup(buttons))

async def quantity_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    qty = q.data.replace("qty_", "")
    s = sessions[q.from_user.id]
    s["qty"] = qty
    s["price"] = PRICES[s["product_key"]][qty]
    s["step"] = "name"
    await q.edit_message_text("✍️ Send your FULL NAME:")

# ================= TEXT INPUT =================
async def text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    s = sessions.get(uid)
    if not s:
        # handle admin text sessions
        admin_session = sessions.get(uid)
        if admin_session:
            await handle_admin_text(update, context, admin_session)
        # handle contact/review text
        await handle_contact(update, context)
        await handle_review_text(update, context)
        return

    if s["step"] == "name":
        s["name"] = update.message.text
        s["step"] = "address"
        await update.message.reply_text("📍 Send your FULL ADDRESS:")
        return

    if s["step"] == "address":
        s["address"] = update.message.text
        order_id = random.randint(100000, 999999)
        orders[order_id] = {"user_id": uid, "status": "Pending payment", **s}

        summary = (
            f"✅ *ORDER SUMMARY*\n\n"
            f"Order #: {order_id}\n"
            f"Product: {s['product']}\n"
            f"Qty: {s['qty']}g\n"
            f"Name: {s['name']}\n"
            f"Address: {s['address']}\n\n"
            f"💰 Amount to pay: *£{s['price']}*\n"
            f"💳 *LTC ONLY*\n`{CRYPTO_WALLET}`"
        )
        buttons = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ I HAVE PAID", callback_data=f"paid_{order_id}")],
            [InlineKeyboardButton("⭐ Leave Review", callback_data=f"review_{order_id}")],
            [InlineKeyboardButton("⬅ Back to Menu", callback_data="back")]
        ])
        await update.message.reply_text(summary, parse_mode="Markdown", reply_markup=buttons)

        # Admin notification
        admin_msg = (
            f"🆕 *NEW ORDER #{order_id}*\n\n"
            f"{s['product']} – {s['qty']}g\n"
            f"£{s['price']}\n\n"
            f"👤 {s['name']}\n📍 {s['address']}"
        )
        await context.bot.send_message(CHANNEL_ID, admin_msg, parse_mode="Markdown")
        sessions.pop(uid)

# ================= USER PAID =================
async def user_paid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    oid = int(q.data.replace("paid_", ""))
    o = orders[oid]
    o["status"] = "Paid – awaiting dispatch"
    text = (
        f"✅ *PAYMENT MARKED*\n\n"
        f"Order #: {oid}\n"
        f"{o['product']} – {o['qty']}g\n\n"
        f"💰 Amount: *£{o['price']}*\n"
        f"💳 LTC Address:\n`{CRYPTO_WALLET}`\n\n"
        f"Status: *{o['status']}*"
    )
    await q.edit_message_text(text, parse_mode="Markdown")

# ================= PROMPT REVIEW =================
async def prompt_review(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    order_id = int(q.data.replace("review_", ""))
    uid = q.from_user.id
    CONTACT_SESSIONS[uid] = {"step": "review", "order_id": order_id}
    await q.edit_message_text("✨ Please leave a review for your order. Send number of stars (1-5):")

# ================= VIEW REVIEWS =================
async def view_reviews(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not REVIEWS:
        text = "⭐ No reviews yet."
    else:
        text = "⭐ Reviews:\n\n"
        for r in REVIEWS[-10:]:
            text += f"{PRODUCTS.get(r['product_key'], r['product_key'])} - {r['stars']}★\n"
            text += f"{r['text']}\n\n"
    buttons = [[InlineKeyboardButton("⬅ Back", callback_data="back")]]
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons))

# ================= CONTACT SUPPORT =================
async def contact_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    CONTACT_SESSIONS[uid] = {"step": "contact_user"}
    await q.edit_message_text("📩 Send your message for support:")

# ================= HANDLE CONTACT =================
async def handle_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    session = CONTACT_SESSIONS.get(uid)
    if not session:
        return

    if session.get("step") == "contact_user":
        msg = update.message.text
        CONTACT_SESSIONS[uid] = {"step": "await_admin_reply", "last_msg": msg}
        await context.bot.send_message(CHANNEL_ID, f"📨 Message from @{update.message.from_user.username or uid}:\n{msg}")
        await update.message.reply_text("✅ Message sent to admin.", reply_markup=main_menu())

# ================= HANDLE REVIEW TEXT =================
async def handle_review_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    session = CONTACT_SESSIONS.get(uid)
    if not session or session.get("step") != "review":
        return

    order_id = session["order_id"]
    order = orders.get(order_id)
    if not order:
        CONTACT_SESSIONS.pop(uid)
        return

    text = update.message.text
    if "stars" not in session:
        try:
            stars = int(text)
            if stars < 1 or stars > 5:
                raise ValueError
            session["stars"] = stars
            await update.message.reply_text("Optional: Send text feedback or type /skip")
        except:
            await update.message.reply_text("❌ Please send a number between 1 and 5.")
    else:
        REVIEWS.append({"user_id": uid, "product_key": order["product_key"], "stars": session["stars"], "text": text})
        CONTACT_SESSIONS.pop(uid)
        await update.message.reply_text("✅ Thank you for your review!", reply_markup=main_menu())

# ================= BACK =================
async def back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text("Main menu:", reply_markup=main_menu())

# ================= ADMIN PANEL =================
async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not ADMINS:
        ADMINS.add(uid)
        await update.message.reply_text(f"✅ You are now the main admin.\nID: `{uid}`", parse_mode="Markdown")
    if uid not in ADMINS:
        await update.message.reply_text("❌ Not authorised.")
        return
    buttons = [
        [InlineKeyboardButton("📦 View Orders", callback_data="admin_view_orders")],
        [InlineKeyboardButton("🛠 Manage Products", callback_data="admin_manage_products")]
    ]
    await update.message.reply_text("🛠 *ADMIN PANEL*", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))

# ================= RUN BOT =================
app = ApplicationBuilder().token(TOKEN).build()

# Command handlers
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("admin", admin))
app.add_handler(CommandHandler("cancel", cancel))

# Product flow
app.add_handler(CallbackQueryHandler(product_select, pattern="^prod_"))
app.add_handler(CallbackQueryHandler(quantity_select, pattern="^qty_"))
app.add_handler(CallbackQueryHandler(user_paid, pattern="^paid_"))
app.add_handler(CallbackQueryHandler(prompt_review, pattern="^review_"))
app.add_handler(CallbackQueryHandler(view_reviews, pattern="view_reviews"))
app.add_handler(CallbackQueryHandler(contact_support, pattern="contact_support"))
app.add_handler(CallbackQueryHandler(back, pattern="^back$"))

# Messages
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_input))

print("✅ BOT RUNNING")
app.run_polling()
