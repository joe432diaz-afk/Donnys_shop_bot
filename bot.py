import os
import sqlite3
import logging
import requests
from uuid import uuid4

from telegram import *
from telegram.ext import *

# ================= CONFIG =================

TOKEN = os.getenv("TOKEN")

ADMIN_ID = 7773622161
CHANNEL_ID = -1001234567890
LTC_ADDRESS = "YOUR_LTC_ADDRESS"

DB_NAME = "shop.db"

logging.basicConfig(level=logging.INFO)

ASK_NAME, ASK_ADDRESS, WRITE_REVIEW = range(3)
ADD_PHOTO, ADD_TITLE, ADD_PRICE, ADD_DESC, ADD_QTY = range(3, 8)

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
        photo TEXT,
        quantity INTEGER DEFAULT 0
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS cart(
        user_id INTEGER,
        product_id INTEGER
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS orders(
        id TEXT PRIMARY KEY,
        user_id INTEGER,
        name TEXT,
        address TEXT,
        total_usd REAL,
        total_ltc REAL,
        status TEXT
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS reviews(
        order_id TEXT PRIMARY KEY,
        user_id INTEGER,
        text TEXT
    )
    """)

    conn.commit()
    conn.close()

# ================= LTC PRICE =================

def get_ltc_price():
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price?ids=litecoin&vs_currencies=usd",
            timeout=10
        )
        return r.json()["litecoin"]["usd"]
    except:
        return 70

# ================= MAIN MENU =================

def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("ðŸ› Products", callback_data="products")],
        [InlineKeyboardButton("ðŸ§º Basket", callback_data="basket")],
        [InlineKeyboardButton("ðŸ“¦ Orders", callback_data="orders")],
        [InlineKeyboardButton("â­ Reviews", callback_data="public_reviews")]
    ])

# ================= START =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Welcome to Shop Bot",
        reply_markup=main_menu()
    )

# ================= PRODUCTS =================

async def show_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    conn = db()
    c = conn.cursor()
    c.execute("SELECT * FROM products")
    products = c.fetchall()
    conn.close()

    if not products:
        await query.edit_message_text("No products.")
        return

    for p in products:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Add Cart", callback_data=f"add_{p[0]}")],
            [InlineKeyboardButton("â¬… Back", callback_data="menu")]
        ])

        await context.bot.send_photo(
            query.message.chat_id,
            p[4],
            caption=f"{p[1]}\nðŸ’° ${p[2]}\nðŸ“¦ In stock: {p[5]}\n\n{p[3]}",
            reply_markup=keyboard
        )

# ================= CART =================

async def add_cart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pid = int(query.data.split("_")[1])

    conn = db()
    c = conn.cursor()
    c.execute("INSERT INTO cart VALUES (?,?)",
              (query.from_user.id, pid))
    conn.commit()
    conn.close()

    await query.answer("Added to cart", show_alert=True)

async def view_cart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    conn = db()
    c = conn.cursor()

    c.execute("""
    SELECT products.name, products.price
    FROM cart
    JOIN products ON cart.product_id=products.id
    WHERE cart.user_id=?
    """, (query.from_user.id,))

    items = c.fetchall()
    conn.close()

    if not items:
        await query.edit_message_text("Cart empty", reply_markup=main_menu())
        return

    total = sum([i[1] for i in items])

    text = "Your Cart:\n\n"
    for i in items:
        text += f"{i[0]} - ${i[1]}\n"

    text += f"\nTotal USD: ${total}"

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("ðŸ’³ Checkout", callback_data="checkout")],
            [InlineKeyboardButton("â¬… Back", callback_data="menu")]
        ])
    )

# ================= ORDERS =================

async def view_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    conn = db()
    c = conn.cursor()
    c.execute("""
    SELECT id, total_usd, total_ltc, status
    FROM orders
    WHERE user_id=?
    ORDER BY rowid DESC
    """, (query.from_user.id,))
    orders = c.fetchall()
    conn.close()

    if not orders:
        await query.edit_message_text("No orders found.", reply_markup=main_menu())
        return

    text = "ðŸ“¦ Your Orders:\n\n"
    for o in orders:
        text += f"ID: {o[0]}\nAmount: ${o[1]} ({o[2]} LTC)\nStatus: {o[3]}\n\n"

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("â¬… Back", callback_data="menu")]
    ]))

# ================= REVIEWS =================

async def show_public_reviews(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    conn = db()
    c = conn.cursor()
    c.execute("SELECT user_id, text FROM reviews ORDER BY rowid DESC LIMIT 20")
    reviews = c.fetchall()
    conn.close()

    if not reviews:
        await query.edit_message_text("No reviews yet.", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("â¬… Back", callback_data="menu")]
        ]))
        return

    text = "â­ Reviews:\n\n"
    for r in reviews:
        text += f"User {r[0]}:\n{r[1]}\n\n"

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("â¬… Back", callback_data="menu")]
    ]))

async def write_review_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    order_id = query.data.split("_", 2)[2]
    context.user_data["review_order_id"] = order_id
    await query.edit_message_text("Please write your review:")
    return WRITE_REVIEW

async def save_review(update: Update, context: ContextTypes.DEFAULT_TYPE):
    order_id = context.user_data.get("review_order_id")
    user_id = update.effective_user.id
    text = update.message.text

    conn = db()
    c = conn.cursor()
    # Check order belongs to user and is paid/dispatched
    c.execute("SELECT id FROM orders WHERE id=? AND user_id=? AND status IN ('Paid','Dispatched')", (order_id, user_id))
    if not c.fetchone():
        conn.close()
        await update.message.reply_text("Invalid order or not eligible for review.")
        return ConversationHandler.END

    c.execute("INSERT OR REPLACE INTO reviews VALUES (?,?,?)", (order_id, user_id, text))
    conn.commit()
    conn.close()

    await update.message.reply_text("âœ… Review saved! Thank you.", reply_markup=main_menu())
    return ConversationHandler.END

# ================= CHECKOUT =================

async def checkout_start(update: Update, context):
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("Enter your name:")
    return ASK_NAME

async def get_name(update: Update, context):
    context.user_data["name"] = update.message.text
    await update.message.reply_text("Enter address:")
    return ASK_ADDRESS

async def get_address(update: Update, context):
    name = context.user_data["name"]
    address = update.message.text
    conn = db()
    c = conn.cursor()

    c.execute("""
    SELECT products.price
    FROM cart
    JOIN products ON cart.product_id=products.id
    WHERE cart.user_id=?
    """, (update.effective_user.id,))

    prices = c.fetchall()

    if not prices:
        conn.close()
        await update.message.reply_text("Your cart is empty.", reply_markup=main_menu())
        return ConversationHandler.END

    total_usd = sum([p[0] for p in prices])

    ltc_price = get_ltc_price()
    total_ltc = round(total_usd / ltc_price, 6)

    order_id = str(uuid4())[:8]

    c.execute("""
    INSERT INTO orders VALUES (?,?,?,?,?,?,?)
    """, (
        order_id,
        update.effective_user.id,
        name,
        address,
        total_usd,
        total_ltc,
        "Awaiting Payment"
    ))

    c.execute("DELETE FROM cart WHERE user_id=?",
              (update.effective_user.id,))

    conn.commit()
    conn.close()

    invoice = f"""
Order ID: {order_id}

USD Total: ${total_usd}
LTC Total: {total_ltc}

Send LTC to: {LTC_ADDRESS}
"""
    await update.message.reply_text(
        invoice,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("âœ… I Have Paid", callback_data=f"paid_{order_id}")]
        ])
    )

    return ConversationHandler.END

# ================= ADMIN PANEL =================

async def admin_panel(update: Update, context):
    if update.effective_user.id != ADMIN_ID:
        return

    conn = db()
    c = conn.cursor()

    c.execute("SELECT id, status FROM orders")
    orders = c.fetchall()
    conn.close()

    if not orders:
        await update.message.reply_text(
            "No orders yet.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("âž• Add Product", callback_data="admin_add_product")]
            ])
        )
        return

    keyboard = []

    for order in orders:
        order_id = order[0]
        status = order[1]

        if status == "Awaiting Payment":
            keyboard.append([
                InlineKeyboardButton(
                    f"âœ… Confirm {order_id}",
                    callback_data=f"admin_confirm_{order_id}"
                )
            ])
            keyboard.append([
                InlineKeyboardButton(
                    f"âŒ Reject {order_id}",
                    callback_data=f"admin_reject_{order_id}"
                )
            ])

        if status == "Paid":
            keyboard.append([
                InlineKeyboardButton(
                    f"ðŸšš Dispatch {order_id}",
                    callback_data=f"admin_dispatch_{order_id}"
                )
            ])

    keyboard.append([
        InlineKeyboardButton("âž• Add Product", callback_data="admin_add_product")
    ])

    await update.message.reply_text(
        "Admin Dashboard",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ================= ADD PRODUCT =================

async def add_product_start(update: Update, context):
    if update.effective_user.id != ADMIN_ID:
        return
    await update.message.reply_text("ðŸ“¸ Send the product photo:")
    return ADD_PHOTO

async def add_product_photo(update: Update, context):
    if not update.message.photo:
        await update.message.reply_text("Please send a photo, not a file or URL.")
        return ADD_PHOTO
    # Store the largest resolution file_id
    context.user_data["new_product_photo"] = update.message.photo[-1].file_id
    await update.message.reply_text("ðŸ“ Enter the product title:")
    return ADD_TITLE

async def add_product_title(update: Update, context):
    context.user_data["new_product_name"] = update.message.text.strip()
    await update.message.reply_text("ðŸ’° Enter the price in USD (e.g. 9.99):")
    return ADD_PRICE

async def add_product_price(update: Update, context):
    try:
        price = float(update.message.text.strip())
        if price <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Invalid price. Please enter a positive number (e.g. 9.99):")
        return ADD_PRICE
    context.user_data["new_product_price"] = price
    await update.message.reply_text("ðŸ“„ Enter a product description:")
    return ADD_DESC

async def add_product_desc(update: Update, context):
    context.user_data["new_product_desc"] = update.message.text.strip()
    await update.message.reply_text("ðŸ“¦ Enter quantity (1â€“1000):")
    return ADD_QTY

async def add_product_qty(update: Update, context):
    try:
        qty = int(update.message.text.strip())
        if not (1 <= qty <= 1000):
            raise ValueError
    except ValueError:
        await update.message.reply_text("Please enter a whole number between 1 and 1000:")
        return ADD_QTY

    d = context.user_data
    conn = db()
    c = conn.cursor()
    c.execute(
        "INSERT INTO products (name, price, description, photo, quantity) VALUES (?,?,?,?,?)",
        (d["new_product_name"], d["new_product_price"], d["new_product_desc"], d["new_product_photo"], qty)
    )
    conn.commit()
    conn.close()

    # Preview the new product
    await update.message.reply_photo(
        d["new_product_photo"],
        caption=(
            f"âœ… Product added!\n\n"
            f"<b>{d['new_product_name']}</b>\n"
            f"ðŸ’° ${d['new_product_price']}\n"
            f"ðŸ“¦ Qty: {qty}\n\n"
            f"{d['new_product_desc']}"
        ),
        parse_mode="HTML"
    )

    # Clean up temp data
    for key in ["new_product_photo", "new_product_name", "new_product_price", "new_product_desc"]:
        context.user_data.pop(key, None)

    return ConversationHandler.END

async def cancel_add_product(update: Update, context):
    await update.message.reply_text("Product creation cancelled.")
    return ConversationHandler.END

# ================= PAYMENT CONFIRM =================

async def user_paid(update, context):
    query = update.callback_query
    await query.answer()

    order_id = query.data.split("_")[1]

    await context.bot.send_message(
        ADMIN_ID,
        f"User claims payment for order {order_id}"
    )

    await query.edit_message_text("Payment submitted. Awaiting admin confirmation.")

async def admin_confirm(update, context):
    query = update.callback_query
    await query.answer()

    order_id = query.data.split("_")[2]

    conn = db()
    c = conn.cursor()

    c.execute("UPDATE orders SET status='Paid' WHERE id=?", (order_id,))
    c.execute("SELECT user_id FROM orders WHERE id=?", (order_id,))

    row = c.fetchone()
    conn.commit()
    conn.close()

    if row:
        await context.bot.send_message(
            row[0],
            f"âœ… Payment confirmed for order {order_id}. You may now leave a review.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("â­ Leave Review", callback_data=f"review_{order_id}")]
            ])
        )

    await query.edit_message_text(f"Payment confirmed for {order_id}.")

async def admin_reject(update, context):
    query = update.callback_query
    await query.answer()

    order_id = query.data.split("_")[2]

    conn = db()
    c = conn.cursor()

    c.execute("UPDATE orders SET status='Rejected' WHERE id=?", (order_id,))
    c.execute("SELECT user_id FROM orders WHERE id=?", (order_id,))

    row = c.fetchone()
    conn.commit()
    conn.close()

    if row:
        await context.bot.send_message(
            row[0],
            f"âŒ Payment rejected for order {order_id}. Please contact support."
        )

    await query.edit_message_text(f"Order {order_id} rejected.")

async def admin_dispatch(update, context):
    query = update.callback_query
    await query.answer()

    order_id = query.data.split("_")[2]

    conn = db()
    c = conn.cursor()

    c.execute("UPDATE orders SET status='Dispatched' WHERE id=?", (order_id,))
    c.execute("SELECT user_id FROM orders WHERE id=?", (order_id,))

    row = c.fetchone()
    conn.commit()
    conn.close()

    if row:
        await context.bot.send_message(
            row[0],
            f"ðŸšš Order {order_id} has been dispatched!"
        )

    await query.edit_message_text(f"Order {order_id} dispatched.")

# ================= ROUTER =================

async def router(update, context):
    data = update.callback_query.data

    if data == "menu":
        await update.callback_query.edit_message_text(
            "Main Menu",
            reply_markup=main_menu()
        )

    elif data == "products":
        await show_products(update, context)

    elif data.startswith("add_"):
        await add_cart(update, context)

    elif data == "basket":
        await view_cart(update, context)

    elif data == "orders":
        await view_orders(update, context)

    elif data == "public_reviews":
        await show_public_reviews(update, context)

    elif data.startswith("paid_"):
        await user_paid(update, context)

    elif data.startswith("admin_confirm_"):
        await admin_confirm(update, context)

    elif data.startswith("admin_reject_"):
        await admin_reject(update, context)

    elif data.startswith("admin_dispatch_"):
        await admin_dispatch(update, context)

    elif data == "admin_add_product":
        if update.effective_user.id != ADMIN_ID:
            return
        await update.callback_query.answer()
        await update.callback_query.message.reply_text("ðŸ“¸ Send the product photo:")
        context.user_data["adding_product_via_router"] = True

# ================= MAIN =================

def main():
    init_db()

    app = ApplicationBuilder().token(TOKEN).build()

    checkout_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(checkout_start, pattern="^checkout$")],
        states={
            ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            ASK_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_address)]
        },
        fallbacks=[]
    )

    review_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(write_review_start, pattern="^review_")],
        states={
            WRITE_REVIEW: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_review)]
        },
        fallbacks=[]
    )

    add_product_conv = ConversationHandler(
        entry_points=[
            CommandHandler("addproduct", add_product_start),
        ],
        states={
            ADD_PHOTO: [MessageHandler(filters.PHOTO, add_product_photo)],
            ADD_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_product_title)],
            ADD_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_product_price)],
            ADD_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_product_desc)],
            ADD_QTY:  [MessageHandler(filters.TEXT & ~filters.COMMAND, add_product_qty)],
        },
        fallbacks=[CommandHandler("cancel", cancel_add_product)]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(checkout_conv)
    app.add_handler(review_conv)
    app.add_handler(add_product_conv)
    app.add_handler(CallbackQueryHandler(router))

    print("Bot running")
    app.run_polling()

if __name__ == "__main__":
    main()
