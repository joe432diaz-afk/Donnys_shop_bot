import os
import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

TOKEN = os.environ.get("TOKEN")
if not TOKEN:
    raise ValueError("TOKEN environment variable is missing!")

# ------------------- CONFIG -------------------
CHANNEL_ID = -1003833257976  # Admin channel ID
CRYPTO_WALLET = "LTC1qv4u6vr0gzp9g4lq0g3qev939vdnwxghn5gtnfc"
ADMINS = []  # Will auto-add first admin
# ---------------------------------------------

# Conversation states
SELECT_PRODUCT, SELECT_QUANTITY, NAME, ADDRESS, SHIPPING, DISCOUNT, CONFIRM, ADMIN_PANEL, ADMIN_ACTION, ADD_ADMIN = range(10)

# Store orders
user_orders = {}       # {user_id: {order info}}
all_orders = {}        # {order_number: {user_id, order info, status}}

# Products
products = {
    "lcg": "Lemon Cherry Gelato",
    "dawg": "Dawg",
    "cherry": "Cherry Punch"
}
quantities = ["3.5g", "7g", "14g", "28g", "56g"]
prices = {"3.5g":30, "7g":50, "14g":80, "28g":150, "56g":270}

# ---------------- /start ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Lemon Cherry Gelato", callback_data="product_lcg")],
        [InlineKeyboardButton("Dawg", callback_data="product_dawg")],
        [InlineKeyboardButton("Cherry Punch", callback_data="product_cherry")],
        [InlineKeyboardButton("Contact Donny", callback_data="contact_donny")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "👋 Hi folks! Welcome to Donny's Shop.\n\n"
        "Select a product below to begin your order, or PM @itsDonny1212 for help.",
        reply_markup=reply_markup
    )
    return SELECT_PRODUCT

