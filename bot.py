import os
import json
import sqlite3
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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
CHANNEL_ID = -1003833257976
CRYPTO_WALLET = "LTC1qv4u6vr0gzp9g4lq0g3qev939vdnwxghn5gtnfc"

ADMINS = set()
USER_SESSIONS = {}   # basket, checkout, reviews, chat sessions
ADMIN_SESSIONS = {}  # admin product flow

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
cur.execute("""
CREATE TABLE IF NOT EXISTS chats (
    chat_id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER,
    sender TEXT,
    message TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
)
""")
db.commit()

# ================= HELPERS =================
def get_products():
    cur.execute("SELECT * FROM products")
    return cur.fetchall()

def main_menu():
    buttons = []
    for pid, name, desc, photo_id, *_ in get_products():
        buttons.append([InlineKeyboardButton(f"{name}", callback_data=f"prod_{pid}")])
    buttons.append([InlineKeyboardButton("🛒 Basket / Checkout", callback_data="basket")])
    buttons.append([InlineKeyboardButton("📦 My Orders", callback_data="my_orders")])
    return InlineKeyboardMarkup(buttons)

def build_basket_text(basket):
    text = "🛒 Your Basket:\n\n"
    total = 0
    for idx, item in enumerate(basket, 1):
        text += f"{idx}. {item['name']} — {item['weight']}g x{item['quantity']} = £{item['price']*item['quantity']}\n"
        total += item['price']*item['quantity']
    text += f"\n💰 Total: £{total}"
    return text, total

def build_order_buttons(order_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 Contact Vendor", callback_data=f"chat_{order_id}")],
        [InlineKeyboardButton("✍️ Leave/Edit Review", callback_data=f"review_{order_id}")],
        [InlineKeyboardButton("👀 View Review", callback_data=f"viewreview_{order_id}")],
        [InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_to_menu")]
    ])

def build_chat_buttons(order_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📩 Send Message", callback_data=f"sendmsg_{order_id}")],
        [InlineKeyboardButton("❌ Close Chat", callback_data=f"closechat_{order_id}")]
    ])

def get_order_by_id(order_id, user_id=None):
    if user_id:
        cur.execute("SELECT * FROM orders WHERE order_id=? AND user_id=?", (order_id, user_id))
    else:
        cur.execute("SELECT * FROM orders WHERE order_id=?", (order_id,))
    return cur.fetchone()

# ================= START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await update.message.reply_text("🌿 Welcome to the shop!\nSelect a product:", reply_markup=main_menu())
    except Exception as e:
        print(f"Error in start: {e}")

# ================= ADMIN =================
async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        uid = update.effective_user.id
        ADMINS.add(uid)
        buttons = [
            [InlineKeyboardButton("➕ Add Product", callback_data="admin_add_product")],
            [InlineKeyboardButton("📦 View Orders", callback_data="admin_orders")]
        ]
        await update.message.reply_text("🛠 ADMIN PANEL", reply_markup=InlineKeyboardMarkup(buttons))
    except Exception as e:
        print(f"Error in admin: {e}")

