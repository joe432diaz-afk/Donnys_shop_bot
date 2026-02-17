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

================= CONFIG =================

TOKEN = os.environ.get("TOKEN")
CHANNEL_ID = -1003833257976
CRYPTO_WALLET = "LTC1qv4u6vr0gzp9g4lq0g3qev939vdnwxghn5gtnfc"

ADMINS = set()
orders = {}
sessions = {}

===== PRODUCTS AND PRICES =====

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

============== MENUS =================

def main_menu():
buttons = [
[InlineKeyboardButton(f"{name}", callback_data=f"prod_{key}")]
for key, name in PRODUCTS.items()
]
return InlineKeyboardMarkup(buttons)

============== START =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
await update.message.reply_text(
"👋 Welcome to Donny’s Shop\n\nSelect a product:",
reply_markup=main_menu()
)

============== CANCEL =================

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
sessions.pop(update.effective_user.id, None)
await update.message.reply_text(
"❌ Action cancelled.\nBack to main menu:",
reply_markup=main_menu()
)

============== PRODUCT FLOW =================

async def product_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
q = update.callback_query
await q.answer()

key = q.data.replace("prod_", "")  
if key not in PRODUCTS:  
    await q.edit_message_text("❌ Product not found.")  
    return  

sessions[q.from_user.id] = {  
    "product_key": key,  
    "product": PRODUCTS[key],  
    "step": "qty"  
}  

buttons = [  
    [InlineKeyboardButton(f"{g}g (£{PRICES[key][g]})", callback_data=f"qty_{g}")]  
    for g in PRICES[key]  
]  
buttons.append([InlineKeyboardButton("⬅ Back", callback_data="back")])  

await q.edit_message_text(  
    f"🛒 {PRODUCTS[key]}\nChoose quantity:",  
    reply_markup=InlineKeyboardMarkup(buttons)  
)

async def quantity_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
q = update.callback_query
await q.answer()

qty = q.data.replace("qty_", "")  
s = sessions[q.from_user.id]  
s["qty"] = qty  
s["price"] = PRICES[s["product_key"]][qty]  
s["step"] = "name"  

await q.edit_message_text("✍️ Send your FULL NAME:")

============== TEXT INPUT =================

async def text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
uid = update.message.from_user.id
s = sessions.get(uid)
if not s:
# Check if admin is in editing name/prices
admin_session = sessions.get(uid)
if admin_session:
await handle_admin_text(update, context, admin_session)
return

if s["step"] == "name":  
    s["name"] = update.message.text  
    s["step"] = "address"  
    await update.message.reply_text("📍 Send your FULL ADDRESS:")  
    return  

if s["step"] == "address":  
    s["address"] = update.message.text  
    order_id = random.randint(100000, 999999)  

    orders[order_id] = {  
        "user_id": uid,  
        "status": "Pending payment",  
        **s  
    }  

    summary = (  
        f"✅ *ORDER SUMMARY*\n\n"  
        f"Order #: {order_id}\n"  
        f"Product: {s['product']}\n"  
        f"Qty: {s['qty']}g\n"  
        f"Name: {s['name']}\n"  
        f"Address: {s['address']}\n\n"  
        f"💰 Amount to pay: *£{s['price']}*\n"  
        f"💳 *LTC ONLY*\n`{CRYPTO_WALLET}`"  
    )  

    buttons = InlineKeyboardMarkup([  
        [InlineKeyboardButton("✅ I HAVE PAID", callback_data=f"paid_{order_id}")],  
        [InlineKeyboardButton("⬅ Back to Menu", callback_data="back")]  
    ])  

    await update.message.reply_text(  
        summary,  
        parse_mode="Markdown",  
        reply_markup=buttons  
    )  

    # Admin notification with full info  
    admin_msg = (  
        f"🆕 *NEW ORDER #{order_id}*\n\n"  
        f"{s['product']} – {s['qty']}g\n"  
        f"£{s['price']}\n\n"  
        f"👤 {s['name']}\n"  
        f"📍 {s['address']}"  
    )  

    await context.bot.send_message(  
        CHANNEL_ID,  
        admin_msg,  
        parse_mode="Markdown"  
    )  

    sessions.pop(uid)

============== USER PAID =================

async def user_paid(update: Update, context: ContextTypes.DEFAULT_TYPE):
q = update.callback_query
await q.answer()

oid = int(q.data.replace("paid_", ""))  
o = orders[oid]  
o["status"] = "Paid – awaiting dispatch"  

text = (  
    f"✅ *PAYMENT MARKED*\n\n"  
    f"Order #: {oid}\n"  
    f"{o['product']} – {o['qty']}g\n\n"  
    f"💰 Amount: *£{o['price']}*\n"  
    f"💳 LTC Address:\n`{CRYPTO_WALLET}`\n\n"  
    f"Status: *{o['status']}*"  
)  

await q.edit_message_text(text, parse_mode="Markdown")

============== ADMIN PANEL =================

async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
uid = update.effective_user.id

if not ADMINS:  
    ADMINS.add(uid)  
    await update.message.reply_text(  
        f"✅ You are now the main admin.\nID: `{uid}`",  
        parse_mode="Markdown"  
    )  

if uid not in ADMINS:  
    await update.message.reply_text("❌ Not authorised.")  
    return  

# Admin options  
buttons = [  
    [InlineKeyboardButton("📦 View Orders", callback_data="admin_view_orders")],  
    [InlineKeyboardButton("🛠 Manage Products", callback_data="admin_manage_products")]  
]  

