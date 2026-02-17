import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler

TOKEN = os.environ.get("TOKEN")
if not TOKEN:
    raise ValueError("TOKEN environment variable is missing!")

# /start command
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
        "Here for all your spiritual chest cheat codes and healing tools.\n\n"
        "Check out the products below or PM @itsDonny1212 for help.",
        reply_markup=reply_markup
    )

# Handle button presses
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "product_lcg":
        await query.edit_message_text(
            "🟢 *Lemon Cherry Gelato*\n\n"
            "Premium Lemon Cherry flavor. High quality • Clean • Reliable.\n\n"
            "💰 Prices:\n"
            "3.5g – £30\n"
            "7g – £50\n"
            "14g – £80\n"
            "28g – £150\n"
            "56g – £270\n\n"
            "💳 Payment: Crypto only\n"
            "📩 After payment, automatic confirmation.\n"
            "For help, PM @itsDonny1212",
            parse_mode="Markdown"
        )
    elif query.data == "product_dawg":
        await query.edit_message_text(
            "🟠 *Dawg*\n\n"
            "Premium Dawg product. High quality • Clean • Reliable.\n\n"
            "💰 Prices:\n"
            "3.5g – £30\n"
            "7g – £50\n"
            "14g – £80\n"
            "28g – £150\n"
            "56g – £270\n\n"
            "💳 Payment: Crypto only\n"
            "📩 After payment, automatic confirmation.\n"
            "For help, PM @itsDonny1212",
            parse_mode="Markdown"
        )
    elif query.data == "product_cherry":
        await query.edit_message_text(
            "🔴 *Cherry Punch*\n\n"
            "Premium Cherry Punch flavor. High quality • Clean • Reliable.\n\n"
            "💰 Prices:\n"
            "3.5g – £30\n"
            "7g – £50\n"
            "14g – £80\n"
            "28g – £150\n"
            "56g – £270\n\n"
            "💳 Payment: Crypto only\n"
            "📩 After payment, automatic confirmation.\n"
            "For help, PM @itsDonny1212",
            parse_mode="Markdown"
        )
    elif query.data == "contact_donny":
        await query.edit_message_text(
            "📩 PM @itsDonny1212 for help!"
        )

# Build and run bot
app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(button_handler))

print("Bot is running...")
app.run_polling()
