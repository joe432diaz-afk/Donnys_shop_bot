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
LTC_ADDRESS = "YOUR_LTC_ADDRESS"

logging.basicConfig(level=logging.INFO)

ASK_NAME, ASK_ADDRESS = range(2)

# ================= DATABASE =================

def db():
    return sqlite3.connect("shop.db")

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

    conn.commit()
    conn.close()

# ================= PRICE API =================

def get_ltc_price():
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price?ids=litecoin&vs_currencies=usd",
            timeout=8
        )
        return r.json()["litecoin"]["usd"]
    except:
        return 70

# ================= MENU =================

def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛍 Products", callback_data="products")],
        [InlineKeyboardButton("🧺 Basket", callback_data="basket")]
    ])

# ================= START =================

async def start(update: Update, context):
    await update.message.reply_text(
        "Welcome to Shop Bot",
        reply_markup=main_menu()
    )

# ================= PRODUCTS =================

async def show_products(update: Update, context):

    query = update.callback_query
    await query.answer()

    conn = db()
    c = conn.cursor()

    c.execute("SELECT * FROM products")
    products = c.fetchall()
    conn.close()

    if not products:
        await query.edit_message_text("No products available.")
        return

    for p in products:

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Add Cart", callback_data=f"add_{p[0]}")]
        ])

        await context.bot.send_photo(
            chat_id=query.message.chat_id,
            photo=p[4],
            caption=f"{p[1]}\n${p[2]}\n\n{p[3]}",
            reply_markup=keyboard
        )

# ================= CART =================

async def add_cart(update: Update, context):

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

# ================= ROUTER =================

async def router(update: Update, context):

    if not update.callback_query:
        return

    query = update.callback_query
    data = query.data

    await query.answer()

    if data == "products":
        await show_products(update, context)

    elif data.startswith("add_"):
        await add_cart(update, context)

    elif data == "menu":
        await query.edit_message_text(
            "Main Menu",
            reply_markup=main_menu()
        )

# ================= ADMIN PANEL =================

async def admin_panel(update: Update, context):

    if update.effective_user.id != ADMIN_ID:
        return

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Product", callback_data="admin_add_product")],
        [InlineKeyboardButton("❌ Close", callback_data="menu")]
    ])

    await update.message.reply_text(
        "Admin Dashboard",
        reply_markup=keyboard
    )

# ================= MAIN =================

def main():

    if not TOKEN:
        raise ValueError("TOKEN environment variable missing")

    init_db()

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CallbackQueryHandler(router))

    print("Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()
