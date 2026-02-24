# -*- coding: utf-8 -*-
import os, json, sqlite3, logging, requests
from uuid import uuid4
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (ApplicationBuilder, CommandHandler, CallbackQueryHandler,
                           MessageHandler, ConversationHandler, ContextTypes, filters)

# CONFIG
TOKEN    = os.getenv("TOKEN")
ADMIN_ID = 7773622161
LTC_ADDR = "YOUR_LTC_ADDRESS"
DB_NAME  = "shop.db"
STARS    = {1:"⭐", 2:"⭐⭐", 3:"⭐⭐⭐", 4:"⭐⭐⭐⭐", 5:"⭐⭐⭐⭐⭐"}
logging.basicConfig(level=logging.INFO)

# States
(ASK_NAME, ASK_ADDR, PICK_STARS, WRITE_REVIEW,
 ADD_PHOTO, ADD_TITLE, ADD_DESC, ADD_QTY, EDIT_TIERS) = range(9)

DEFAULT_TIERS = [
    {"qty":1,   "price":10.0},
    {"qty":3.5, "price":5.0},
    {"qty":7,   "price":4.0},
    {"qty":14,  "price":3.0},
    {"qty":28,  "price":2.0},
    {"qty":56,  "price":1.0},
]

# DATABASE
def db(): return sqlite3.connect(DB_NAME)

def init_db():
    c = db(); cur = c.cursor()
    cur.executescript("""
    CREATE TABLE IF NOT EXISTS products(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT, description TEXT, photo TEXT,
        stock INTEGER DEFAULT 0, tiers TEXT DEFAULT '[]');
    CREATE TABLE IF NOT EXISTS cart(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, product_id INTEGER,
        chosen_qty REAL, chosen_price REAL);
    CREATE TABLE IF NOT EXISTS orders(
        id TEXT PRIMARY KEY, user_id INTEGER,
        name TEXT, address TEXT,
        total_gbp REAL, total_ltc REAL, status TEXT);
    CREATE TABLE IF NOT EXISTS reviews(
        order_id TEXT PRIMARY KEY, user_id INTEGER,
        stars INTEGER DEFAULT 0, text TEXT);
    """)
    try: cur.execute("ALTER TABLE reviews ADD COLUMN stars INTEGER DEFAULT 0")
    except: pass
    c.commit(); c.close()

# HELPERS
def fq(q): return f"{int(q)}g" if q == int(q) else f"{q}g"
def ft(t): return f"⚖️ {fq(t['qty'])} — £{t['price']:.2f}/g"
def mask_user(uid): return "**********"

def ltc_rate():
    try:
        r = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=litecoin&vs_currencies=gbp", timeout=10)
        return r.json()["litecoin"]["gbp"]
    except: return 55

def menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛍️ Products",  callback_data="products")],
        [InlineKeyboardButton("🧺 Basket",    callback_data="basket")],
        [InlineKeyboardButton("📦 My Orders", callback_data="orders")],
        [InlineKeyboardButton("⭐ Reviews",   callback_data="pub_reviews")],
    ])

def back_btn(): return InlineKeyboardButton("⬅️ Back", callback_data="menu")

