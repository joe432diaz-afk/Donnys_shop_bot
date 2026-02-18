import os
import json
import sqlite3
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)

# ================= CONFIG =================
TOKEN = os.environ.get("TOKEN") or "PUT_YOUR_TOKEN_HERE"
CRYPTO_WALLET = "LTC1qv4u6vr0gzp9g4lq0g3qev939vdnwxghn5gtnfc"
CONTACT_CHANNEL_ID = "@YourChannelOrPM"  # Where messages go

ADMINS = set()
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

# ================= CALLBACK ROUTER =================
async def callback_router(update, context):
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
            f"📩 Contact from user {q.from_user.full_name} (@{q.from_user.username}): Send your message here."
        )
        await q.edit_message_text("✅ Your message has been sent to the vendor.", reply_markup=home_menu())
        return

    # ===== Product navigation =====
    if data.startswith("prod_page_"):
        page = int(data.replace("prod_page_", ""))
        await show_product_page(update, context, uid, page)
        return

    if data.startswith("weight_"):
        products = get_products()
        page = USER_PRODUCT_PAGE.get(uid, 0)
        p = products[page]
        session = USER_SESSIONS.get(uid, {"step": "weight", "basket": []})
        weight = data.replace("weight_", "")
        prices = {"3.5": p[4], "7": p[5], "14": p[6], "28": p[7], "56": p[8]}
        session["basket"].append({
            "name": p[1],
            "weight": weight,
            "price": prices[weight],
            "quantity": 1
        })
        session["step"] = "name"
        USER_SESSIONS[uid] = session
        text, total = basket_text(session["basket"])
        await q.edit_message_text(f"🛒 Basket:\n{text}\n💰 £{total}\n\nSend FULL NAME to checkout:")
        return

    if data.startswith("my_orders_"):
        page = int(data.split("_")[-1])
        await show_user_order(update, context, uid, page)
        return

    if data.startswith("review_"):
        oid = int(data.replace("review_", ""))
        USER_SESSIONS[uid] = {"step": "review", "order_id": oid}
        await q.message.reply_text("✍️ Send review as:\n`5 Amazing product`")
        return

    if data == "back":
        await q.edit_message_text("🏠 Main Menu", reply_markup=home_menu())
        return

    # ===== Admin buttons =====
    if data == "admin_add_product":
        ADMIN_SESSIONS[uid] = {"step": "name"}
        await q.message.reply_text("🆕 Send product NAME:")
        return
    if data == "admin_add_announcement":
        ADMIN_SESSIONS[uid] = {"step": "announcement"}
        await q.message.reply_text("📝 Send announcement text:")
        return
    if data.startswith("admin_orders_"):
        page = int(data.split("_")[-1])
        await show_admin_orders(update, context, uid, page)
        return
    if data.startswith("paid_"):
        oid = int(data.replace("paid_", ""))
        cur.execute("UPDATE orders SET status='Paid' WHERE order_id=?", (oid,))
        db.commit()
        await q.edit_message_text(f"✅ Order {oid} marked PAID")
        return
    if data.startswith("dispatch_"):
        oid = int(data.replace("dispatch_", ""))
        cur.execute("UPDATE orders SET status='Dispatched' WHERE order_id=?", (oid,))
        db.commit()
        await q.edit_message_text(f"📦 Order {oid} DISPATCHED")
        return

# ================= PRODUCTS =================
async def show_product_page(update, context, uid, page):
    products = get_products()
    if not products:
        await update.callback_query.edit_message_text("No products available.", reply_markup=home_menu())
        return
    if page < 0: page = 0
    if page >= len(products): page = len(products)-1
    USER_PRODUCT_PAGE[uid] = page
    p = products[page]

    rating = product_rating(p[1])

    buttons = [[InlineKeyboardButton(f"{w}g £{price}", callback_data=f"weight_{w}")]
               for w, price in {"3.5": p[4], "7": p[5], "14": p[6], "28": p[7], "56": p[8]}.items()]

    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"prod_page_{page-1}"))
    if page < len(products)-1:
        nav_buttons.append(InlineKeyboardButton("Next ➡️", callback_data=f"prod_page_{page+1}"))
    if nav_buttons:
        buttons.append(nav_buttons)

    buttons.append([InlineKeyboardButton("🏠 Back", callback_data="back")])
    markup = InlineKeyboardMarkup(buttons)

    if p[3]:
        await update.callback_query.edit_message_media(
            media=InputMediaPhoto(media=p[3], caption=f"📦 {p[1]}\n{rating}\n\n{p[2]}\n\nChoose weight:"),
            reply_markup=markup
        )
    else:
        await update.callback_query.edit_message_text(
            f"📦 {p[1]}\n{rating}\n\n{p[2]}\n\nChoose weight:",
            reply_markup=markup
        )

