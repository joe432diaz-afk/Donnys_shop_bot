import os
import json
import sqlite3
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)

# ================= CONFIG =================
TOKEN = os.environ.get("TOKEN") or "PUT_YOUR_TOKEN_HERE"
CHANNEL_ID = -1003833257976
CRYPTO_WALLET = "LTC1qv4u6vr0gzp9g4lq0g3qev939vdnwxghn5gtnfc"

ADMINS = set()
USER_SESSIONS = {}
ADMIN_SESSIONS = {}
ADMIN_ORDER_PAGE = {}  # track which order is being viewed

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
    cur.execute("SELECT * FROM products")
    return cur.fetchall()

def main_menu():
    buttons = []
    for pid, name, *_ in get_products():
        buttons.append([InlineKeyboardButton(name, callback_data=f"prod_{pid}")])
    buttons.append([InlineKeyboardButton("📦 My Orders", callback_data="my_orders")])
    return InlineKeyboardMarkup(buttons)

def basket_text(items):
    total = 0
    text = ""
    for i in items:
        cost = i["price"] * i["quantity"]
        total += cost
        text += f"- {i['name']} {i['weight']}g x{i['quantity']} = £{cost}\n"
    return text, total

def product_rating(product_name):
    cur.execute("""
    SELECT AVG(r.stars), COUNT(*)
    FROM reviews r
    JOIN orders o ON r.order_id = o.order_id
    WHERE o.items LIKE ?
    """, (f'%"{product_name}"%',))
    avg, count = cur.fetchone()
    if count:
        return f"\n⭐ {round(avg,1)}/5 ({count} reviews)"
    return "\n⭐ No reviews yet"

# ================= START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🌿 Welcome!\nChoose a product:", reply_markup=main_menu())

# ================= ADMIN =================
async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ADMINS.add(update.effective_user.id)
    await update.message.reply_text(
        "🛠 ADMIN PANEL",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Add Product", callback_data="admin_add_product")],
            [InlineKeyboardButton("📦 View Orders", callback_data="admin_orders_0")]
        ])
    )