# START
async def start(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await u.message.reply_text(
        "🛒 Welcome to <b>Shop Bot</b>!\n\nUse the menu below to get started.",
        reply_markup=menu(), parse_mode="HTML")

# PRODUCTS
async def show_products(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = u.callback_query; await q.answer()
    c = db().cursor(); c.execute("SELECT id,name,description,photo,stock,tiers FROM products")
    rows = c.fetchall()
    if not rows:
        await q.edit_message_text("😔 No products available.", reply_markup=menu()); return
    for pid, name, desc, photo, stock, tj in rows:
        tiers = json.loads(tj) if tj else DEFAULT_TIERS[:]
        btns  = [InlineKeyboardButton(ft(t), callback_data=f"pick_{pid}_{t['qty']}_{t['price']}") for t in tiers]
        rows2 = [btns[i:i+2] for i in range(0, len(btns), 2)]
        rows2.append([back_btn()])
        cap = (f"🌿 <b>{name}</b>\n\n📝 {desc}\n\n"
               f"📦 In stock: <b>{stock}</b>\n\n"
               f"<b>Select weight:</b>\n" + "\n".join(ft(t) for t in tiers))
        await ctx.bot.send_photo(q.message.chat_id, photo, caption=cap,
                                 reply_markup=InlineKeyboardMarkup(rows2), parse_mode="HTML")

# ADD TO CART
async def pick_weight(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = u.callback_query
    parts = q.data.split("_")
    pid = int(parts[1]); qty = float(parts[2]); price = float(parts[3])
    con = db(); cur = con.cursor()
    cur.execute("SELECT name,stock FROM products WHERE id=?", (pid,)); row = cur.fetchone()
    if not row or row[1] < 1:
        con.close(); await q.answer("❌ Out of stock!", show_alert=True); return
    cur.execute("INSERT INTO cart(user_id,product_id,chosen_qty,chosen_price) VALUES(?,?,?,?)",
                (q.from_user.id, pid, qty, price))
    con.commit(); con.close()
    await q.answer(f"✅ Added {fq(qty)} of {row[0]} — £{price:.2f}", show_alert=True)

# BASKET
async def view_basket(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = u.callback_query; await q.answer()
    con = db(); cur = con.cursor()
    cur.execute("""SELECT cart.id, products.name, cart.chosen_qty, cart.chosen_price
                   FROM cart JOIN products ON cart.product_id=products.id
                   WHERE cart.user_id=?""", (q.from_user.id,))
    items = cur.fetchall(); con.close()
    if not items:
        await q.edit_message_text("🧺 Your basket is empty.", reply_markup=menu()); return
    total = sum(i[3] for i in items)
    txt = "🧺 <b>Your Basket</b>\n\n"
    for _, n, qy, p in items:
        txt += f"🌿 {n} ({fq(qy)}) — £{p:.2f}\n"
    txt += f"\n💰 <b>Total: £{total:.2f}</b>"
    rm  = [[InlineKeyboardButton(f"🗑️ Remove {n} ({fq(qy)})", callback_data=f"remove_{cid}")] for cid,n,qy,_ in items]
    kb  = rm + [[InlineKeyboardButton("💳 Checkout", callback_data="checkout")], [back_btn()]]
    await q.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")

async def remove_item(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = u.callback_query; await q.answer()
    cid = int(q.data.split("_")[1])
    con = db(); cur = con.cursor()
    cur.execute("DELETE FROM cart WHERE id=? AND user_id=?", (cid, q.from_user.id))
    con.commit(); con.close()
    await view_basket(u, ctx)

# ORDERS
async def view_orders(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = u.callback_query; await q.answer()
    con = db(); cur = con.cursor()
    cur.execute("SELECT id,total_gbp,total_ltc,status FROM orders WHERE user_id=? ORDER BY rowid DESC", (q.from_user.id,))
    rows = cur.fetchall(); con.close()
    if not rows:
        await q.edit_message_text("📭 No orders found.", reply_markup=menu()); return
    emap = {"Awaiting Payment":"⏳ Awaiting Payment", "Paid":"✅ Paid", "Dispatched":"🚚 Dispatched", "Rejected":"❌ Rejected"}
    txt  = "📦 <b>Your Orders</b>\n\n"
    for o in rows:
        txt += f"🔖 <code>{o[0]}</code>\n💷 £{o[1]:.2f} ({o[2]} LTC)\n{emap.get(o[3], o[3])}\n\n"
    await q.edit_message_text(txt, parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[back_btn()]]))

# PUBLIC REVIEWS
async def pub_reviews(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = u.callback_query; await q.answer()
    con = db(); cur = con.cursor()
    cur.execute("SELECT user_id,stars,text FROM reviews ORDER BY rowid DESC LIMIT 20")
    rows = cur.fetchall(); con.close()
    if not rows:
        await q.edit_message_text("💬 No reviews yet.", reply_markup=InlineKeyboardMarkup([[back_btn()]])); return
    txt = "⭐ <b>Customer Reviews</b>\n\n"
    for r in rows:
        txt += f"👤 **********\n{STARS.get(r[1], 'No rating')}\n💬 {r[2]}\n\n"
    await q.edit_message_text(txt, parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[back_btn()]]))

# REVIEW FLOW
async def review_start(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = u.callback_query; await q.answer()
    ctx.user_data["rev_order"] = q.data[7:]
    kb = [
        [InlineKeyboardButton("⭐ 1",    callback_data="stars_1"),
         InlineKeyboardButton("⭐⭐ 2",   callback_data="stars_2"),
         InlineKeyboardButton("⭐⭐⭐ 3",  callback_data="stars_3")],
        [InlineKeyboardButton("⭐⭐⭐⭐ 4",   callback_data="stars_4"),
         InlineKeyboardButton("⭐⭐⭐⭐⭐ 5",  callback_data="stars_5")],
    ]
    await q.edit_message_text("⭐ <b>Rate Your Order</b>\n\nHow many stars?",
                               parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
    return PICK_STARS

async def pick_stars(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = u.callback_query; await q.answer()
    s = int(q.data.split("_")[1])
    ctx.user_data["rev_stars"] = s
    await q.edit_message_text(f"✨ You picked: {STARS[s]}\n\n✏️ Now write your review and send it:")
    return WRITE_REVIEW

async def save_review(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    oid   = ctx.user_data.get("rev_order")
    stars = ctx.user_data.get("rev_stars", 0)
    uid   = u.effective_user.id
    txt   = u.message.text
    con   = db(); cur = con.cursor()
    cur.execute("SELECT id FROM orders WHERE id=? AND user_id=? AND status IN ('Paid','Dispatched')", (oid, uid))
    if not cur.fetchone():
        con.close()
        await u.message.reply_text("⚠️ This order is not eligible for a review.")
        return ConversationHandler.END
    cur.execute("INSERT OR REPLACE INTO reviews VALUES(?,?,?,?)", (oid, uid, stars, txt))
    con.commit(); con.close()
    await u.message.reply_text(f"✅ Review saved! {STARS.get(stars, '')} Thank you 🙏", reply_markup=menu())
    return ConversationHandler.END

# CHECKOUT
async def checkout_start(u: Update, ctx):
    await u.callback_query.answer()
    await u.callback_query.edit_message_text("✍️ Enter your name:")
    return ASK_NAME

async def get_name(u: Update, ctx):
    ctx.user_data["name"] = u.message.text
    await u.message.reply_text("🏠 Enter your delivery address:")
    return ASK_ADDR

async def get_addr(u: Update, ctx):
    name = ctx.user_data["name"]; addr = u.message.text; uid = u.effective_user.id
    con  = db(); cur = con.cursor()
    cur.execute("SELECT chosen_price FROM cart WHERE user_id=?", (uid,)); prices = cur.fetchall()
    if not prices:
        con.close(); await u.message.reply_text("🧺 Your basket is empty.", reply_markup=menu()); return ConversationHandler.END
    gbp = round(sum(p[0] for p in prices), 2)
    ltc = round(gbp / ltc_rate(), 6)
    oid = str(uuid4())[:8]
    cur.execute("INSERT INTO orders VALUES(?,?,?,?,?,?,?)", (oid, uid, name, addr, gbp, ltc, "Awaiting Payment"))
    cur.execute("DELETE FROM cart WHERE user_id=?", (uid,))
    con.commit(); con.close()
    await u.message.reply_text(
        f"🧾 <b>Order Summary</b>\n\n🔖 Order ID: <code>{oid}</code>\n👤 Name: {name}\n🏠 Address: {addr}\n\n"
        f"💷 Total: £{gbp}\n⚡ LTC Total: {ltc}\n\n📤 Send LTC to:\n<code>{LTC_ADDR}</code>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ I Have Paid", callback_data=f"paid_{oid}")]]))
    return ConversationHandler.END

# ADMIN
async def admin_panel(u: Update, ctx):
    if u.effective_user.id != ADMIN_ID: return
    con = db(); cur = con.cursor()
    cur.execute("SELECT id,status FROM orders ORDER BY rowid DESC"); orders = cur.fetchall(); con.close()
    kb = []
    for oid, st in orders:
        if st == "Awaiting Payment":
            kb.append([InlineKeyboardButton(f"✅ Confirm {oid}", callback_data=f"adm_ok_{oid}"),
                       InlineKeyboardButton(f"❌ Reject {oid}",  callback_data=f"adm_no_{oid}")])
        elif st == "Paid":
            kb.append([InlineKeyboardButton(f"🚚 Dispatch {oid}", callback_data=f"adm_go_{oid}")])
    kb += [[InlineKeyboardButton("➕ Add Product",  callback_data="adm_addprod")],
           [InlineKeyboardButton("✏️ Edit Tiers",   callback_data="adm_tiers")]]
    await u.message.reply_text("🔧 <b>Admin Dashboard</b>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))

async def adm_confirm(u, ctx):
    q = u.callback_query; await q.answer(); oid = q.data[7:]
    con = db(); cur = con.cursor()
    cur.execute("UPDATE orders SET status='Paid' WHERE id=?", (oid,))
    cur.execute("SELECT user_id FROM orders WHERE id=?", (oid,)); row = cur.fetchone()
    con.commit(); con.close()
    if row:
        await ctx.bot.send_message(row[0],
            f"✅ Payment confirmed for order <code>{oid}</code>\n\n🌟 Leave a review once your order arrives:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⭐ Leave a Review", callback_data=f"review_{oid}")]]))
    await q.edit_message_text(f"Confirmed order {oid}")

