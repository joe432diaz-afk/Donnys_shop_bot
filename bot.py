import os
import json
import sqlite3
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)

# ================= CONFIG =================
TOKEN = os.environ.get("TOKEN") or "PUT_YOUR_TOKEN_HERE"
CHANNEL_ID = -1003833257976
CRYPTO_WALLET = "LTC1qv4u6vr0gzp9g4lq0g3qev939vdnwxghn5gtnfc"

ADMINS = set()
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
        text += f"- {i['name']} {i['weight']}g x{i['quantity']} = £{cost}\n"
    return text, total

def product_rating(product_name):
    cur.execute("""
    SELECT AVG(r.stars), COUNT(*)
    FROM reviews r
    JOIN orders o ON r.order_id = o.order_id
    WHERE o.items LIKE ?
    """, (f'%"{product_name}"%',))
    avg, count = cur.fetchone()
    if count:
        return f"\n⭐ {round(avg,1)}/5 ({count} reviews)"
    return "\n⭐ No reviews yet"

def main_menu(uid):
    return InlineKeyboardMarkup([[InlineKeyboardButton("📦 My Orders", callback_data="my_orders_0")]])

# ================= START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    USER_PRODUCT_PAGE[uid] = 0
    await show_product_page(update, context, uid, 0)

# ================= SHOW PRODUCT PAGE =================
async def show_product_page(update, context, uid, page):
    products = get_products()
    if not products:
        await update.message.reply_text("No products available.")
        return
    if page < 0: page = 0
    if page >= len(products): page = len(products)-1
    USER_PRODUCT_PAGE[uid] = page
    p = products[page]

    rating = product_rating(p[1])
    buttons = [[InlineKeyboardButton(f"{w}g £{price}", callback_data=f"weight_{w}")]
               for w, price in {"3.5": p[4], "7": p[5], "14": p[6], "28": p[7], "56": p[8]}.items()]

    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"prod_page_{page-1}"))
    if page < len(products)-1:
        nav_buttons.append(InlineKeyboardButton("Next ➡️", callback_data=f"prod_page_{page+1}"))
    if nav_buttons:
        buttons.append(nav_buttons)
    buttons.append([InlineKeyboardButton("🏠 Back", callback_data="back")])

    if hasattr(update, 'message') and update.message:
        await update.message.reply_text(
            f"📦 {p[1]}{rating}\n\n{p[2]}\n\nChoose weight:",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
    else:
        await update.callback_query.edit_message_text(
            f"📦 {p[1]}{rating}\n\n{p[2]}\n\nChoose weight:",
            reply_markup=InlineKeyboardMarkup(buttons)
        )

# ================= ADMIN PANEL =================
async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    ADMINS.add(uid)
    ADMIN_ORDER_PAGE[uid] = 0
    await update.message.reply_text(
        "🛠 ADMIN PANEL",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Add Product", callback_data="admin_add_product")],
            [InlineKeyboardButton("📦 View Orders", callback_data="admin_orders_0")],
        ])
    )

# ================= CALLBACK ROUTER =================
async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = q.data
    uid = q.from_user.id
    await q.answer()

    # Product navigation
    if data.startswith("prod_page_"):
        page = int(data.replace("prod_page_", ""))
        await show_product_page(update, context, uid, page)
        return

    # Weight selection
    if data.startswith("weight_"):
        products = get_products()
        page = USER_PRODUCT_PAGE.get(uid, 0)
        p = products[page]
        session = USER_SESSIONS.get(uid, {"step": "weight", "basket": []})
        weight = data.replace("weight_", "")
        prices = {"3.5": p[4], "7": p[5], "14": p[6], "28": p[7], "56": p[8]}
        session["basket"].append({
            "name": p[1],
            "weight": weight,
            "price": prices[weight],
            "quantity": 1
        })
        session["step"] = "name"
        USER_SESSIONS[uid] = session
        text, total = basket_text(session["basket"])
        await q.edit_message_text(
            f"🛒 Basket:\n{text}\n💰 £{total}\n\nSend FULL NAME to checkout:"
        )
        return

    # User orders
    if data.startswith("my_orders_"):
        page = int(data.split("_")[-1])
        await show_user_order(update, context, uid, page)
        return

    # Review
    if data.startswith("review_"):
        oid = int(data.replace("review_", ""))
        USER_SESSIONS[uid] = {"step": "review", "order_id": oid}
        await q.message.reply_text("✍️ Send review as:\n`5 Amazing product`")
        return

    # Back
    if data == "back":
        await show_product_page(update, context, uid, USER_PRODUCT_PAGE.get(uid,0))
        return

    # Admin callbacks
    if data in ("admin_add_product", "admin_menu") or data.startswith(("admin_orders_", "paid_", "dispatch_")):
        await admin_callback(update, context)
        return

# ================= USER ORDERS =================
async def show_user_order(update, context, uid, page):
    cur.execute("SELECT * FROM orders WHERE user_id=? ORDER BY order_id DESC", (uid,))
    orders = cur.fetchall()
    if not orders:
        await update.callback_query.edit_message_text("📦 No orders yet.", reply_markup=main_menu(uid))
        return
    if page < 0: page = 0
    if page >= len(orders): page = len(orders)-1
    USER_ORDER_PAGE[uid] = page

    o = orders[page]
    oid, _, items, total, status, name, address = o
    items = json.loads(items)
    items_text = "\n".join([f"- {i['name']} {i['weight']}g x{i['quantity']}" for i in items])

    buttons = []
    if status in ("Paid", "Dispatched"):
        buttons.append([InlineKeyboardButton("⭐ Leave / Edit Review", callback_data=f"review_{oid}")])
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"my_orders_{page-1}"))
    if page < len(orders)-1:
        nav_buttons.append(InlineKeyboardButton("Next ➡️", callback_data=f"my_orders_{page+1}"))
    if nav_buttons:
        buttons.append(nav_buttons)
    buttons.append([InlineKeyboardButton("🏠 Back", callback_data="back")])

    await update.callback_query.edit_message_text(
        f"🧾 Order #{oid}\n{name}\n{address}\n{items_text}\n💰 £{total}\n📌 {status}",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

# ================= MESSAGE HANDLER =================
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    text = update.message.text

    # Checkout & review
    if uid in USER_SESSIONS:
        session = USER_SESSIONS[uid]
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
                f"✅ Order placed\n\n{items}\n💰 £{total}\n💳 Pay to:\n{CRYPTO_WALLET}"
            )
            return
        if session.get("step") == "review":
            try:
                stars, body = text.split(" ", 1)
                stars = int(stars)
                if not 1 <= stars <= 5:
                    raise ValueError
            except:
                await update.message.reply_text("❌ Format: `5 Amazing product`")
                return
            cur.execute(
                "INSERT OR REPLACE INTO reviews VALUES (?,?,?,?)",
                (session["order_id"], uid, stars, body)
            )
            db.commit()
            USER_SESSIONS.pop(uid)
            await update.message.reply_text("✅ Review saved! ⭐")
            return

# ================= APP =================
app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("admin", admin))
app.add_handler(CallbackQueryHandler(callback_router))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
app.add_handler(MessageHandler(filters.PHOTO, message_handler))

print("✅ BOT RUNNING")
app.run_polling()
