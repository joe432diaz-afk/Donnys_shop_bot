import os
import json
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

# Conversation states
(
    ASK_NAME, ASK_ADDRESS, WRITE_REVIEW,
    ADD_PHOTO, ADD_TITLE, ADD_DESC, ADD_QTY,
    EDIT_TIERS_WAIT,
) = range(8)

# Default weight tiers â€” qty in grams, price in GBP
DEFAULT_TIERS = [
    {"qty": 1,   "price": 10.0},
    {"qty": 3.5, "price": 5.0},
    {"qty": 7,   "price": 4.0},
    {"qty": 14,  "price": 3.0},
    {"qty": 28,  "price": 2.0},
    {"qty": 56,  "price": 1.0},
]

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
        description TEXT,
        photo TEXT,
        stock INTEGER DEFAULT 0,
        tiers TEXT DEFAULT '[]'
    )
    """)

    # cart stores chosen weight qty and its price per line item
    c.execute("""
    CREATE TABLE IF NOT EXISTS cart(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        product_id INTEGER,
        chosen_qty REAL,
        chosen_price REAL
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS orders(
        id TEXT PRIMARY KEY,
        user_id INTEGER,
        name TEXT,
        address TEXT,
        total_gbp REAL,
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

# ================= HELPERS =================

def fmt_qty(qty):
    return f"{int(qty)}g" if qty == int(qty) else f"{qty}g"

def fmt_tier(t):
    return f"{fmt_qty(t['qty'])} â€” Â£{t['price']:.2f}"

def get_ltc_price_gbp():
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price?ids=litecoin&vs_currencies=gbp",
            timeout=10
        )
        return r.json()["litecoin"]["gbp"]
    except:
        return 55  # fallback

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
        "Welcome to Shop Bot ðŸ›’\n\nUse the menu below to browse products.",
        reply_markup=main_menu()
    )

# ================= PRODUCTS =================

async def show_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    conn = db()
    c = conn.cursor()
    c.execute("SELECT id, name, description, photo, stock, tiers FROM products")
    products = c.fetchall()
    conn.close()

    if not products:
        await query.edit_message_text("No products available.", reply_markup=main_menu())
        return

    for p in products:
        pid, name, description, photo, stock, tiers_json = p
        tiers = json.loads(tiers_json) if tiers_json else DEFAULT_TIERS[:]

        # Build one button per weight tier
        tier_buttons = []
        for t in tiers:
            tier_buttons.append(
                InlineKeyboardButton(
                    fmt_tier(t),
                    callback_data=f"pick_{pid}_{t['qty']}_{t['price']}"
                )
            )

        # 2 buttons per row
        rows = [tier_buttons[i:i+2] for i in range(0, len(tier_buttons), 2)]
        rows.append([InlineKeyboardButton("â¬… Back", callback_data="menu")])

        tiers_text = "\n".join(fmt_tier(t) for t in tiers)
        caption = (
            f"<b>{name}</b>\n\n"
            f"{description}\n\n"
            f"ðŸ“¦ In stock: {stock}\n\n"
            f"<b>Select weight:</b>\n{tiers_text}"
        )

        await context.bot.send_photo(
            query.message.chat_id,
            photo,
            caption=caption,
            reply_markup=InlineKeyboardMarkup(rows),
            parse_mode="HTML"
        )

# ================= PICK WEIGHT & ADD TO CART =================