async def adm_reject(u, ctx):
    q = u.callback_query; await q.answer(); oid = q.data[7:]
    con = db(); cur = con.cursor()
    cur.execute("UPDATE orders SET status='Rejected' WHERE id=?", (oid,))
    cur.execute("SELECT user_id FROM orders WHERE id=?", (oid,)); row = cur.fetchone()
    con.commit(); con.close()
    if row: await ctx.bot.send_message(row[0], f"❌ Payment for order <code>{oid}</code> was rejected. Please contact support.", parse_mode="HTML")
    await q.edit_message_text(f"Rejected order {oid}")

async def adm_dispatch(u, ctx):
    q = u.callback_query; await q.answer(); oid = q.data[7:]
    con = db(); cur = con.cursor()
    cur.execute("UPDATE orders SET status='Dispatched' WHERE id=?", (oid,))
    cur.execute("SELECT user_id FROM orders WHERE id=?", (oid,)); row = cur.fetchone()
    con.commit(); con.close()
    if row: await ctx.bot.send_message(row[0], f"🚚 Order <code>{oid}</code> has been dispatched! 📬", parse_mode="HTML")
    await q.edit_message_text(f"Dispatched order {oid}")

async def user_paid(u, ctx):
    q = u.callback_query; await q.answer(); oid = q.data[5:]
    await ctx.bot.send_message(ADMIN_ID, f"💬 User {q.from_user.id} claims payment for order <code>{oid}</code>", parse_mode="HTML")
    await q.edit_message_text("⏳ Payment submitted. Awaiting admin confirmation.")

