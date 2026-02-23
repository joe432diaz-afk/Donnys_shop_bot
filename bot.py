import asyncio
import aiosqlite
import os
import random
import string
import json

from telegram import *
from telegram.ext import *

# ================= CONFIG =================

TOKEN = "TOKEN"
CHANNEL_ID = -1000000000000

ADMIN_IDS = {7773622161}

LTC_RATE = 0.01
DB = "shop.db"

# ================= UTILITIES =================

def generate_order():
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

# ================= KEYBOARDS =================

def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛒 Products","products")],
        [InlineKeyboardButton("🧺 Basket","basket")],
        [InlineKeyboardButton("⭐ Reviews","reviews")],
        [InlineKeyboardButton("🔧 Admin","admin")]
    ])

def back_btn(target="main"):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅ Back", callback_data=target)]
    ])

# ================= START =================

async def start(update: Update, context):
    await update.message.reply_text(
        "🛍 Shop Bot Ready",
        reply_markup=main_menu()
    )

# ================= ROUTER =================

async def router(update: Update, context):

    query = update.callback_query
    await query.answer()

    uid = query.from_user.id
    data = query.data

    # ---------- MAIN ----------
    if data == "main":
        await query.edit_message_text(
            "Main Menu",
            reply_markup=main_menu()
        )

    # ---------- PRODUCTS ----------
    elif data == "products":

        async with aiosqlite.connect(DB) as db:

            cursor = await db.execute(
                "SELECT id,name,price FROM products"
            )

            products = await cursor.fetchall()

        if not products:
            await query.edit_message_text(
                "No products available",
                reply_markup=back_btn()
            )
            return

        buttons = [
            [InlineKeyboardButton(
                f"{p[1]} - ${p[2]}",
                callback_data=f"product:{p[0]}"
            )]
            for p in products
        ]

        buttons.append([InlineKeyboardButton("⬅ Back","main")])

        await query.edit_message_text(
            "Products:",
            reply_markup=InlineKeyboardMarkup(buttons)
        )

    # ---------- PRODUCT DETAIL ----------
    elif data.startswith("product:"):

        pid = int(data.split(":")[1])

        context.user_data["product_id"] = pid

        async with aiosqlite.connect(DB) as db:

            cursor = await db.execute(
                "SELECT name,description,price,photo FROM products WHERE id=?",
                (pid,)
            )

            product = await cursor.fetchone()

        if not product:
            return

        name, desc, price, photo = product

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Add Basket","addbasket")],
            [InlineKeyboardButton("⬅ Back","products")]
        ])

        await query.message.reply_photo(
            photo=photo,
            caption=f"{name}\n\n{desc}\nPrice: ${price}",
            reply_markup=kb
        )

    # ---------- BASKET ----------
    elif data == "basket":

        uid = query.from_user.id

        async with aiosqlite.connect(DB) as db:

            cursor = await db.execute(
                "SELECT product_id,quantity FROM basket WHERE user_id=?",
                (uid,)
            )

            rows = await cursor.fetchall()

        if not rows:
            await query.edit_message_text(
                "Basket empty",
                reply_markup=back_btn()
            )
            return

        total = 0
        text = "🧺 Basket\n\n"

        async with aiosqlite.connect(DB) as db:

            for pid, qty in rows:

                cursor = await db.execute(
                    "SELECT name,price FROM products WHERE id=?",
                    (pid,)
                )

                prod = await cursor.fetchone()

                if prod:
                    name, price = prod
                    subtotal = price * qty
                    total += subtotal
                    text += f"{name} x{qty} = ${subtotal}\n"

        ltc = total * LTC_RATE

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("💳 Checkout","checkout")],
            [InlineKeyboardButton("⬅ Back","main")]
        ])

        await query.edit_message_text(
            text + f"\nTotal: ${total}\nLTC ≈ {ltc:.6f}",
            reply_markup=kb
        )

    # ---------- ADMIN ----------
    elif data == "admin":

        if not is_admin(uid):
            await query.answer("Admin only", show_alert=True)
            return

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📦 Orders","admin_orders")],
            [InlineKeyboardButton("⬅ Back","main")]
        ])

        await query.edit_message_text(
            "Admin Panel",
            reply_markup=kb
        )

# ================= BASKET ADD =================

async def add_basket(update: Update, context):

    query = update.callback_query
    await query.answer()

    uid = query.from_user.id
    pid = context.user_data.get("product_id")

    if not pid:
        return

    async with aiosqlite.connect(DB) as db:

        await db.execute("""
        INSERT INTO basket(user_id,product_id,quantity)
        VALUES(?,?,1)
        """,(uid,pid))

        await db.commit()

    await query.answer("Added to basket", show_alert=True)

# ================= MAIN APP =================

async def main():

    await init_db()

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))

    app.add_handler(CallbackQueryHandler(router))
    app.add_handler(CallbackQueryHandler(add_basket, pattern="addbasket"))

    print("Bot running...")
    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
