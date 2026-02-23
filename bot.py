import os
import json
import sqlite3
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
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
CRYPTO_WALLET = "LTC1qv4u6vr0gzp9g4lq0g3qev939vdnwxghn5gtnfc"
CONTACT_CHANNEL_ID = "@YourChannelOrPM"  # Where contact/announcements go

ADMINS = set()           # users who used /admin
USER_SESSIONS = {}
ADMIN_SESSIONS = {}
USER_PRODUCT_PAGE = {}
USER_ORDER_PAGE = {}
ADMIN_ORDER_PAGE = {}

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
    price_56 REAL
)
""")

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

cur.execute("""
CREATE TABLE IF NOT EXISTS reviews (
    order_id INTEGER,
    user_id INTEGER,
    stars INTEGER,
    text TEXT,
    PRIMARY KEY (order_id, user_id)
)
""")
db.commit()

# ================= HELPERS =================
def get_products():
    cur.execute("SELECT * FROM products ORDER BY name ASC")
    return cur.fetchall()

def basket_text(items):
    total = 0
    text = ""
    for i in items:
        qty = i.get("quantity", 1)
        cost = i["price"] * qty
        total += cost
        text += f"- {i['name']} {i['weight']}g x{qty} = £{cost:.2f}\n"
    return text, total

def product_rating(product_name):
    cur.execute("""
        SELECT AVG(r.stars), COUNT(*)
        FROM reviews r
        JOIN orders o ON r.order_id = o.order_id
        WHERE o.items LIKE ?
    """, (f'%"{product_name}"%',))
    row = cur.fetchone()
    avg, count = row if row else (None, 0)
    if count and avg is not None:
        return "⭐" * round(avg)
    return "No reviews yet"

# ================= MAIN MENU =================
def home_menu():
    buttons = [
        [InlineKeyboardButton("🛒 Products", callback_data="home_products")],
        [InlineKeyboardButton("📦 My Orders", callback_data="home_my_orders")],
        [InlineKeyboardButton("⭐ View Reviews", callback_data="home_reviews")],
        [InlineKeyboardButton("📞 Contact Vendor", callback_data="home_contact")]
    ]
    return InlineKeyboardMarkup(buttons)

# ================= START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🏠 Welcome! Choose an option:", reply_markup=home_menu())

# ================= ADMIN COMMAND =================
async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    ADMINS.add(uid)
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Product",       callback_data="admin_add_product")],
        [InlineKeyboardButton("📢 Add Announcement", callback_data="admin_add_announcement")],
        [InlineKeyboardButton("📦 View Orders",       callback_data="admin_orders_0")]
    ])
    await update.message.reply_text("🛠 ADMIN PANEL", reply_markup=markup)

# ================= CALLBACK ROUTER =================
async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = q.data
    uid = q.from_user.id
    await q.answer()

    # ===== Home menu =====
    if data == "home_products":
        USER_PRODUCT_PAGE[uid] = 0
        await show_product_page(update, context, uid, 0)
        return

    if data == "home_my_orders":
        await show_user_order(update, context, uid, 0)
        return

    if data == "home_reviews":
        await show_all_reviews(update)
        return

    if data == "home_contact":
        await context.bot.send_message(
            CONTACT_CHANNEL_ID,
            f"📩 Contact from user {q.from_user.full_name} (@{q.from_user.username or 'no-username'}): Send your message here."
        )
        await q.edit_message_text("✅ Your message has been sent to the vendor.", reply_markup=home_menu())
        return

    # ===== Product navigation =====
    if data.startswith("prod_page_"):
        try:
            page = int(data.replace("prod_page_", ""))
            await show_product_page(update, context, uid, page)
        except:
            await q.edit_message_text("Invalid page", reply_markup=home_menu())
        return

    if data.startswith("weight_"):
        products = get_products()
        page = USER_PRODUCT_PAGE.get(uid, 0)
        if not (0 <= page < len(products)):
            await q.edit_message_text("Product page expired.", reply_markup=home_menu())
            return
        p = products[page]
        weight = data.replace("weight_", "")
        prices = {"3.5": p[4], "7": p[5], "14": p[6], "28": p[7], "56": p[8]}
        if weight not in prices or prices[weight] is None:
            await q.answer("Invalid weight", show_alert=True)
            return

        session = USER_SESSIONS.setdefault(uid, {"step": "weight", "basket": []})
        session["basket"].append({
            "name": p[1],
            "weight": weight,
            "price": prices[weight],
            "quantity": 1
        })
        session["step"] = "name"
        text, total = basket_text(session["basket"])
        await q.edit_message_text(
            f"🛒 Basket:\n{text}\n💰 £{total:.2f}\n\nSend FULL NAME to checkout:",
            reply_markup=None
        )
        return

    # ===== User orders =====
    if data.startswith("my_orders_"):
        try:
            page = int(data.split("_")[-1])
            await show_user_order(update, context, uid, page)
        except:
            await q.edit_message_text("Invalid order page", reply_markup=home_menu())
        return

    if data.startswith("review_"):
        try:
            oid = int(data.replace("review_", ""))
            USER_SESSIONS[uid] = {"step": "review", "order_id": oid}
            await q.message.reply_text("✍️ Send review as:\n5 Amazing product")
        except:
            await q.answer("Invalid review request", show_alert=True)
        return

    if data == "back":
        await q.edit_message_text("🏠 Main Menu", reply_markup=home_menu())
        return

    # ===== Admin area =====
    if uid not in ADMINS:
        await q.answer("Admin access required", show_alert=True)
        return

    if data == "admin_add_product":
        ADMIN_SESSIONS[uid] = {"step": "name"}
        await q.message.reply_text("🆕 Send product NAME:")
        return

    if data == "admin_add_announcement":
        ADMIN_SESSIONS[uid] = {"step": "announcement"}
        await q.message.reply_text("📝 Send announcement text:")
        return

    if data == "admin_orders_0" or data.startswith("admin_orders_"):
        try:
            page = int(data.split("_")[-1]) if data != "admin_orders_0" else 0
            await show_admin_orders(update, context, uid, page)
        except:
            await q.edit_message_text("Invalid orders page", reply_markup=home_menu())
        return

    if data.startswith("paid_"):
        try:
            oid = int(data.replace("paid_", ""))
            cur.execute("UPDATE orders SET status='Paid' WHERE order_id=?", (oid,))
            db.commit()
            await q.edit_message_text(f"✅ Order {oid} marked PAID")
        except Exception as e:
            await q.answer(f"Error: {str(e)}", show_alert=True)
        return

    if data.startswith("dispatch_"):
        try:
            oid = int(data.replace("dispatch_", ""))
            cur.execute("UPDATE orders SET status='Dispatched' WHERE order_id=?", (oid,))
            db.commit()
            await q.edit_message_text(f"📦 Order {oid} DISPATCHED")
        except Exception as e:
            await q.answer(f"Error: {str(e)}", show_alert=True)
        return

    await q.answer("Unknown action", show_alert=True)

# ================= PRODUCTS =================
async def show_product_page(update: Update, context: ContextTypes.DEFAULT_TYPE, uid: int, page: int):
    products = get_products()
    if not products:
        await update.callback_query.edit_message_text("No products available.", reply_markup=home_menu())
        return

    page = max(0, min(page, len(products)-1))
    USER_PRODUCT_PAGE[uid] = page
    p = products[page]
    rating = product_rating(p[1])

    buttons = [
        [InlineKeyboardButton(f"{w}g £{price:.2f}", callback_data=f"weight_{w}")]
        for w, price in {"3.5": p[4], "7": p[5], "14": p[6], "28": p[7], "56": p[8]}.items()
        if price is not None and price > 0
    ]

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"prod_page_{page-1}"))
    if page < len(products)-1:
        nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"prod_page_{page+1}"))
    if nav:
        buttons.append(nav)
    buttons.append([InlineKeyboardButton("🏠 Back", callback_data="back")])

    markup = InlineKeyboardMarkup(buttons)
    caption = f"📦 {p[1]}\n{rating}\n\n{p[2]}\n\nChoose weight:"

    q = update.callback_query
    try:
        if p[3]:
            await q.edit_message_media(
                media=InputMediaPhoto(media=p[3], caption=caption),
                reply_markup=markup
            )
        else:
            await q.edit_message_text(caption, reply_markup=markup)
    except Exception as e:
        await q.edit_message_text(f"Error displaying product:\n{str(e)[:200]}", reply_markup=home_menu())

# ================= USER ORDERS =================
async def show_user_order(update: Update, context: ContextTypes.DEFAULT_TYPE, uid: int, page: int):
    cur.execute("SELECT * FROM orders WHERE user_id=? ORDER BY order_id DESC", (uid,))
    orders = cur.fetchall()
    if not orders:
        await update.callback_query.edit_message_text("📦 No orders yet.", reply_markup=home_menu())
        return

    page = max(0, min(page, len(orders)-1))
    USER_ORDER_PAGE[uid] = page
    o = orders[page]
    oid, _, items_json, total, status, name, address = o

    try:
        items = json.loads(items_json)
    except:
        items = []
    items_text = "\n".join([f"- {i['name']} {i['weight']}g x{i.get('quantity',1)}" for i in items])

    buttons = []
    if status in ("Paid", "Dispatched"):
        buttons.append([InlineKeyboardButton("⭐ Leave / Edit Review", callback_data=f"review_{oid}")])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"my_orders_{page-1}"))
    if page < len(orders)-1:
        nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"my_orders_{page+1}"))
    if nav:
        buttons.append(nav)
    buttons.append([InlineKeyboardButton("🏠 Back", callback_data="back")])

    await update.callback_query.edit_message_text(
        f"🧾 Order #{oid}\n{name or '?'}\n{address or '?'}\n\n{items_text}\n\n💰 £{total:.2f}\n📌 {status}",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

# ================= ALL REVIEWS =================
async def show_all_reviews(update: Update):
    cur.execute("""
        SELECT r.stars, r.text
        FROM reviews r
        JOIN orders o ON r.order_id=o.order_id
        ORDER BY r.order_id DESC
    """)
    reviews = cur.fetchall()
    if not reviews:
        await update.callback_query.edit_message_text("No reviews yet.", reply_markup=
