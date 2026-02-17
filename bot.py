import json
from pathlib import Path
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

TOKEN = "PUT_YOUR_BOT_TOKEN_HERE"
ADMIN_ID = 123456789  # ← YOUR TELEGRAM USER ID

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

ORDERS_FILE = DATA_DIR / "orders.json"
REVIEWS_FILE = DATA_DIR / "reviews.json"

def load_json(path, default):
    try:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        print("Load error:", e)
    return default

def save_json(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print("Save error:", e)

orders = {int(k): v for k, v in load_json(ORDERS_FILE, {}).items()}
reviews = load_json(REVIEWS_FILE, [])

user_states = {}

def next_order_id():
    return max(orders.keys(), default=1000) + 1

# ───────── USER ─────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [
        [InlineKeyboardButton("🛒 Place Order", callback_data="order")],
        [InlineKeyboardButton("📦 My Orders", callback_data="my_orders")],
    ]
    await update.message.reply_text(
        "Welcome. Choose an option:",
        reply_markup=InlineKeyboardMarkup(kb),
    )

async def user_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.data == "order":
        user_states[q.from_user.id] = {}
        await q.message.reply_text("Send your delivery address:")

    elif q.data == "my_orders":
        uid = q.from_user.id
        text = ""
        for oid, o in orders.items():
            if o["user_id"] == uid:
                text += f"🆔 {oid}\nStatus: {o['status']}\n\n"
        await q.message.reply_text(text or "No orders yet.")

    elif q.data.startswith("paid_"):
        oid = int(q.data.split("_")[1])
        orders[oid]["status"] = "Paid – awaiting dispatch"
        save_json(ORDERS_FILE, orders)

        await context.bot.send_message(
            orders[oid]["user_id"],
            f"✅ Order {oid} marked as PAID.",
        )
        await q.message.reply_text(f"Order {oid} marked paid.")

    elif q.data.startswith("dispatch_"):
        oid = int(q.data.split("_")[1])
        orders[oid]["status"] = "Dispatched"
        save_json(ORDERS_FILE, orders)

        await context.bot.send_message(
            orders[oid]["user_id"],
            f"📦 Order {oid} has been DISPATCHED.",
        )
        await q.message.reply_text(f"Order {oid} dispatched.")

    elif q.data.startswith("review_"):
        oid = int(q.data.split("_")[1])
        user_states[q.from_user.id] = {"review_order": oid}
        await q.message.reply_text("Send your review text:")

# ───────── TEXT INPUT ─────────

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id

    if uid in user_states and "review_order" in user_states[uid]:
        oid = user_states[uid]["review_order"]
        text = update.message.text

        existing = next((r for r in reviews if r["order_id"] == oid), None)
        if existing:
            existing["text"] = text
        else:
            reviews.append({"order_id": oid, "user_id": uid, "text": text})

        save_json(REVIEWS_FILE, reviews)
        user_states.pop(uid)
        await update.message.reply_text("⭐ Review saved (you can edit anytime).")
        return

    if uid in user_states:
        address = update.message.text
        oid = next_order_id()
        orders[oid] = {
            "user_id": uid,
            "address": address,
            "status": "Awaiting payment",
        }
        save_json(ORDERS_FILE, orders)
        user_states.pop(uid)

        admin_kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✔ Mark Paid", callback_data=f"paid_{oid}"),
                InlineKeyboardButton("📦 Dispatch", callback_data=f"dispatch_{oid}"),
            ]
        ])

        await context.bot.send_message(
            ADMIN_ID,
            f"New order {oid}\nAddress:\n{address}",
            reply_markup=admin_kb,
        )

        await update.message.reply_text(
            f"Order placed.\nOrder ID: {oid}\nSend payment when ready.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Leave / Edit Review", callback_data=f"review_{oid}")]
            ]),
        )

# ───────── MAIN ─────────

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(user_buttons))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    print("Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()
