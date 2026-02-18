import os
import json
import sqlite3
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)

# ================= CONFIG =================
TOKEN = os.environ.get("TOKEN") or "PUT_YOUR_TOKEN_HERE"
CRYPTO_WALLET = "LTC1qv4u6vr0gzp9g4lq0g3qev939vdnwxghn5gtnfc"
CONTACT_CHANNEL_ID = "@YourChannelOrPM"

USER_SESSIONS = {}
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

def get_session(uid):
    if uid not in USER_SESSIONS:
        USER_SESSIONS[uid] = {"basket": [], "step": None}
    return USER_SESSIONS[uid]

def add_to_basket(uid, name, weight, price):
    session = get_session(uid)
    for item in session["basket"]:
        if item["name"] == name and item["weight"] == weight:
            item["quantity"] += 1
            return
    session["basket"].append({
        "name": name,
        "weight": weight,
        "price": price,
        "quantity": 1
    })

def basket_text(basket):
    total = 0
    lines = []
    for i in basket:
        cost = i["price"] * i["quantity"]
        total += cost
        lines.append(f"- {i['name']} {i['weight']}g x{i['quantity']} = £{cost}")
    return "\n".join(lines), total

# ================= MENUS =================
def home_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛒 Products", callback_data="home_products")],
        [InlineKeyboardButton("🛍 View Basket", callback_data="view_basket")],
        [InlineKeyboardButton("📦 My Orders", callback_data="home_my_orders")],
        [InlineKeyboardButton("📞 Contact Vendor", callback_data="home_contact")]
    ])

def basket_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Checkout", callback_data="checkout")],
        [InlineKeyboardButton("❌ Clear Basket", callback_data="clear_basket")],
        [InlineKeyboardButton("🏠 Back", callback_data="back")]
    ])

# ================= START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🏠 Welcome", reply_markup=home_menu())

# ================= CALLBACK ROUTER =================
async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    data = q.data
    await q.answer()

    session = get_session(uid)

    if data == "home_products":
        USER_PRODUCT_PAGE[uid] = 0
        await show_product_page(update, context, uid, 0)
        return

    if data == "view_basket":
        if not session["basket"]:
            await q.edit_message_text("🛒 Basket empty", reply_markup=home_menu())
            return
        text, total = basket_text(session["basket"])
        await q.edit_message_text(
            f"🛍 Basket:\n{text}\n\n💰 £{total}",
            reply_markup=basket_menu()
        )
        return

    if data == "clear_basket":
        session["basket"].clear()
        await q.edit_message_text("❌ Basket cleared", reply_markup=home_menu())
        return

    if data == "checkout":
        if not session["basket"]:
            await q.edit_message_text("Basket empty", reply_markup=home_menu())
            return
        session["step"] = "name"
        await q.edit_message_text("👤 Send FULL NAME:")
        return

    if data.startswith("prod_page_"):
        page = int(data.split("_")[-1])
        await show_product_page(update, context, uid, page)
        return

    if data.startswith("add_"):
        _, weight = data.split("_")
        page = USER_PRODUCT_PAGE.get(uid, 0)
        p = get_products()[page]
        prices = {"3.5": p[4], "7": p[5], "14": p[6], "28": p[7], "56": p[8]}
        add_to_basket(uid, p[1], weight, prices[weight])
        await q.answer("Added to basket ✅", show_alert=False)
        return

    if data == "back":
        await q.edit_message_text("🏠 Main Menu", reply_markup=home_menu())
        return

# ================= PRODUCTS =================
async def show_product_page(update, context, uid, page):
    products = get_products()
    if not products:
        await update.callback_query.edit_message_text("No products.")
        return

    page = max(0, min(page, len(products)-1))
    USER_PRODUCT_PAGE[uid] = page
    p = products[page]

    buttons = [
        [InlineKeyboardButton(f"{w}g £{price}", callback_data=f"add_{w}")]
        for w, price in {
            "3.5": p[4], "7": p[5], "14": p[6], "28": p[7], "56": p[8]
        }.items()
    ]

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"prod_page_{page-1}"))
    if page < len(products)-1:
        nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"prod_page_{page+1}"))
    if nav:
        buttons.append(nav)

    buttons.append([InlineKeyboardButton("🛍 View Basket", callback_data="view_basket")])
    buttons.append([InlineKeyboardButton("🏠 Back", callback_data="back")])

    markup = InlineKeyboardMarkup(buttons)

    if p[3]:
        await update.callback_query.edit_message_media(
            InputMediaPhoto(p[3], caption=f"📦 {p[1]}\n\n{p[2]}"),
            reply_markup=markup
        )
    else:
        await update.callback_query.edit_message_text(
            f"📦 {p[1]}\n\n{p[2]}",
            reply_markup=markup
        )

# ================= MESSAGE HANDLER =================
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    text = update.message.text
    session = get_session(uid)

    if session.get("step") == "name":
        session["name"] = text
        session["step"] = "address"
        await update.message.reply_text("📍 Address:")
        return

    if session.get("step") == "address":
        session["address"] = text
        items, total = basket_text(session["basket"])
        cur.execute(
            "INSERT INTO orders VALUES (NULL,?,?,?,?,?,?)",
            (uid, json.dumps(session["basket"]), total, "Pending", session["name"], session["address"])
        )
        db.commit()
        USER_SESSIONS.pop(uid)
        await update.message.reply_text(
            f"✅ Order placed\n\n{items}\n\n💰 £{total}\n💳 Pay to:\n{CRYPTO_WALLET}",
            reply_markup=home_menu()
        )

# ================= APP =================
app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(callback_router))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

print("✅ BOT RUNNING")
app.run_polling()