# ================= USER ORDERS =================
async def show_user_order(update, context, uid, page):
    cur.execute("SELECT * FROM orders WHERE user_id=? ORDER BY order_id DESC", (uid,))
    orders = cur.fetchall()
    if not orders:
        await update.callback_query.edit_message_text("📦 No orders yet.", reply_markup=home_menu())
        return
    if page < 0: page = 0
    if page >= len(orders): page = len(orders)-1
    USER_ORDER_PAGE[uid] = page

    o = orders[page]
    oid, _, items, total, status, name, address = o
    items = json.loads(items)
    items_text = "\n".join([f"- {i['name']} {i['weight']}g x{i['quantity']}" for i in items])

    buttons = []
    if status in ("Paid", "Dispatched"):
        buttons.append([InlineKeyboardButton("⭐ Leave / Edit Review", callback_data=f"review_{oid}")])

    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"my_orders_{page-1}"))
    if page < len(orders)-1:
        nav_buttons.append(InlineKeyboardButton("Next ➡️", callback_data=f"my_orders_{page+1}"))
    if nav_buttons:
        buttons.append(nav_buttons)
    buttons.append([InlineKeyboardButton("🏠 Back", callback_data="back")])

    await update.callback_query.edit_message_text(
        f"🧾 Order #{oid}\n{name}\n{address}\n{items_text}\n💰 £{total}\n📌 {status}",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

# ================= ALL REVIEWS =================
async def show_all_reviews(update):
    cur.execute("""
        SELECT r.stars, r.text 
        FROM reviews r 
        JOIN orders o ON r.order_id=o.order_id
        ORDER BY r.order_id DESC
    """)
    reviews = cur.fetchall()
    if not reviews:
        await update.callback_query.edit_message_text("No reviews yet.", reply_markup=home_menu())
        return
    text = ""
    for s, t in reviews:
        text += f"⭐" * s + f"\n{t}\n\n"
    await update.callback_query.edit_message_text(text, reply_markup=home_menu())

# ================= ADMIN ORDERS =================
async def show_admin_orders(update, context, uid, page):
    cur.execute("SELECT * FROM orders ORDER BY order_id DESC")
    orders = cur.fetchall()
    if not orders:
        await update.callback_query.edit_message_text("No orders found.")
        return
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
        buttons.append([InlineKeyboardButton("📦 Mark Dispatched", callback_data=f"dispatch_{oid}")])

    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"admin_orders_{page-1}"))
    if page < len(orders)-1:
        nav_buttons.append(InlineKeyboardButton("Next ➡️", callback_data=f"admin_orders_{page+1}"))
    if nav_buttons:
        buttons.append(nav_buttons)
    buttons.append([InlineKeyboardButton("🏠 Back", callback_data="back")])

    await update.callback_query.edit_message_text(
        f"🧾 Order #{oid}\n{name}\n{address}\n{items_text}\n💰 £{total}\n📌 {status}",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

# ================= MESSAGE HANDLER =================
async def message_handler(update, context):
    uid = update.message.from_user.id
    text = update.message.text

    # Admin Add Product / Announcement
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
            await update.message.reply_text("✅ Product added!", reply_markup=home_menu())
            return
        if step == "announcement":
            await context.bot.send_message(CONTACT_CHANNEL_ID, f"📢 Announcement:\n{text}")
            ADMIN_SESSIONS.pop(uid)
            await update.message.reply_text("✅ Announcement sent!", reply_markup=home_menu())
            return

    # Checkout / Review
    if uid in USER_SESSIONS:
        session = USER_SESSIONS[uid]
        if session.get("step") == "name":
            session["name"] = text
            session["step"] = "address"
            await update.message.reply_text("📍 Address:")
            return
        if session.get("step") == "address":
            session["address"] = text
            items, total = basket_text(session["basket"])
            cur.execute(
                "INSERT INTO orders VALUES (NULL,?,?,?,?,?,?)",
                (uid, json.dumps(session["basket"]), total, "Pending", session["name"], session["address"])
            )
            db.commit()
            USER_SESSIONS.pop(uid)
            await update.message.reply_text(
                f"✅ Order placed\n\n{items}\n💰 £{total}\n💳 Pay to:\n{CRYPTO_WALLET}",
                reply_markup=home_menu()
            )
            return
        if session.get("step") == "review":
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
                (session["order_id"], uid, stars, body)
            )
            db.commit()
            USER_SESSIONS.pop(uid)
            await update.message.reply_text("✅ Review saved! ⭐", reply_markup=home_menu())
            return

# ================= ADMIN COMMAND =================
async def admin_cmd(update, context):
    uid = update.effective_user.id
    ADMINS.add(uid)
    await update.message.reply_text(
        "🛠 ADMIN PANEL",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Add Product", callback_data="admin_add_product")],
            [InlineKeyboardButton("📢 Add Announcement", callback_data="admin_add_announcement")],
            [InlineKeyboardButton("📦 View Orders", callback_data="admin_orders_0")]
        ])
    )

# ================= APP =================
app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("admin", admin_cmd))
app.add_handler(CallbackQueryHandler(callback_router))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
app.add_handler(MessageHandler(filters.PHOTO, message_handler))

print("✅ BOT RUNNING")
app.run_polling()
