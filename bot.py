import os
import json
import sqlite3
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters
)

# ================= CONFIG =================
TOKEN = os.environ.get("TOKEN") or "PUT_YOUR_TOKEN_HERE"
CHANNEL_ID = -1003833257976
CRYPTO_WALLET = "LTC1qv4u6vr0gzp9g4lq0g3qev939vdnwxghn5gtnfc"

ADMINS = set()
USER_SESSIONS = {}   # basket, checkout, reviews sessions
ADMIN_SESSIONS = {}  # admin product flow

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

# ================= START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🌿 Welcome to the shop!\nSelect a product:", reply_markup=main_menu())

# ================= ADMIN =================
async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    ADMINS.add(uid)
    buttons = [
        [InlineKeyboardButton("➕ Add Product", callback_data="admin_add_product")],
        [InlineKeyboardButton("📦 View Orders", callback_data="admin_orders")]
    ]
    await update.message.reply_text("🛠 ADMIN PANEL", reply_markup=InlineKeyboardMarkup(buttons))

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
            "prices": {"3.5": p[4], "7": p[5], "14": p[6], "28": p[7], "56": p[8]}
        }
    }

    buttons = [[InlineKeyboardButton(f"{w}g (£{price})", callback_data=f"weight_{w}")] for w, price in USER_SESSIONS[q.from_user.id]["current_product"]["prices"].items()]

    await context.bot.send_photo(chat_id=q.from_user.id, photo=p[3],
                                 caption=f"📦 {p[1]}\n{p[2]}\n\nChoose weight:",
                                 reply_markup=InlineKeyboardMarkup(buttons))
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

# ================= SHOW BASKET =================
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

# ================= BASKET ACTIONS =================
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

# ================= MY ORDERS (FIXED) =================
async def my_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    cur.execute("SELECT * FROM orders WHERE user_id=?", (uid,))
    orders = cur.fetchall()
    if not orders:
        await q.edit_message_text("📦 No orders yet.", reply_markup=main_menu())
        return

    # Build text with all orders
    text = "📦 Your Orders:\n\n"
    for order in orders:
        items = json.loads(order[2])
        items_str = ", ".join([f"{i['name']} {i['weight']}g x{i['quantity']}" for i in items])
        text += f"#{order[0]} — {items_str}\nStatus: {order[4]}\nTotal: £{order[3]}\n\n"

    # Only show review buttons for Paid orders
    buttons = []
    for order in orders:
        if order[4] == "Paid":
            buttons.append([InlineKeyboardButton(f"✍️ Leave/Edit Review #{order[0]}", callback_data=f"review_{order[0]}")])
            buttons.append([InlineKeyboardButton(f"👀 View Review #{order[0]}", callback_data=f"viewreview_{order[0]}")])

    buttons.append([InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_to_menu")])
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons))

# ================= REVIEWS HANDLER =================
async def review_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    data = q.data
    if data.startswith("review_"):
        oid = int(data.replace("review_", ""))
        cur.execute("SELECT stars, text FROM reviews WHERE order_id=? AND user_id=?", (oid, uid))
        r = cur.fetchone()
        USER_SESSIONS[uid] = {"step": "writing_review", "order_id": oid, "existing": r}
        if r:
            await q.edit_message_text(f"📝 Edit your review (current {r[0]}★):\n\n{r[1]}")
        else:
            await q.edit_message_text("📝 Write your review (1-5 stars + text). Example: 5 Excellent product!")
    elif data.startswith("viewreview_"):
        oid = int(data.replace("viewreview_", ""))
        cur.execute("SELECT stars, text FROM reviews WHERE order_id=? AND user_id=?", (oid, uid))
        r = cur.fetchone()
        if r:
            await q.edit_message_text(f"⭐ {r[0]} stars\n\n{r[1]}", reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Back to Orders", callback_data="my_orders")]
            ]))
        else:
            await q.edit_message_text("❌ No review yet for this order.", reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Back to Orders", callback_data="my_orders")]
            ]))
    elif data == "back_to_menu":
        await q.edit_message_text("Back to menu:", reply_markup=main_menu())

