import os
import json
import sqlite3
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters
)

# ================= CONFIG =================
TOKEN = os.environ.get("TOKEN") or "PUT_YOUR_TOKEN_HERE"
CHANNEL_ID = -1003833257976
CRYPTO_WALLET = "LTC1qv4u6vr0gzp9g4lq0g3qev939vdnwxghn5gtnfc"

ADMINS = set()
USER_SESSIONS = {}   # basket, checkout, reviews, chat

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

# Contact messages table
cur.execute("""
CREATE TABLE IF NOT EXISTS contact_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    from_vendor INTEGER,
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
    buttons.append([InlineKeyboardButton("📝 My Reviews", callback_data="my_reviews")])
    buttons.append([InlineKeyboardButton("📩 Contact Donny", callback_data="contact_menu")])
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
    uid = update.effective_user.id
    if uid not in USER_SESSIONS:
        USER_SESSIONS[uid] = {}
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

    session = USER_SESSIONS.setdefault(q.from_user.id, {})
    session["step"] = "weight_select"
    session["current_product"] = {
        "id": p[0],
        "name": p[1],
        "description": p[2],
        "photo_file_id": p[3],
        "prices": {"3.5": p[4], "7": p[5], "14": p[6], "28": p[7], "56": p[8]}
    }

    buttons = [[InlineKeyboardButton(f"{w}g (£{price})", callback_data=f"weight_{w}")]
               for w, price in session["current_product"]["prices"].items()]

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
    session = USER_SESSIONS.get(uid, {})
    basket = session.get("basket", [])
    if not basket:
        await q.edit_message_text("🛒 Basket empty.", reply_markup=main_menu())
        return

    text, total = build_basket_text(basket)
    buttons = []
    for idx, item in enumerate(basket):
        buttons.append([
            InlineKeyboardButton(f"➕ {item['name']} x{item['quantity']}", callback_data=f"add_{idx}"),
            InlineKeyboardButton(f"➖ {item['name']} x{item['quantity']}", callback_data=f"remove_{idx}")
        ])
    buttons.append([InlineKeyboardButton("✅ Checkout", callback_data="checkout")])
    await context.bot.send_message(chat_id=uid, text=text, reply_markup=InlineKeyboardMarkup(buttons))

async def basket_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    session = USER_SESSIONS.get(uid, {})
    if not session or session.get("step") != "basket":
        await q.edit_message_text("❌ No basket active.")
        return

    data = q.data
    basket = session.get("basket", [])
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
        total = sum([item["price"]*item["quantity"] for item in session.get("basket", [])])
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

    items_json = json.dumps(session.get("basket", []))
    cur.execute("""INSERT INTO orders (user_id, items, total, status, name, address) VALUES (?, ?, ?, ?, ?, ?)""",
                (uid, items_json, session.get("total", 0), "Pending payment", session.get("name", ""), session.get("address", "")))
    db.commit()
    order_id = cur.lastrowid

    await q.edit_message_text(f"✅ Order #{order_id} placed!\n💳 Pay to LTC Wallet: {CRYPTO_WALLET}\nTotal: £{session.get('total', 0)}")
    await context.bot.send_message(CHANNEL_ID, f"🆕 ORDER #{order_id}\nUser: {session.get('name', '')}\nAddress: {session.get('address', '')}\nTotal: £{session.get('total', 0)}")
    session["basket"] = []
    session["step"] = None

# ================= MESSAGE HANDLER =================
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    text = update.message.text
    session = USER_SESSIONS.get(uid, {})

    # Review writing
    if session.get("step") == "writing_review":
        try:
            parts = text.strip().split(" ", 1)
            stars = int(parts[0])
            review_text = parts[1] if len(parts) > 1 else ""
            if not 1 <= stars <= 5:
                raise ValueError
        except:
            await update.message.reply_text("❌ Invalid format. Example: 5 Excellent product!")
            return

        cur.execute("INSERT OR REPLACE INTO reviews (order_id, user_id, stars, text) VALUES (?,?,?,?)",
                    (session["order_id"], uid, stars, review_text))
        db.commit()
        await update.message.reply_text(f"✅ Review saved! {stars}★\n\n{review_text}")
        session["step"] = None
        return

    # Checkout flow
    await checkout_handler(update, context)

# ================= SETUP HANDLERS =================
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(product_select, pattern="^prod_"))
    app.add_handler(CallbackQueryHandler(weight_select, pattern="^weight_"))
    app.add_handler(CallbackQueryHandler(basket_actions, pattern="^(add_|remove_|checkout)$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    app.run_polling()

if __name__ == "__main__":
    main()
