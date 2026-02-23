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

# 🔒 CHANGE THIS TO YOUR TELEGRAM USER ID
ADMINS = { }

CRYPTO_WALLET = "LTC1qv4u6vr0gzp9g4lq0g3qev939vdnwxghn5gtnfc"
CONTACT_CHANNEL_ID = "@YourChannelOrPM"

# ================= SESSION STORAGE =================

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
    PRIMARY KEY(order_id,user_id)
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
        await update.message.reply_text("❌ Not authorised.")
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
        await q.edit_message_text("📦 Products page coming soon", reply_markup=home_menu())
        return

    if data == "home_my_orders":
        await q.edit_message_text("📦 Orders page coming soon", reply_markup=home_menu())
        return

    if data == "home_reviews":
        await q.edit_message_text("⭐ Reviews page", reply_markup=home_menu())
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

    # ===== BACK BUTTONS =====

    if data == "back":
        await q.edit_message_text(
            "🏠 Main Menu",
            reply_markup=home_menu()
        )
        return

    if data == "admin_back":
        if uid in ADMINS:
            await q.edit_message_text(
                "🛠 ADMIN PANEL",
                reply_markup=admin_menu()
            )
        return

    # ===== ADMIN SECURITY =====

    if data.startswith("admin_") and uid not in ADMINS:
        await q.answer("Not authorised", show_alert=True)
        return

    # ===== ADMIN ACTIONS =====

    if data == "admin_add_product":
        ADMIN_SESSIONS[uid] = {"step": "name"}
        await q.message.reply_text("🆕 Send product NAME:")
        return

    if data.startswith("admin_orders_"):
        await q.edit_message_text(
            "📦 Order system coming later.",
            reply_markup=admin_menu()
        )
        return

# ================= MESSAGE HANDLER =================

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    text = update.message.text

    # ===== ADMIN PRODUCT CREATION FLOW =====

    if uid in ADMIN_SESSIONS:
        admin = ADMIN_SESSIONS[uid]
        step = admin.get("step")

        # NAME
        if step == "name":
            admin["name"] = text
            admin["step"] = "desc"

            await update.message.reply_text("📝 Send product description:")
            return

        # DESCRIPTION
        if step == "desc":
            admin["desc"] = text
            admin["step"] = "photo"

            await update.message.reply_text("📷 Send product photo:")
            return

        # PHOTO
        if step == "photo":

            if not update.message.photo:
                await update.message.reply_text("❌ Send an image photo.")
                return

            admin["photo_file_id"] = update.message.photo[-1].file_id
            admin["step"] = "prices"

            await update.message.reply_text(
                "💰 Send prices:\n3.5,7,14,28,56"
            )
            return

        # PRICES
        if step == "prices":
            try:
                prices = list(map(float, text.split(",")))

                if len(prices) != 5:
                    raise ValueError

            except Exception:
                await update.message.reply_text("❌ Format must be:\n3.5,7,14,28,56")
                return

            pid = admin["name"].lower().replace(" ", "_")

            cur.execute("""
                INSERT OR REPLACE INTO products
                VALUES (?,?,?,?,?,?,?,?,?)
            """, (
                pid,
                admin["name"],
                admin["desc"],
                admin["photo_file_id"],
                *prices
            ))

            db.commit()
            ADMIN_SESSIONS.pop(uid, None)

            await update.message.reply_text(
                "✅ Product added!",
                reply_markup=home_menu()
            )
            return

# ================= APP =================

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_cmd))

    app.add_handler(CallbackQueryHandler(callback_router))
    app.add_handler(MessageHandler(filters.TEXT | filters.PHOTO, message_handler))

    print("✅ BOT RUNNING")
    app.run_polling()

if __name__ == "__main__":
    main()
