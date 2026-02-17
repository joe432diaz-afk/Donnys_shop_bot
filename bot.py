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
USER_SESSIONS = {}   # Used for basket, checkout, ordering, reviews, chat
ADMIN_SESSIONS = {}  # Used for admin add product flow

# ================= DATABASE =================
db = sqlite3.connect("shop.db", check_same_thread=False)
cur = db.cursor()

# Products table
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

# Orders table
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

# Reviews table
cur.execute("""
CREATE TABLE IF NOT EXISTS reviews (
    order_id INTEGER PRIMARY KEY,
    user_id INTEGER,
    stars INTEGER,
    text TEXT
)
""")

# Chats table
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

# ================= START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🌿 Welcome to the shop!\nSelect a product:", reply_markup=main_menu())

# ================= PRODUCT SELECTION =================
async def product_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

# ================= WEIGHT SELECTION =================
async def weight_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

async def show_basket(q, context):
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

# ================= BASKET EDITING =================
async def basket_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        return

# ================= CHECKOUT =================
async def checkout_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        return

# ================= CONFIRM ORDER =================
async def confirm_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

# ================= MY ORDERS =================
async def my_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    cur.execute("SELECT order_id, items, total, status FROM orders WHERE user_id=?", (uid,))
    rows = cur.fetchall()
    if not rows:
        await q.edit_message_text("📦 No orders.", reply_markup=main_menu())
        return
    text = "📦 Your Orders:\n\n"
    for oid, items_json, total, status in rows:
        items = json.loads(items_json)
        items_str = ", ".join([f"{i['name']} {i['weight']}g x{i['quantity']}" for i in items])
        text += f"#{oid} — {items_str}\nStatus: {status}\nTotal: £{total}\n\n"
    # Add buttons to select an order
    buttons = [[InlineKeyboardButton(f"Order #{oid}", callback_data=f"order_{oid}")] for oid, _, _, _ in rows]
    buttons.append([InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_to_menu")])
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons))

# ================= ORDER DETAIL =================
async def order_detail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    oid = int(q.data.replace("order_", ""))
    cur.execute("SELECT items, total, status FROM orders WHERE order_id=?", (oid,))
    order = cur.fetchone()
    if not order:
        await q.edit_message_text("❌ Order not found.", reply_markup=main_menu())
        return
    items = json.loads(order[0])
    items_str = "\n".join([f"{i['name']} {i['weight']}g x{i['quantity']}" for i in items])
    text = f"📦 Order #{oid}\n\n{items_str}\n\nStatus: {order[2]}\nTotal: £{order[1]}"
    await q.edit_message_text(text, reply_markup=build_order_buttons(oid))

# ================= REVIEW HANDLERS =================
async def leave_edit_review(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    oid = int(q.data.replace("review_", ""))
    USER_SESSIONS[q.from_user.id] = {"step": "review", "order_id": oid}
    await q.edit_message_text("✍️ Send your review text (1–200 chars):")

async def view_review(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    oid = int(q.data.replace("viewreview_", ""))
    cur.execute("SELECT stars, text FROM reviews WHERE order_id=?", (oid,))
    review = cur.fetchone()
    if review:
        stars, text = review
        await q.edit_message_text(f"⭐ {stars}/5\n{text}", reply_markup=build_order_buttons(oid))
    else:
        await q.edit_message_text("❌ No review yet.", reply_markup=build_order_buttons(oid))

# ================= CHAT HANDLERS =================
async def open_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    oid = int(q.data.replace("chat_", ""))
    USER_SESSIONS[q.from_user.id] = {"step": "chat", "order_id": oid}
    # Fetch last 20 messages
    cur.execute("SELECT sender, message, timestamp FROM chats WHERE order_id=? ORDER BY timestamp ASC", (oid,))
    messages = cur.fetchall()
    text = f"💬 Chat for Order #{oid}:\n\n"
    for sender, msg, ts in messages:
        display_name = "Donny" if sender == "buyer" else "Vendor"
        text += f"{display_name}: {msg}\n"
    await q.edit_message_text(text, reply_markup=build_chat_buttons(oid))

async def send_chat_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    oid = int(q.data.replace("sendmsg_", ""))
    USER_SESSIONS[q.from_user.id] = {"step": "send_chat", "order_id": oid}
    await q.edit_message_text("✉️ Send your message:")

async def close_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    oid = int(q.data.replace("closechat_", ""))
    await q.edit_message_text("❌ Chat closed.", reply_markup=build_order_buttons(oid))

# ================= ADMIN PANEL =================
async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    ADMINS.add(uid)
    buttons = [
        [InlineKeyboardButton("➕ Add Product", callback_data="admin_add_product")],
        [InlineKeyboardButton("📦 View Orders", callback_data="admin_orders")]
    ]
    await update.message.reply_text("🛠 ADMIN PANEL", reply_markup=InlineKeyboardMarkup(buttons))

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    if uid not in ADMINS:
        await q.edit_message_text("❌ Not authorised.")
        return
    data = q.data
    if data == "admin_add_product":
        ADMIN_SESSIONS[uid] = {"step": "name"}
        await q.edit_message_text("➕ Send product NAME:")
        return
    if data.startswith("paid_") or data.startswith("dispatch_"):
        oid = int(data.split("_")[1])
        status = "Paid" if data.startswith("paid_") else "Dispatched"
        cur.execute("UPDATE orders SET status=? WHERE order_id=?", (status, oid))
        db.commit()
        cur.execute("SELECT user_id FROM orders WHERE order_id=?", (oid,))
        user_id = cur.fetchone()[0]
        await context.bot.send_message(user_id, f"✅ Your Order #{oid} status updated: {status}")
        await q.edit_message_text(f"✅ Order #{oid} status updated: {status}")
        return

# ================= MESSAGE HANDLER =================
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    # Admin product creation
    if uid in ADMIN_SESSIONS:
        admin = ADMIN_SESSIONS[uid]
        step = admin.get("step")
        if step == "name":
            admin["name"] = update.message.text
            admin["step"] = "description"
            await update.message.reply_text("📝 Send product DESCRIPTION:")
            return
        if step == "description":
            admin["description"] = update.message.text
            admin["step"] = "photo"
            await update.message.reply_text("📷 Send product PHOTO (as image, not URL):")
            return
        if step == "photo":
            if update.message.photo:
                admin["photo_file_id"] = update.message.photo[-1].file_id
                admin["step"] = "prices"
                await update.message.reply_text("💰 Send prices for 3.5,7,14,28,56 (comma-separated):")
                return
            else:
                await update.message.reply_text("❌ Send photo!")
                return
        if step == "prices":
            try:
                prices = list(map(float, update.message.text.split(",")))
                if len(prices) != 5: raise ValueError
            except:
                await update.message.reply_text("❌ Invalid format")
                return
            pid = admin["name"].lower().replace(" ","_")
            cur.execute("""
            INSERT OR REPLACE INTO products VALUES (?,?,?,?,?,?,?,?,?)
            """, (pid, admin["name"], admin["description"], admin["photo_file_id"], *prices))
            db.commit()
            ADMIN_SESSIONS.pop(uid)
            await update.message.reply_text("✅ Product added!", reply_markup=main_menu())
            return

    # User checkout
    session = USER_SESSIONS.get(uid)
    if session:
        step = session.get("step")
        # Reviews
        if step == "review":
            oid = session["order_id
