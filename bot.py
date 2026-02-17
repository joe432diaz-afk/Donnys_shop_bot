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
    description TEXT,
    photo_file_id TEXT,
    price_3_5 REAL,
    price_7 REAL,
    price_14 REAL,
    price_28 REAL,
    price_58 REAL
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS orders (
    order_id INTEGER PRIMARY KEY,
    user_id INTEGER,
    product_id TEXT,
    product_name TEXT,
    weight TEXT,
    price REAL,
    status TEXT,
    name TEXT,
    address TEXT
)
""")
db.commit()

# ================= HELPERS =================
def get_products():
    cur.execute("SELECT id, name, description, photo_file_id, price_3_5 FROM products")
    return cur.fetchall()

def main_menu():
    buttons = []
    for pid, name, desc, photo_id, price in get_products():
        buttons.append([InlineKeyboardButton(f"{name} (£{price})", callback_data=f"prod_{pid}")])
    buttons.append([InlineKeyboardButton("📦 My Orders", callback_data="my_orders")])
    return InlineKeyboardMarkup(buttons)

# ================= START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🌿 Welcome\nSelect a product:", reply_markup=main_menu())

# ================= PRODUCT SELECTION =================
async def product_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    pid = q.data.replace("prod_", "")
    cur.execute(
        "SELECT name, description, price_3_5, price_7, price_14, price_28, price_58, photo_file_id FROM products WHERE id=?",
        (pid,)
    )
    product = cur.fetchone()

    if not product:
        await q.edit_message_text("❌ Product not found.", reply_markup=main_menu())
        return

    # Save session
    USER_SESSIONS[q.from_user.id] = {
        "product_id": pid,
        "product_name": product[0],
        "description": product[1],
        "photo_file_id": product[7],
        "prices": {
            "3.5": product[2],
            "7": product[3],
            "14": product[4],
            "28": product[5],
            "58": product[6]
        },
        "step": "weight"
    }

    # Weight selection buttons
    buttons = [
        [InlineKeyboardButton(f"{w}g (£{p})", callback_data=f"weight_{w}")] 
        for w, p in USER_SESSIONS[q.from_user.id]["prices"].items()
    ]

    # Send photo with description and buttons
    await context.bot.send_photo(
        chat_id=q.from_user.id,
        photo=USER_SESSIONS[q.from_user.id]["photo_file_id"],
        caption=f"📦 {product[0]}\n{product[1]}\n\nChoose weight:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

    # Delete the previous message to keep chat clean
    await q.delete_message()

# ================= WEIGHT SELECTION =================
async def weight_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    s = USER_SESSIONS.get(uid)

    if not s or s.get("step") != "weight":
        await q.edit_message_text("❌ No active product selection.")
        return

    weight = q.data.replace("weight_", "")
    s["weight"] = weight
    s["price"] = s["prices"][weight]
    s["step"] = "name"
    await q.edit_message_text(f"💰 Selected {weight}g — £{s['price']}\n\nSend your FULL NAME:")

# ================= TEXT HANDLER =================
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id

    # -------- ADMIN PRODUCT CREATION --------
    admin = ADMIN_SESSIONS.get(uid)
    if admin:
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
                photo_file = update.message.photo[-1].file_id
                admin["photo_file_id"] = photo_file
                admin["step"] = "prices"
                await update.message.reply_text(
                    "💰 Send product prices for each weight in the format:\n"
                    "3.5,7,14,28,58 (comma separated, e.g., 10,20,35,60,100)"
                )
                return
            else:
                await update.message.reply_text("❌ Please send a photo, not text or URL.")
                return

        if step == "prices":
            try:
                prices = list(map(float, update.message.text.split(",")))
                if len(prices) != 5:
                    raise ValueError
            except:
                await update.message.reply_text("❌ Invalid format. Send 5 comma-separated numbers.")
                return

            admin["price_3_5"], admin["price_7"], admin["price_14"], admin["price_28"], admin["price_58"] = prices
            pid = admin["name"].lower().replace(" ", "_")
            cur.execute("""
            INSERT OR REPLACE INTO products VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                pid,
                admin["name"],
                admin["description"],
                admin["photo_file_id"],
                admin["price_3_5"],
                admin["price_7"],
                admin["price_14"],
                admin["price_28"],
                admin["price_58"]
            ))
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
        INSERT INTO orders (order_id, user_id, product_id, product_name, weight, price, status, name, address)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            oid,
            uid,
            s["product_id"],
            s["product_name"],
            s["weight"],
            s["price"],
            "Pending payment",
            s["name"],
            s["address"]
        ))
        db.commit()

        await update.message.reply_text(
            f"✅ ORDER #{oid}\n\n"
            f"{s['product_name']} — {s['weight']}g\n"
            f"💰 £{s['price']}\n\n"
            f"💳 LTC ONLY:\n{CRYPTO_WALLET}"
        )

        await context.bot.send_message(
            CHANNEL_ID,
            f"🆕 ORDER #{oid}\n{s['product_name']} — {s['weight']}g £{s['price']}\n{s['name']}\n{s['address']}"
        )

        USER_SESSIONS.pop(uid)

# ================= MY ORDERS =================
async def my_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    cur.execute("SELECT order_id, product_name, weight, status FROM orders WHERE user_id=?", (uid,))
    rows = cur.fetchall()

    if not rows:
        await q.edit_message_text("📦 No orders.", reply_markup=main_menu())
        return

    text = "📦 Your Orders:\n\n"
    for oid, name, weight, status in rows:
        text += f"#{oid} — {name} ({weight}g)\nStatus: {status}\n\n"

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
        cur.execute("SELECT order_id, product_name, weight, status FROM orders")
        rows = cur.fetchall()

        if not rows:
            await q.edit_message_text("No orders.")
            return

        text = "📦 ORDERS:\n\n"
        buttons = []
        for oid, name, weight, status in rows:
            text += f"#{oid} — {name} ({weight}g) ({status})\n"
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
app.add_handler(CallbackQueryHandler(weight_select, pattern="^weight_"))
app.add_handler(CallbackQueryHandler(my_orders, pattern="^my_orders$"))
app.add_handler(CallbackQueryHandler(admin_callback, pattern="^admin_"))
app.add_handler(CallbackQueryHandler(admin_callback, pattern="^(paid_|dispatch_)"))

app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
app.add_handler(MessageHandler(filters.PHOTO, text_handler))  # handle photos

print("✅ BOT RUNNING")
app.run_polling()
