import os
import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ================= CONFIG =================
TOKEN = os.environ.get("TOKEN")
CHANNEL_ID = -1003833257976  # Admin channel
CRYPTO_WALLET = "LTC1qv4u6vr0gzp9g4lq0g3qev939vdnwxghn5gtnfc"

ADMINS = set()
orders = {}
sessions = {}
user_baskets = {}
user_contact_history = {}

# ===== PRODUCTS AND PRICES =====
PRODUCTS = {
    "lcg": "Lemon Cherry Gelato",
    "dawg": "Dawg",
    "cherry": "Cherry Punch",
}

PRICES = {
    "lcg": {"3.5": 30, "7": 50, "14": 80, "28": 150, "56": 270},
    "dawg": {"3.5": 30, "7": 50, "14": 80, "28": 150, "56": 270},
    "cherry": {"3.5": 30, "7": 50, "14": 80, "28": 150, "56": 270},
}

# ============== MAIN MENU =================
def main_menu_keyboard():
    buttons = [
        [InlineKeyboardButton(name, callback_data=f"prod_{key}")] 
        for key, name in PRODUCTS.items()
    ]
    buttons.append([InlineKeyboardButton("🛒 Basket", callback_data="view_basket")])
    buttons.append([InlineKeyboardButton("💬 Contact Donny", callback_data="contact_admin")])
    return InlineKeyboardMarkup(buttons)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome to Donny’s Shop!\n\n"
        "Here for all your spiritual chest cheat codes and healing tools.\n\n"
        "Select a product or contact Donny:",
        reply_markup=main_menu_keyboard()
    )

# ============== BASKET =================
def basket_text(user_id):
    basket = user_baskets.get(user_id, {})
    if not basket:
        return "🛒 Your basket is empty."
    text = "🛒 Your Basket:\n"
    total = 0
    for key, item in basket.items():
        text += f"{PRODUCTS[key]} – {item['qty']}g – £{item['price']}\n"
        total += item['price']
    text += f"\n💰 Total: £{total}"
    return text

def basket_buttons(user_id):
    basket = user_baskets.get(user_id, {})
    buttons = []
    for key in basket:
        buttons.append([InlineKeyboardButton(f"Remove {PRODUCTS[key]}", callback_data=f"remove_{key}")])
    if basket:
        buttons.append([InlineKeyboardButton("✅ Checkout", callback_data="checkout")])
    buttons.append([InlineKeyboardButton("⬅ Back", callback_data="back")])
    return InlineKeyboardMarkup(buttons)

