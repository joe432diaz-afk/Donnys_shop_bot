import os
import sqlite3
import logging
import requests

from telegram import *
from telegram.ext import *

# ================= CONFIG =================

TOKEN = os.getenv("TOKEN")
ADMIN_ID = 7773622161

DB_NAME = "shop.db"

logging.basicConfig(level=logging.INFO)

# ================= STEP 1 ✅ STATES PATCHED =================

(
    ADMIN_ADD_PHOTO,
    ADMIN_ADD_NAME,
    ADMIN_ADD_PRICE,
    ADMIN_ADD_DESC
) = range(4)

# ================= DATABASE =================

def db():
    return sqlite3.connect(DB_NAME)

def init_db():

    conn = db()
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS products(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        price REAL,
        description TEXT,
        photo TEXT
    )
    """)

    conn.commit()
    conn.close()

# ================= MENU =================

def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛍 Products", callback_data="products")],
        [InlineKeyboardButton("🧺 Basket", callback_data="basket")],
        [InlineKeyboardButton("🔧 Admin", callback_data="admin_product_manager")]
    ])

# ================= START =================

async def start(update: Update, context):

    await update.message.reply_text(
        "Welcome Shop Bot",
        reply_markup=main_menu()
    )

# ================= STEP 2 ✅ ADMIN PRODUCT MANAGER MENU =================

async def admin_product_manager_trigger(update: Update, context):

    user_id = update.effective_user.id

    if user_id != ADMIN_ID:
        return

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Product", callback_data="admin_add_product")],
        [InlineKeyboardButton("❌ Delete Product", callback_data="admin_delete_product")],
        [InlineKeyboardButton("📦 View Products", callback_data="admin_view_products")],
        [InlineKeyboardButton("⬅ Close", callback_data="menu")]
    ])

    query = update.callback_query

    if query:
        await query.answer()
        await query.edit_message_text(
            "🔧 Product Manager",
            reply_markup=keyboard
        )
    else:
        await update.message.reply_text(
            "🔧 Product Manager",
            reply_markup=keyboard
        )

# ================= ADMIN ADD PRODUCT FLOW =================

async def admin_add_product_photo(update: Update, context):

    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END

    photo = update.message.photo[-1].file_id
    context.user_data["photo"] = photo

    await update.message.reply_text("Product name:")
    return ADMIN_ADD_NAME

async def admin_add_product_name(update: Update, context):

    context.user_data["name"] = update.message.text

    await update.message.reply_text("Price:")
    return ADMIN_ADD_PRICE

async def admin_add_product_price(update: Update, context):

    try:
        context.user_data["price"] = float(update.message.text)
    except:
        await update.message.reply_text("Send numeric price.")
        return ADMIN_ADD_PRICE

    await update.message.reply_text("Description:")
    return ADMIN_ADD_DESC

async def admin_add_product_desc(update: Update, context):

    data = context.user_data

    conn = db()
    c = conn.cursor()

    c.execute("""
    INSERT INTO products(name,price,description,photo)
    VALUES (?,?,?,?)
    """, (
        data.get("name"),
        data.get("price"),
        update.message.text,
        data.get("photo")
    ))

    conn.commit()
    conn.close()

    await update.message.reply_text("✅ Product added!")

    return ConversationHandler.END

# ================= ROUTER =================

async def router(update: Update, context):

    query = update.callback_query
    if not query:
        return

    data = query.data

    await query.answer()

    if data == "menu":
        await query.edit_message_text(
            "Main Menu",
            reply_markup=main_menu()
        )

    elif data == "admin_product_manager":
        await admin_product_manager_trigger(update, context)

    elif data == "admin_add_product":
        await query.edit_message_text("Send product photo:")
        return ADMIN_ADD_PHOTO

    elif data == "admin_delete_product":

        await query.edit_message_text("Send Product ID to delete:")

    elif data == "admin_view_products":

        conn = db()
        c = conn.cursor()

        c.execute("SELECT id,name,price FROM products")
        products = c.fetchall()
        conn.close()

        text = "Products List:\n\n"

        for p in products:
            text += f"ID:{p[0]} | {p[1]} | ${p[2]}\n"

        await query.edit_message_text(text)

    elif data == "products":

        conn = db()
        c = conn.cursor()

        c.execute("SELECT * FROM products")
        products = c.fetchall()
        conn.close()

        if not products:
            await query.edit_message_text("No products")
            return

        for p in products:

            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("Add Cart", callback_data=f"add_{p[0]}")]
            ])

            await context.bot.send_photo(
                query.message.chat_id,
                p[4],
                caption=f"{p[1]}\n${p[2]}\n\n{p[3]}",
                reply_markup=keyboard
            )

# ================= MAIN =================

def main():

    init_db()

    app = ApplicationBuilder().token(TOKEN).build()

    conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(
                router,
                pattern="^admin_add_product$"
            )
        ],
        states={
            ADMIN_ADD_PHOTO: [MessageHandler(filters.PHOTO, admin_add_product_photo)],
            ADMIN_ADD_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_product_name)],
            ADMIN_ADD_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_product_price)],
            ADMIN_ADD_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_product_desc)],
        },
        fallbacks=[]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_product_manager_trigger))

    app.add_handler(CallbackQueryHandler(router))
    app.add_handler(conv)

    print("Bot Running...")
    app.run_polling()

if __name__ == "__main__":
    main()