# ADD PRODUCT
async def addprod_start(u, ctx):
    if u.effective_user.id != ADMIN_ID: return
    await u.message.reply_text("📸 Send the product photo:"); return ADD_PHOTO

async def addprod_photo(u, ctx):
    if not u.message.photo: await u.message.reply_text("⚠️ Please send a photo."); return ADD_PHOTO
    ctx.user_data["ph"] = u.message.photo[-1].file_id
    await u.message.reply_text("📝 Enter product title:"); return ADD_TITLE

async def addprod_title(u, ctx):
    ctx.user_data["nm"] = u.message.text.strip()
    await u.message.reply_text("📄 Enter product description:"); return ADD_DESC

async def addprod_desc(u, ctx):
    ctx.user_data["ds"] = u.message.text.strip()
    await u.message.reply_text("📦 Enter stock quantity (1–1000):"); return ADD_QTY

async def addprod_qty(u, ctx):
    try:
        qty = int(u.message.text.strip()); assert 1 <= qty <= 1000
    except:
        await u.message.reply_text("⚠️ Please enter a number between 1 and 1000:"); return ADD_QTY
    d = ctx.user_data; con = db(); cur = con.cursor()
    cur.execute("INSERT INTO products(name,description,photo,stock,tiers) VALUES(?,?,?,?,?)",
                (d["nm"], d["ds"], d["ph"], qty, json.dumps(DEFAULT_TIERS)))
    con.commit(); con.close()
    await u.message.reply_photo(d["ph"], caption=f"✅ <b>Product added!</b>\n\n🌿 {d['nm']}\n📦 Stock: {qty}", parse_mode="HTML")
    return ConversationHandler.END

async def cancel(u, ctx):
    await u.message.reply_text("🚫 Cancelled."); return ConversationHandler.END

# EDIT TIERS
async def adm_list_tiers(u, ctx):
    q = u.callback_query; await q.answer()
    con = db(); cur = con.cursor(); cur.execute("SELECT id,name FROM products"); rows = cur.fetchall(); con.close()
    if not rows: await q.edit_message_text("😔 No products found."); return
    kb = [[InlineKeyboardButton(r[1], callback_data=f"edtier_{r[0]}")] for r in rows] + [[back_btn()]]
    await q.edit_message_text("✏️ Select a product to edit tiers:", reply_markup=InlineKeyboardMarkup(kb))