await update.message.reply_text(  
    "🛠 *ADMIN PANEL*",  
    parse_mode="Markdown",  
    reply_markup=InlineKeyboardMarkup(buttons)  
)

============== ADMIN CALLBACKS =================

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
q = update.callback_query
await q.answer()
data = q.data
uid = q.from_user.id

# --- Manage Products Menu ---  
if data == "admin_manage_products":  
    buttons = [[InlineKeyboardButton("➕ Add Product", callback_data="add_product")]]  
    for key, name in PRODUCTS.items():  
        buttons.append([InlineKeyboardButton(f"✏️ Edit {name}", callback_data=f"edit_{key}")])  
        buttons.append([InlineKeyboardButton(f"💲 Edit Prices", callback_data=f"price_{key}")])  
        buttons.append([InlineKeyboardButton(f"❌ Delete {name}", callback_data=f"del_{key}")])  
    buttons.append([InlineKeyboardButton("⬅ Back", callback_data="back")])  
    await q.edit_message_text(  
        "🛠 *PRODUCT MANAGEMENT*",  
        parse_mode="Markdown",  
        reply_markup=InlineKeyboardMarkup(buttons)  
    )  
    return  

# --- Add Product ---  
if data == "add_product":  
    sessions[uid] = {"step": "add_name"}  
    await q.edit_message_text("✍️ Send the NAME of the new product:")  
    return  

# --- Edit Product Name ---  
if data.startswith("edit_"):  
    key = data.replace("edit_", "")  
    sessions[uid] = {"step": "edit_name", "key": key}  
    await q.edit_message_text(f"✍️ Send the NEW NAME for {PRODUCTS[key]}:")  
    return  

# --- Edit Product Prices ---  
if data.startswith("price_"):  
    key = data.replace("price_", "")  
    sessions[uid] = {"step": "edit_prices", "key": key}  
    current = "\n".join([f"{g}:{p}" for g, p in PRICES[key].items()])  
    await q.edit_message_text(f"✍️ Send new price tiers for {PRODUCTS[key]} in this format:\n`{current}`\nExample:\n3.5:30\n7:50\n14:80", parse_mode="Markdown")  
    return  

# --- Delete Product ---  
if data.startswith("del_"):  
    key = data.replace("del_", "")  
    del PRODUCTS[key]  
    del PRICES[key]  
    await q.edit_message_text("✅ Product deleted.", reply_markup=main_menu())  
    return  

# --- Back ---  
if data == "back":  
    await q.edit_message_text("🛠 Back to Admin Panel", reply_markup=None)  
    await admin(update, context)  
    return

============== ADMIN TEXT HANDLER =================

async def handle_admin_text(update: Update, context: ContextTypes.DEFAULT_TYPE, session):
uid = update.message.from_user.id
step = session["step"]

# Add Product  
if step == "add_name":  
    name = update.message.text  
    key = name.lower().replace(" ", "_")  
    PRODUCTS[key] = name  
    PRICES[key] = {}  
    sessions[uid] = {"step": "add_prices", "key": key}  
    await update.message.reply_text(f"Send price tiers for {name} in format:\n3.5:30\n7:50\n14:80")  
    return  

if step == "add_prices":  
    key = session["key"]  
    new_prices = {}  
    try:  
        for line in update.message.text.splitlines():  
            g, p = line.strip().split(":")  
            new_prices[g] = int(p)  
        PRICES[key] = new_prices  
        sessions.pop(uid)  
        await update.message.reply_text(f"✅ Product {PRODUCTS[key]} added with prices {PRICES[key]}", reply_markup=main_menu())  
    except Exception as e:  
        await update.message.reply_text("❌ Invalid format. Use g:p per line, e.g., 3.5:30")  
    return  

# Edit Product Name  
if step == "edit_name":  
    key = session["key"]  
    PRODUCTS[key] = update.message.text  
    sessions.pop(uid)  
    await update.message.reply_text(f"✅ Product name updated to {PRODUCTS[key]}", reply_markup=main_menu())  
    return  

# Edit Prices  
if step == "edit_prices":  
    key = session["key"]  
    new_prices = {}  
    try:  
        for line in update.message.text.splitlines():  
            g, p = line.strip().split(":")  
            new_prices[g] = int(p)  
        PRICES[key] = new_prices  
        sessions.pop(uid)  
        await update.message.reply_text(f"✅ Prices updated for {PRODUCTS[key]}: {PRICES[key]}", reply_markup=main_menu())  
    except:  
        await update.message.reply_text("❌ Invalid format. Use g:p per line, e.g., 3.5:30")  
    return

============== BACK =================

async def back(update: Update, context: ContextTypes.DEFAULT_TYPE):
q = update.callback_query
await q.answer()
await q.edit_message_text("Main menu:", reply_markup=main_menu())

============== APP =================

app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("admin", admin))
app.add_handler(CommandHandler("cancel", cancel))

User product flow

app.add_handler(CallbackQueryHandler(product_select, pattern="^prod_"))
app.add_handler(CallbackQueryHandler(quantity_select, pattern="^qty_"))
app.add_handler(CallbackQueryHandler(user_paid, pattern="^paid_"))
app.add_handler(CallbackQueryHandler(back, pattern="^back$"))

Admin product management

app.add_handler(CallbackQueryHandler(admin_callback, pattern="^admin_"))
app.add_handler(CallbackQueryHandler(admin_callback, pattern="^(add_|edit_|del_|price_|admin_manage_products)$"))

Messages

app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_input))

print("✅ BOT RUNNING")
app.run_polling()
