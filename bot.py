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

ADMIN_USERNAME = "@highlandhaze420"
CRYPTO_WALLET = "LTC1qv4u6vr0gzp9g4lq0g3qev939vdnwxghn5gtnfc"

# Conversation states
SELECT_PRODUCT, SELECT_QUANTITY, NAME, ADDRESS, SHIPPING, DISCOUNT, CONFIRM = range(7)

# Store user orders in memory
user_orders = {}

# Products
products = {
    "lcg": "Lemon Cherry Gelato",
    "dawg": "Dawg",
    "cherry": "Cherry Punch"
}

quantities = ["3.5g", "7g", "14g", "28g", "56g"]
prices = {"3.5g":30, "7g":50, "14g":80, "28g":150, "56g":270}

# ---------------------- Start ----------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Lemon Cherry Gelato", callback_data="product_lcg")],
        [InlineKeyboardButton("Dawg", callback_data="product_dawg")],
        [InlineKeyboardButton("Cherry Punch", callback_data="product_cherry")],
        [InlineKeyboardButton("Contact Donny", callback_data="contact_donny")],
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
        [InlineKeyboardButton("Back to Main Menu", callback_data="back")],
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
        final_price = int(final_price * 0.9)  # 10% discount example
    order["final_price"] = final_price

    # Generate order number
    order_number = random.randint(1000, 9999)
    order["order_number"] = order_number

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
        f"💳 Send LTC ONLY to: {CRYPTO_WALLET}\n\n"
        f"Press 'Confirm Payment' when done or /cancel to cancel."
    )

    keyboard = [[InlineKeyboardButton("Back to Menu", callback_data="back")],
                [InlineKeyboardButton("Confirm Payment", callback_data="confirm_payment")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(summary, parse_mode="Markdown", reply_markup=reply_markup)

    # Notify admin
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
        f"Amount: £{final_price}"
    )
    try:
        await context.bot.send_message(chat_id=ADMIN_USERNAME, text=admin_message, parse_mode="Markdown")
    except Exception as e:
        print("Admin notification failed:", e)

    return CONFIRM

# ---------------- Confirm Payment ----------------
async def confirm_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    await query.edit_message_text("✅ Payment confirmed! Thank you for your order.\nBack to main menu.")
    return await start(update, context)

# ---------------- Cancel ----------------
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Order cancelled. Returning to main menu.")
    return await start(update, context)

# ---------------- Application Setup ----------------
app = ApplicationBuilder().token(TOKEN).build()

conv_handler = ConversationHandler(
    entry_points=[CommandHandler("start", start)],
    states={
        SELECT_PRODUCT: [CallbackQueryHandler(product_select)],
        SELECT_QUANTITY: [CallbackQueryHandler(select_quantity)],
        NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, name_input)],
        ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, address_input)],
        SHIPPING: [CallbackQueryHandler(shipping_select)],
        DISCOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, discount_input)],
        CONFIRM: [CallbackQueryHandler(confirm_payment, pattern="confirm_payment")]
    },
    fallbacks=[CommandHandler("cancel", cancel)],
)

app.add_handler(conv_handler)

print("Bot is running...")
app.run_polling()
