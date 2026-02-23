import os
import sqlite3
import logging

from telegram import *
from telegram.ext import *

# ================= CONFIG =================

TOKEN = os.getenv("TOKEN")
ADMIN_ID = 7773622161

DB_NAME = "shop.db"

logging.basicConfig(level=logging.INFO)

# ================= STATES =================

ADMIN_ADD_PHOTO, ADMIN_ADD_NAME, ADMIN_ADD_PRICE, ADMIN_ADD_DESC = range(4)

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

# ================= MENUS =================

def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛍 Products", callback_data="products")],
        [InlineKeyboardButton("🔧 Admin", callback_data="admin_panel")]
    ])

def admin_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Product", callback_data="admin_add_product")],
        [InlineKeyboardButton("📦 View Products", callback_data="admin_view_products")],
        [InlineKeyboardButton("⬅ Close", callback_data="menu")]
    ])

# ================= START =================

async def start(update: Update, context):

    await update.message.reply_text(
        "Welcome Shop Bot",
        reply_markup=main_menu()
    )

# ================= ADMIN PANEL =================

async def admin_panel(update: Update, context):

    if update.effective_user.id != ADMIN_ID:
        return

    query = update.callback_query

    if query:
        await query.answer()
        await query.edit_message_text(
            "🔧 Admin Panel",
            reply_markup=admin_menu()
        )
    else:
        await update.message.reply_text(
            "🔧 Admin Panel",
            reply_markup=admin_menu()
        )

# ================= ADD PRODUCT FLOW =================

async def start_add_product(update: Update, context):

    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END

    query = update.callback_query
    await query.answer()

    await query.edit_message_text("📷 Send product photo:")

    return ADMIN_ADD_PHOTO

async def admin_add_product_photo(update: Update, context):

    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END

    context.user_data["photo"] = update.message.photo[-1].file_id

    await update.message.reply_text("✏ Product name:")
    return ADMIN_ADD_NAME

async def admin_add_product_name(update: Update, context):

    context.user_data["name"] = update.message.text

    await update.message.reply_text("💰 Product price:")
    return ADMIN_ADD_PRICE

async def admin_add_product_price(update: Update, context):

    try:
        context.user_data["price"] = float(update.message.text)
    except:
        await update.message.reply_text("Send numeric price.")
        return ADMIN_ADD_PRICE

    await update.message.reply_text("📝 Product description:")
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

# ================= SHOW PRODUCTS =================

async def show_products(update: Update, context):

    query = update.callback_query
    await query.answer()

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

    elif data == "products":
        await show_products(update, context)

    elif data == "admin_panel":
        await admin_panel(update, context)

# ================= MAIN =================

def main():

    init_db()

    app = ApplicationBuilder().token(TOKEN).build()

    conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(
                start_add_product,
                pattern="^admin_add_product$"
            )
        ],
        states={
            ADMIN_ADD_PHOTO: [
                MessageHandler(filters.PHOTO, admin_add_product_photo)
            ],
            ADMIN_ADD_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_product_name)
            ],
            ADMIN_ADD_PRICE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_product_price)
            ],
            ADMIN_ADD_DESC: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_product_desc)
            ],
        },
        fallbacks=[]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_panel))

    app.add_handler(CallbackQueryHandler(router))
    app.add_handler(conv)

    print("Bot Running...")
    app.run_polling()

if __name__ == "__main__":
    main()
