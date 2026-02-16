import os
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

TOKEN = os.environ["TOKEN"]  # BotFather token from Render env vars

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Hi folks! Welcome to Donny's Shop.\n\n"
        "Here for all your spiritual chest cheat codes and healing tools.\n\n"
        "PM @itsDonny1212 for help, or check the price lists and send your crypto "
        "account according to the product price.\n\n"
        "You’ll automatically get a confirmation message once processed."
    )

app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))

print("Bot is running...")
app.run_polling()
