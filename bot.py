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

ADMINS = {7773622161}   # CHANGE THIS

CRYPTO_WALLET = "LTC1qv4u6vr0gzp9g4lq0g3qev939vdnwxghn5gtnfc"

# ================= SESSION STORAGE =================

USER_SESSIONS = {}
ADMIN_SESSIONS = {}
USER_PRODUCT_PAGE = {}
USER_BASKET = {}

# ================= DATABASE =================

db = sqlite3.connect("shop.db", check_same_thread=False)
cur = db.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS products(
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

db.commit()

# ================= HELPERS =================

def get_products():
    cur.execute("SELECT * FROM products ORDER BY name ASC")
    return cur.fetchall()

def basket_text(uid):
    basket = USER_BASKET.get(uid, [])

    total = 0
    text = ""

    for item in basket:
        cost = item["price"] * item["quantity"]
        total += cost
        text += f"- {item['name']} {item['weight']}g x{item['quantity']} = £{cost}\n"

    return text or "Basket empty", total

# ================= MENUS =================

def home_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛒 Products", callback_data="home_products")],
        [InlineKeyboardButton("🧺 View Basket", callback_data="view_basket")]
    ])

# ================= START =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🏠 Welcome",
        reply_markup=home_menu()
    )

# ================= PRODUCT PAGE =================

async def show_products(update, context, uid, page=0):

    products = get_products()

    if not products:
        await update.callback_query.edit_message_text(
            "No products available",
            reply_markup=home_menu()
        )
        return

    page = max(0, min(page, len(products)-1))

    USER_PRODUCT_PAGE[uid] = page

    p = products[page]

    weights = {
        "3.5": p[4],
        "7": p[5],
        "14": p[6],
        "28": p[7],
        "56": p[8]
    }

    buttons = []

    # Weight buttons
    for w, price in weights.items():
        buttons.append([
            InlineKeyboardButton(
                f"{w}g £{price}",
                callback_data=f"add_{p[0]}_{w}"
            )
        ])

    # Navigation
    nav = []

    if page > 0:
        nav.append(
            InlineKeyboardButton(
                "⬅ Prev",
                callback_data=f"prod_page_{page-1}"
            )
        )

    if page < len(products)-1:
        nav.append(
            InlineKeyboardButton(
                "Next ➡",
                callback_data=f"prod_page_{page+1}"
            )
        )

    if nav:
        buttons.append(nav)

    buttons.append([
        InlineKeyboardButton("🏠 Back", callback_data="back")
    ])

    markup = InlineKeyboardMarkup(buttons)

    caption = f"{p[1]}\n\n{p[2]}\n\nChoose weight:"

    if p[3]:
        await update.callback_query.edit_message_media(
            InputMediaPhoto(p[3], caption=caption),
            reply_markup=markup
        )
    else:
        await update.callback_query.edit_message_text(
            caption,
            reply_markup=markup
        )

# ================= BASKET =================

async def add_to_basket(update, context, uid, product_id, weight):

    cur.execute("SELECT * FROM products WHERE id=?", (product_id,))
    product = cur.fetchone()

    if not product:
        return

    prices = {
        "3.5": product[4],
        "7": product[5],
        "14": product[6],
        "28": product[7],
        "56": product[8]
    }

    price = prices.get(weight)

    if price is None:
        return

    basket = USER_BASKET.setdefault(uid, [])

    basket.append({
        "name": product[1],
        "weight": weight,
        "price": price,
        "quantity": 1
    })

    text, total = basket_text(uid)

    await update.callback_query.edit_message_text(
        f"🧺 Basket Updated\n\n{text}\n💰 Total £{total}",
        reply_markup=home_menu()
    )

# ================= CALLBACK ROUTER =================

async def callback_router(update, context):

    q = update.callback_query
    await q.answer()

    data = q.data
    uid = q.from_user.id

    # Home products
    if data == "home_products":
        await show_products(update, context, uid, 0)
        return

    # Basket view
    if data == "view_basket":
        text, total = basket_text(uid)

        await q.edit_message_text(
            f"🧺 Your Basket\n\n{text}\n💰 Total £{total}",
            reply_markup=home_menu()
        )
        return

    # Pagination
    if data.startswith("prod_page_"):
        page = int(data.split("_")[-1])
        await show_products(update, context, uid, page)
        return

    # Add product to basket
    if data.startswith("add_"):
        _, pid, weight = data.split("_")
        await add_to_basket(update, context, uid, pid, weight)
        return

    if data == "back":
        await q.edit_message_text(
            "🏠 Main Menu",
            reply_markup=home_menu()
        )
        return

# ================= APP =================

def main():

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback_router))

    print("✅ BOT RUNNING")
    app.run_polling()

if __name__ == "__main__":
    main()
