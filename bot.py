import os
import json
import sqlite3
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)

TOKEN = os.environ.get("TOKEN") or "PUT_YOUR_TOKEN_HERE"
CHANNEL_ID = -1003833257976
CRYPTO_WALLET = "LTC1qv4u6vr0gzp9g4lq0g3qev939vdnwxghn5gtnfc"

ADMINS = set()
USER_SESSIONS = {}

# ================= DATABASE =================
db = sqlite3.connect("shop.db", check_same_thread=False)
cur = db.cursor()

cur.execute("""CREATE TABLE IF NOT EXISTS products (
    id TEXT PRIMARY KEY,
    name TEXT,
    description TEXT,
    photo_file_id TEXT,
    price_3_5 REAL,
    price_7 REAL,
    price_14 REAL,
    price_28 REAL,
    price_56 REAL
)""")

cur.execute("""CREATE TABLE IF NOT EXISTS orders (
    order_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    items TEXT,
    total REAL,
    status TEXT,
    name TEXT,
    address TEXT
)""")

cur.execute("""CREATE TABLE IF NOT EXISTS reviews (
    order_id INTEGER,
    user_id INTEGER,
    stars INTEGER,
    text TEXT,
    PRIMARY KEY (order_id, user_id)
)""")

cur.execute("""CREATE TABLE IF NOT EXISTS contact_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    from_vendor INTEGER,
    text TEXT
)""")

db.commit()

# ================= HELPERS =================
def get_products():
    cur.execute("SELECT * FROM products")
    return cur.fetchall()

def main_menu():
    buttons = []
    for pid, name, *_ in get_products():
        buttons.append([InlineKeyboardButton(name, callback_data=f"prod_{pid}")])
    buttons += [
        [InlineKeyboardButton("🛒 Basket / Checkout", callback_data="basket")],
        [InlineKeyboardButton("📦 My Orders", callback_data="my_orders")],
        [InlineKeyboardButton("📝 My Reviews", callback_data="my_reviews")],
        [InlineKeyboardButton("📩 Contact Donny", callback_data="contact_menu")]
    ]
    return InlineKeyboardMarkup(buttons)

def build_basket(uid):
    basket = USER_SESSIONS.get(uid, {}).get("basket", [])
    text = "🛒 Your Basket:\n\n"
    total = 0
    for i, item in enumerate(basket, 1):
        cost = item["price"] * item["quantity"]
        total += cost
        text += f"{i}. {item['name']} {item['weight']}g x{item['quantity']} = £{cost}\n"
    return text + f"\n💰 Total: £{total}", total

# ================= START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    USER_SESSIONS.setdefault(update.effective_user.id, {})
    await update.message.reply_text("🌿 Welcome!", reply_markup=main_menu())

# ================= PRODUCT =================
async def product_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    pid = q.data.replace("prod_", "")
    cur.execute("SELECT * FROM products WHERE id=?", (pid,))
    p = cur.fetchone()
    if not p:
        await q.edit_message_text("❌ Product not found", reply_markup=main_menu())
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

    buttons = [[InlineKeyboardButton(f"{w}g £{pr}", callback_data=f"weight_{w}")]
               for w, pr in USER_SESSIONS[q.from_user.id]["product"]["prices"].items()]

    await q.edit_message_text(
        f"📦 {p[1]}\n\nChoose weight:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def weight_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    session = USER_SESSIONS.get(uid)

    if not session:
        await q.edit_message_text("❌ Session expired")
        return

    weight = q.data.replace("weight_", "")
    prod = session["product"]

    session["basket"].append({
        "product_id": prod["id"],
        "name": prod["name"],
        "weight": weight,
        "quantity": 1,
        "price": prod["prices"][weight]
    })

    session["step"] = "basket"
    await show_basket(update, context)

async def show_basket(update, context):
    uid = update.effective_user.id
    text, _ = build_basket(uid)

    buttons = [
        [InlineKeyboardButton("➕", callback_data=f"add_{i}"),
         InlineKeyboardButton("➖", callback_data=f"remove_{i}")]
        for i in range(len(USER_SESSIONS[uid]["basket"]))
    ]
    buttons.append([InlineKeyboardButton("✅ Checkout", callback_data="checkout")])

    await context.bot.send_message(uid, text, reply_markup=InlineKeyboardMarkup(buttons))

# ================= BASKET =================
async def basket_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    basket = USER_SESSIONS.get(uid, {}).get("basket", [])

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

    await show_basket(update, context)

# ================= CHECKOUT =================
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    session = USER_SESSIONS.get(uid)

    if not session:
        return

    if session.get("step") == "name":
        session["name"] = update.message.text
        session["step"] = "address"
        await update.message.reply_text("📍 Send your ADDRESS:")
    elif session.get("step") == "address":
        session["address"] = update.message.text
        text, total = build_basket(uid)
        session["total"] = total
        session["step"] = "confirm"
        await update.message.reply_text(
            f"{text}\n\n💳 Pay to:\n{CRYPTO_WALLET}",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("✅ Confirm Order", callback_data="confirm")]]
            )
        )

async def confirm_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    s = USER_SESSIONS.get(uid)

    cur.execute(
        "INSERT INTO orders (user_id, items, total, status, name, address) VALUES (?,?,?,?,?,?)",
        (uid, json.dumps(s["basket"]), s["total"], "Pending", s["name"], s["address"])
    )
    db.commit()

    await q.edit_message_text("✅ Order placed!")
    USER_SESSIONS.pop(uid, None)

# ================= APP =================
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(product_select, pattern="^prod_"))
    app.add_handler(CallbackQueryHandler(weight_select, pattern="^weight_"))
    app.add_handler(CallbackQueryHandler(basket_actions, pattern="^(add_|remove_|checkout)$"))
    app.add_handler(CallbackQueryHandler(confirm_order, pattern="^confirm$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    app.run_polling()

if __name__ == "__main__":
    main()