async def view_basket(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(
        basket_text(q.from_user.id),
        reply_markup=basket_buttons(q.from_user.id)
    )

# ============== PRODUCT FLOW =================
async def product_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    key = q.data.replace("prod_", "")
    if key not in PRODUCTS:
        await q.edit_message_text("❌ Product not found.")
        return
    # Show quantity buttons
    buttons = [
        [InlineKeyboardButton(f"{g}g (£{PRICES[key][g]})", callback_data=f"add_{key}_{g}")]
        for g in PRICES[key]
    ]
    buttons.append([InlineKeyboardButton("⬅ Back", callback_data="back")])
    await q.edit_message_text(f"🛒 {PRODUCTS[key]} – choose quantity:", reply_markup=InlineKeyboardMarkup(buttons))

async def add_to_basket(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    _, key, qty = q.data.split("_")
    price = PRICES[key][qty]
    user_id = q.from_user.id
    if user_id not in user_baskets:
        user_baskets[user_id] = {}
    user_baskets[user_id][key] = {"qty": qty, "price": price}
    await q.edit_message_text(f"✅ Added {PRODUCTS[key]} {qty}g (£{price}) to your basket.", reply_markup=main_menu_keyboard())

# ============== REMOVE ITEM =================
async def remove_item(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    key = q.data.replace("remove_", "")
    user_baskets.get(q.from_user.id, {}).pop(key, None)
    await view_basket(update, context)

# ============== CHECKOUT =================
async def checkout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    user_id = q.from_user.id
    basket = user_baskets.get(user_id, {})
    if not basket:
        await q.edit_message_text("🛒 Your basket is empty.", reply_markup=main_menu_keyboard())
        return
    sessions[user_id] = {"step": "checkout_name", "basket": basket}
    await q.edit_message_text("✍️ Send your FULL NAME for checkout:")

async def checkout_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    s = sessions.get(uid)
    if not s or "basket" not in s:
        return
    if s["step"] == "checkout_name":
        s["name"] = update.message.text
        s["step"] = "checkout_address"
        await update.message.reply_text("📍 Send your FULL ADDRESS:")
        return
    if s["step"] == "checkout_address":
        s["address"] = update.message.text
        # Create order
        order_id = random.randint(100000, 999999)
        total = sum([i['price'] for i in s['basket'].values()])
        orders[order_id] = {
            "user_id": uid,
            "status": "Pending payment",
            "name": s["name"],
            "address": s["address"],
            "basket": s["basket"],
            "total": total
        }
        # Send summary to user
        summary = f"✅ *ORDER SUMMARY*\nOrder #: {order_id}\n"
        for k, v in s['basket'].items():
            summary += f"{PRODUCTS[k]} – {v['qty']}g – £{v['price']}\n"
        summary += f"\n💰 Total: £{total}\n💳 *LTC ONLY*\n`{CRYPTO_WALLET}`"
        buttons = InlineKeyboardMarkup([[InlineKeyboardButton("✅ I HAVE PAID", callback_data=f"paid_{order_id}")]])
        await update.message.reply_text(summary, parse_mode="Markdown", reply_markup=buttons)
        # Notify admin
        admin_msg = f"🆕 *NEW ORDER #{order_id}*\n👤 {s['name']}\n📍 {s['address']}\n"
        for k,v in s['basket'].items():
            admin_msg += f"{PRODUCTS[k]} – {v['qty']}g – £{v['price']}\n"
        admin_msg += f"\n💰 Total: £{total}"
        await context.bot.send_message(CHANNEL_ID, admin_msg, parse_mode="Markdown")
        user_baskets[uid] = {}  # clear basket
        sessions.pop(uid)

# ============== USER PAID =================
async def user_paid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    order_id = int(q.data.replace("paid_", ""))
    o = orders[order_id]
    o["status"] = "Paid – awaiting dispatch"
    text = f"✅ *PAYMENT MARKED*\nOrder #: {order_id}\nStatus: *{o['status']}*\n💰 Total: £{o['total']}\n💳 LTC Address:\n`{CRYPTO_WALLET}`"
    await q.edit_message_text(text, parse_mode="Markdown")

# ============== CONTACT ADMIN =================
async def contact_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    sessions[uid] = {"step": "contact"}
    await q.edit_message_text("💬 Send your message to Donny:")

async def contact_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    s = sessions.get(uid)
    if s and s.get("step") == "contact":
        user_contact_history.setdefault(uid, []).append(update.message.text)
        await context.bot.send_message(CHANNEL_ID, f"💬 Message from {update.message.from_user.username or uid}:\n{update.message.text}")
        await update.message.reply_text("✅ Message sent to Donny.", reply_markup=main_menu_keyboard())
        sessions.pop(uid)

# ============== BACK =================
async def back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text("Main Menu:", reply_markup=main_menu_keyboard())

# ============== APP =================
app = ApplicationBuilder().token(TOKEN).build()

# Commands
app.add_handler(CommandHandler("start", start))

# CallbackQuery Handlers
app.add_handler(CallbackQueryHandler(product_select, pattern="^prod_"))
app.add_handler(CallbackQueryHandler(add_to_basket, pattern="^add_"))
app.add_handler(CallbackQueryHandler(view_basket, pattern="view_basket"))
app.add_handler(CallbackQueryHandler(remove_item, pattern="^remove_"))
app.add_handler(CallbackQueryHandler(checkout, pattern="checkout"))
app.add_handler(CallbackQueryHandler(user_paid, pattern="^paid_"))
app.add_handler(CallbackQueryHandler(contact_admin, pattern="contact_admin"))
app.add_handler(CallbackQueryHandler(back, pattern="^back$"))

# Messages
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, checkout_text))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, contact_text))

print("✅ BOT RUNNING")
app.run_polling()
