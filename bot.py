import asyncio
import aiosqlite
import random
import string

from telegram import *
from telegram.ext import *

# ================= CONFIG =================

TOKEN = "TOKEN"
CHANNEL_ID = -1000000000000
ADMIN_IDS = {7773622161}

DB = "shop.db"
LTC_RATE = 0.01

# ================= UTILITIES =================

def generate_order():
    return "ORD-" + "".join(
        random.choices(string.ascii_uppercase + string.digits, k=10)
    )

def is_admin(uid):
    return uid in ADMIN_IDS

# ================= DATABASE HELPERS =================

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
        [InlineKeyboardButton("🛒 Products","products")],
        [InlineKeyboardButton("🧺 Basket","basket")],
        [InlineKeyboardButton("🔧 Admin","admin")]
    ])

# ================= START =================

async def start(update: Update, context):
    await update.message.reply_text(
        "🛍 Shop Bot Ready",
        reply_markup=main_menu()
    )

# ================= CALLBACK ROUTER =================

async def router(update: Update, context):

    query = update.callback_query
    if not query:
        return

    try:
        await query.answer()
    except:
        return

    uid = query.from_user.id
    data = query.data

    # MAIN MENU
    if data == "main":
        await query.edit_message_text(
            "Main Menu",
            reply_markup=main_menu()
        )
        return

    # PRODUCTS LIST
    if data == "products":

        products = await db_fetch(
            "SELECT id,name,price FROM products"
        )

        buttons = [
            [InlineKeyboardButton(
                f"{p[1]} - ${p[2]}",
                callback_data=f"product:{p[0]}"
            )]
            for p in products
        ]

        buttons.append([InlineKeyboardButton("⬅ Back","main")])

        await query.edit_message_text(
            "Products",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        return

    # PRODUCT DETAIL
    if data.startswith("product:"):

        pid = int(data.split(":")[1])
        context.user_data["product_id"] = pid

        product = await db_fetchone(
            "SELECT name,description,price,photo FROM products WHERE id=?",
            (pid,)
        )

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
        return

    # BASKET
    if data == "basket":

        rows = await db_fetch(
            "SELECT product_id,quantity FROM basket WHERE user_id=?",
            (uid,)
        )

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

        await query.edit_message_text(
            text + f"\nTotal: ${total}\nLTC ≈ {ltc:.6f}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅ Back","main")]
            ])
        )
        return

    # ADMIN PANEL
    if data == "admin":

        if not is_admin(uid):
            await query.answer("Admin only", show_alert=True)
            return

        await query.edit_message_text(
            "Admin Panel\n\nProducts are manually managed in database.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅ Back","main")]
            ])
        )

# ================= ADD BASKET =================

async def addbasket(update: Update, context):

    query = update.callback_query
    if not query:
        return

    try:
        await query.answer()
    except:
        return

    uid = query.from_user.id
    pid = context.user_data.get("product_id")

    if not pid:
        return

    await db_execute("""
    INSERT INTO basket(user_id,product_id,quantity)
    VALUES(?,?,1)
    """,(uid,pid))

    await query.answer("Added!", show_alert=True)

# ================= MAIN =================

async def main():

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(router))
    app.add_handler(CallbackQueryHandler(addbasket, pattern="addbasket"))

    print("Bot running...")
    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
