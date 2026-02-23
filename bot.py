import os
import json
import sqlite3
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto
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

TOKEN = "YOUR_BOT_TOKEN"
ADMINS = {123456789}
CONTACT_CHANNEL_ID = "@yourchannel"
CRYPTO_WALLET = "YOUR_CRYPTO_ADDRESS"

# ================= DATABASE =================

db = sqlite3.connect("shop.db", check_same_thread=False)
cur = db.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    description TEXT,
    photo TEXT,
    prices TEXT
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
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
    PRIMARY KEY(order_id, user_id)
)
""")

db.commit()

# ================= MEMORY =================

user_sessions = {}
admin_sessions = {}

# ================= HELPERS =================

def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛒 Products", callback_data="products")],
        [InlineKeyboardButton("📦 My Orders", callback_data="my_orders")],
        [InlineKeyboardButton("⭐ Reviews", callback_data="reviews")],
        [InlineKeyboardButton("📞 Contact", callback_data="contact")]
    ])

def get_products():
    cur.execute("SELECT * FROM products ORDER BY id DESC")
    return cur.fetchall()

def calculate_total(items):
    return sum(i["price"] * i["qty"] for i in items)

# ================= START =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Welcome to the shop.", reply_markup=main_menu())

# ================= ADMIN PANEL =================

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in ADMINS:
        await update.message.reply_text("Not authorised.")
        return

    await update.message.reply_text(
        "ADMIN PANEL",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Add Product", callback_data="admin_add")],
            [InlineKeyboardButton("📦 View Orders", callback_data="admin_orders")],
            [InlineKeyboardButton("📢 Announcement", callback_data="admin_announce")]
        ])
    )

# ================= CALLBACK ROUTER =================

async def callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    uid = q.from_user.id

    # ===== PRODUCTS =====
    if data == "products":
        products = get_products()
        if not products:
            await q.edit_message_text("No products available.", reply_markup=main_menu())
            return

        p = products[0]
        prices = json.loads(p[4])

        buttons = [
            [InlineKeyboardButton(f"{k}g £{v}", callback_data=f"buy_{p[0]}_{k}")]
            for k, v in prices.items()
        ]
        buttons.append([InlineKeyboardButton("🏠 Back", callback_data="home")])

        await q.edit_message_media(
            InputMediaPhoto(
                media=p[3],
                caption=f"{p[1]}\n\n{p[2]}"
            ),
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        return

    if data.startswith("buy_"):
        _, pid, weight = data.split("_")
        cur.execute("SELECT * FROM products WHERE id=?", (pid,))
        p = cur.fetchone()
        prices = json.loads(p[4])

        session = user_sessions.setdefault(uid, {"basket": []})
        session["basket"].append({
            "name": p[1],
            "weight": weight,
            "price": prices[weight],
            "qty": 1
        })

        total = calculate_total(session["basket"])
        await q.edit_message_text(
            f"Added to basket.\nTotal: £{total}\n\nSend FULL NAME to checkout."
        )
        session["step"] = "name"
        return

    # ===== ADMIN =====
    if data.startswith("admin_"):
        if uid not in ADMINS:
            await q.answer("Not authorised", show_alert=True)
            return

        if data == "admin_add":
            admin_sessions[uid] = {"step": "name"}
            await q.message.reply_text("Send product name:")
            return

        if data == "admin_orders":
            cur.execute("SELECT * FROM orders ORDER BY id DESC")
            orders = cur.fetchall()
            if not orders:
                await q.edit_message_text("No orders.")
                return

            o = orders[0]
            await q.edit_message_text(
                f"Order #{o[0]}\nStatus: {o[4]}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Mark Paid", callback_data=f"paid_{o[0]}")],
                    [InlineKeyboardButton("Mark Dispatched", callback_data=f"dispatch_{o[0]}")]
                ])
            )
            return

    if data.startswith("paid_"):
        oid = data.split("_")[1]
        cur.execute("UPDATE orders SET status='Paid' WHERE id=?", (oid,))
        db.commit()
        await q.edit_message_text(f"Order {oid} marked Paid")
        return

    if data.startswith("dispatch_"):
        oid = data.split("_")[1]
        cur.execute("UPDATE orders SET status='Dispatched' WHERE id=?", (oid,))
        db.commit()
        await q.edit_message_text(f"Order {oid} dispatched")
        return

# ================= MESSAGE HANDLER =================

async def messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    text = update.message.text

    # ===== ADMIN PRODUCT CREATION =====
    if uid in admin_sessions:
        session = admin_sessions[uid]

        if session["step"] == "name":
            session["name"] = text
            session["step"] = "desc"
            await update.message.reply_text("Send description:")
            return

        if session["step"] == "desc":
            session["desc"] = text
            session["step"] = "photo"
            await update.message.reply_text("Send photo:")
            return

        if session["step"] == "prices":
            try:
                parts = text.split(",")
                prices = {
                    "3.5": float(parts[0]),
                    "7": float(parts[1]),
                    "14": float(parts[2]),
                    "28": float(parts[3]),
                    "56": float(parts[4]),
                }
            except:
                await update.message.reply_text("Invalid format.")
                return

            cur.execute(
                "INSERT INTO products (name, description, photo, prices) VALUES (?,?,?,?)",
                (session["name"], session["desc"], session["photo"], json.dumps(prices))
            )
            db.commit()

            admin_sessions.pop(uid)
            await update.message.reply_text("Product added.")
            return

    # ===== PHOTO HANDLER FOR ADMIN =====
    if uid in admin_sessions and update.message.photo:
        session = admin_sessions[uid]
        if session["step"] == "photo":
            session["photo"] = update.message.photo[-1].file_id
            session["step"] = "prices"
            await update.message.reply_text("Send prices: 3.5,7,14,28,56")
            return

    # ===== CHECKOUT =====
    if uid in user_sessions:
        session = user_sessions[uid]

        if session.get("step") == "name":
            session["name"] = text
            session["step"] = "address"
            await update.message.reply_text("Send address:")
            return

        if session.get("step") == "address":
            session["address"] = text
            total = calculate_total(session["basket"])

            cur.execute(
                "INSERT INTO orders (user_id, items, total, status, name, address) VALUES (?,?,?,?,?,?)",
                (
                    uid,
                    json.dumps(session["basket"]),
                    total,
                    "Pending",
                    session["name"],
                    session["address"]
                )
            )
            db.commit()

            user_sessions.pop(uid)

            await update.message.reply_text(
                f"Order placed.\nTotal: £{total}\n\nPay to:\n{CRYPTO_WALLET}",
                reply_markup=main_menu()
            )
            return

# ================= APP =================

app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("admin", admin_panel))
app.add_handler(CallbackQueryHandler(callbacks))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, messages))
app.add_handler(MessageHandler(filters.PHOTO, messages))

print("Bot running...")
app.run_polling()
