import logging
import sqlite3
import json
import requests
from telegram import (
    InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove,
    KeyboardButton, Update, InputMediaPhoto
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, filters, ContextTypes
)

# Enable logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Config - Replace LTC_ADDRESS with your real wallet
TOKEN = 'TOKEN'
ADMIN_IDS = [7773622161]  # Your admin ID
CHANNEL_ID = -1001234567890  # ← CHANGE THIS to your real channel ID
LTC_ADDRESS = 'YOUR_FIXED_LITECOIN_ADDRESS'  # ← CHANGE THIS

# Database file
DB_FILE = 'bot.db'

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS products
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  name TEXT NOT NULL,
                  description TEXT NOT NULL,
                  price REAL NOT NULL,
                  photo_id TEXT NOT NULL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS baskets
                 (user_id INTEGER,
                  product_id INTEGER,
                  quantity INTEGER,
                  PRIMARY KEY (user_id, product_id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS orders
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER NOT NULL,
                  name TEXT,
                  address TEXT,
                  total REAL NOT NULL,
                  ltc_amount REAL NOT NULL,
                  status TEXT DEFAULT 'pending')''')  # pending, paid, dispatched
    c.execute('''CREATE TABLE IF NOT EXISTS order_items
                 (order_id INTEGER,
                  product_id INTEGER,
                  quantity INTEGER,
                  PRIMARY KEY (order_id, product_id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS reviews
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  product_id INTEGER NOT NULL,
                  user_id INTEGER NOT NULL,
                  text TEXT NOT NULL)''')
    conn.commit()
    conn.close()

init_db()

# States
ADMIN_NAME, ADMIN_DESC, ADMIN_PRICE, ADMIN_PHOTO = range(4)
CHECKOUT_NAME, CHECKOUT_ADDRESS, CHECKOUT_CONFIRM = range(3)
REVIEW_TEXT = range(1)

def get_ltc_price():
    try:
        response = requests.get('https://api.coingecko.com/api/v3/simple/price?ids=litecoin&vs_currencies=usd')
        return response.json()['litecoin']['usd']
    except:
        return 0  # fallback

def calculate_ltc_amount(total_usd):
    price = get_ltc_price()
    return total_usd / price if price > 0 else 0

def get_public_reviews(limit=5):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('SELECT text FROM reviews ORDER BY id DESC LIMIT ?', (limit,))
    rows = c.fetchall()
    conn.close()
    return [r[0] for r in rows]

def main_menu_keyboard(is_admin=False):
    keyboard = [
        [KeyboardButton("Products"), KeyboardButton("Basket")],
        [KeyboardButton("Reviews")]
    ]
    if is_admin:
        keyboard.append([KeyboardButton("Admin Panel")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    is_admin = user_id in ADMIN_IDS
    reviews = get_public_reviews()
    review_text = "\n\nPublic Reviews:\n" + "\n".join(f"• {r}" for r in reviews) if reviews else ""
    await update.message.reply_text(
        f"Welcome to the shop!{review_text}",
        reply_markup=main_menu_keyboard(is_admin)
    )

async def show_products(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('SELECT id, name, price FROM products')
    products = c.fetchall()
    conn.close()

    if not products:
        await update.message.reply_text("No products yet.", reply_markup=main_menu_keyboard())
        return

    for pid, name, price in products:
        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Add to Basket", callback_data=f"add_{pid}"),
                InlineKeyboardButton("View", callback_data=f"view_{pid}")
            ],
            [InlineKeyboardButton("Back", callback_data="back_main")]
        ])
        await update.message.reply_text(f"• {name} — ${price:.2f}", reply_markup=kb)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    data = query.data
    uid = query.from_user.id

    if data == "back_main":
        await query.message.delete()
        await start(update, context)
        return ConversationHandler.END

    if data.startswith("add_"):
        pid = int(data.split("_")[1])
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute(
            "INSERT INTO baskets (user_id, product_id, quantity) "
            "VALUES (?, ?, COALESCE((SELECT quantity FROM baskets WHERE user_id=? AND product_id=?) + 1, 1)) "
            "ON CONFLICT(user_id, product_id) DO UPDATE SET quantity = excluded.quantity",
            (uid, pid, uid, pid)
        )
        conn.commit()
        conn.close()
        await query.answer("Added ✓")

    if data.startswith("view_"):
        pid = int(data.split("_")[1])
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute('SELECT name, description, price, photo_id FROM products WHERE id=?', (pid,))
        row = c.fetchone()
        conn.close()
        if row:
            name, desc, price, photo = row
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("Add to Basket", callback_data=f"add_{pid}")],
                [InlineKeyboardButton("Reviews", callback_data=f"reviews_{pid}")],
                [InlineKeyboardButton("Back", callback_data="back_main")]
            ])
            await query.message.reply_photo(photo, f"{name}\n\n{desc}\n\n${price:.2f}", reply_markup=kb)

    if data.startswith("reviews_"):
        pid = int(data.split("_")[1])
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute('SELECT text FROM reviews WHERE product_id=? ORDER BY id DESC LIMIT 10', (pid,))
        reviews = [r[0] for r in c.fetchall()]
        conn.close()
        text = "Product Reviews:\n\n" + "\n".join(f"• {r}" for r in reviews) if reviews else "No reviews yet."
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("Write Review", callback_data=f"addreview_{pid}")],
            [InlineKeyboardButton("Back", callback_data=f"view_{pid}")]
        ])
        await query.message.reply_text(text, reply_markup=kb)

    if data.startswith("addreview_"):
        context.user_data["review_pid"] = int(data.split("_")[1])
        await query.message.reply_text(
            "Please write your review:",
            reply_markup=ReplyKeyboardMarkup([[KeyboardButton("Cancel")]], resize_keyboard=True)
        )
        return REVIEW_TEXT

    if data.startswith("remove_"):
        pid = int(data.split("_")[1])
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute('DELETE FROM baskets WHERE user_id=? AND product_id=?', (uid, pid))
        conn.commit()
        conn.close()
        await query.answer("Removed")
        await show_basket(update, context)

    if data == "checkout":
        await query.message.reply_text(
            "Full name for delivery:",
            reply_markup=ReplyKeyboardMarkup([[KeyboardButton("Cancel")]], resize_keyboard=True)
        )
        return CHECKOUT_NAME

    if data.startswith("order_mark_paid_"):
        oid = int(data.split("_")[-1])
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("UPDATE orders SET status = 'paid' WHERE id = ?", (oid,))
        conn.commit()
        conn.close()
        await query.answer("Marked as PAID")
        await show_admin_orders(update, context)

    if data.startswith("order_mark_dispatched_"):
        oid = int(data.split("_")[-1])
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("UPDATE orders SET status = 'dispatched' WHERE id = ?", (oid,))
        c.execute("SELECT name, address, total FROM orders WHERE id = ?", (oid,))
        name, addr, total = c.fetchone()
        c.execute("SELECT p.name, oi.quantity FROM order_items oi JOIN products p ON oi.product_id = p.id WHERE order_id = ?", (oid,))
        items = c.fetchall()
        conn.close()

        msg = (
            f"Order #{oid} DISPATCHED\n"
            f"Customer: {name}\n"
            f"Address: {addr}\n"
            f"Total: ${total:.2f}\n\n"
            "Items:\n" + "\n".join(f"• {n} × {q}" for n, q in items)
        )
        await context.bot.send_message(CHANNEL_ID, msg)
        await query.answer("Marked DISPATCHED + notified channel")
        await show_admin_orders(update, context)

    return ConversationHandler.END

async def show_basket(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    source = update.message or update.callback_query.message

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        "SELECT p.id, p.name, p.price, b.quantity "
        "FROM baskets b JOIN products p ON b.product_id = p.id "
        "WHERE b.user_id = ?",
        (uid,)
    )
    items = c.fetchall()
    conn.close()

    if not items:
        await source.reply_text("Your basket is empty.", reply_markup=main_menu_keyboard(uid in ADMIN_IDS))
        return

    total = 0
    lines = ["Your Basket:\n"]
    buttons = []
    for pid, name, price, qty in items:
        subtotal = price * qty
        total += subtotal
        lines.append(f"• {name} × {qty}  —  ${subtotal:.2f}")
        buttons.append([InlineKeyboardButton(f"Remove {name}", callback_data=f"remove_{pid}")])

    lines.append(f"\nTotal: ${total:.2f}")
    buttons.extend([
        [InlineKeyboardButton("Proceed to Checkout", callback_data="checkout")],
        [InlineKeyboardButton("Back", callback_data="back_main")]
    ])

    await source.reply_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(buttons))

async def show_reviews(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    reviews = get_public_reviews(10)
    text = "Recent Public Reviews:\n\n" + "\n".join(f"• {r}" for r in reviews) if reviews else "No reviews yet."
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="back_main")]])
    await update.message.reply_text(text, reply_markup=kb)

async def add_review_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if text in ("Cancel", "Back"):
        await update.message.reply_text("Cancelled.", reply_markup=main_menu_keyboard(update.effective_user.id in ADMIN_IDS))
        return ConversationHandler.END

    pid = context.user_data.get("review_pid")
    if not pid:
        await update.message.reply_text("Error. Try again.", reply_markup=main_menu_keyboard())
        return ConversationHandler.END

    uid = update.effective_user.id
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO reviews (product_id, user_id, text) VALUES (?, ?, ?)", (pid, uid, text))
    conn.commit()
    conn.close()

    await update.message.reply_text("Thank you! Review added.", reply_markup=main_menu_keyboard(uid in ADMIN_IDS))
    return ConversationHandler.END

async def checkout_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if text in ("Cancel", "Back"):
        await show_basket(update, context)
        return ConversationHandler.END
    context.user_data["checkout_name"] = text
    await update.message.reply_text("Delivery address:")
    return CHECKOUT_ADDRESS

async def checkout_address(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if text in ("Cancel", "Back"):
        await update.message.reply_text("Full name again:")
        return CHECKOUT_NAME

    uid = update.effective_user.id
    name = context.user_data.get("checkout_name")
    address = text

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        "SELECT SUM(p.price * b.quantity) FROM baskets b JOIN products p ON b.product_id = p.id WHERE user_id = ?",
        (uid,)
    )
    total = c.fetchone()[0] or 0.0

    ltc_amount = calculate_ltc_amount(total)

    c.execute(
        "INSERT INTO orders (user_id, name, address, total, ltc_amount) VALUES (?, ?, ?, ?, ?)",
        (uid, name, address, total, ltc_amount)
    )
    order_id = c.lastrowid

    c.execute("SELECT product_id, quantity FROM baskets WHERE user_id = ?", (uid,))
    for pid, qty in c.fetchall():
        c.execute("INSERT INTO order_items (order_id, product_id, quantity) VALUES (?, ?, ?)", (order_id, pid, qty))

    c.execute("DELETE FROM baskets WHERE user_id = ?", (uid,))
    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"Order #{order_id} created!\n"
        f"Total: ${total:.2f}\n"
        f"To pay: {ltc_amount:.8f} LTC\n"
        f"Address: {LTC_ADDRESS}\n\n"
        "Please send the exact amount.\nWe'll confirm payment manually.",
        reply_markup=main_menu_keyboard(uid in ADMIN_IDS)
    )
    return ConversationHandler.END

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    if uid not in ADMIN_IDS:
        await update.message.reply_text("No access.")
        return
    kb = ReplyKeyboardMarkup([
        [KeyboardButton("Add Product"), KeyboardButton("View Orders")],
        [KeyboardButton("Back")]
    ], resize_keyboard=True)
    await update.message.reply_text("Admin Panel", reply_markup=kb)

async def admin_add_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "Product name:",
        reply_markup=ReplyKeyboardMarkup([[KeyboardButton("Cancel")]], resize_keyboard=True)
    )
    return ADMIN_NAME

async def admin_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if text == "Cancel":
        await admin_panel(update, context)
        return ConversationHandler.END
    context.user_data["prod_name"] = text
    await update.message.reply_text("Description:")
    return ADMIN_DESC

async def admin_desc(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if text == "Cancel":
        await admin_panel(update, context)
        return ConversationHandler.END
    context.user_data["prod_desc"] = text
    await update.message.reply_text("Price (USD):")
    return ADMIN_PRICE

async def admin_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if text == "Cancel":
        await admin_panel(update, context)
        return ConversationHandler.END
    try:
        context.user_data["prod_price"] = float(text)
    except ValueError:
        await update.message.reply_text("Please enter a valid number for price:")
        return ADMIN_PRICE
    await update.message.reply_text("Send product photo:")
    return ADMIN_PHOTO

async def admin_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.text == "Cancel":
        await admin_panel(update, context)
        return ConversationHandler.END

    photo = update.message.photo
    if not photo:
        await update.message.reply_text("Please send a photo.")
        return ADMIN_PHOTO

    photo_id = photo[-1].file_id

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        "INSERT INTO products (name, description, price, photo_id) VALUES (?, ?, ?, ?)",
        (
            context.user_data["prod_name"],
            context.user_data["prod_desc"],
            context.user_data["prod_price"],
            photo_id
        )
    )
    conn.commit()
    conn.close()

    await update.message.reply_text("Product added successfully!", reply_markup=main_menu_keyboard(True))
    return ConversationHandler.END

async def show_admin_orders(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    if uid not in ADMIN_IDS:
        return

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT id, status FROM orders WHERE status != 'dispatched' ORDER BY id DESC")
    orders = c.fetchall()
    conn.close()

    if not orders:
        await update.message.reply_text("No active orders.", reply_markup=main_menu_keyboard(True))
        return

    for oid, status in orders:
        buttons = []
        if status == "pending":
            buttons.append(InlineKeyboardButton("Mark PAID", callback_data=f"order_mark_paid_{oid}"))
        if status in ("pending", "paid"):
            buttons.append(InlineKeyboardButton("Mark DISPATCHED", callback_data=f"order_mark_dispatched_{oid}"))

        kb = InlineKeyboardMarkup([buttons] if buttons else [], row_width=2)
        await update.message.reply_text(f"Order #{oid} — {status}", reply_markup=kb)

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text
    uid = update.effective_user.id
    is_admin = uid in ADMIN_IDS

    if text == "Products":
        await show_products(update, context)
    elif text == "Basket":
        await show_basket(update, context)
    elif text == "Reviews":
        await show_reviews(update, context)
    elif text == "Admin Panel" and is_admin:
        await admin_panel(update, context)
    elif text == "Add Product" and is_admin:
        return await admin_add_start(update, context)
    elif text == "View Orders" and is_admin:
        await show_admin_orders(update, context)
    elif text in ("Back", "Cancel"):
        await start(update, context)

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))

    # Main menu buttons
    app.add_handler(MessageHandler(filters.TEXT & \~filters.COMMAND, message_handler))

    # Callback buttons (add to basket, view, checkout, remove, etc.)
    app.add_handler(CallbackQueryHandler(button_handler))

    # Checkout flow
    checkout_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_handler)],
        states={
            CHECKOUT_NAME:    [MessageHandler(filters.TEXT & \~filters.COMMAND, checkout_name)],
            CHECKOUT_ADDRESS: [MessageHandler(filters.TEXT & \~filters.COMMAND, checkout_address)],
        },
        fallbacks=[],
        allow_reentry=True
    )
    app.add_handler(checkout_handler)

    # Review flow
    review_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_handler)],
        states={
            REVIEW_TEXT: [MessageHandler(filters.TEXT & \~filters.COMMAND, add_review_text)],
        },
        fallbacks=[],
        allow_reentry=True
    )
    app.add_handler(review_handler)

    # Admin add product flow
    product_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.TEXT & \~filters.COMMAND, message_handler)],
        states={
            ADMIN_NAME:  [MessageHandler(filters.TEXT & \~filters.COMMAND, admin_name)],
            ADMIN_DESC:  [MessageHandler(filters.TEXT & \~filters.COMMAND, admin_desc)],
            ADMIN_PRICE: [MessageHandler(filters.TEXT & \~filters.COMMAND, admin_price)],
            ADMIN_PHOTO: [MessageHandler(filters.PHOTO | (filters.TEXT & \~filters.COMMAND), admin_photo)],
        },
        fallbacks=[],
        allow_reentry=True
    )
    app.add_handler(product_handler)

    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
