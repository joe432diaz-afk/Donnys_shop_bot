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
TOKEN = os.environ.get("TOKEN")  # or paste your token
CHANNEL_ID = -1003833257976
CRYPTO_WALLET = "LTC1qv4u6vr0gzp9g4lq0g3qev939vdnwxghn5gtnfc"

ADMINS = set()
orders = {}            # order_id -> order dict
sessions = {}          # user_id -> session dict
CONTACT_SESSIONS = {}  # user_id -> review/contact session dict
REVIEWS = []           # list of reviews

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
    buttons = [[InlineKeyboardButton(name, callback_data=f"prod_{key}")] for key, name in PRODUCTS.items()]
    buttons.append([InlineKeyboardButton("⭐ Reviews", callback_data="view_reviews")])
    buttons.append([InlineKeyboardButton("📦 My Orders", callback_data="my_orders")])
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
    CONTACT_SESSIONS.pop(update.effective_user.id, None)
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
    buttons = [[InlineKeyboardButton(f"{g}g (£{PRICES[key][g]})", callback_data=f"qty_{g}")] for g in PRICES[key]]
    buttons.append([InlineKeyboardButton("⬅ Back", callback_data="back")])
    await q.edit_message_text(f"🛒 {PRODUCTS[key]}\nChoose quantity:", reply_markup=InlineKeyboardMarkup(buttons))

async def quantity_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    s = sessions.get(q.from_user.id)
    if not s:
        await q.edit_message_text("❌ Session expired. Please start again.", reply_markup=main_menu())
        return
    qty = q.data.replace("qty_", "")
    s["qty"] = qty
    s["price"] = PRICES[s["product_key"]][qty]
    s["step"] = "name"
    await q.edit_message_text("✍️ Send your FULL NAME:")

# ================= TEXT INPUT =================
async def text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    s = sessions.get(uid)

    # Handle contact/review session
    contact = CONTACT_SESSIONS.get(uid)
    if contact:
        if contact.get("step") == "review":
            await handle_review_text(update, context)
        elif contact.get("step") in ["contact_user", "await_admin_reply"]:
            await handle_contact(update, context)
        return

    if not s:
        await update.message.reply_text("❌ No active session. Back to main menu.", reply_markup=main_menu())
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
            [InlineKeyboardButton("⭐ Leave/Edit Review", callback_data=f"review_{order_id}")],
            [InlineKeyboardButton("⬅ Back to Menu", callback_data="back")]
        ])

        await update.message.reply_text(summary, parse_mode="Markdown", reply_markup=buttons)

        # Notify admin
        admin_msg = (
            f"🆕 *NEW ORDER #{order_id}*\n\n"
            f"{s['product']} – {s['qty']}g\n£{s['price']}\n\n"
            f"👤 {s['name']}\n📍 {s['address']}"
        )
        await context.bot.send_message(CHANNEL_ID, admin_msg, parse_mode="Markdown")
        sessions.pop(uid)

# ================= VIEW USER ORDERS =================
async def my_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    user_orders = {oid: o for oid, o in orders.items() if o["user_id"] == uid}

    if not user_orders:
        await q.edit_message_text("📦 You have no past orders.", reply_markup=main_menu())
        return

    text = "📦 Your Orders:\n\n"
    buttons = []
    for oid, o in user_orders.items():
        review = next((r for r in REVIEWS if r["user_id"] == uid and r["product_key"] == o["product_key"]), None)
        review_text = f"⭐ {review['stars']}★" if review else "No review"
        text += f"#{oid} - {o['product']} {o['qty']}g\nStatus: {o['status']}\nReview: {review_text}\n\n"
        buttons.append([InlineKeyboardButton("⭐ Leave/Edit Review", callback_data=f"review_{oid}")])
    buttons.append([InlineKeyboardButton("⬅ Back", callback_data="back")])
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons))

# ================= USER PAID =================
async def user_paid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    try:
        oid = int(q.data.replace("paid_", ""))
        order = orders[oid]
    except:
        await q.edit_message_text("❌ Order not found.")
        return
    order["status"] = "Paid – awaiting dispatch"
    # Notify user
    await context.bot.send_message(order["user_id"], f"✅ Your order #{oid} has been marked as PAID by admin!")
    await q.edit_message_text(
        f"✅ Payment marked for Order #{oid}\n\n"
        f"{order['product']} – {order['qty']}g\n"
        f"Amount: £{order['price']}\nStatus: {order['status']}\n💳 LTC: `{CRYPTO_WALLET}`",
        parse_mode="Markdown"
    )