# ---------------- Product selection ----------------
async def product_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "contact_donny":
        await query.edit_message_text("📩 PM @itsDonny1212 for help!")
        return SELECT_PRODUCT

    product_key = query.data.replace("product_", "")
    user_orders[query.from_user.id] = {"product": products.get(product_key, "Unknown")}

    keyboard = [[InlineKeyboardButton(q, callback_data=q)] for q in quantities]
    keyboard.append([InlineKeyboardButton("Back to Main Menu", callback_data="back")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        f"🛒 *{user_orders[query.from_user.id]['product']}*\nSelect quantity:",
        parse_mode="Markdown",
        reply_markup=reply_markup
    )
    return SELECT_QUANTITY

# ---------------- Quantity selection ----------------
async def select_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "back":
        return await start(update, context)

    user_orders[query.from_user.id]["quantity"] = query.data
    user_orders[query.from_user.id]["price"] = prices[query.data]

    await query.edit_message_text("Enter your full name for checkout:")
    return NAME

# ---------------- Name input ----------------
async def name_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_orders[update.message.from_user.id]["name"] = update.message.text
    await update.message.reply_text("Enter your shipping address:")
    return ADDRESS

# ---------------- Address input ----------------
async def address_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_orders[update.message.from_user.id]["address"] = update.message.text
    keyboard = [
        [InlineKeyboardButton("T24", callback_data="T24")],
        [InlineKeyboardButton("Back to Main Menu", callback_data="back")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Select your shipping method:", reply_markup=reply_markup)
    return SHIPPING

# ---------------- Shipping selection ----------------
async def shipping_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "back":
        return await start(update, context)

    user_orders[query.from_user.id]["shipping"] = query.data
    await query.edit_message_text("Enter discount code if you have one, or type 'none':")
    return DISCOUNT

# ---------------- Discount input ----------------
async def discount_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text
    order = user_orders[update.message.from_user.id]
    order["discount"] = code

    final_price = order["price"]
    if code.lower() != "none":
        final_price = int(final_price * 0.9)  # 10% discount
    order["final_price"] = final_price

    # Generate order number
    order_number = random.randint(1000, 9999)
    order["order_number"] = order_number
    all_orders[order_number] = {"user_id": update.message.from_user.id, "info": order.copy(), "status": "Pending"}

    summary = (
        f"✅ *Order Summary*\n"
        f"Order #: {order_number}\n"
        f"Product: {order['product']}\n"
        f"Quantity: {order['quantity']}\n"
        f"Name: {order['name']}\n"
        f"Address: {order['address']}\n"
        f"Shipping: {order['shipping']}\n"
        f"Discount: {order['discount']}\n"
        f"Amount to pay: £{final_price}\n"
        f"⏰ Payment timeframe: 3 hours\n"
        f"💳 LTC Wallet (copyable): `{CRYPTO_WALLET}`\n\n"
        f"Press 'Confirm Payment' when done or /cancel to cancel."
    )

    keyboard = [
        [InlineKeyboardButton("Back to Main Menu", callback_data="back")],
        [InlineKeyboardButton("Confirm Payment", callback_data=f"confirm_payment_{order_number}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(summary, parse_mode="Markdown", reply_markup=reply_markup)

    # Admin channel notification
    admin_message = (
        f"🛒 *New Order*\n"
        f"Order #: {order_number}\n"
        f"User: @{update.message.from_user.username}\n"
        f"Product: {order['product']}\n"
        f"Quantity: {order['quantity']}\n"
        f"Name: {order['name']}\n"
        f"Address: {order['address']}\n"
        f"Shipping: {order['shipping']}\n"
        f"Discount: {order['discount']}\n"
        f"Amount: £{final_price}\n"
        f"Status: Pending"
    )
    try:
        await context.bot.send_message(chat_id=CHANNEL_ID, text=admin_message, parse_mode="Markdown")
    except Exception as e:
        print("Admin notification failed:", e)

    return CONFIRM

# ---------------- Confirm Payment ----------------
async def confirm_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    if data.startswith("confirm_payment_"):
        order_number = int(data.replace("confirm_payment_", ""))
        if order_number in all_orders:
            all_orders[order_number]["status"] = "Paid, awaiting dispatch"
            user_id = all_orders[order_number]["user_id"]
            await context.bot.send_message(
                chat_id=user_id,
                text=f"✅ Payment confirmed for Order #{order_number}! Status: Paid, awaiting dispatch.\n"
                     f"LTC Wallet (copyable): `{CRYPTO_WALLET}`"
            )
            await query.edit_message_text(f"Order #{order_number} marked as Paid, awaiting dispatch.\nBack to main menu.")
    return await start(update, context)

# ---------------- Cancel ----------------
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Order cancelled. Returning to main menu.")
    return await start(update, context)

# ---------------- Admin Panel ----------------
async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    # Auto-add first admin if list is empty
    if len(ADMINS) == 0:
        ADMINS.append(user_id)
        await update.message.reply_text(f"✅ Your ID {user_id} has been added as the first admin.")

    # Show numeric ID for debug
    await update.message.reply_text(f"Your numeric Telegram ID is: `{user_id}`", parse_mode="Markdown")

    if user_id not in ADMINS:
        await update.message.reply_text("❌ You are not authorized to use the admin panel.")
        return ConversationHandler.END

    keyboard = []
    for order_number, data in all_orders.items():
        status = data["status"]
        keyboard.append([InlineKeyboardButton(f"Order #{order_number} - {status}", callback_data=f"admin_order_{order_number}")])

    # Add button to add new admin
    keyboard.append([InlineKeyboardButton("➕ Add New Admin", callback_data="add_new_admin")])
    keyboard.append([InlineKeyboardButton("Back to Menu", callback_data="back")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("📋 Admin Panel - Select an order or manage admins:", reply_markup=reply_markup)
    return ADMIN_PANEL

# ---------------- Add New Admin ----------------
async def add_new_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        new_admin_id = int(update.message.text.strip())
        if new_admin_id in ADMINS:
            await update.message.reply_text(f"User {new_admin_id} is already an admin.")
        else:
            ADMINS.append(new_admin_id)
            await update.message.reply_text(f"✅ User {new_admin_id} added as admin!")
    except:
        await update.message.reply_text("❌ Invalid numeric ID. Try again.")
    return await admin(update, context)

# ---------------- Application Setup ----------------
app = ApplicationBuilder().token(TOKEN).build()

conv_handler = ConversationHandler(
    entry_points=[CommandHandler("start", start), CommandHandler("admin", admin)],
    states={
        SELECT_PRODUCT: [CallbackQueryHandler(product_select)],
        SELECT_QUANTITY: [CallbackQueryHandler(select_quantity)],
        NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, name_input)],
        ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, address_input)],
        SHIPPING: [CallbackQueryHandler(shipping_select)],
        DISCOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, discount_input)],
        CONFIRM: [CallbackQueryHandler(confirm_payment, pattern="confirm_payment_")],
        ADMIN_PANEL: [CallbackQueryHandler(admin, pattern="admin_order_.*|add_new_admin|back")],
        ADD_ADMIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_new_admin)]
    },
    fallbacks=[CommandHandler("cancel", cancel)],
)

app.add_handler(conv_handler)

print("Bot is running...")
app.run_polling()
