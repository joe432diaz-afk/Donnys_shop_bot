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

# ✅ YOUR ADMIN ID
ADMINS = {7773622161}

CRYPTO_WALLET = "LTC1qv4u6vr0gzp9g4lq0g3qev939vdnwxghn5gtnfc"

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

# ================= SESSION STORAGE =================

USER_BASKET = {}
ADMIN_SESSIONS = {}
USER_PRODUCT_PAGE = {}

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

def admin_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Product", callback_data="admin_add_product")],
        [InlineKeyboardButton("📦 View Products", callback_data="admin_view_products")],
        [InlineKeyboardButton("⬅ Back", callback_data="admin_back")]
    ])

# ================= START =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🏠 Welcome",
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

# ================= PRODUCT DISPLAY =================

async def show_products(update, uid, page=0):

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

    for w in weights:
        buttons.append([
            InlineKeyboardButton(
                f"{w}g £{weights[w]}",
                callback_data=f"add_{p[0]}_{w}"
            )
        ])

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

async def add_to_basket(update, uid, product_id, weight):

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
        f"🧺 Basket\n\n{text}\n💰 Total £{total}",
        reply_markup=home_menu()
    )

# ================= CALLBACK ROUTER =================

async def callback_router(update, context):

    q = update.callback_query
    await q.answer()

    data = q.data
    uid = q.from_user.id

    if data == "home_products":
        await show_products(update, uid, 0)
        return

    if data == "view_basket":
        text, total = basket_text(uid)

        await q.edit_message_text(
            f"🧺 Basket\n\n{text}\n💰 Total £{total}",
            reply_markup=home_menu()
        )
        return

    if data.startswith("prod_page_"):
        page = int(data.split("_")[-1])
        await show_products(update, uid, page)
        return

    if data.startswith("add_"):
        _, pid, weight = data.split("_")
        await add_to_basket(update, uid, pid, weight)
        return

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

    if data.startswith("admin_") and uid not in ADMINS:
        await q.answer("Not authorised", show_alert=True)
        return

    if data == "admin_add_product":
        ADMIN_SESSIONS[uid] = {"step": "name"}
        await q.message.reply_text("🆕 Send product NAME:")
        return

    if data == "admin_view_products":
        await q.edit_message_text(
            "Feature coming soon",
            reply_markup=admin_menu()
        )
        return

# ================= MESSAGE HANDLER =================

async def message_handler(update, context):

    uid = update.message.from_user.id
    text = update.message.text

    if uid in ADMIN_SESSIONS:

        admin = ADMIN_SESSIONS[uid]
        step = admin.get("step")

        if step == "name":
            admin["name"] = text
            admin["step"] = "desc"

            await update.message.reply_text("📝 Send description:")
            return

        if step == "desc":
            admin["desc"] = text
            admin["step"] = "photo"

            await update.message.reply_text("📷 Send photo:")
            return

        if step == "photo":

            if not update.message.photo:
                await update.message.reply_text("❌ Send image photo.")
                return

            admin["photo_file_id"] = update.message.photo[-1].file_id
            admin["step"] = "prices"

            await update.message.reply_text("💰 Send prices:\n3.5,7,14,28,56")
            return

        if step == "prices":

            try:
                prices = list(map(float, text.split(",")))
                if len(prices) != 5:
                    raise ValueError

            except:
                await update.message.reply_text("❌ Format must be:\n3.5,7,14,28,56")
                return

            pid = admin["name"].lower().replace(" ", "_")

            cur.execute("""
            INSERT OR REPLACE INTO products VALUES (?,?,?,?,?,?,?,?,?)
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
