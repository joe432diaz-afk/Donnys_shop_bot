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

TOKEN = os.getenv("TOKEN")
ADMIN_ID = 123456789  # CHANGE
CHANNEL_ID = -1001234567890  # CHANGE

DB_NAME = "shop.db"

logging.basicConfig(level=logging.INFO)

ASK_NAME, ASK_ADDRESS, WRITE_REVIEW = range(3)

# ================= DATABASE =================

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

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
        user_id INTEGER PRIMARY KEY,
        text TEXT
    )""")

    conn.commit()
    conn.close()

def seed_products():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM products")
    if c.fetchone()[0] == 0:
        c.execute("INSERT INTO products (name, price, description) VALUES (?, ?, ?)",
                  ("Product A", 10, "Description A"))
        c.execute("INSERT INTO products (name, price, description) VALUES (?, ?, ?)",
                  ("Product B", 20, "Description B"))
    conn.commit()
    conn.close()

# ================= MENUS =================

def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛍 Products", callback_data="products")],
        [InlineKeyboardButton("🧺 Basket", callback_data="basket")],
        [InlineKeyboardButton("📦 Order History", callback_data="history")],
        [InlineKeyboardButton("⭐ Public Reviews", callback_data="public_reviews")]
    ])

# ================= START =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Welcome to the Production Shop.",
        reply_markup=main_menu()
    )

# ================= PRODUCTS =================

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
        "Products:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ================= BASKET =================

async def add_to_basket(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    pid = int(query.data.split("_")[1])

    context.user_data.setdefault("basket", []).append(pid)

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
            "Basket empty.",
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

# ================= CHECKOUT =================

async def checkout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("Enter your name:")
    return ASK_NAME

async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["name"] = update.message.text
    await update.message.reply_text("Enter your address:")
    return ASK_ADDRESS

async def get_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = context.user_data["name"]
    address = update.message.text
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
        f"Order Created!\nOrder ID: {order_id}\nStatus: Pending",
        reply_markup=main_menu()
    )

    await context.bot.send_message(
        chat_id=CHANNEL_ID,
        text=f"New Order\nID: {order_id}\nName: {name}\nAddress: {address}\nTotal: {total}"
    )

    return ConversationHandler.END

# ================= ORDER HISTORY =================

async def order_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT id, status FROM orders WHERE user_id=?",
              (query.from_user.id,))
    orders = c.fetchall()
    conn.close()

    if not orders:
        text = "No orders yet."
    else:
        text = "Your Orders:\n\n"
        for o in orders:
            text += f"Order: {o[0]} | Status: {o[1]}\n"

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅ Back", callback_data="menu")]
        ])
    )

# ================= REVIEWS =================

async def public_reviews(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT text FROM reviews")
    reviews = c.fetchall()
    conn.close()

    if not reviews:
        text = "No reviews yet."
    else:
        text = "Public Reviews:\n\n"
        for r in reviews:
            text += f"⭐ {r[0]}\n\n"

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅ Back", callback_data="menu")]
        ])
    )

async def write_review(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("Write your review:")
    return WRITE_REVIEW

async def save_review(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO reviews VALUES (?, ?)",
              (user_id, text))
    conn.commit()
    conn.close()

    await update.message.reply_text(
        "Review saved.",
        reply_markup=main_menu()
    )

    return ConversationHandler.END

# ================= ADMIN =================

async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT id FROM orders WHERE status='Pending'")
    orders = c.fetchall()
    conn.close()

    keyboard = []
    for o in orders:
        keyboard.append([
            InlineKeyboardButton(
                f"Mark Paid {o[0]}",
                callback_data=f"paid_{o[0]}"
            )
        ])

    await update.message.reply_text(
        "Pending Orders:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def mark_paid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    order_id = query.data.split("_")[1]

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE orders SET status='Paid' WHERE id=?", (order_id,))
    c.execute("SELECT user_id FROM orders WHERE id=?", (order_id,))
    user_id = c.fetchone()[0]
    conn.commit()
    conn.close()

    await context.bot.send_message(
        chat_id=user_id,
        text=f"Order {order_id} marked as PAID.\nLeave a review?",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Write Review", callback_data="write_review")]
        ])
    )

    await query.edit_message_text("Marked as Paid.")

# ================= ROUTER =================

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
    elif data == "history":
        await order_history(update, context)
    elif data == "public_reviews":
        await public_reviews(update, context)
    elif data.startswith("paid_"):
        await mark_paid(update, context)
    elif data == "write_review":
        return await write_review(update, context)

# ================= MAIN =================

def main():
    init_db()
    seed_products()

    app = ApplicationBuilder().token(TOKEN).build()

    review_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(write_review, pattern="^write_review$")],
        states={
            WRITE_REVIEW: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_review)]
        },
        fallbacks=[]
    )

    checkout_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(checkout, pattern="^checkout$")],
        states={
            ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            ASK_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_address)]
        },
        fallbacks=[]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(review_conv)
    app.add_handler(checkout_conv)
    app.add_handler(CallbackQueryHandler(router))

    print("Production Shop Running...")
    app.run_polling()

if __name__ == "__main__":
    main()
