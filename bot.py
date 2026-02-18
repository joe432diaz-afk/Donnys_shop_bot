import os
import json
import sqlite3
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)

# ================= CONFIG =================
TOKEN = os.environ.get("TOKEN") or "PUT_YOUR_TOKEN_HERE"
CRYPTO_WALLET = "LTC1qv4u6vr0gzp9g4lq0g3qev939vdnwxghn5gtnfc"
CONTACT_CHANNEL_ID = "@YourChannelOrPM"

ADMINS = set()
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

def basket_text(items):
    total = 0
    text = ""
    for i in items:
        cost = i["price"] * i["quantity"]
        total += cost
        text += f"- {i['name']} {i['weight']}g ×{i['quantity']} = £{cost:.2f}\n"
    return text, total

def product_rating(product_name):
    cur.execute("""
    SELECT AVG(r.stars), COUNT(*)
    FROM reviews r
    JOIN orders o ON r.order_id=o.order_id
    WHERE o.items LIKE ?
    """, (f'%"{product_name}"%',))
    avg, count = cur.fetchone()
    if count:
        return "⭐" * round(avg)
    return "No reviews yet"

def home_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛒 Products", callback_data="home_products")],
        [InlineKeyboardButton("📦 My Orders", callback_data="home_my_orders")],
        [InlineKeyboardButton("⭐ Reviews", callback_data="home_reviews")],
        [InlineKeyboardButton("📞 Contact Vendor", callback_data="home_contact")]
    ])

# ================= START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🏠 Welcome", reply_markup=home_menu())

# ================= CALLBACK ROUTER =================
async def callback_router(update, context):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    data = q.data

    USER_SESSIONS.setdefault(uid, {"basket": []})

    # ===== HOME =====
    if data == "home_products":
        USER_PRODUCT_PAGE[uid] = 0
        await show_product(update, uid)
        return

    if data == "home_my_orders":
        await show_user_order(update, uid, 0)
        return

    if data == "home_reviews":
        await show_all_reviews(update)
        return

    if data == "home_contact":
        await q.edit_message_text("📩 Message sent", reply_markup=home_menu())
        return

    # ===== PRODUCT NAV =====
    if data.startswith("prod_"):
        USER_PRODUCT_PAGE[uid] = int(data.split("_")[1])
        await show_product(update, uid)
        return

    # ===== ADD TO BASKET =====
    if data.startswith("add_"):
        _, pid, weight = data.split("_")
        product = next(p for p in get_products() if p[0] == pid)
        prices = {"3.5": product[4], "7": product[5], "14": product[6], "28": product[7], "56": product[8]}

        USER_SESSIONS[uid]["basket"].append({
            "name": product[1],
            "weight": weight,
            "price": prices[weight],
            "quantity": 1
        })
        await show_basket(update, uid)
        return

    # ===== QUANTITY =====
    if data.startswith("qty_"):
        _, idx, op = data.split("_")
        idx = int(idx)
        item = USER_SESSIONS[uid]["basket"][idx]

        if op == "plus":
            item["quantity"] += 1
        elif op == "minus":
            item["quantity"] = max(1, item["quantity"] - 1)

        await show_basket(update, uid)
        return

    # ===== CHECKOUT =====
    if data == "checkout":
        USER_SESSIONS[uid]["step"] = "name"
        await q.edit_message_text("👤 Send FULL NAME:")
        return

    if data == "back":
        await q.edit_message_text("🏠 Main Menu", reply_markup=home_menu())
        return

# ================= PRODUCTS =================
async def show_product(update, uid):
    products = get_products()
    page = USER_PRODUCT_PAGE[uid]
    p = products[page]

    rating = product_rating(p[1])

    buttons = [
        [InlineKeyboardButton(f"{w}g £{price}", callback_data=f"add_{p[0]}_{w}")]
        for w, price in {
            "3.5": p[4], "7": p[5], "14": p[6], "28": p[7], "56": p[8]
        }.items()
    ]

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️", callback_data=f"prod_{page-1}"))
    if page < len(products)-1:
        nav.append(InlineKeyboardButton("➡️", callback_data=f"prod_{page+1}"))
    if nav:
        buttons.append(nav)

    buttons.append([InlineKeyboardButton("🛒 View Basket", callback_data="basket")])
    buttons.append([InlineKeyboardButton("🏠 Back", callback_data="back")])

    await update.callback_query.edit_message_text(
        f"📦 {p[1]}\n{rating}\n\n{p[2]}",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

# ================= BASKET =================
async def show_basket(update, uid):
    basket = USER_SESSIONS[uid]["basket"]
    if not basket:
        await update.callback_query.edit_message_text("🛒 Basket empty", reply_markup=home_menu())
        return

    text, total = basket_text(basket)

    buttons = []
    for i in range(len(basket)):
        buttons.append([
            InlineKeyboardButton("➖", callback_data=f"qty_{i}_minus"),
            InlineKeyboardButton("➕", callback_data=f"qty_{i}_plus")
        ])

    buttons.append([InlineKeyboardButton("✅ Checkout", callback_data="checkout")])
    buttons.append([InlineKeyboardButton("🏠 Back", callback_data="back")])

    await update.callback_query.edit_message_text(
        f"🛒 Basket:\n{text}\n💰 £{total:.2f}",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

# ================= USER ORDERS =================
async def show_user_order(update, uid, page):
    cur.execute("SELECT * FROM orders WHERE user_id=? ORDER BY order_id DESC", (uid,))
    orders = cur.fetchall()
    if not orders:
        await update.callback_query.edit_message_text("No orders.", reply_markup=home_menu())
        return

    o = orders[page]
    items = json.loads(o[2])
    items_text = "\n".join(f"- {i['name']} {i['weight']}g ×{i['quantity']}" for i in items)

    await update.callback_query.edit_message_text(
        f"🧾 Order #{o[0]}\n{items_text}\n💰 £{o[3]}\n📌 {o[4]}",
        reply_markup=home_menu()
    )

# ================= REVIEWS (ANONYMOUS) =================
async def show_all_reviews(update):
    cur.execute("SELECT stars, text FROM reviews ORDER BY order_id DESC")
    rows = cur.fetchall()
    if not rows:
        await update.callback_query.edit_message_text("No reviews yet.", reply_markup=home_menu())
        return

    text = ""
    for s, t in rows:
        text += "⭐" * s + "\n" + t + "\n\n"

    await update.callback_query.edit_message_text(text, reply_markup=home_menu())

# ================= MESSAGE HANDLER =================
async def message_handler(update, context):
    uid = update.message.from_user.id
    session = USER_SESSIONS.get(uid)

    if not session:
        return

    if session.get("step") == "name":
        session["name"] = update.message.text
        session["step"] = "address"
        await update.message.reply_text("📍 Address:")
        return

    if session.get("step") == "address":
        session["address"] = update.message.text
        text, total = basket_text(session["basket"])

        cur.execute(
            "INSERT INTO orders VALUES (NULL,?,?,?,?,?,?)",
            (uid, json.dumps(session["basket"]), total, "Pending",
             session["name"], session["address"])
        )
        db.commit()

        USER_SESSIONS.pop(uid)
        await update.message.reply_text(
            f"✅ Order placed\n\n{text}\n💰 £{total:.2f}\n💳 Pay to:\n{CRYPTO_WALLET}",
            reply_markup=home_menu()
        )

# ================= APP =================
app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(callback_router))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

print("✅ BOT RUNNING")
app.run_polling()
