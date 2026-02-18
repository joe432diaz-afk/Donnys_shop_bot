import sqlite3, json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)

# ================= CONFIG =================
TOKEN = "PUT_YOUR_TOKEN_HERE"
ADMINS = {123456789}
CHANNEL_ID = -1001234567890

WEIGHTS = ["3.5", "7", "14", "28", "56"]

USER = {}

# ================= DATABASE =================
db = sqlite3.connect("shop.db", check_same_thread=False)
cur = db.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
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
    status TEXT
)
""")

db.commit()

# ================= MENUS =================
def main_menu(admin=False):
    buttons = [
        [InlineKeyboardButton("🛒 Shop", callback_data="shop")],
        [InlineKeyboardButton("🧺 Basket", callback_data="basket")]
    ]
    if admin:
        buttons.append([InlineKeyboardButton("🧑‍💼 Admin Panel", callback_data="admin")])
    return InlineKeyboardMarkup(buttons)

def admin_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Create Product", callback_data="admin_add")],
        [InlineKeyboardButton("📦 Orders", callback_data="admin_orders")],
        [InlineKeyboardButton("⬅️ Back", callback_data="back")]
    ])

# ================= START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    USER.setdefault(uid, {"basket": []})
    await update.message.reply_text(
        "Welcome to the shop 👋",
        reply_markup=main_menu(uid in ADMINS)
    )

# ================= SHOP =================
async def shop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    cur.execute("SELECT id,name FROM products")
    rows = cur.fetchall()

    if not rows:
        await q.edit_message_text("No products yet.")
        return

    buttons = [[InlineKeyboardButton(n, callback_data=f"prod_{i}")] for i,n in rows]
    buttons.append([InlineKeyboardButton("⬅️ Back", callback_data="back")])
    await q.edit_message_text("Select product:", reply_markup=InlineKeyboardMarkup(buttons))

async def product_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    pid = int(q.data.split("_")[1])
    cur.execute("SELECT name,photo,prices FROM products WHERE id=?", (pid,))
    name, photo, prices = cur.fetchone()
    prices = json.loads(prices)

    USER[q.from_user.id]["current"] = {"id": pid, "name": name, "prices": prices}

    buttons = [[InlineKeyboardButton(f"{w}g £{prices[w]}", callback_data=f"weight_{w}")] for w in WEIGHTS]
    buttons.append([InlineKeyboardButton("⬅️ Back", callback_data="shop")])

    await context.bot.send_photo(
        q.from_user.id, photo,
        caption=name,
        reply_markup=InlineKeyboardMarkup(buttons)
    )

# ================= BASKET =================
async def weight_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    w = q.data.split("_")[1]
    u = USER[q.from_user.id]
    p = u["current"]

    u["basket"].append({
        "name": p["name"],
        "weight": w,
        "price": p["prices"][w],
        "qty": 1
    })

    await q.edit_message_text("Added to basket ✅")

async def basket(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    b = USER[q.from_user.id]["basket"]

    if not b:
        await q.edit_message_text("Basket empty.")
        return

    text = "🧺 Basket:\n"
    total = 0
    buttons = []

    for i,item in enumerate(b):
        total += item["price"] * item["qty"]
        text += f"{item['name']} {item['weight']}g x{item['qty']}\n"
        buttons.append([
            InlineKeyboardButton("➕", callback_data=f"add_{i}"),
            InlineKeyboardButton("➖", callback_data=f"rem_{i}")
        ])

    buttons.append([InlineKeyboardButton("✅ Checkout", callback_data="checkout")])
    buttons.append([InlineKeyboardButton("⬅️ Back", callback_data="back")])

    await q.edit_message_text(text + f"\nTotal £{total}", reply_markup=InlineKeyboardMarkup(buttons))

async def basket_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    u = USER[q.from_user.id]["basket"]
    i = int(q.data.split("_")[1])

    if q.data.startswith("add_"):
        u[i]["qty"] += 1
    else:
        u[i]["qty"] -= 1
        if u[i]["qty"] <= 0:
            u.pop(i)

    await basket(update, context)

# ================= CHECKOUT =================
async def checkout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    b = USER[q.from_user.id]["basket"]
    total = sum(i["price"]*i["qty"] for i in b)

    cur.execute(
        "INSERT INTO orders (user_id,items,total,status) VALUES (?,?,?,?)",
        (q.from_user.id, json.dumps(b), total, "Pending")
    )
    db.commit()
    oid = cur.lastrowid

    for admin in ADMINS:
        await context.bot.send_message(
            admin,
            f"🆕 Order #{oid} £{total}",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ Paid", callback_data=f"paid_{oid}"),
                    InlineKeyboardButton("📦 Sent", callback_data=f"sent_{oid}")
                ]
            ])
        )

    USER[q.from_user.id]["basket"] = []
    await q.edit_message_text("Order placed ✅")

# ================= ADMIN =================
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    await q.edit_message_text("Admin Panel:", reply_markup=admin_menu())

async def admin_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    USER[q.from_user.id]["admin_add"] = {"step": "name"}
    await q.edit_message_text("Send product NAME:")

async def admin_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.from_user.id
    s = USER.get(uid, {}).get("admin_add")
    if not s: return

    if s["step"] == "name":
        s["name"] = update.text
        s["step"] = "photo"
        await update.reply_text("Send product PHOTO")
    elif s["step"] == "photo":
        s["photo"] = update.photo[-1].file_id
        s["prices"] = {}
        s["step"] = "prices"
        await update.reply_text("Send prices as:\n3.5 10\n7 20\n14 35\n28 60\n56 100")
    else:
        for line in update.text.splitlines():
            w,p = line.split()
            s["prices"][w] = float(p)
        cur.execute(
            "INSERT INTO products (name,photo,prices) VALUES (?,?,?)",
            (s["name"], s["photo"], json.dumps(s["prices"]))
        )
        db.commit()
        USER[uid].pop("admin_add")
        await update.reply_text("✅ Product created")

async def admin_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    oid = int(q.data.split("_")[1])
    status = "Paid" if q.data.startswith("paid_") else "Dispatched"
    cur.execute("UPDATE orders SET status=? WHERE id=?", (status,oid))
    db.commit()
    await q.edit_message_text(f"Order #{oid} → {status}")

# ================= ROUTER =================
async def back(update: Update, context):
    q = update.callback_query; await q.answer()
    await q.edit_message_text("Menu", reply_markup=main_menu(q.from_user.id in ADMINS))

# ================= RUN =================
app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(shop, pattern="^shop$"))
app.add_handler(CallbackQueryHandler(product_page, pattern="^prod_"))
app.add_handler(CallbackQueryHandler(weight_select, pattern="^weight_"))
app.add_handler(CallbackQueryHandler(basket, pattern="^basket$"))
app.add_handler(CallbackQueryHandler(basket_edit, pattern="^(add_|rem_)"))
app.add_handler(CallbackQueryHandler(checkout, pattern="^checkout$"))
app.add_handler(CallbackQueryHandler(admin_panel, pattern="^admin$"))
app.add_handler(CallbackQueryHandler(admin_add, pattern="^admin_add$"))
app.add_handler(CallbackQueryHandler(admin_order, pattern="^(paid_|sent_)"))
app.add_handler(CallbackQueryHandler(back, pattern="^back$"))
app.add_handler(MessageHandler(filters.TEXT | filters.PHOTO, admin_message))

print("BOT RUNNING")
app.run_polling()
