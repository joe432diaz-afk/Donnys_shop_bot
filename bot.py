import os
import random
import sqlite3
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
USER_SESSIONS = {}
ADMIN_SESSIONS = {}

# ================= DATABASE =================
db = sqlite3.connect("shop.db", check_same_thread=False)
cur = db.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS products (
    id TEXT PRIMARY KEY,
    name TEXT,
    price REAL,
    photo TEXT
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS orders (
    order_id INTEGER PRIMARY KEY,
    user_id INTEGER,
    product_id TEXT,
    product_name TEXT,
    price REAL,
    status TEXT,
    name TEXT,
    address TEXT
)
""")
db.commit()

# ================= HELPERS =================
def get_products():
    cur.execute("SELECT id, name, price, photo FROM products")
    return cur.fetchall()

def main_menu():
    buttons = []
    for pid, name, price, _ in get_products():
        buttons.append([InlineKeyboardButton(f"{name} (£{price})", callback_data=f"prod_{pid}")])
    buttons.append([InlineKeyboardButton("📦 My Orders", callback_data="my_orders")])
    return InlineKeyboardMarkup(buttons)

# ================= START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🌿 Welcome\nSelect a product:", reply_markup=main_menu())

# ================= PRODUCT FLOW =================
async def product_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    pid = q.data.replace("prod_", "")
    cur.execute("SELECT name, price FROM products WHERE id=?", (pid,))
    product = cur.fetchone()

    if not product:
        await q.edit_message_text("❌ Product not found.", reply_markup=main_menu())
        return

    USER_SESSIONS[q.from_user.id] = {
        "product_id": pid,
        "product_name": product[0],
        "price": product[1],
        "step": "name"
    }

    await q.edit_message_text("✍️ Send your FULL NAME:")

# ================= TEXT HANDLER =================
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id

    # -------- ADMIN PRODUCT CREATION --------
    admin = ADMIN_SESSIONS.get(uid)
    if admin:
        if admin["step"] == "name":
            admin["name"] = update.message.text
            admin["step"] = "price"
            await update.message.reply_text("💰 Send product price:")
            return

        if admin["step"] == "price":
            try:
                admin["price"] = float(update.message.text)
            except:
                await update.message.reply_text("❌ Invalid price.")
                return
            admin["step"] = "photo"
            await update.message.reply_text("📷 Send product photo URL:")
            return

        if admin["step"] == "photo":
            pid = admin["name"].lower().replace(" ", "_")
            cur.execute(
                "INSERT OR REPLACE INTO products VALUES (?, ?, ?, ?)",
                (pid, admin["name"], admin["price"], update.message.text)
            )
            db.commit()
            ADMIN_SESSIONS.pop(uid)
            await update.message.reply_text("✅ Product added!", reply_markup=main_menu())
            return

    # -------- USER ORDER FLOW --------
    s = USER_SESSIONS.get(uid)
    if not s:
        await update.message.reply_text("❌ No active order.", reply_markup=main_menu())
        return

    if s["step"] == "name":
        s["name"] = update.message.text
        s["step"] = "address"
        await update.message.reply_text("📍 Send your FULL ADDRESS:")
        return

    if s["step"] == "address":
        s["address"] = update.message.text
        oid = random.randint(100000, 999999)

        cur.execute("""
        INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            oid,
            uid,
            s["product_id"],
            s["product_name"],
            s["price"],
            "Pending payment",
            s["name"],
            s["address"]
        ))
        db.commit()

        await update.message.reply_text(
            f"✅ ORDER #{oid}\n\n"
            f"{s['product_name']}\n"
            f"💰 £{s['price']}\n\n"
            f"💳 LTC ONLY:\n{CRYPTO_WALLET}"
        )

        await context.bot.send_message(
            CHANNEL_ID,
            f"🆕 ORDER #{oid}\n{s['product_name']} £{s['price']}\n{s['name']}\n{s['address']}"
        )

        USER_SESSIONS.pop(uid)

# ================= MY ORDERS =================
async def my_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    uid = q.from_user.id
    cur.execute("SELECT order_id, product_name, status FROM orders WHERE user_id=?", (uid,))
    rows = cur.fetchall()

    if not rows:
        await q.edit_message_text("📦 No orders.", reply_markup=main_menu())
        return

    text = "📦 Your Orders:\n\n"
    for oid, name, status in rows:
        text += f"#{oid} — {name}\nStatus: {status}\n\n"

    await q.edit_message_text(text, reply_markup=main_menu())

# ================= ADMIN =================
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

    if q.data == "admin_add_product":
        ADMIN_SESSIONS[uid] = {"step": "name"}
        await q.edit_message_text("➕ Send product NAME:")
        return

    if q.data == "admin_orders":
        cur.execute("SELECT order_id, product_name, status FROM orders")
        rows = cur.fetchall()

        if not rows:
            await q.edit_message_text("No orders.")
            return

        text = "📦 ORDERS:\n\n"
        buttons = []
        for oid, name, status in rows:
            text += f"#{oid} — {name} ({status})\n"
            buttons.append([
                InlineKeyboardButton("✅ Paid", callback_data=f"paid_{oid}"),
                InlineKeyboardButton("📦 Dispatch", callback_data=f"dispatch_{oid}")
            ])

        await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons))

    if q.data.startswith("paid_"):
        oid = int(q.data.replace("paid_", ""))
        cur.execute("UPDATE orders SET status='Paid' WHERE order_id=?", (oid,))
        db.commit()
        await q.edit_message_text(f"✅ Order #{oid} marked PAID")

    if q.data.startswith("dispatch_"):
        oid = int(q.data.replace("dispatch_", ""))
        cur.execute("UPDATE orders SET status='Dispatched' WHERE order_id=?", (oid,))
        db.commit()
        await q.edit_message_text(f"📦 Order #{oid} DISPATCHED")

# ================= APP =================
app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("admin", admin))

app.add_handler(CallbackQueryHandler(product_select, pattern="^prod_"))
app.add_handler(CallbackQueryHandler(my_orders, pattern="^my_orders$"))
app.add_handler(CallbackQueryHandler(admin_callback, pattern="^admin_"))
app.add_handler(CallbackQueryHandler(admin_callback, pattern="^(paid_|dispatch_)"))

app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

print("✅ BOT RUNNING")
app.run_polling()