# ================= PROMPT REVIEW =================
async def prompt_review(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    try:
        order_id = int(q.data.replace("review_", ""))
        CONTACT_SESSIONS[q.from_user.id] = {"step": "review", "order_id": order_id}
        await q.edit_message_text("✨ Please leave a review for your order.\nSend number of stars (1-5):")
    except:
        await q.edit_message_text("❌ Order not found.")

# ================= HANDLE REVIEW =================
async def handle_review_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    session = CONTACT_SESSIONS.get(uid)
    if not session or session.get("step") != "review":
        return

    order_id = session["order_id"]
    order = orders.get(order_id)
    if not order:
        CONTACT_SESSIONS.pop(uid)
        await update.message.reply_text("❌ Order not found.", reply_markup=main_menu())
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
        return

    existing = next((r for r in REVIEWS if r["user_id"] == uid and r["product_key"] == order["product_key"]), None)
    if existing:
        existing.update({"stars": session["stars"], "text": text})
        await update.message.reply_text("✅ Your review has been updated!", reply_markup=main_menu())
    else:
        REVIEWS.append({"user_id": uid, "product_key": order["product_key"], "stars": session["stars"], "text": text})
        await update.message.reply_text("✅ Thank you for your review!", reply_markup=main_menu())

    CONTACT_SESSIONS.pop(uid)

# ================= VIEW REVIEWS =================
async def view_reviews(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not REVIEWS:
        text = "⭐ No reviews yet."
    else:
        text = "⭐ Reviews:\n\n"
        for r in REVIEWS[-10:]:
            text += f"{PRODUCTS.get(r['product_key'], r['product_key'])} - {r['stars']}★\n{r['text']}\n\n"
    buttons = [[InlineKeyboardButton("⬅ Back", callback_data="back")]]
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons))

# ================= CONTACT SUPPORT =================
async def contact_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    CONTACT_SESSIONS[q.from_user.id] = {"step": "contact_user"}
    await q.edit_message_text("📩 Send your message for support:")

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

# ================= ADMIN CALLBACK =================
async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    data = q.data

    if uid not in ADMINS:
        await q.edit_message_text("❌ Not authorised.")
        return

    # --- VIEW ORDERS ---
    if data == "admin_view_orders":
        if not orders:
            await q.edit_message_text("📦 No orders yet.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅ Back", callback_data="back")]]))
            return
        text = "📦 Orders:\n\n"
        buttons = []
        for oid, o in orders.items():
            text += f"#{oid} - {o['product']} {o['qty']}g - {o['status']}\n"
            buttons.append([
                InlineKeyboardButton("✅ Paid", callback_data=f"admin_paid_{oid}"),
                InlineKeyboardButton("📦 Dispatch", callback_data=f"admin_dispatch_{oid}")
            ])
        buttons.append([InlineKeyboardButton("⬅ Back", callback_data="back")])
        await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons))
        return

    # --- MARK PAID ---
    if data.startswith("admin_paid_"):
        try:
            oid = int(data.replace("admin_paid_", ""))
            orders[oid]["status"] = "Paid – awaiting dispatch"
            # Notify user
            await context.bot.send_message(orders[oid]["user_id"], f"✅ Your order #{oid} has been marked as PAID by admin!")
            await q.edit_message_text(
                f"📦 Order #{oid} marked as PAID ✅\n{orders[oid]['product']} – {orders[oid]['qty']}g\nStatus: {orders[oid]['status']}"
            )
        except:
            await q.edit_message_text("❌ Order not found.")
        return

    # --- MARK DISPATCHED ---
    if data.startswith("admin_dispatch_"):
        try:
            oid = int(data.replace("admin_dispatch_", ""))
            orders[oid]["status"] = "Dispatched"
            # Notify user
            await context.bot.send_message(orders[oid]["user_id"], f"📦 Your order #{oid} has been marked as DISPATCHED by admin!")
            await q.edit_message_text(
                f"📦 Order #{oid} marked as DISPATCHED ✅\n{orders[oid]['product']} – {orders[oid]['qty']}g\nStatus: {orders[oid]['status']}"
            )
        except:
            await q.edit_message_text("❌ Order not found.")
        return

# ================= APP =================
app = ApplicationBuilder().token(TOKEN).build()

# --- Handlers ---
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("admin", admin))
app.add_handler(CommandHandler("cancel", cancel))

app.add_handler(CallbackQueryHandler(product_select, pattern="^prod_"))
app.add_handler(CallbackQueryHandler(quantity_select, pattern="^qty_"))
app.add_handler(CallbackQueryHandler(user_paid, pattern="^paid_"))
app.add_handler(CallbackQueryHandler(prompt_review, pattern="^review_"))
app.add_handler(CallbackQueryHandler(view_reviews, pattern="view_reviews"))
app.add_handler(CallbackQueryHandler(my_orders, pattern="my_orders"))
app.add_handler(CallbackQueryHandler(contact_support, pattern="contact_support"))
app.add_handler(CallbackQueryHandler(back, pattern="^back$"))
app.add_handler(CallbackQueryHandler(admin_callback, pattern="^admin_"))

app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_input))

print("✅ BOT RUNNING")
app.run_polling()
