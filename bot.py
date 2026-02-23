import os
import sqlite3
import logging
from uuid import uuid4
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler
)

# ================= CONFIG =================

TOKEN = os.getenv("TOKEN")
ADMIN_ID = 123456789  # CHANGE
CHANNEL_ID = -1001234567890  # CHANGE

DB_NAME = "shop.db"

logging.basicConfig(level=logging.INFO)

# =============== DATABASE =================

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    c.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        price REAL,
        description TEXT
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS orders (
        id TEXT PRIMARY KEY,
        user_id INTEGER,
        name TEXT,
        address TEXT,
        total REAL,
        status TEXT
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS reviews (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        text TEXT
    )""")

    conn.commit()
    conn.close()

# =============== SAMPLE PRODUCTS ===============

def seed_products():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM products")
    if c.fetchone()[0] == 0:
        c.execute("INSERT INTO products (name, price, description) VALUES (?, ?, ?)",
                  ("Product A", 10.0, "Description A"))
        c.execute("INSERT INTO products (name, price, description) VALUES (?, ?, ?)",
                  ("Product B", 20.0, "Description B"))
    conn.commit()
    conn.close()

# =============== STATES ===============

ASK_NAME, ASK_ADDRESS, REVIEW_TEXT = range(3)

# =============== MAIN MENU ===============

def main_menu():
    keyboard = [
        [InlineKeyboardButton("🛍 Products", callback_data="products")],
        [InlineKeyboardButton("🧺 Basket", callback_data="basket")],
        [InlineKeyboardButton("⭐ Reviews", callback_data="reviews")]
    ]
    return InlineKeyboardMarkup(keyboard)

# =============== START ===============

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users VALUES (?)", (user.id,))
    conn.commit()
    conn.close()

    await update.message.reply_text(
        "Welcome to the Shop!",
        reply_markup=main_menu()
    )

# =============== PRODUCTS ===============

async def show_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT * FROM products")
    products = c.fetchall()
    conn.close()

    keyboard = []
    for p in products:
        keyboard.append([InlineKeyboardButton(
            f"{p[1]} - ${p[2]}",
            callback_data=f"add_{p[0]}"
        )])

    keyboard.append([InlineKeyboardButton("⬅ Back", callback_data="menu")])

    await query.edit_message_text(
        "Available Products:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# =============== BASKET ===============

async def add_to_basket(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    product_id = int(query.data.split("_")[1])

    if "basket" not in context.user_data:
        context.user_data["basket"] = []

    context.user_data["basket"].append(product_id)

    await query.edit_message_text(
        "Added to basket.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🧺 View Basket", callback_data="basket")],
            [InlineKeyboardButton("⬅ Back", callback_data="products")]
        ])
    )

async def view_basket(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    basket = context.user_data.get("basket", [])
    if not basket:
        await query.edit_message_text(
            "Basket is empty.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅ Back", callback_data="menu")]
            ])
        )
        return

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    total = 0
    text = "Your Basket:\n\n"

    for pid in basket:
        c.execute("SELECT name, price FROM products WHERE id=?", (pid,))
        p = c.fetchone()
        if p:
            text += f"{p[0]} - ${p[1]}\n"
            total += p[1]

    conn.close()

    text += f"\nTotal: ${total}"

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("💳 Checkout", callback_data="checkout")],
            [InlineKeyboardButton("⬅ Back", callback_data="menu")]
        ])
    )

# =============== CHECKOUT ===============

async def checkout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Enter your name:")
    return ASK_NAME

async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["name"] = update.message.text
    await update.message.reply_text("Enter your address:")
    return ASK_ADDRESS

async def get_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    address = update.message.text
    name = context.user_data["name"]
    basket = context.user_data.get("basket", [])

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    total = 0
    for pid in basket:
        c.execute("SELECT price FROM products WHERE id=?", (pid,))
        p = c.fetchone()
        if p:
            total += p[0]

    order_id = str(uuid4())[:8]

    c.execute("INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?)",
              (order_id, update.effective_user.id, name, address, total, "Pending"))

    conn.commit()
    conn.close()

    context.user_data["basket"] = []

    await update.message.reply_text(
        f"Order Created!\nOrder ID: {order_id}\nTotal LTC: {total}",
        reply_markup=main_menu()
    )

    await context.bot.send_message(
        chat_id=CHANNEL_ID,
        text=f"New Order\nID: {order_id}\nName: {name}\nAddress: {address}\nTotal: {total}"
    )

    return ConversationHandler.END

# =============== ADMIN PANEL ===============

async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    keyboard = [
        [InlineKeyboardButton("📦 Orders", callback_data="admin_orders")]
    ]

    await update.message.reply_text(
        "Admin Panel",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# =============== ROUTER ===============

async def router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = update.callback_query.data

    if data == "menu":
        await update.callback_query.edit_message_text(
            "Main Menu",
            reply_markup=main_menu()
        )
    elif data == "products":
        await show_products(update, context)
    elif data.startswith("add_"):
        await add_to_basket(update, context)
    elif data == "basket":
        await view_basket(update, context)
    elif data == "checkout":
        return await checkout(update, context)

# =============== MAIN ===============

def main():
    init_db()
    seed_products()

    app = ApplicationBuilder().token(TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(checkout, pattern="^checkout$")],
        states={
            ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            ASK_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_address)]
        },
        fallbacks=[]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(router))

    print("Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()