# ================= PRODUCT SELECTION =================
async def product_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    pid = q.data.replace("prod_", "")
    cur.execute("SELECT * FROM products WHERE id=?", (pid,))
    p = cur.fetchone()
    if not p:
        await q.edit_message_text("❌ Product not found.")
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

    rating = product_rating(p[1])

    buttons = [
        [InlineKeyboardButton(f"{w}g £{price}", callback_data=f"weight_{w}")]
        for w, price in USER_SESSIONS[q.from_user.id]["product"]["prices"].items()
    ]

    await q.edit_message_text(
        f"📦 {p[1]}{rating}\n\nChoose weight:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

# ================= WEIGHT SELECTION =================
async def weight_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    session = USER_SESSIONS[uid]

    weight = q.data.replace("weight_", "")
    prod = session["product"]

    session["basket"].append({
        "name": prod["name"],
        "weight": weight,
        "price": prod["prices"][weight],
        "quantity": 1
    })

    text, total = basket_text(session["basket"])
    await q.edit_message_text(
        f"🛒 Basket:\n{text}\n💰 £{total}\n\nSend FULL NAME to checkout:"
    )
    session["step"] = "name"

# ================= MESSAGE HANDLER =================
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    text = update.message.text

    # ===== ADMIN ADD PRODUCT FLOW =====
    if uid in ADMIN_SESSIONS:
        admin = ADMIN_SESSIONS[uid]
        step = admin["step"]

        if step == "name":
            admin["name"] = text
            admin["step"] = "desc"
            await update.message.reply_text("📝 Description:")
            return

        if step == "desc":
            admin["desc"] = text
            admin["step"] = "photo"
            await update.message.reply_text("📷 Send product PHOTO (as image, not URL):")
            return

        if step == "photo":
            if update.message.photo:
                admin["photo_file_id"] = update.message.photo[-1].file_id
                admin["step"] = "prices"
                await update.message.reply_text("💰 Prices 3.5,7,14,28,56 (comma separated):")
                return
            else:
                await update.message.reply_text("❌ Send a photo!")
                return

        if step == "prices":
            try:
                prices = list(map(float, text.split(",")))
                if len(prices) != 5:
                    raise ValueError
            except:
                await update.message.reply_text("❌ Invalid format")
                return
            pid = admin["name"].lower().replace(" ", "_")
            cur.execute("INSERT OR REPLACE INTO products VALUES (?,?,?,?,?,?,?,?,?)",
                        (pid, admin["name"], admin["desc"], admin["photo_file_id"], *prices))
            db.commit()
            ADMIN_SESSIONS.pop(uid)
            await update.message.reply_text("✅ Product added!", reply_markup=main_menu())
            return

    # ===== REVIEW WRITING =====
    if uid in USER_SESSIONS and USER_SESSIONS[uid].get("step") == "review":
        s = USER_SESSIONS[uid]
        try:
            stars, body = text.split(" ", 1)
            stars = int(stars)
            if not 1 <= stars <= 5:
                raise ValueError
        except:
            await update.message.reply_text("❌ Format: `5 Amazing product`")
            return

        cur.execute(
            "INSERT OR REPLACE INTO reviews VALUES (?,?,?,?)",
            (s["order_id"], uid, stars, body)
        )
        db.commit()

        USER_SESSIONS.pop(uid)
        await update.message.reply_text("✅ Review saved! ⭐")
        return

    # ===== CHECKOUT FLOW =====
    if uid in USER_SESSIONS:
        session = USER_SESSIONS[uid]
        if session["step"] == "name":
            session["name"] = text
            session["step"] = "address"
            await update.message.reply_text("📍 Address:")
            return
        if session["step"] == "address":
            session["address"] = text
            items, total = basket_text(session["basket"])
            cur.execute(
                "INSERT INTO orders VALUES (NULL,?,?,?,?,?,?)",
                (uid, json.dumps(session["basket"]), total, "Pending", session["name"], session["address"])
            )
            db.commit()
            USER_SESSIONS.pop(uid)
            await update.message.reply_text(
                f"✅ Order placed\n\n{items}\n💰 £{total}\n💳 Pay to:\n{CRYPTO_WALLET}"
            )
            return

# ================= MY ORDERS =================
async def my_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id

    cur.execute("SELECT * FROM orders WHERE user_id=? ORDER BY order_id DESC", (uid,))
    orders = cur.fetchall()

    if not orders:
        await q.edit_message_text("📦 No orders yet.", reply_markup=main_menu())
        return

    # Show all orders with a back button
    text = ""
    buttons = []
    for o in orders:
        oid, _, items, total, status, _, _ = o
        items = json.loads(items)
        items_text = "\n".join([f"- {i['name']} {i['weight']}g x{i['quantity']}" for i in items])
        text += f"🧾 Order #{oid}\n{items_text}\n💰 £{total}\n📌 {status}\n\n"
        if status in ("Paid", "Dispatched"):
            buttons.append([InlineKeyboardButton(f"⭐ Review #{oid}", callback_data=f"review_{oid}")])
    buttons.append([InlineKeyboardButton("⬅️ Back", callback_data="back")])

    await q.edit_message_text(text.strip(), reply_markup=InlineKeyboardMarkup(buttons))

# ================= REVIEW CALLBACK =================
async def review_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id

    if q.data.startswith("review_"):
        oid = int(q.data.replace("review_", ""))
        USER_SESSIONS[uid] = {"step": "review", "order_id": oid}
        await q.message.reply_text("✍️ Send review as:\n`5 Amazing product`")

    elif q.data == "back":
        await q.edit_message_text("🏠 Main Menu", reply_markup=main_menu())

# ================= ADMIN CALLBACK =================
async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id

    if uid not in ADMINS:
        return

    # ===== ADD PRODUCT =====
    if q.data == "admin_add_product":
        ADMIN_SESSIONS[uid] = {"step": "name"}
        await q.edit_message_text("🆕 Send product NAME:")
        return

    # ===== VIEW ORDERS =====
    if q.data.startswith("admin_orders_"):
        page = int(q.data.split("_")[-1])
        cur.execute("SELECT * FROM orders ORDER BY order_id DESC")
        orders = cur.fetchall()
        if not orders:
            await q.edit_message_text("📦 No orders yet.")
            return

        # Make sure page is valid
        if page < 0: page = 0
        if page >= len(orders): page = len(orders)-1
        ADMIN_ORDER_PAGE[uid] = page

        o = orders[page]
        oid, user_id, items, total, status, name, address = o
        items = json.loads(items)
        items_text = "\n".join([f"- {i['name']} {i['weight']}g x{i['quantity']}" for i in items])

        buttons = []
        if status != "Paid":
            buttons.append([InlineKeyboardButton("💰 Mark Paid", callback_data=f"paid_{oid}")])
        if status == "Paid":
            buttons.append([InlineKeyboardButton("📦 Dispatch", callback_data=f"dispatch_{oid}")])
        # navigation
        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"admin_orders_{page-1}"))
        if page < len(orders)-1:
            nav_buttons.append(InlineKeyboardButton("Next ➡️", callback_data=f"admin_orders_{page+1}"))
        if nav_buttons:
            buttons.append(nav_buttons)
        buttons.append([InlineKeyboardButton("⬅️ Back to Menu", callback_data="admin_menu")])

        await q.edit_message_text(
            f"🧾 Order #{oid}\n{name}\n{address}\n{items_text}\n£{total}\nStatus: {status}",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        return

    # ===== NAVIGATE BACK TO ADMIN MENU =====
    if q.data == "admin_menu":
        await q.edit_message_text(
            "🛠 ADMIN PANEL",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ Add Product", callback_data="admin_add_product")],
                [InlineKeyboardButton("📦 View Orders", callback_data="admin_orders_0")]
            ])
        )
        return

    # ===== MARK PAID =====
    if q.data.startswith("paid_"):
        oid = int(q.data.replace("paid_", ""))
        cur.execute("UPDATE orders SET status='Paid' WHERE order_id=?", (oid,))
        db.commit()
        await q.answer("✅ Marked Paid", show_alert=True)
        # Refresh order page
        page = ADMIN_ORDER_PAGE.get(uid, 0)
        await admin_callback(update, context)
        return

    # ===== DISPATCH =====
    if q.data.startswith("dispatch_"):
        oid = int(q.data.replace("dispatch_", ""))
        cur.execute("UPDATE orders SET status='Dispatched' WHERE order_id=?", (oid,))
        db.commit()
        await q.answer("📦 Dispatched", show_alert=True)
        # Refresh order page
        page = ADMIN_ORDER_PAGE.get(uid, 0)
        await admin_callback(update, context)
        return

# ================= APP =================
app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("admin", admin))

app.add_handler(CallbackQueryHandler(admin_callback, pattern="^(admin_|paid_|dispatch_).*"))
app.add_handler(CallbackQueryHandler(product_select, pattern="^prod_"))
app.add_handler(CallbackQueryHandler(weight_select, pattern="^weight_"))
app.add_handler(CallbackQueryHandler(my_orders, pattern="^my_orders$"))
app.add_handler(CallbackQueryHandler(review_callback, pattern="^(review_|back)$"))

app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
app.add_handler(MessageHandler(filters.PHOTO, message_handler))

print("✅ BOT RUNNING")
app.run_polling()
