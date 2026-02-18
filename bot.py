import os
import json
import sqlite3
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)

# ================= CONFIG =================
TOKEN = "PUT_YOUR_TOKEN_HERE"
CHANNEL_ID = -1003833257976
CRYPTO_WALLET = "LTC1qv4u6vr0gzp9g4lq0g3qev939vdnwxghn5gtnfc"

ADMINS = {123456789}  # ← YOUR TELEGRAM USER ID
USER_SESSIONS = {}

# ================= DATABASE =================
db = sqlite3.connect("shop.db", check_same_thread=False)
cur = db.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS orders (
    order_id INTEGER PRIMARY KEY AUTOINCREMENT,
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
CREATE TABLE IF NOT EXISTS contact_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    from_vendor INTEGER,
    text TEXT
)
""")
db.commit()

# ================= HELPERS =================
def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛒 Place Order", callback_data="start_order")],
        [InlineKeyboardButton("📦 My Orders", callback_data="my_orders")],
        [InlineKeyboardButton("📝 My Reviews", callback_data="my_reviews")],
        [InlineKeyboardButton("💬 Contact Donny", callback_data="contact")]
    ])

# ================= START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Welcome 👋", reply_markup=main_menu())

# ================= ORDER FLOW =================
async def start_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    USER_SESSIONS[q.from_user.id] = {"step": "name"}
    await q.edit_message_text("Send your FULL NAME:")

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    text = update.message.text
    session = USER_SESSIONS.get(uid)

    if session:
        if session["step"] == "name":
            session["name"] = text
            session["step"] = "address"
            await update.message.reply_text("Send your FULL ADDRESS:")
            return

        if session["step"] == "address":
            session["address"] = text
            session["items"] = [{"name": "Product", "qty": 1, "price": 50}]
            session["total"] = 50
            session["step"] = "confirm"

            await update.message.reply_text(
                f"💳 Pay £50 to:\n{CRYPTO_WALLET}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Confirm Order", callback_data="confirm_order")]
                ])
            )
            return

        if session.get("chat"):
            cur.execute("INSERT INTO contact_messages VALUES (NULL,?,?,?)", (uid,0,text))
            db.commit()
            for admin in ADMINS:
                await context.bot.send_message(admin, f"💬 User {uid}: {text}")
            return

    # Review writing
    if session and session.get("review"):
        try:
            stars, msg = text.split(" ",1)
            stars = int(stars)
        except:
            await update.message.reply_text("Example: 5 Great product")
            return

        cur.execute(
            "INSERT OR REPLACE INTO reviews VALUES (?,?,?,?)",
            (session["order_id"], uid, stars, msg)
        )
        db.commit()
        USER_SESSIONS.pop(uid)
        await update.message.reply_text("✅ Review saved!")
        return

# ================= CONFIRM ORDER =================
async def confirm_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    s = USER_SESSIONS[uid]

    cur.execute(
        "INSERT INTO orders (user_id,items,total,status,name,address) VALUES (?,?,?,?,?,?)",
        (uid, json.dumps(s["items"]), s["total"], "Pending", s["name"], s["address"])
    )
    db.commit()
    order_id = cur.lastrowid

    admin_buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Mark Paid", callback_data=f"admin_paid_{order_id}"),
            InlineKeyboardButton("📦 Mark Dispatched", callback_data=f"admin_sent_{order_id}")
        ]
    ])

    for admin in ADMINS:
        await context.bot.send_message(
            admin,
            f"🆕 ORDER #{order_id}\n£{s['total']}\n{s['name']}\n{s['address']}",
            reply_markup=admin_buttons
        )

    await q.edit_message_text("✅ Order placed. Waiting for confirmation.")
    USER_SESSIONS.pop(uid)

# ================= ADMIN BUTTONS =================
async def admin_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.from_user.id not in ADMINS:
        await q.edit_message_text("❌ Not authorised")
        return

    if q.data.startswith("admin_paid_"):
        oid = int(q.data.split("_")[-1])
        cur.execute("UPDATE orders SET status='Paid' WHERE order_id=?", (oid,))
        db.commit()
        await q.edit_message_text(f"✅ Order #{oid} marked PAID")

    if q.data.startswith("admin_sent_"):
        oid = int(q.data.split("_")[-1])
        cur.execute("UPDATE orders SET status='Dispatched' WHERE order_id=?", (oid,))
        db.commit()
        await q.edit_message_text(f"📦 Order #{oid} DISPATCHED")

# ================= RUN =================
if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(start_order, pattern="^start_order$"))
    app.add_handler(CallbackQueryHandler(confirm_order, pattern="^confirm_order$"))
    app.add_handler(CallbackQueryHandler(admin_handler, pattern="^admin_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    print("BOT RUNNING")
    app.run_polling()
