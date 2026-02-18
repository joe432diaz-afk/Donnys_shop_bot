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
    order_id INTEGER PRIMARY KEY,
    user_id INTEGER,
    stars INTEGER,
    text TEXT
)
""")

db.commit()

# ================= HELPERS =================
def get_products():
    cur.execute("SELECT * FROM products")
    return cur.fetchall()

def main_menu():
    buttons = []
    for pid, name, *_ in get_products():
        buttons.append([InlineKeyboardButton(name, callback_data=f"prod_{pid}")])
    buttons.append([InlineKeyboardButton("🛒 Basket / Checkout", callback_data="basket")])
    buttons.append([InlineKeyboardButton("📦 My Orders", callback_data="my_orders")])
    return InlineKeyboardMarkup(buttons)

def build_basket_text(basket):
    total = 0
    text = "🛒 Your Basket:\n\n"
    for i, item in enumerate(basket, 1):
        cost = item["price"] * item["quantity"]
        total += cost
        text += f"{i}. {item['name']} {item['weight']}g x{item['quantity']} = £{cost}\n"
    text += f"\n💰 Total: £{total}"
    return text, total

# ================= START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🌿 Welcome!\nChoose a product:", reply_markup=main_menu())

# ================= ADMIN =================
async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ADMINS.add(update.effective_user.id)
    await update.message.reply_text(
        "🛠 ADMIN PANEL",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Add Product", callback_data="admin_add_product")],
            [InlineKeyboardButton("📦 View Orders", callback_data="admin_orders")]
        ])
    )

# ================= PRODUCT FLOW =================
async def product_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    pid = q.data.replace("prod_", "")

    cur.execute("SELECT * FROM products WHERE id=?", (pid,))
    p = cur.fetchone()
    if not p:
        await q.edit_message_text("❌ Product not found.")
        return

    USER_SESSIONS[q.from_user.id] = {
        "step": "weight",
        "product": {
            "id": p[0],
            "name": p[1],
            "prices": {"3.5": p[4], "7": p[5], "14": p[6], "28": p[7], "56": p[8]}
        },
        "basket": []
    }

    buttons = [
        [InlineKeyboardButton(f"{w}g £{price}", callback_data=f"weight_{w}")]
        for w, price in USER_SESSIONS[q.from_user.id]["product"]["prices"].items()
    ]

    await q.edit_message_text(
        f"📦 {p[1]}\nChoose weight:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def weight_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id

    session = USER_SESSIONS[uid]
    weight = q.data.replace("weight_", "")
    prod = session["product"]

    session["basket"].append({
        "name": prod["name"],
        "weight": weight,
        "price": prod["prices"][weight],
        "quantity": 1
    })

    session["step"] = "basket"
    await show_basket(uid, context)

async def show_basket(uid, context):
    basket = USER_SESSIONS[uid]["basket"]
    text, _ = build_basket_text(basket)

    buttons = []
    for i in range(len(basket)):
        buttons.append([
            InlineKeyboardButton("➕", callback_data=f"add_{i}"),
            InlineKeyboardButton("➖", callback_data=f"remove_{i}")
        ])

    buttons.append([InlineKeyboardButton("✅ Checkout", callback_data="checkout")])

    await context.bot.send_message(uid, text, reply_markup=InlineKeyboardMarkup(buttons))

# ================= BASKET =================
async def basket_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    basket = USER_SESSIONS[uid]["basket"]

    if q.data.startswith("add_"):
        basket[int(q.data[4:])]["quantity"] += 1
    elif q.data.startswith("remove_"):
        i = int(q.data[7:])
        basket[i]["quantity"] -= 1
        if basket[i]["quantity"] <= 0:
            basket.pop(i)
    elif q.data == "checkout":
        USER_SESSIONS[uid]["step"] = "name"
        await q.edit_message_text("✍️ Send your FULL NAME:")
        return

    await show_basket(uid, context)

# ================= CHECKOUT =================
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    text = update.message.text

    # Admin add product
    if uid in ADMIN_SESSIONS:
        admin = ADMIN_SESSIONS[uid]
        step = admin["step"]

        if step == "name":
            admin["name"] = text
            admin["step"] = "desc"
            await update.message.reply_text("📝 Description:")
            return

        if step == "desc":
            admin["desc"] = text
            admin["step"] = "prices"
            await update.message.reply_text("💰 Prices 3.5,7,14,28,56 (comma separated):")
            return

        if step == "prices":
            prices = list(map(float, text.split(",")))
            pid = admin["name"].lower().replace(" ", "_")
            cur.execute(
                "INSERT OR REPLACE INTO products VALUES (?,?,?,?,?,?,?,?,?)",
                (pid, admin["name"], admin["desc"], "", *prices)
            )
            db.commit()
            ADMIN_SESSIONS.pop(uid)
            await update.message.reply_text("✅ Product added", reply_markup=main_menu())
            return

    # User checkout
    session = USER_SESSIONS.get(uid)
    if not session:
        return

    if session["step"] == "name":
        session["name"] = text
        session["step"] = "address"
        await update.message.reply_text("📍 Address:")
        return

    if session["step"] == "address":
        session["address"] = text
        _, total = build_basket_text(session["basket"])
        cur.execute(
            "INSERT INTO orders VALUES (NULL,?,?,?,?,?,?)",
            (uid, json.dumps(session["basket"]), total, "Pending", session["name"], session["address"])
        )
        db.commit()
        USER_SESSIONS.pop(uid)
        await update.message.reply_text(f"✅ Order placed\nPay to: {CRYPTO_WALLET}")

# ================= ADMIN CALLBACK =================
async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id

    if uid not in ADMINS:
        await q.edit_message_text("❌ Not authorised")
        return

    if q.data == "admin_add_product":
        ADMIN_SESSIONS[uid] = {"step": "name"}
        await q.edit_message_text("🆕 Send product NAME:")
        return

    if q.data == "admin_orders":
        cur.execute("SELECT * FROM orders ORDER BY order_id DESC")
        for o in cur.fetchall():
            oid, _, _, total, status, name, address = o
            buttons = []
            if status != "Paid":
                buttons.append([InlineKeyboardButton("💰 Mark Paid", callback_data=f"paid_{oid}")])
            if status == "Paid":
                buttons.append([InlineKeyboardButton("📦 Dispatch", callback_data=f"dispatch_{oid}")])

            await q.message.reply_text(
                f"🧾 #{oid}\n{name}\n{address}\n£{total}\nStatus: {status}",
                reply_markup=InlineKeyboardMarkup(buttons)
            )
        return

    if q.data.startswith("paid_"):
        oid = int(q.data[5:])
        cur.execute("UPDATE orders SET status='Paid' WHERE order_id=?", (oid,))
        db.commit()
        await q.edit_message_text(f"✅ Order {oid} PAID")

    if q.data.startswith("dispatch_"):
        oid = int(q.data[9:])
        cur.execute("UPDATE orders SET status='Dispatched' WHERE order_id=?", (oid,))
        db.commit()
        await q.edit_message_text(f"📦 Order {oid} DISPATCHED")

# ================= APP =================
app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("admin", admin))

app.add_handler(CallbackQueryHandler(admin_callback, pattern="^(admin_|paid_|dispatch_)"))
app.add_handler(CallbackQueryHandler(product_select, pattern="^prod_"))
app.add_handler(CallbackQueryHandler(weight_select, pattern="^weight_"))
app.add_handler(CallbackQueryHandler(basket_actions, pattern="^(add_|remove_|checkout)"))

app.add_handler(MessageHandler(filters.PHOTO | filters.TEXT & ~filters.COMMAND, message_handler))

print("✅ BOT RUNNING")
app.run_polling()
