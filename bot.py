# ================================
# COMMERCIAL TELEGRAM SHOP BOT
# ================================

import asyncio
import aiosqlite
import random
import string
import json
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters
)

# ================= CONFIG =================

TOKEN = "TOKEN"
CHANNEL_ID = -1000000000000
ADMIN_IDS = {7773622161}

DB = "shop.db"
LTC_RATE = 0.01

# ================= UTILITIES =================

def generate_order_id():
    return "ORD-" + "".join(
        random.choices(string.ascii_uppercase + string.digits, k=10)
    )

def is_admin(uid):
    return uid in ADMIN_IDS

# ================= DATABASE =================

async def init_db():
    async with aiosqlite.connect(DB) as db:

        await db.execute("""
        CREATE TABLE IF NOT EXISTS products(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            description TEXT,
            price REAL,
            photo BLOB
        )
        """)

        await db.execute("""
        CREATE TABLE IF NOT EXISTS basket(
            user_id INTEGER,
            product_id INTEGER,
            quantity INTEGER
        )
        """)

        await db.execute("""
        CREATE TABLE IF NOT EXISTS orders(
            order_id TEXT,
            user_id INTEGER,
            name TEXT,
            address TEXT,
            items TEXT,
            total REAL,
            status TEXT
        )
        """)

        await db.execute("""
        CREATE TABLE IF NOT EXISTS reviews(
            user_id INTEGER,
            text TEXT
        )
        """)

        await db.commit()

async def db_fetch(query, params=()):
    async with aiosqlite.connect(DB) as db:
        cursor = await db.execute(query, params)
        return await cursor.fetchall()

async def db_fetchone(query, params=()):
    async with aiosqlite.connect(DB) as db:
        cursor = await db.execute(query, params)
        return await cursor.fetchone()

async def db_execute(query, params=()):
    async with aiosqlite.connect(DB) as db:
        await db.execute(query, params)
        await db.commit()

# ================= KEYBOARDS =================

def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛒 Products", "products")],
        [InlineKeyboardButton("🧺 Basket", "basket")],
        [InlineKeyboardButton("⭐ Reviews", "reviews")],
        [InlineKeyboardButton("🔧 Admin", "admin")]
    ])

def back(target):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅ Back", target)]
    ])

# ================= START =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🛍 Commercial Shop Bot",
        reply_markup=main_menu()
    )

# ================= ROUTER =================

async def router(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    if not query:
        return

    try:
        await query.answer()
    except:
        pass

    uid = query.from_user.id
    data = query.data

    # MAIN
    if data == "main":
        await query.edit_message_text("Main Menu", reply_markup=main_menu())
        return

    # PRODUCTS
    if data == "products":
        products = await db_fetch("SELECT id,name,price FROM products")

        if not products:
            await query.edit_message_text(
                "No products available",
                reply_markup=back("main")
            )
            return

        buttons = []
        for p in products:
            buttons.append([
                InlineKeyboardButton(
                    f"{p[1]} - ${p[2]}",
                    callback_data=f"product:{p[0]}"
                )
            ])
        buttons.append([InlineKeyboardButton("⬅ Back", "main")])

        await query.edit_message_text(
            "Products:",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        return

    # PRODUCT DETAIL
    if data.startswith("product:"):
        pid = int(data.split(":")[1])
        context.user_data["product_id"] = pid

        product = await db_fetchone(
            "SELECT name,description,price FROM products WHERE id=?",
            (pid,)
        )

        if not product:
            return

        name, desc, price = product

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Add", "addbasket")],
            [InlineKeyboardButton("⬅ Back", "products")]
        ])

        await query.edit_message_text(
            f"{name}\n\n{desc}\nPrice: ${price}",
            reply_markup=kb
        )
        return

    # ADD TO BASKET
    if data == "addbasket":
        pid = context.user_data.get("product_id")
        if not pid:
            return

        await db_execute("""
        INSERT INTO basket(user_id,product_id,quantity)
        VALUES(?,?,1)
        """,(uid,pid))

        await query.answer("Added to basket", show_alert=True)
        return

    # BASKET
    if data == "basket":
        rows = await db_fetch(
            "SELECT product_id,quantity FROM basket WHERE user_id=?",
            (uid,)
        )

        if not rows:
            await query.edit_message_text(
                "Basket empty",
                reply_markup=back("main")
            )
            return

        total = 0
        text = "🧺 Basket\n\n"

        for pid, qty in rows:
            prod = await db_fetchone(
                "SELECT name,price FROM products WHERE id=?",
                (pid,)
            )
            if prod:
                name, price = prod
                subtotal = price * qty
                total += subtotal
                text += f"{name} x{qty} = ${subtotal}\n"

        ltc = total * LTC_RATE

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("💳 Checkout", "checkout")],
            [InlineKeyboardButton("⬅ Back", "main")]
        ])

        await query.edit_message_text(
            text + f"\nTotal: ${total}\nLTC ≈ {ltc:.6f}",
            reply_markup=kb
        )
        return

    # CHECKOUT
    if data == "checkout":
        context.user_data["checkout_state"] = "name"
        await query.edit_message_text(
            "Enter your full name:",
            reply_markup=back("basket")
        )
        return

    # REVIEWS
    if data == "reviews":
        reviews = await db_fetch("SELECT text FROM reviews LIMIT 10")
        text = "⭐ Reviews\n\n"
        for r in reviews:
            text += f"• {r[0]}\n"

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("Add Review", "add_review")],
            [InlineKeyboardButton("⬅ Back", "main")]
        ])

        await query.edit_message_text(text, reply_markup=kb)
        return

    # ADMIN
    if data == "admin":
        if not is_admin(uid):
            await query.answer("Admin only", show_alert=True)
            return

        await query.edit_message_text(
            "Admin Panel",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("View Orders", "admin_orders")],
                [InlineKeyboardButton("⬅ Back", "main")]
            ])
        )
        return

# ================= TEXT HANDLER =================

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):

    uid = update.message.from_user.id
    text = update.message.text

    state = context.user_data.get("checkout_state")

    if state == "name":
        context.user_data["name"] = text
        context.user_data["checkout_state"] = "address"
        await update.message.reply_text("Enter your address:")
        return

    if state == "address":
        context.user_data["address"] = text

        basket = await db_fetch(
            "SELECT product_id,quantity FROM basket WHERE user_id=?",
            (uid,)
        )

        total = 0
        items = []

        for pid, qty in basket:
            prod = await db_fetchone(
                "SELECT name,price FROM products WHERE id=?",
                (pid,)
            )
            if prod:
                name, price = prod
                total += price * qty
                items.append({"name": name, "qty": qty})

        order_id = generate_order_id()

        await db_execute("""
        INSERT INTO orders(order_id,user_id,name,address,items,total,status)
        VALUES(?,?,?,?,?,?,?)
        """,(
            order_id,
            uid,
            context.user_data["name"],
            context.user_data["address"],
            json.dumps(items),
            total,
            "pending"
        ))

        await db_execute("DELETE FROM basket WHERE user_id=?", (uid,))

        ltc = total * LTC_RATE

        await update.message.reply_text(
            f"Order Created!\n\nOrder ID: {order_id}\n"
            f"Total: ${total}\n"
            f"Pay LTC ≈ {ltc:.6f}"
        )

        await update.message.bot.send_message(
            chat_id=CHANNEL_ID,
            text=f"New Order\nID: {order_id}\nUser: {uid}\nTotal: ${total}"
        )

        context.user_data.clear()

# ================= MAIN =================

async def main():
    await init_db()

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(router))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    print("Commercial bot running...")
    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