# ================= MESSAGE HANDLER =================
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    text = update.message.text

    # Admin Add Product Flow
    if uid in ADMIN_SESSIONS:
        admin = ADMIN_SESSIONS[uid]
        step = admin.get("step")
        if step == "name":
            admin["name"] = text
            admin["step"] = "description"
            await update.message.reply_text("📝 Send product DESCRIPTION:")
            return
        if step == "description":
            admin["description"] = text
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
                await update.message.reply_text("❌ Send a photo!")
                return
        if step == "prices":
            try:
                prices = list(map(float, text.split(",")))
                if len(prices) !=5: raise ValueError
            except:
                await update.message.reply_text("❌ Invalid format")
                return
            pid = admin["name"].lower().replace(" ","_")
            cur.execute("INSERT OR REPLACE INTO products VALUES (?,?,?,?,?,?,?,?,?)",
                        (pid, admin["name"], admin["description"], admin["photo_file_id"], *prices))
            db.commit()
            ADMIN_SESSIONS.pop(uid)
            await update.message.reply_text("✅ Product added!", reply_markup=main_menu())
            return

    # Checkout flow
    await checkout_handler(update, context)

    # Review writing flow
    if uid in USER_SESSIONS and USER_SESSIONS[uid].get("step") == "writing_review":
        session = USER_SESSIONS[uid]
        oid = session["order_id"]
        try:
            parts = text.strip().split(" ",1)
            stars = int(parts[0])
            review_text = parts[1] if len(parts)>1 else ""
            if not 1<=stars<=5:
                raise ValueError
        except:
            await update.message.reply_text("❌ Invalid format. Example: 5 Excellent product!")
            return
        cur.execute("INSERT OR REPLACE INTO reviews (order_id, user_id, stars, text) VALUES (?,?,?,?)",
                    (oid, uid, stars, review_text))
        db.commit()
        await update.message.reply_text(f"✅ Review saved! {stars}★\n\n{review_text}")
        USER_SESSIONS.pop(uid)

# ================= ADMIN CALLBACK =================
async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    if uid not in ADMINS:
        await q.edit_message_text("❌ Not authorised.")
        return
    data = q.data
    if data.startswith("paid_"):
        oid = int(data.replace("paid_",""))
        cur.execute("UPDATE orders SET status='Paid' WHERE order_id=?",(oid,))
        db.commit()
        cur.execute("SELECT user_id FROM orders WHERE order_id=?",(oid,))
        user_id = cur.fetchone()[0]
        await context.bot.send_message(user_id,f"✅ Your Order #{oid} is now PAID. You can now leave a review!")
        await q.edit_message_text(f"✅ Order #{oid} marked PAID")
        return
    if data.startswith("dispatch_"):
        oid = int(data.replace("dispatch_",""))
        cur.execute("UPDATE orders SET status='Dispatched' WHERE order_id=?",(oid,))
        db.commit()
        cur.execute("SELECT user_id FROM orders WHERE order_id=?",(oid,))
        user_id = cur.fetchone()[0]
        await context.bot.send_message(user_id,f"📦 Your Order #{oid} is DISPATCHED")
        await q.edit_message_text(f"📦 Order #{oid} DISPATCHED")
        return

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
app.add_handler(CallbackQueryHandler(admin_callback, pattern="^(admin_|paid_|dispatch_|admin_orders)"))
app.add_handler(CallbackQueryHandler(my_orders, pattern="^my_orders$"))
app.add_handler(CallbackQueryHandler(review_handler, pattern="^(review_|viewreview_|back_to_menu)"))

# Message handlers
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
app.add_handler(MessageHandler(filters.PHOTO, message_handler))

print("✅ BOT RUNNING WITH FIXED REVIEWS & BACK BUTTON")
app.run_polling()