async def adm_show_tiers(u, ctx):
    q = u.callback_query; await q.answer()
    pid = int(q.data.split("_")[1]); ctx.user_data["tpid"] = pid
    con = db(); cur = con.cursor(); cur.execute("SELECT name,tiers FROM products WHERE id=?", (pid,)); row = cur.fetchone(); con.close()
    tiers = json.loads(row[1]); txt = "\n".join(ft(t) for t in tiers)
    await q.message.reply_text(
        f"✏️ <b>Tiers for {row[0]}</b>\n\n{txt}\n\nSend new tiers one per line as qty,price\nExample:\n<code>1,10\n3.5,5\n7,4</code>\n\nSend /cancel to stop.",
        parse_mode="HTML")
    return EDIT_TIERS

async def save_tiers(u, ctx):
    pid = ctx.user_data.get("tpid"); lines = u.message.text.strip().splitlines(); new = []; errs = []
    for i, line in enumerate(lines, 1):
        p = line.strip().split(",")
        if len(p) != 2: errs.append(f"Line {i}: expected qty,price"); continue
        try:
            q2, pr = float(p[0]), float(p[1]); assert q2 > 0 and pr > 0; new.append({"qty":q2,"price":pr})
        except: errs.append(f"Line {i}: invalid numbers")
    if errs or not new:
        await u.message.reply_text("Errors:\n" + "\n".join(errs or ["No valid tiers."]) + "\n\nFix and retry or /cancel.")
        return EDIT_TIERS
    new.sort(key=lambda t: t["qty"])
    con = db(); cur = con.cursor(); cur.execute("UPDATE products SET tiers=? WHERE id=?", (json.dumps(new), pid)); con.commit(); con.close()
    await u.message.reply_text("✅ <b>Tiers updated!</b>\n\n" + "\n".join(ft(t) for t in new), parse_mode="HTML")
    return ConversationHandler.END

# ROUTER
async def router(u: Update, ctx):
    data = u.callback_query.data
    if   data == "menu":           await u.callback_query.edit_message_text("🏠 Main Menu", reply_markup=menu())
    elif data == "products":       await show_products(u, ctx)
    elif data == "basket":         await view_basket(u, ctx)
    elif data == "orders":         await view_orders(u, ctx)
    elif data == "pub_reviews":    await pub_reviews(u, ctx)
    elif data.startswith("pick_"):     await pick_weight(u, ctx)
    elif data.startswith("remove_"):   await remove_item(u, ctx)
    elif data.startswith("paid_"):     await user_paid(u, ctx)
    elif data.startswith("adm_ok_"):   await adm_confirm(u, ctx)
    elif data.startswith("adm_no_"):   await adm_reject(u, ctx)
    elif data.startswith("adm_go_"):   await adm_dispatch(u, ctx)
    elif data == "adm_addprod":
        if u.effective_user.id == ADMIN_ID:
            await u.callback_query.message.reply_text("Use /addproduct to add a new product.")
    elif data == "adm_tiers":
        if u.effective_user.id == ADMIN_ID: await adm_list_tiers(u, ctx)

# MAIN
def main():
    init_db()
    app = ApplicationBuilder().token(TOKEN).build()

    review_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(review_start, pattern="^review_")],
        states={
            PICK_STARS:   [CallbackQueryHandler(pick_stars, pattern="^stars_")],
            WRITE_REVIEW: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_review)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False
    )
    checkout_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(checkout_start, pattern="^checkout$")],
        states={
            ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            ASK_ADDR: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_addr)],
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    addprod_conv = ConversationHandler(
        entry_points=[CommandHandler("addproduct", addprod_start)],
        states={
            ADD_PHOTO: [MessageHandler(filters.PHOTO, addprod_photo)],
            ADD_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, addprod_title)],
            ADD_DESC:  [MessageHandler(filters.TEXT & ~filters.COMMAND, addprod_desc)],
            ADD_QTY:   [MessageHandler(filters.TEXT & ~filters.COMMAND, addprod_qty)],
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    edtiers_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(adm_show_tiers, pattern="^edtier_")],
        states={EDIT_TIERS: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_tiers)]},
        fallbacks=[CommandHandler("cancel", cancel)]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(review_conv)       # Must be before router
    app.add_handler(checkout_conv)
    app.add_handler(addprod_conv)
    app.add_handler(edtiers_conv)
    app.add_handler(CallbackQueryHandler(router))

    print("Bot is running")
    app.run_polling()

if __name__ == "__main__":
    main()