async def pick_weight(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User tapped a weight tier â€” add that specific line to cart."""
    query = update.callback_query

    # callback_data: pick_{pid}_{qty}_{price}
    parts = query.data.split("_")
    pid = int(parts[1])
    chosen_qty = float(parts[2])
    chosen_price = float(parts[3])

    conn = db()
    c = conn.cursor()
    c.execute("SELECT name, stock FROM products WHERE id=?", (pid,))
    row = c.fetchone()

    if not row or row[1] < 1:
        conn.close()
        await query.answer("âŒ Out of stock!", show_alert=True)
        return

    c.execute(
        "INSERT INTO cart (user_id, product_id, chosen_qty, chosen_price) VALUES (?,?,?,?)",
        (query.from_user.id, pid, chosen_qty, chosen_price)
    )
    conn.commit()
    conn.close()

    await query.answer(f"âœ… Added {fmt_qty(chosen_qty)} of {row[0]} â€” Â£{chosen_price:.2f}", show_alert=True)

# ================= CART =================

async def view_cart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    conn = db()
    c = conn.cursor()
    c.execute("""
        SELECT cart.id, products.name, cart.chosen_qty, cart.chosen_price
        FROM cart
        JOIN products ON cart.product_id = products.id
        WHERE cart.user_id = ?
    """, (query.from_user.id,))
    items = c.fetchall()
    conn.close()

    if not items:
        await query.edit_message_text("ðŸ§º Your basket is empty.", reply_markup=main_menu())
        return

    total = sum(i[3] for i in items)
    text = "ðŸ§º <b>Your Basket:</b>\n\n"
    remove_buttons = []

    for cart_id, name, qty, price in items:
        text += f"â€¢ {name} ({fmt_qty(qty)}) â€” Â£{price:.2f}\n"
        remove_buttons.append([
            InlineKeyboardButton(
                f"âŒ Remove {name} ({fmt_qty(qty)})",
                callback_data=f"remove_{cart_id}"
            )
        ])

    text += f"\n<b>Total: Â£{total:.2f}</b>"

    keyboard = remove_buttons + [
        [InlineKeyboardButton("ðŸ’³ Checkout", callback_data="checkout")],
        [InlineKeyboardButton("â¬… Back", callback_data="menu")]
    ]

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )

async def remove_from_cart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    cart_id = int(query.data.split("_")[1])
    conn = db()
    c = conn.cursor()
    c.execute("DELETE FROM cart WHERE id=? AND user_id=?", (cart_id, query.from_user.id))
    conn.commit()
    conn.close()

    # Refresh the basket view
    await view_cart(update, context)

# ================= ORDERS =================

async def view_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    conn = db()
    c = conn.cursor()
    c.execute("""
        SELECT id, total_gbp, total_ltc, status
        FROM orders WHERE user_id=?
        ORDER BY rowid DESC
    """, (query.from_user.id,))
    orders = c.fetchall()
    conn.close()

    if not orders:
        await query.edit_message_text("No orders found.", reply_markup=main_menu())
        return

    text = "ðŸ“¦ <b>Your Orders:</b>\n\n"
    for o in orders:
        text += f"ID: <code>{o[0]}</code>\nÂ£{o[1]:.2f} ({o[2]} LTC)\nStatus: {o[3]}\n\n"

    await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup([
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

    text = "â­ <b>Reviews:</b>\n\n"
    for r in reviews:
        text += f"User {r[0]}:\n{r[1]}\n\n"

    await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("â¬… Back", callback_data="menu")]
    ]))

async def write_review_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    order_id = query.data.split("_", 2)[2]
    context.user_data["review_order_id"] = order_id
    await query.edit_message_text("âœï¸ Please write your review:")
    return WRITE_REVIEW

async def save_review(update: Update, context: ContextTypes.DEFAULT_TYPE):
    order_id = context.user_data.get("review_order_id")
    user_id = update.effective_user.id
    text = update.message.text

    conn = db()
    c = conn.cursor()
    c.execute(
        "SELECT id FROM orders WHERE id=? AND user_id=? AND status IN ('Paid','Dispatched')",
        (order_id, user_id)
    )
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
    await update.callback_query.edit_message_text("ðŸ“ Enter your name:")
    return ASK_NAME

async def get_name(update: Update, context):
    context.user_data["name"] = update.message.text
    await update.message.reply_text("ðŸ  Enter your delivery address:")
    return ASK_ADDRESS

async def get_address(update: Update, context):
    name = context.user_data["name"]
    address = update.message.text
    user_id = update.effective_user.id

    conn = db()
    c = conn.cursor()
    c.execute("SELECT chosen_price FROM cart WHERE user_id=?", (user_id,))
    prices = c.fetchall()

    if not prices:
        conn.close()
        await update.message.reply_text("Your basket is empty.", reply_markup=main_menu())
        return ConversationHandler.END

    total_gbp = round(sum(p[0] for p in prices), 2)
    ltc_price = get_ltc_price_gbp()
    total_ltc = round(total_gbp / ltc_price, 6)
    order_id = str(uuid4())[:8]

    c.execute(
        "INSERT INTO orders VALUES (?,?,?,?,?,?,?)",
        (order_id, user_id, name, address, total_gbp, total_ltc, "Awaiting Payment")
    )
    c.execute("DELETE FROM cart WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

    invoice = (
        f"ðŸ§¾ <b>Order Summary</b>\n\n"
        f"Order ID: <code>{order_id}</code>\n"
        f"Name: {name}\n"
        f"Address: {address}\n\n"
        f"ðŸ’· Total: Â£{total_gbp}\n"
        f"âš¡ LTC Total: {total_ltc}\n\n"
        f"Send LTC to:\n<code>{LTC_ADDRESS}</code>"
    )

    await update.message.reply_text(
        invoice,
        parse_mode="HTML",
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
    c.execute("SELECT id, status FROM orders ORDER BY rowid DESC")
    orders = c.fetchall()
    conn.close()

    keyboard = []
    for order_id, status in orders:
        if status == "Awaiting Payment":
            keyboard.append([
                InlineKeyboardButton(f"âœ… Confirm {order_id}", callback_data=f"admin_confirm_{order_id}"),
                InlineKeyboardButton(f"âŒ Reject {order_id}", callback_data=f"admin_reject_{order_id}")
            ])
        elif status == "Paid":
            keyboard.append([
                InlineKeyboardButton(f"ðŸšš Dispatch {order_id}", callback_data=f"admin_dispatch_{order_id}")
            ])

    keyboard.append([InlineKeyboardButton("âž• Add Product", callback_data="admin_add_product")])
    keyboard.append([InlineKeyboardButton("âœï¸ Edit Weight Tiers", callback_data="admin_list_tiers")])

    await update.message.reply_text(
        "ðŸ”§ <b>Admin Dashboard</b>",
        parse_mode="HTML",
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
        await update.message.reply_text("Please send a photo image (not a file or URL).")
        return ADD_PHOTO
    context.user_data["np_photo"] = update.message.photo[-1].file_id
    await update.message.reply_text("ðŸ“ Enter the product title:")
    return ADD_TITLE

async def add_product_title(update: Update, context):
    context.user_data["np_name"] = update.message.text.strip()
    await update.message.reply_text("ðŸ“„ Enter a product description:")
    return ADD_DESC

async def add_product_desc(update: Update, context):
    context.user_data["np_desc"] = update.message.text.strip()
    await update.message.reply_text("ðŸ“¦ Enter available stock quantity (1â€“1000):")
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
        "INSERT INTO products (name, description, photo, stock, tiers) VALUES (?,?,?,?,?)",
        (d["np_name"], d["np_desc"], d["np_photo"], qty, json.dumps(DEFAULT_TIERS))
    )
    conn.commit()
    conn.close()

    tiers_text = "\n".join(fmt_tier(t) for t in DEFAULT_TIERS)

    await update.message.reply_photo(
        d["np_photo"],
        caption=(
            f"âœ… <b>Product added!</b>\n\n"
            f"<b>{d['np_name']}</b>\n"
            f"ðŸ“¦ Stock: {qty}\n\n"
            f"<b>Default weight tiers:</b>\n{tiers_text}\n\n"
            f"Go to /admin â†’ Edit Weight Tiers to customise pricing."
        ),
        parse_mode="HTML"
    )

    for key in ["np_photo", "np_name", "np_desc"]:
        context.user_data.pop(key, None)

    return ConversationHandler.END

async def cancel_add_product(update: Update, context):
    await update.message.reply_text("Product creation cancelled.")
    return ConversationHandler.END

# ================= EDIT TIERS =================

async def admin_list_tiers(update: Update, context):
    """List all products so admin can pick one to edit tiers."""
    query = update.callback_query
    await query.answer()

    conn = db()
    c = conn.cursor()
    c.execute("SELECT id, name FROM products")
    products = c.fetchall()
    conn.close()

    if not products:
        await query.edit_message_text("No products yet.")
        return

    keyboard = [
        [InlineKeyboardButton(p[1], callback_data=f"edit_tiers_{p[0]}")]
        for p in products
    ]
    keyboard.append([InlineKeyboardButton("â¬… Back", callback_data="menu")])

    await query.edit_message_text(
        "âœï¸ Select a product to edit its weight tiers:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def admin_show_tiers(update: Update, context):
    """Show current tiers for chosen product, prompt admin for new ones."""
    query = update.callback_query
    await query.answer()

    product_id = int(query.data.split("_")[2])
    context.user_data["editing_tiers_pid"] = product_id

    conn = db()
    c = conn.cursor()
    c.execute("SELECT name, tiers FROM products WHERE id=?", (product_id,))
    row = c.fetchone()
    conn.close()

    name, tiers_json = row
    tiers = json.loads(tiers_json)
    tiers_text = "\n".join(fmt_tier(t) for t in tiers)

    await query.message.reply_text(
        f"âœï¸ <b>Editing tiers for: {name}</b>\n\n"
        f"<b>Current tiers:</b>\n{tiers_text}\n\n"
        f"Send new tiers, one per line in the format <code>qty,price</code>:\n\n"
        f"Example:\n<code>1,10\n3.5,5\n7,4\n14,3\n28,2\n56,1</code>\n\n"
        f"Send /cancel to abort.",
        parse_mode="HTML"
    )
    return EDIT_TIERS_WAIT

async def save_tiers(update: Update, context):
    product_id = context.user_data.get("editing_tiers_pid")
    lines = update.message.text.strip().splitlines()

    new_tiers = []
    errors = []
    for i, line in enumerate(lines, 1):
        parts = line.strip().split(",")
        if len(parts) != 2:
            errors.append(f"Line {i}: expected 'qty,price' â€” got '{line.strip()}'")
            continue
        try:
            qty = float(parts[0].strip())
            price = float(parts[1].strip())
            if qty <= 0 or price <= 0:
                raise ValueError("Must be positive")
            new_tiers.append({"qty": qty, "price": price})
        except ValueError as e:
            errors.append(f"Line {i}: {e}")

    if errors or not new_tiers:
        err_text = "\n".join(errors) if errors else "No valid tiers found."
        await update.message.reply_text(
            f"âŒ Errors:\n{err_text}\n\nFix and try again, or /cancel."
        )
        return EDIT_TIERS_WAIT

    # Sort by weight ascending
    new_tiers.sort(key=lambda t: t["qty"])

    conn = db()
    c = conn.cursor()
    c.execute("UPDATE products SET tiers=? WHERE id=?", (json.dumps(new_tiers), product_id))
    conn.commit()
    conn.close()

    tiers_text = "\n".join(fmt_tier(t) for t in new_tiers)
    await update.message.reply_text(
        f"âœ… <b>Weight tiers updated!</b>\n\n{tiers_text}",
        parse_mode="HTML"
    )
    return ConversationHandler.END

async def cancel_edit_tiers(update: Update, context):
    await update.message.reply_text("Tier editing cancelled.")
    return ConversationHandler.END

# ================= PAYMENT / ORDER ACTIONS =================

async def user_paid(update, context):
    query = update.callback_query
    await query.answer()
    order_id = query.data.split("_")[1]

    await context.bot.send_message(
        ADMIN_ID,
        f"ðŸ’¬ User {query.from_user.id} claims payment for order <code>{order_id}</code>",
        parse_mode="HTML"
    )
    await query.edit_message_text("âœ… Payment submitted. Awaiting admin confirmation.")

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
            f"âœ… Payment confirmed for order <code>{order_id}</code>. You can now leave a review!",
            parse_mode="HTML",
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
            f"âŒ Payment for order <code>{order_id}</code> was rejected. Please contact support.",
            parse_mode="HTML"
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
            f"ðŸšš Order <code>{order_id}</code> has been dispatched!",
            parse_mode="HTML"
        )
    await query.edit_message_text(f"Order {order_id} dispatched.")

# ================= ROUTER =================

async def router(update, context):
    data = update.callback_query.data

    if data == "menu":
        await update.callback_query.edit_message_text("Main Menu", reply_markup=main_menu())

    elif data == "products":
        await show_products(update, context)

    elif data.startswith("pick_"):
        await pick_weight(update, context)

    elif data.startswith("remove_"):
        await remove_from_cart(update, context)

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
        await update.callback_query.message.reply_text(
            "Use /addproduct to add a new product."
        )

    elif data == "admin_list_tiers":
        if update.effective_user.id != ADMIN_ID:
            return
        await admin_list_tiers(update, context)
# ================= MAIN =================
def main():
    init_db()
    app = ApplicationBuilder().token(TOKEN).build()
    checkout_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(checkout_start, pattern="^checkout$")],
        states={
            ASK_NAME:    [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            ASK_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_address)],
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
        entry_points=[CommandHandler("addproduct", add_product_start)],
        states={
            ADD_PHOTO: [MessageHandler(filters.PHOTO, add_product_photo)],
            ADD_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_product_title)],
            ADD_DESC:  [MessageHandler(filters.TEXT & ~filters.COMMAND, add_product_desc)],
            ADD_QTY:   [MessageHandler(filters.TEXT & ~filters.COMMAND, add_product_qty)],
        },
        fallbacks=[CommandHandler("cancel", cancel_add_product)]
    )
    edit_tiers_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_show_tiers, pattern="^edit_tiers_")],
        states={
            EDIT_TIERS_WAIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_tiers)]
        },
        fallbacks=[CommandHandler("cancel", cancel_edit_tiers)]
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(checkout_conv)
    app.add_handler(review_conv)
    app.add_handler(add_product_conv)
    app.add_handler(edit_tiers_conv)
    app.add_handler(CallbackQueryHandler(router))

    print("Bot running")
    app.run_polling()

if __name__ == "__main__":
    main()
