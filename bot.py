import os
import sqlite3
import logging
import requests
from uuid import uuid4

from telegram import *
from telegram.ext import *

# ================= CONFIG =================

TOKEN = os.getenv("TOKEN")

ADMIN_ID = 7773622161
CHANNEL_ID = -1001234567890
LTC_ADDRESS = "YOUR_LTC_ADDRESS"

DB_NAME = "shop.db"

logging.basicConfig(level=logging.INFO)

# ✅ STEP 1 PATCHED STATES
ASK_NAME, ASK_ADDRESS, WRITE_REVIEW, ADMIN_ADD_PHOTO, ADMIN_ADD_NAME, ADMIN_ADD_PRICE, ADMIN_ADD_DESC, ADMIN_DELETE_ID = range(8)

# ================= DATABASE =================

def db():
    return sqlite3.connect(DB_NAME)

def init_db():
    conn = db()
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS products(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        price REAL,
        description TEXT,
        photo TEXT
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS cart(
        user_id INTEGER,
        product_id INTEGER
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS orders(
        id TEXT PRIMARY KEY,
        user_id INTEGER,
        name TEXT,
        address TEXT,
        total_usd REAL,
        total_ltc REAL,
        status TEXT
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS reviews(
        order_id TEXT PRIMARY KEY,
        user_id INTEGER,
        text TEXT
    )
    """)

    conn.commit()
    conn.close()

# ================= LTC PRICE =================

def get_ltc_price():
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price?ids=litecoin&vs_currencies=usd",
            timeout=10
        )
        return r.json()["litecoin"]["usd"]
    except:
        return 70

# ================= MAIN MENU =================

def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛍 Products", callback_data="products")],
        [InlineKeyboardButton("🧺 Basket", callback_data="basket")],
        [InlineKeyboardButton("📦 Orders", callback_data="orders")],
        [InlineKeyboardButton("⭐ Reviews", callback_data="public_reviews")]
    ])

# ================= START =================

async def start(update: Update, context):
    await update.message.reply_text(
        "Welcome to Shop Bot",
        reply_markup=main_menu()
    )

# ================= PRODUCTS =================

async def show_products(update, context):

    query = update.callback_query
    await query.answer()

    conn = db()
    c = conn.cursor()

    c.execute("SELECT * FROM products")
    products = c.fetchall()
    conn.close()

    if not products:
        await query.edit_message_text("No products.")
        return

    for p in products:

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Add Cart", callback_data=f"add_{p[0]}")],
            [InlineKeyboardButton("⬅ Back", callback_data="menu")]
        ])

        await context.bot.send_photo(
            query.message.chat_id,
            p[4],
            caption=f"{p[1]}\n${p[2]}\n\n{p[3]}",
            reply_markup=keyboard
        )

# ================= CART =================

async def add_cart(update, context):

    query = update.callback_query
    await query.answer()

    pid = int(query.data.split("_")[1])

    conn = db()
    c = conn.cursor()

    c.execute("INSERT INTO cart VALUES (?,?)",
              (query.from_user.id, pid))

    conn.commit()
    conn.close()

    await query.answer("Added to cart")

async def view_cart(update, context):

    query = update.callback_query
    await query.answer()

    conn = db()
    c = conn.cursor()

    c.execute("""
    SELECT products.name,products.price
    FROM cart
    JOIN products ON cart.product_id=products.id
    WHERE cart.user_id=?
    """, (query.from_user.id,))

    items = c.fetchall()
    conn.close()

    if not items:
        await query.edit_message_text("Cart empty", reply_markup=main_menu())
        return

    total = sum([i[1] for i in items])

    text = "Your Cart:\n\n"
    for i in items:
        text += f"{i[0]} - ${i[1]}\n"

    text += f"\nTotal USD: ${total}"

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("💳 Checkout", callback_data="checkout")],
            [InlineKeyboardButton("⬅ Back", callback_data="menu")]
        ])
    )

# ================= ADMIN PANEL =================

async def admin_panel(update, context):

    if update.effective_user.id != ADMIN_ID:
        return

    conn = db()
    c = conn.cursor()

    c.execute("SELECT id,status FROM orders")
    orders = c.fetchall()
    conn.close()

    keyboard = []

    for order_id, status in orders:

        if status == "Awaiting Payment":

            keyboard.append([
                InlineKeyboardButton(
                    f"Confirm Payment {order_id}",
                    callback_data=f"admin_confirm_{order_id}"
                )
            ])

            keyboard.append([
                InlineKeyboardButton(
                    f"Reject {order_id}",
                    callback_data=f"admin_reject_{order_id}"
                )
            ])

        elif status == "Paid":

            keyboard.append([
                InlineKeyboardButton(
                    f"Dispatch {order_id}",
                    callback_data=f"admin_dispatch_{order_id}"
                )
            ])

    keyboard.append([
        InlineKeyboardButton("⬅ Close", callback_data="menu")
    ])

    await update.message.reply_text(
        "🔧 Product Manager",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ================= ROUTER =================

async def router(update, context):

elif data == "admin_product_manager":
        await admin_product_manager_trigger(update, context)

    elif data == "admin_add_product":
        await update.callback_query.edit_message_text(
            "Send product photo:"
        )

    elif data == "admin_delete_product":
        await update.callback_query.edit_message_text(
            "Send Product ID to delete:"
        )

    elif data == "admin_view_products":

        conn = db()
        c = conn.cursor()

        c.execute("SELECT id,name,price FROM products")
        products = c.fetchall()
        conn.close()

        text = "Products List:\n\n"

        for p in products:
            text += f"ID:{p[0]} | {p[1]} | ${p[2]}\n"

        await update.callback_query.edit_message_text(
            text,
            reply_markup=main_menu()
        )
    data = update.callback_query.data

    if data == "menu":
        await update.callback_query.edit_message_text(
            "Main Menu",
            reply_markup=main_menu()
        )

    elif data == "products":
        await show_products(update, context)

    elif data.startswith("add_"):
        await add_cart(update, context)

    elif data == "basket":
        await view_cart(update, context)

    elif data == "paid_":
        await update.callback_query.answer()

# ================= MAIN =================

def main():

    init_db()

    app = ApplicationBuilder().token(TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(lambda u,c: None, pattern="^checkout$")],
        states={},
        fallbacks=[]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(router))

    print("Bot Running")
    app.run_polling()

# ================= ADMIN PRODUCT MANAGER MENU (STEP 2) =================

async def admin_product_manager_trigger(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.effective_user.id != ADMIN_ID:
        return

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Product", callback_data="admin_add_product")],
        [InlineKeyboardButton("❌ Delete Product", callback_data="admin_delete_product")],
        [InlineKeyboardButton("📦 View Products", callback_data="admin_view_products")],
        [InlineKeyboardButton("⬅ Close", callback_data="menu")]
    ])

    if update.message:
        await update.message.reply_text(
            "🔧 Product Manager",
            reply_markup=keyboard
        )

    elif update.callback_query:
        await update.callback_query.edit_message_text(
            "🔧 Product Manager",
            reply_markup=keyboard
        )

if __name__ == "__main__":
    main()