# ================= PRODUCT SELECTION =================
async def product_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        q = update.callback_query
        await q.answer()
        pid = q.data.replace("prod_", "")
        cur.execute("SELECT * FROM products WHERE id=?", (pid,))
        p = cur.fetchone()
        if not p:
            await q.edit_message_text("❌ Product not found.", reply_markup=main_menu())
            return

        USER_SESSIONS[q.from_user.id] = {
            "step": "weight_select",
            "current_product": {
                "id": p[0],
                "name": p[1],
                "description": p[2],
                "photo_file_id": p[3],
                "prices": {
                    "3.5": p[4],
                    "7": p[5],
                    "14": p[6],
                    "28": p[7],
                    "56": p[8]
                }
            }
        }

        buttons = [[InlineKeyboardButton(f"{w}g (£{price})", callback_data=f"weight_{w}")] for w, price in USER_SESSIONS[q.from_user.id]["current_product"]["prices"].items()]

        await context.bot.send_photo(
            chat_id=q.from_user.id,
            photo=p[3],
            caption=f"📦 {p[1]}\n{p[2]}\n\nChoose weight:",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        await q.delete_message()
    except Exception as e:
        print(f"Error in product_select: {e}")

# ================= WEIGHT SELECTION =================
async def weight_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        q = update.callback_query
        await q.answer()
        uid = q.from_user.id
        session = USER_SESSIONS.get(uid)
        if not session or session.get("step") != "weight_select":
            await q.edit_message_text("❌ No product selected.")
            return

        weight = q.data.replace("weight_", "")
        prod = session["current_product"]
        price = prod["prices"][weight]
        basket_item = {"product_id": prod["id"], "name": prod["name"], "weight": weight, "quantity": 1, "price": price}

        basket = session.get("basket", [])
        basket.append(basket_item)
        session["basket"] = basket
        session["step"] = "basket"

        await show_basket(q, context)
    except Exception as e:
        print(f"Error in weight_select: {e}")

# ================= SHOW BASKET =================
async def show_basket(q, context):
    try:
        uid = q.from_user.id
        basket = USER_SESSIONS[uid]["basket"]
        text, total = build_basket_text(basket)

        buttons = []
        for idx, item in enumerate(basket):
            buttons.append([
                InlineKeyboardButton(f"➕ {item['name']} x{item['quantity']}", callback_data=f"add_{idx}"),
                InlineKeyboardButton(f"➖ {item['name']} x{item['quantity']}", callback_data=f"remove_{idx}")
            ])
        buttons.append([InlineKeyboardButton("✅ Checkout", callback_data="checkout")])
        await context.bot.send_message(chat_id=uid, text=text, reply_markup=InlineKeyboardMarkup(buttons))
    except Exception as e:
        print(f"Error in show_basket: {e}")

# ================= BASKET ACTIONS =================
async def basket_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        q = update.callback_query
        await q.answer()
        uid = q.from_user.id
        session = USER_SESSIONS.get(uid)
        if not session or session.get("step") != "basket":
            await q.edit_message_text("❌ No basket active.")
            return

        data = q.data
        basket = session["basket"]

        if data.startswith("add_"):
            idx = int(data.replace("add_", ""))
            basket[idx]["quantity"] += 1
            await show_basket(q, context)
            return
        elif data.startswith("remove_"):
            idx = int(data.replace("remove_", ""))
            basket[idx]["quantity"] -= 1
            if basket[idx]["quantity"] <= 0:
                basket.pop(idx)
            if not basket:
                session["step"] = None
                await q.edit_message_text("🛒 Basket empty.", reply_markup=main_menu())
                return
            await show_basket(q, context)
            return
        elif data == "checkout":
            session["step"] = "checkout_name"
            await q.edit_message_text("✍️ Send your FULL NAME for checkout:")
    except Exception as e:
        print(f"Error in basket_actions: {e}")

# ================= CHECKOUT =================
async def checkout_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        uid = update.message.from_user.id
        session = USER_SESSIONS.get(uid)
        if not session or not session.get("step"):
            return

        step = session["step"]
        if step == "checkout_name":
            session["name"] = update.message.text
            session["step"] = "checkout_address"
            await update.message.reply_text("📍 Send your FULL ADDRESS:")
            return
        elif step == "checkout_address":
            session["address"] = update.message.text
            total = sum([item["price"]*item["quantity"] for item in session["basket"]])
            session["total"] = total
            session["step"] = "checkout_confirm"
            text = build_basket_text(session["basket"])[0] + f"\n\n💳 Pay to LTC Wallet: {CRYPTO_WALLET}\nTotal: £{total}\n\nPress ✅ to confirm order."
            buttons = [[InlineKeyboardButton("✅ Confirm Order", callback_data="confirm_order")]]
            await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons))
    except Exception as e:
        print(f"Error in checkout_handler: {e}")

# ================= CONFIRM ORDER =================
async def confirm_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        q = update.callback_query
        await q.answer()
        uid = q.from_user.id
        session = USER_SESSIONS.get(uid)
        if not session or session.get("step") != "checkout_confirm":
            await q.edit_message_text("❌ No order to confirm.")
            return

        items_json = json.dumps(session["basket"])
        cur.execute("""
        INSERT INTO orders (user_id, items, total, status, name, address)
        VALUES (?, ?, ?, ?, ?, ?)
        """, (uid, items_json, session["total"], "Pending payment", session["name"], session["address"]))
        db.commit()
        order_id = cur.lastrowid

        await q.edit_message_text(f"✅ Order #{order_id} placed!\n💳 Pay to LTC Wallet: {CRYPTO_WALLET}\nTotal: £{session['total']}")
        await context.bot.send_message(CHANNEL_ID, f"🆕 ORDER #{order_id}\nUser: {session['name']}\nAddress: {session['address']}\nTotal: £{session['total']}")
        USER_SESSIONS.pop(uid)
    except Exception as e:
        print(f"Error in confirm_order: {e}")

# ================= APP =================
app = ApplicationBuilder().token(TOKEN).build()

# Command handlers
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("admin", admin))

# Callback handlers
app.add_handler(CallbackQueryHandler(product_select, pattern="^prod_"))
app.add_handler(CallbackQueryHandler(weight_select, pattern="^weight_"))
app.add_handler(CallbackQueryHandler(basket_actions, pattern="^(add_|remove_|checkout)"))
app.add_handler(CallbackQueryHandler(confirm_order, pattern="^confirm_order$"))

# Message handlers
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, checkout_handler))

print("✅ BOT RUNNING")
app.run_polling()
