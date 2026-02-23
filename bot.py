import logging
import sqlite3
import requests
import os
from telegram import (
    InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup,
    KeyboardButton, Update
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, filters, ContextTypes
)

# Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ────────────────────────────────────────────────
# CONFIG
TOKEN = os.environ.get("TOKEN")
if not TOKEN:
    raise ValueError("TOKEN environment variable is not set! Add it in Railway Variables.")

ADMIN_IDS = [7773622161]
CHANNEL_ID = -1001234567890           # ← CHANGE THIS to your real channel ID
LTC_ADDRESS = 'YOUR_FIXED_LITECOIN_ADDRESS'  # ← CHANGE THIS

DB_FILE = 'bot.db'

# ────────────────────────────────────────────────
# DATABASE
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
                  status TEXT DEFAULT 'pending')''')
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
CHECKOUT_NAME, CHECKOUT_ADDRESS = range(2)
REVIEW_TEXT = 0

# ────────────────────────────────────────────────
# HELPERS
def get_ltc_price():
    try:
        r = requests.get('https://api.coingecko.com/api/v3/simple/price?ids=litecoin&vs_currencies=usd', timeout=8)
        return r.json()['litecoin']['usd']
    except Exception as e:
        logger.error(f"Failed to get LTC price: {e}")
        return 0

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
    kb = [
        [KeyboardButton("Products"), KeyboardButton("Basket")],
        [KeyboardButton("Reviews")]
    ]
    if is_admin:
        kb.append([KeyboardButton("Admin Panel")])
    return ReplyKeyboardMarkup(kb, resize_keyboard=True)

# ────────────────────────────────────────────────
# START COMMAND
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    is_admin = uid in ADMIN_IDS
    reviews = get_public_reviews()
    review_text = "\n\nPublic Reviews:\n" + "\n".join(f"• {r}" for r in reviews) if reviews else ""
    await update.message.reply_text(
        f"Welcome to the shop!{review_text}",
        reply_markup=main_menu_keyboard(is_admin)
    )

# ────────────────────────────────────────────────
# PRODUCTS LIST
async def show_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            [InlineKeyboardButton("Add to Basket", callback_data=f"add_{pid}"),
             InlineKeyboardButton("View", callback_data=f"view_{pid}")],
            [InlineKeyboardButton("Back", callback_data="back_main")]
        ])
        await update.message.reply_text(f"• {name} — ${price:.2f}", reply_markup=kb)

# ────────────────────────────────────────────────
# BUTTON / CALLBACK HANDLER
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
            reply_markup=ReplyKeyboardMarkup([[KeyboardButton("Cancel")]], resize
