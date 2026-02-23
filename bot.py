import os
import json
import sqlite3
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ================= CONFIG =================

TOKEN = os.environ.get("TOKEN") or "PUT_YOUR_TOKEN_HERE"
CRYPTO_WALLET = "LTC1qv4u6vr0gzp9g4lq0g3qev939vdnwxghn5gtnfc"
CONTACT_CHANNEL_ID = "@YourChannelOrPM"

# 🔒 SET YOUR REAL TELEGRAM USER ID HERE
ADMINS = {123456789}  # <-- CHANGE THIS

USER_SESSIONS = {}
ADMIN_SESSIONS = {}
USER_PRODUCT_PAGE = {}
USER_ORDER_PAGE = {}
ADMIN_ORDER_PAGE = {}

# ================= DATABASE =================

db = sqlite3.connect("shop.db", check_same_thread=False)
cur = db.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS products (
    id TEXT PRIMARY KEY,
    name TEXT,
    description TEXT,
    photo_file_id TEXT,
    price_3_5 REAL,
    price_7 REAL,
    price_14 REAL,
    price_28 REAL,
    price_56 REAL
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS orders (
    order_id INTEGER PRIMARY KEY,
    user_id INTEGER,
    items TEXT,
    total REAL,
    status TEXT,
    name TEXT,
    address TEXT
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS reviews (
    order_id INTEGER,
    user_id INTEGER,
    stars INTEGER,
    text TEXT,
    PRIMARY KEY (order_id, user_id)
)
""")

db.commit()

# ================= HELPERS =================

def get_products():
    cur.execute("SELECT * FROM products ORDER BY name ASC")
    return cur.fetchall()

def basket_text(items):
    total = 0
    text = ""
    for i in items:
        cost = i["price"] * i["quantity"]
        total += cost
        text += f"- {i['name']} {i['weight']}g x{i['quantity']} = £{cost}\n"
    return text, total

# ================= MENUS =================

def home_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛒 Products", callback_data="home_products")],
        [InlineKeyboardButton("📦 My Orders", callback_data="home_my_orders")],
        [InlineKeyboardButton("⭐ Reviews", callback_data="home_reviews")],
        [InlineKeyboardButton("📞 Contact Vendor", callback_data="home_contact")]
    ])

def admin_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Product", callback_data="admin_add_product")],
        [InlineKeyboardButton("📢 Announcement", callback_data="admin_add_announcement")],
        [InlineKeyboardButton("📦 View Orders", callback_data="admin_orders_0")],
        [InlineKeyboardButton("⬅ Back", callback_data="admin_back")]
    ])

# ================= START =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🏠 Welcome! Choose an option:",
        reply_markup=home_menu()
    )

# ================= ADMIN COMMAND =================

async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id

    if uid not in ADMINS:
        await update.message.reply_text("❌ You are not authorised.")
        return

    await update.message.reply_text(
        "🛠 ADMIN PANEL",
        reply_markup=admin_menu()
    )

# ================= CALLBACK ROUTER =================

async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    data = q.data
    uid = q.from_user.id

    # ===== HOME =====

    if data == "home_products":
        USER_PRODUCT_PAGE[uid] = 0
        await show_product_page(update, context, uid, 0)
        return

    if data == "home_my_orders":
        await show_user_orders(update, uid, 0)
        return

    if data == "home_reviews":
        await show_reviews(update)
        return

    if data == "home_contact":
        await context.bot.send_message(
            CONTACT_CHANNEL_ID,
            f"📩 Contact from {q.from_user.full_name}"
        )
        await q.edit_message_text(
            "✅ Vendor notified.",
            reply_markup=home_menu()
        )
        return

    if data == "back":
        await q.edit_message_text(
            "🏠 Main Menu",
            reply_markup=home_menu()
        )
        return

    # ===== ADMIN BACK =====

    if data == "admin_back":
        if uid in ADMINS:
            await q.edit_message_text("🛠 ADMIN PANEL", reply_markup=admin_menu())
        return

    # ===== ADMIN ONLY BUTTONS =====

    if data.startswith("admin_") and uid not in ADMINS:
        await q.answer("Not authorised", show_alert=True)
        return

    if data == "admin_add_product":
        ADMIN_SESSIONS[uid] = {"step": "name"}
        await q.message.reply_text("Send product name:")
        return

    if data.startswith("admin_orders_"):
        page = int(data.split("_")[-1])
        await show_admin_orders(update, uid, page)
        return

# ================= PRODUCTS =================

async def show_product_page(update, context, uid, page):
    products = get_products()

    if not products:
        await update.callback_query.edit_message_text(
            "No products available.",
            reply_markup=home_menu()
        )
        return

    page = max(0, min(page, len(products) - 1))
    USER_PRODUCT_PAGE[uid] = page

    p = products[page]

    buttons = [
        [InlineKeyboardButton("3.5g £" + str(p[4]), callback_data="weight_3.5")],
        [InlineKeyboardButton("7g £" + str(p[5]), callback_data="weight_7")],
        [InlineKeyboardButton("14g £" + str(p[6]), callback_data="weight_14")],
        [InlineKeyboardButton("28g £" + str(p[7]), callback_data="weight_28")],
        [InlineKeyboardButton("56g £" + str(p[8]), callback_data="weight_56")]
    ]

    buttons.append([InlineKeyboardButton("🏠 Back", callback_data="back")])

    await update.callback_query.edit_message_text(
        f"📦 {p[1]}\n\n{p[2]}",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

# ================= USER ORDERS =================

async def show_user_orders(update, uid, page):
    cur.execute("SELECT * FROM orders WHERE user_id=? ORDER BY order_id DESC", (uid,))
    orders = cur.fetchall()

    if not orders:
        await update.callback_query.edit_message_text(
            "No orders yet.",
            reply_markup=home_menu()
        )
        return

    page = max(0, min(page, len(orders) - 1))
    o = orders[page]

    await update.callback_query.edit_message_text(
        f"Order #{o[0]}\nStatus: {o[4]}\nTotal: £{o[3]}",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🏠 Back", callback_data="back")]
        ])
    )

# ================= REVIEWS =================

async def show_reviews(update):
    cur.execute("SELECT stars, text FROM reviews")
    reviews = cur.fetchall()

    if not reviews:
        await update.callback_query.edit_message_text(
            "No reviews yet.",
            reply_markup=home_menu()
        )
        return

    text = ""
    for s, t in reviews:
        text += "⭐" * s + f"\n{t}\n\n"

    await update.callback_query.edit_message_text(
        text,
        reply_markup=home_menu()
    )

# ================= ADMIN ORDERS =================

async def show_admin_orders(update, uid, page):
    cur.execute("SELECT * FROM orders ORDER BY order_id DESC")
    orders = cur.fetchall()

    if not orders:
        await update.callback_query.edit_message_text("No orders found.")
        return

    page = max(0, min(page, len(orders) - 1))
    o = orders[page]

    await update.callback_query.edit_message_text(
        f"🧾 Order #{o[0]}\nUser: {o[1]}\nTotal: £{o[3]}\nStatus: {o[4]}",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅ Back", callback_data="admin_back")]
        ])
    )

# ================= MESSAGE HANDLER =================

async def message_handler(update, context):
    uid = update.message.from_user.id

    if uid in ADMIN_SESSIONS:
        admin = ADMIN_SESSIONS[uid]
        if admin["step"] == "name":
            admin["name"] = update.message.text
            admin["step"] = "desc"
            await update.message.reply_text("Send description:")
            return

# ================= APP =================

app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("admin", admin_cmd))
app.add_handler(CallbackQueryHandler(callback_router))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

print("✅ BOT RUNNING")
app.run_polling()
