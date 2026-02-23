import os
import sqlite3
import logging
import requests
from uuid import uuid4
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)

TOKEN = os.getenv("TOKEN")
ADMIN_ID = 7773622161
CHANNEL_ID = -1001234567890  # CHANGE
LTC_ADDRESS = "YOUR_LTC_ADDRESS_HERE"

DB_NAME = "shop.db"

logging.basicConfig(level=logging.INFO)

ASK_NAME, ASK_ADDRESS, WRITE_REVIEW = range(3)

# ================= DATABASE =================

def db():
    return sqlite3.connect(DB_NAME)

def init_db():
    conn = db()
    c = conn.cursor()

    c.execute("""CREATE TABLE IF NOT EXISTS products(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        price REAL,
        description TEXT,
        photo TEXT
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS cart(
        user_id INTEGER,
        product_id INTEGER
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS orders(
        id TEXT PRIMARY KEY,
        user_id INTEGER,
        name TEXT,
        address TEXT,
        total_usd REAL,
        total_ltc REAL,
        status TEXT
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS reviews(
        order_id TEXT PRIMARY KEY,
        user_id INTEGER,
        text TEXT
    )""")

    conn.commit()
    conn.close()

# ================= LTC PRICE =================

def get_ltc_price():
    try:
        r = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=litecoin&vs_currencies=usd", timeout=10)
        return r.json()["litecoin"]["usd"]
    except:
        return 70  # fallback price

# ================= MAIN MENU =================

def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛍 Products", callback_data="products")],
        [InlineKeyboardButton("🧺 Basket", callback_data="basket")],
        [InlineKeyboardButton("📦 Orders", callback_data="orders")],
        [InlineKeyboardButton("⭐ Reviews", callback_data="public_reviews")]
    ])

# ================= START =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Welcome to Advanced Shop", reply_markup=main_menu())

# ================= PRODUCTS =================

async def show_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    conn = db()
    c = conn.cursor()
    c.execute("SELECT * FROM products")
    products = c.fetchall()
    conn.close()

    if not products:
        await query.edit_message_text("No products available.", reply_markup=main_menu())
        return

    for p in products:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Add to Cart", callback_data=f"add_{p[0]}")],
            [InlineKeyboardButton("⬅ Back", callback_data="menu")]
        ])

        await context.bot.send_photo(
            chat_id=query.message.chat_id,
            photo=p[4],
            caption=f"{p[1]}\n${p[2]}\n\n{p[3]}",
            reply_markup=keyboard
        )

# ================= CART =================

async def add_to_cart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pid = int(query.data.split("_")[1])

    conn = db()
    c = conn.cursor()
    c.execute("INSERT INTO cart VALUES (?, ?)", (query.from_user.id, pid))
    conn.commit()
    conn.close()

    await query.answer("Added to cart")

async def view_cart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    conn = db()
    c = conn.cursor()
    c.execute("""SELECT products.name, products.price 
                 FROM cart JOIN products 
                 ON cart.product_id = products.id 
                 WHERE cart.user_id=?""", (query.from_user.id,))
    items = c.fetchall()
    conn.close()

    if not items:
        await query.edit_message_text("Cart empty.", reply_markup=main_menu())
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

# ================= CHECKOUT =================

async def checkout_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

    conn = db()
    c = conn.cursor()
    c.execute("""SELECT products.price 
                 FROM cart JOIN products 
                 ON cart.product_id = products.id 
                 WHERE cart.user_id=?""", (update.effective_user.id,))
    prices = c.fetchall()

    total_usd = sum([p[0] for p in prices])
    ltc_price = get_ltc_price()
    total_ltc = round(total_usd / ltc_price, 6)

    order_id = str(uuid4())[:8]

    c.execute("INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?, ?)",
              (order_id, update.effective_user.id, name, address,
               total_usd, total_ltc, "Awaiting Payment"))

    c.execute("DELETE FROM cart WHERE user_id=?", (update.effective_user.id,))
    conn.commit()
    conn.close()

    invoice = f"""
Order ID: {order_id}

Total USD: ${total_usd}
LTC Price: ${ltc_price}
Total LTC: {total_ltc}

Send LTC to:
{LTC_ADDRESS}
"""

    await update.message.reply_text(
        invoice,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ I Have Paid", callback_data=f"paid_{order_id}")],
            [InlineKeyboardButton("⬅ Main Menu", callback_data="menu")]
        ])
    )

    return ConversationHandler.END

# ================= PAYMENT BUTTON =================

async def user_paid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    order_id = query.data.split("_")[1]

    await context.bot.send_message(
        ADMIN_ID,
        f"User claims payment for order {order_id}",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Confirm Payment", callback_data=f"admin_confirm_{order_id}")],
            [InlineKeyboardButton("Reject Payment", callback_data=f"admin_reject_{order_id}")]
        ])
    )

    await query.edit_message_text("Payment submitted for review.")

# ================= ADMIN ACTIONS =================

async def admin_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    order_id = query.data.split("_")[2]

    conn = db()
    c = conn.cursor()
    c.execute("UPDATE orders SET status='Paid' WHERE id=?", (order_id,))
    c.execute("SELECT user_id FROM orders WHERE id=?", (order_id,))
    user_id = c.fetchone()[0]
    conn.commit()
    conn.close()

    await context.bot.send_message(user_id,
        f"Payment confirmed for order {order_id}. Leave a review?",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Write Review", callback_data=f"review_{order_id}")]
        ])
    )

    await query.edit_message_text("Payment confirmed.")

async def admin_reject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    order_id = query.data.split("_")[2]

    conn = db()
    c = conn.cursor()
    c.execute("UPDATE orders SET status='Payment Rejected' WHERE id=?", (order_id,))
    c.execute("SELECT user_id FROM orders WHERE id=?", (order_id,))
    user_id = c.fetchone()[0]
    conn.commit()
    conn.close()

    await context.bot.send_message(user_id, f"Payment rejected for order {order_id}.")
    await query.edit_message_text("Payment rejected.")

async def admin_dispatch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    order_id = query.data.split("_")[2]

    conn = db()
    c = conn.cursor()
    c.execute("UPDATE orders SET status='Dispatched' WHERE id=?", (order_id,))
    c.execute("SELECT user_id FROM orders WHERE id=?", (order_id,))
    user_id = c.fetchone()[0]
    conn.commit()
    conn.close()

    await context.bot.send_message(user_id, f"Order {order_id} dispatched 🚚")
    await query.edit_message_text("Order dispatched.")

# ================= ROUTER =================

async def router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = update.callback_query.data

    if data == "menu":
        await update.callback_query.edit_message_text("Main Menu", reply_markup=main_menu())
    elif data == "products":
        await show_products(update, context)
    elif data.startswith("add_"):
        await add_to_cart(update, context)
    elif data == "basket":
        await view_cart(update, context)
    elif data.startswith("paid_"):
        await user_paid(update, context)
    elif data.startswith("admin_confirm_"):
        await admin_confirm(update, context)
    elif data.startswith("admin_reject_"):
        await admin_reject(update, context)
    elif data.startswith("admin_dispatch_"):
        await admin_dispatch(update, context)

# ================= MAIN =================

def main():
    init_db()

    app = ApplicationBuilder().token(TOKEN).build()

    checkout_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(checkout_start, pattern="^checkout$")],
        states={
            ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            ASK_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_address)]
        },
        fallbacks=[]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(checkout_conv)
    app.add_handler(CallbackQueryHandler(router))

    print("Bot running...")
    app.run_polling()


if __name__ == "__main__":
    main()
