# -*- coding: utf-8 -*-
import os, json, sqlite3, logging, requests
from uuid import uuid4
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (ApplicationBuilder, CommandHandler, CallbackQueryHandler,
                           MessageHandler, ConversationHandler, ContextTypes, filters)

# ── CONFIG ──────────────────────────────────────────────────────────────────
TOKEN      = os.getenv("TOKEN")
ADMIN_ID   = 7773622161
CHANNEL_ID = -1003833257976
LTC_ADDR   = "ltc1qv4u6vr0gzp9g4lq0g3qev939vdnwxghn5gtnfc"
DB_NAME    = "shop.db"
STARS      = {1:"⭐",2:"⭐⭐",3:"⭐⭐⭐",4:"⭐⭐⭐⭐",5:"⭐⭐⭐⭐⭐"}
DISCOUNT_CODES = {"SAVE10": 0.10}
SHIPPING   = {"tracked24":{"label":"📦 Tracked24","price":5.0},
              "free":     {"label":"🚶 Collection (Free)","price":0.0}}
DEFAULT_TIERS = [{"qty":1,"price":10.0},{"qty":3.5,"price":5.0},{"qty":7,"price":4.0},
                 {"qty":14,"price":3.0},{"qty":28,"price":2.0},{"qty":56,"price":1.0}]
logging.basicConfig(level=logging.INFO)

# ── STATES ──────────────────────────────────────────────────────────────────
(PICK_STARS, WRITE_REVIEW, ADD_PHOTO, ADD_TITLE, ADD_DESC, ADD_QTY,
 EDIT_TIERS, ASK_CONTACT, ASK_ANN_TITLE, ASK_ANN_BODY,
 CO_NAME, CO_ADDR, CO_DISC) = range(13)

# ── DATABASE ─────────────────────────────────────────────────────────────────
def db(): return sqlite3.connect(DB_NAME)

def init_db():
    c = db(); cur = c.cursor()
    cur.executescript("""
    CREATE TABLE IF NOT EXISTS products(id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT, description TEXT, photo TEXT, stock INTEGER DEFAULT 0, tiers TEXT DEFAULT '[]');
    CREATE TABLE IF NOT EXISTS cart(id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, product_id INTEGER, chosen_qty REAL, chosen_price REAL);
    CREATE TABLE IF NOT EXISTS orders(id TEXT PRIMARY KEY, user_id INTEGER,
        name TEXT, address TEXT, total_gbp REAL, total_ltc REAL, status TEXT);
    CREATE TABLE IF NOT EXISTS reviews(order_id TEXT PRIMARY KEY, user_id INTEGER,
        stars INTEGER DEFAULT 0, text TEXT);
    CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, username TEXT, message TEXT, reply TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS announcements(id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT, body TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS users(user_id INTEGER PRIMARY KEY, username TEXT);
    """)
    try: cur.execute("ALTER TABLE reviews ADD COLUMN stars INTEGER DEFAULT 0")
    except: pass
    c.commit(); c.close()

# ── HELPERS ──────────────────────────────────────────────────────────────────
def fq(q): return f"{int(q)}g" if q == int(q) else f"{q}g"
def ft(t): return f"⚖️ {fq(t['qty'])} — £{t['price']:.2f}/g"
def back(): return [InlineKeyboardButton("⬅️ Back", callback_data="menu")]
def is_admin(u): return u.effective_user.id == ADMIN_ID

def ltc_rate():
    try: return requests.get("https://api.coingecko.com/api/v3/simple/price?ids=litecoin&vs_currencies=gbp", timeout=10).json()["litecoin"]["gbp"]
    except: return 55

def menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛍️ Products",       callback_data="products")],
        [InlineKeyboardButton("🧺 Basket",         callback_data="basket")],
        [InlineKeyboardButton("📦 My Orders",      callback_data="orders")],
        [InlineKeyboardButton("⭐ Reviews",        callback_data="pub_reviews")],
        [InlineKeyboardButton("📢 Announcements",  callback_data="announcements")],
        [InlineKeyboardButton("💬 Contact Vendor", callback_data="contact_vendor")],
    ])

def co_kb(ud):
    name=ud.get("co_name"); addr=ud.get("co_addr"); ship=ud.get("co_shipping"); dp=ud.get("co_disc_pct",0); dc=ud.get("co_discount","")
    rows=[
        [InlineKeyboardButton(f"✅ {name}" if name else "👤 Enter Name", callback_data="co_setname")],
        [InlineKeyboardButton("✅ Address set" if addr else "🏠 Enter Address", callback_data="co_setaddr")],
        [InlineKeyboardButton(("✅ " if ship=="tracked24" else "")+"📦 Tracked24 (+£5)", callback_data="co_ship_tracked24"),
         InlineKeyboardButton(("✅ " if ship=="free" else "")+"🚶 Collection (Free)", callback_data="co_ship_free")],
        [InlineKeyboardButton(f"🏷️ {dc} ({int(dp*100)}% off) ✅" if dp else "🏷️ Discount Code", callback_data="co_setdiscount")],
    ]
    if name and addr and ship:
        rows.append([InlineKeyboardButton("✅ Confirm & Place Order", callback_data="co_confirm")])
    rows.append([InlineKeyboardButton("❌ Cancel", callback_data="menu")])
    return InlineKeyboardMarkup(rows)

def co_txt(ud):
    sub=ud.get("co_subtotal",0); dp=ud.get("co_disc_pct",0); dc=ud.get("co_discount","")
    sk=ud.get("co_shipping"); sp=SHIPPING[sk]["price"] if sk else 0; sl=SHIPPING[sk]["label"] if sk else "Not selected"
    da=round(sub*dp,2); total=round(sub-da+sp,2)
    t = f"🛒 <b>Checkout</b>\n\n👤 {ud.get('co_name','—')}\n🏠 {ud.get('co_addr','—')}\n🚚 {sl} (+£{sp:.2f})\n"
    if dp: t += f"🏷️ {dc}: -£{da:.2f}\n"
    return t + f"\n💷 Subtotal: £{sub:.2f}\n💰 <b>Total: £{total:.2f}</b>", total

# ── START ─────────────────────────────────────────────────────────────────────
async def start(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    c=db(); cur=c.cursor()
    cur.execute("INSERT OR IGNORE INTO users VALUES(?,?)", (u.effective_user.id, u.effective_user.username or ""))
    c.commit(); c.close()
    await u.message.reply_text(
        "👋 Welcome to <b>Donny's Shop</b>! 🌿\n\n"
        "🛍️ <b>Products</b> — Browse & pick your weight\n"
        "🧺 <b>Basket</b> — Review before checkout\n"
        "📦 <b>My Orders</b> — Track your orders\n"
        "⭐ <b>Reviews</b> — See what customers say\n"
        "📢 <b>Announcements</b> — Latest news\n"
        "💬 <b>Contact Vendor</b> — Message us\n\n"
        "Tap <b>Products</b> to get started! 🚀",
        reply_markup=menu(), parse_mode="HTML")

# ── PRODUCTS ──────────────────────────────────────────────────────────────────
async def show_products(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q=u.callback_query; await q.answer()
    c=db(); cur=c.cursor(); cur.execute("SELECT id,name,stock FROM products"); rows=cur.fetchall(); c.close()
    if not rows: await q.edit_message_text("😔 No products available.", reply_markup=InlineKeyboardMarkup([back()])); return
    kb=[[InlineKeyboardButton(f"🌿 {n} (📦 {s})", callback_data=f"prod_{i}")] for i,n,s in rows]+[back()]
    await q.edit_message_text("🛍️ <b>Choose a product:</b>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))

async def show_product(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q=u.callback_query; await q.answer(); pid=int(q.data.split("_")[1])
    c=db(); cur=c.cursor(); cur.execute("SELECT name,description,photo,stock,tiers FROM products WHERE id=?",(pid,)); row=cur.fetchone(); c.close()
    if not row: await q.edit_message_text("❌ Not found.", reply_markup=InlineKeyboardMarkup([back()])); return
    name,desc,photo,stock,tj=row; tiers=json.loads(tj) if tj else DEFAULT_TIERS[:]
    tb=[InlineKeyboardButton(ft(t), callback_data=f"pick_{pid}_{t['qty']}_{t['price']}") for t in tiers]
    rows2=[tb[i:i+2] for i in range(0,len(tb),2)]+[[InlineKeyboardButton("⬅️ Back to Products", callback_data="products")]]
    cap=f"🌿 <b>{name}</b>\n\n📝 {desc}\n\n📦 In stock: <b>{stock}</b>\n\n<b>Select weight:</b>\n"+"\n".join(ft(t) for t in tiers)
    try: await q.message.delete()
    except: pass
    await ctx.bot.send_photo(q.message.chat_id, photo, caption=cap, reply_markup=InlineKeyboardMarkup(rows2), parse_mode="HTML")

async def pick_weight(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q=u.callback_query; parts=q.data.split("_"); pid=int(parts[1]); qty=float(parts[2]); price=float(parts[3])
    c=db(); cur=c.cursor(); cur.execute("SELECT name,stock FROM products WHERE id=?",(pid,)); row=cur.fetchone()
    if not row or row[1]<1: c.close(); await q.answer("❌ Out of stock!", show_alert=True); return
    cur.execute("INSERT INTO cart(user_id,product_id,chosen_qty,chosen_price) VALUES(?,?,?,?)",(q.from_user.id,pid,qty,price))
    c.commit(); c.close(); await q.answer(f"✅ Added {fq(qty)} of {row[0]} — £{price:.2f}/g", show_alert=True)

# ── BASKET ────────────────────────────────────────────────────────────────────
async def view_basket(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q=u.callback_query; await q.answer()
    c=db(); cur=c.cursor()
    cur.execute("SELECT cart.id,products.name,cart.chosen_qty,cart.chosen_price FROM cart JOIN products ON cart.product_id=products.id WHERE cart.user_id=?",(q.from_user.id,))
    items=cur.fetchall(); c.close()
    if not items: await q.edit_message_text("🧺 Your basket is empty.", reply_markup=InlineKeyboardMarkup([back()])); return
    txt="🧺 <b>Your Basket</b>\n\n"+"".join(f"🌿 {n} ({fq(qy)}) — £{p:.2f}\n" for _,n,qy,p in items)+f"\n💰 <b>Total: £{sum(i[3] for i in items):.2f}</b>"
    kb=[[InlineKeyboardButton(f"🗑️ Remove {n} ({fq(qy)})", callback_data=f"remove_{cid}")] for cid,n,qy,_ in items]
    kb+=[[InlineKeyboardButton("💳 Checkout", callback_data="checkout")], back()]
    await q.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")

async def remove_item(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q=u.callback_query; await q.answer(); cid=int(q.data.split("_")[1])
    c=db(); cur=c.cursor(); cur.execute("DELETE FROM cart WHERE id=? AND user_id=?",(cid,q.from_user.id)); c.commit(); c.close()
    await view_basket(u,ctx)

# ── ORDERS ────────────────────────────────────────────────────────────────────
async def view_orders(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q=u.callback_query; await q.answer()
    c=db(); cur=c.cursor(); cur.execute("SELECT id,total_gbp,total_ltc,status FROM orders WHERE user_id=? ORDER BY rowid DESC",(q.from_user.id,)); rows=cur.fetchall(); c.close()
    if not rows: await q.edit_message_text("📭 No orders found.", reply_markup=InlineKeyboardMarkup([back()])); return
    emap={"Awaiting Payment":"⏳ Awaiting","Paid":"✅ Paid","Dispatched":"🚚 Dispatched","Rejected":"❌ Rejected"}
    txt="📦 <b>Your Orders</b>\n\n"+"".join(f"🔖 <code>{o}</code>\n💷 £{g:.2f} ({l} LTC)\n{emap.get(s,s)}\n\n" for o,g,l,s in rows)
    await q.edit_message_text(txt, parse_mode="HTML", reply_markup=InlineKeyboardMarkup([back()]))

# ── REVIEWS ───────────────────────────────────────────────────────────────────
async def pub_reviews(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q=u.callback_query; await q.answer()
    c=db(); cur=c.cursor(); cur.execute("SELECT stars,text FROM reviews ORDER BY rowid DESC LIMIT 20"); rows=cur.fetchall(); c.close()
    if not rows: await q.edit_message_text("💬 No reviews yet.", reply_markup=InlineKeyboardMarkup([back()])); return
    txt="⭐ <b>Customer Reviews</b>\n\n"+"".join(f"👤 **********\n{STARS.get(r[0],'')}\n💬 {r[1]}\n\n" for r in rows)
    await q.edit_message_text(txt, parse_mode="HTML", reply_markup=InlineKeyboardMarkup([back()]))

async def review_start(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q=u.callback_query; await q.answer(); ctx.user_data["rev_order"]=q.data[7:]
    kb=[[InlineKeyboardButton(f"{'⭐'*i} {i}",callback_data=f"stars_{i}") for i in range(1,4)],
        [InlineKeyboardButton(f"{'⭐'*i} {i}",callback_data=f"stars_{i}") for i in range(4,6)]]
    await q.edit_message_text("⭐ <b>Rate Your Order</b>\n\nHow many stars?", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
    return PICK_STARS

async def pick_stars(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q=u.callback_query; await q.answer(); s=int(q.data.split("_")[1]); ctx.user_data["rev_stars"]=s
    await q.edit_message_text(f"✨ {STARS[s]}\n\n✏️ Write your review:"); return WRITE_REVIEW

async def save_review(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    oid=ctx.user_data.get("rev_order"); stars=ctx.user_data.get("rev_stars",0); uid=u.effective_user.id
    c=db(); cur=c.cursor(); cur.execute("SELECT id FROM orders WHERE id=? AND user_id=? AND status IN ('Paid','Dispatched')",(oid,uid))
    if not cur.fetchone(): c.close(); await u.message.reply_text("⚠️ Order not eligible.", reply_markup=menu()); return ConversationHandler.END
    cur.execute("INSERT OR REPLACE INTO reviews VALUES(?,?,?,?)",(oid,uid,stars,u.message.text)); c.commit(); c.close()
    await u.message.reply_text(f"✅ Review saved! {STARS.get(stars,'')} Thank you 🙏", reply_markup=menu()); return ConversationHandler.END

# ── ANNOUNCEMENTS ─────────────────────────────────────────────────────────────
async def show_announcements(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q=u.callback_query; await q.answer()
    c=db(); cur=c.cursor(); cur.execute("SELECT title,body,created_at FROM announcements ORDER BY id DESC LIMIT 10"); rows=cur.fetchall(); c.close()
    if not rows: await q.edit_message_text("📢 No announcements yet.", reply_markup=InlineKeyboardMarkup([back()])); return
    txt="📢 <b>Announcements</b>\n\n"+"".join(f"📌 <b>{t}</b>\n{b}\n<i>🕐 {dt[:10]}</i>\n\n" for t,b,dt in rows)
    if len(txt)>4000: txt=txt[:4000]+"…"
    await q.edit_message_text(txt, parse_mode="HTML", reply_markup=InlineKeyboardMarkup([back()]))

async def adm_ann_start(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q=u.callback_query; await q.answer()
    if not is_admin(u): return
    await q.edit_message_text("📢 <b>New Announcement</b>\n\nEnter the title:", parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="admin_back")]]))
    return ASK_ANN_TITLE

async def adm_ann_title(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["ann_title"]=u.message.text.strip()
    await u.message.reply_text("✏️ Now enter the announcement body:"); return ASK_ANN_BODY

async def adm_ann_body(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    title=ctx.user_data.get("ann_title",""); body=u.message.text.strip()
    c=db(); cur=c.cursor(); cur.execute("INSERT INTO announcements(title,body) VALUES(?,?)",(title,body)); c.commit()
    cur.execute("SELECT user_id FROM users"); uids=[r[0] for r in cur.fetchall()]; c.close()
    sent=0
    for uid in uids:
        try: await ctx.bot.send_message(uid, f"📢 <b>{title}</b>\n\n{body}", parse_mode="HTML", reply_markup=menu()); sent+=1
        except: pass
    await u.message.reply_text(f"✅ Posted & broadcast to {sent} users!", reply_markup=menu()); return ConversationHandler.END

# ── CONTACT VENDOR ────────────────────────────────────────────────────────────
async def contact_start(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q=u.callback_query; await q.answer()
    await q.edit_message_text("💬 <b>Contact Vendor</b>\n\nType your message below:", parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="menu")]])); return ASK_CONTACT

async def contact_save(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid=u.effective_user.id; uname=u.effective_user.username or u.effective_user.first_name or str(uid)
    c=db(); cur=c.cursor(); cur.execute("INSERT INTO messages(user_id,username,message) VALUES(?,?,?)",(uid,uname,u.message.text)); mid=cur.lastrowid; c.commit(); c.close()
    await ctx.bot.send_message(ADMIN_ID, f"💬 <b>Message from @{uname}</b> (ID:{uid})\n🔖 #{mid}\n\n{u.message.text}\n\nReply: /reply {mid} &lt;text&gt;", parse_mode="HTML")
    await u.message.reply_text("✅ Message sent! We'll reply soon.", reply_markup=menu()); return ConversationHandler.END

async def admin_reply_cmd(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(u): return
    args=ctx.args
    if not args or len(args)<2: await u.message.reply_text("Usage: /reply <id> <text>"); return
    try: mid=int(args[0])
    except: await u.message.reply_text("⚠️ Invalid ID."); return
    reply_text=" ".join(args[1:])
    c=db(); cur=c.cursor(); cur.execute("SELECT user_id,username,message FROM messages WHERE id=?",(mid,)); row=cur.fetchone()
    if not row: c.close(); await u.message.reply_text("❌ Not found."); return
    cur.execute("UPDATE messages SET reply=? WHERE id=?",(reply_text,mid)); c.commit(); c.close()
    try:
        await ctx.bot.send_message(row[0], f"💬 <b>Reply from Vendor</b>\n\n📩 Your msg: <i>{row[2]}</i>\n\n✉️ {reply_text}", parse_mode="HTML", reply_markup=menu())
        await u.message.reply_text(f"✅ Replied to @{row[1]}.")
    except Exception as e: await u.message.reply_text(f"❌ Failed: {e}")

# ── CHECKOUT ──────────────────────────────────────────────────────────────────
async def checkout_start(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q=u.callback_query; await q.answer(); uid=q.from_user.id
    c=db(); cur=c.cursor(); cur.execute("SELECT chosen_price FROM cart WHERE user_id=?",(uid,)); prices=cur.fetchall(); c.close()
    if not prices: await q.edit_message_text("🧺 Basket is empty.", reply_markup=menu()); return ConversationHandler.END
    ctx.user_data.update({"co_name":None,"co_addr":None,"co_shipping":None,"co_discount":None,"co_disc_pct":0,"co_subtotal":round(sum(p[0] for p in prices),2)})
    txt,_=co_txt(ctx.user_data); await q.edit_message_text(txt, parse_mode="HTML", reply_markup=co_kb(ctx.user_data)); return ConversationHandler.END

async def co_setname(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q=u.callback_query; await q.answer()
    await q.edit_message_text("👤 <b>Enter your name:</b>", parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="co_refresh")]])); return CO_NAME

async def co_setaddr(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q=u.callback_query; await q.answer()
    await q.edit_message_text("🏠 <b>Enter your delivery address:</b>", parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="co_refresh")]])); return CO_ADDR

async def co_setdiscount(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q=u.callback_query; await q.answer()
    await q.edit_message_text("🏷️ <b>Enter discount code:</b>", parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="co_refresh")]])); return CO_DISC

async def co_recv_name(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["co_name"]=u.message.text.strip(); txt,_=co_txt(ctx.user_data)
    await u.message.reply_text(txt, parse_mode="HTML", reply_markup=co_kb(ctx.user_data)); return ConversationHandler.END

async def co_recv_addr(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["co_addr"]=u.message.text.strip(); txt,_=co_txt(ctx.user_data)
    await u.message.reply_text(txt, parse_mode="HTML", reply_markup=co_kb(ctx.user_data)); return ConversationHandler.END

async def co_recv_disc(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    code=u.message.text.strip().upper(); pct=DISCOUNT_CODES.get(code)
    if pct: ctx.user_data["co_discount"]=code; ctx.user_data["co_disc_pct"]=pct; await u.message.reply_text(f"✅ {code} applied — {int(pct*100)}% off!")
    else: ctx.user_data["co_discount"]=None; ctx.user_data["co_disc_pct"]=0; await u.message.reply_text("❌ Invalid code.")
    txt,_=co_txt(ctx.user_data); await u.message.reply_text(txt, parse_mode="HTML", reply_markup=co_kb(ctx.user_data)); return ConversationHandler.END

async def co_set_ship(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q=u.callback_query; await q.answer(); ctx.user_data["co_shipping"]=q.data.split("co_ship_")[1]
    txt,_=co_txt(ctx.user_data); await q.edit_message_text(txt, parse_mode="HTML", reply_markup=co_kb(ctx.user_data))

async def co_refresh(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q=u.callback_query; await q.answer(); txt,_=co_txt(ctx.user_data)
    await q.edit_message_text(txt, parse_mode="HTML", reply_markup=co_kb(ctx.user_data))

async def co_confirm(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q=u.callback_query; await q.answer(); uid=q.from_user.id; ud=ctx.user_data
    name=ud.get("co_name"); addr=ud.get("co_addr"); sk=ud.get("co_shipping")
    if not (name and addr and sk): await q.answer("⚠️ Fill in all fields first.", show_alert=True); return
    c=db(); cur=c.cursor(); cur.execute("SELECT chosen_price FROM cart WHERE user_id=?",(uid,)); prices=cur.fetchall()
    if not prices: c.close(); await q.edit_message_text("🧺 Basket empty.", reply_markup=menu()); return
    sub=round(sum(p[0] for p in prices),2); dp=ud.get("co_disc_pct",0); sp=SHIPPING[sk]["price"]; sl=SHIPPING[sk]["label"]
    gbp=round(sub-round(sub*dp,2)+sp,2); ltc=round(gbp/ltc_rate(),6); oid=str(uuid4())[:8]
    cur.execute("INSERT INTO orders VALUES(?,?,?,?,?,?,?)",(oid,uid,name,addr,gbp,ltc,"Awaiting Payment"))
    cur.execute("DELETE FROM cart WHERE user_id=?",(uid,)); c.commit(); c.close()
    await ctx.bot.send_message(CHANNEL_ID, f"🛒 <b>New Order!</b>\n🔖 <code>{oid}</code>\n👤 {name}\n🏠 {addr}\n🚚 {sl}\n💷 £{gbp} / {ltc} LTC", parse_mode="HTML")
    await q.edit_message_text(
        f"🧾 <b>Order Placed!</b>\n\n🔖 <code>{oid}</code>\n👤 {name}\n🏠 {addr}\n🚚 {sl}\n\n💷 £{gbp}\n⚡ {ltc} LTC\n\n📤 Send to:\n<code>{LTC_ADDR}</code>",
        parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ I Have Paid", callback_data=f"paid_{oid}")]]))
    for k in ["co_name","co_addr","co_shipping","co_discount","co_disc_pct","co_subtotal"]: ud.pop(k,None)

async def user_paid(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q=u.callback_query; await q.answer(); oid=q.data[5:]
    await ctx.bot.send_message(ADMIN_ID, f"💬 User {q.from_user.id} claims payment for <code>{oid}</code>", parse_mode="HTML")
    await q.edit_message_text("⏳ Payment submitted. Awaiting admin confirmation.")

# ── ADMIN ─────────────────────────────────────────────────────────────────────
async def admin_panel(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(u): return
    c=db(); cur=c.cursor()
    cur.execute("SELECT id,status FROM orders ORDER BY rowid DESC"); orders=cur.fetchall()
    cur.execute("SELECT COUNT(*) FROM messages WHERE reply IS NULL"); unread=cur.fetchone()[0]; c.close()
    kb=[]
    for oid,st in orders:
        if st=="Awaiting Payment": kb.append([InlineKeyboardButton(f"✅ Confirm {oid}",callback_data=f"adm_ok_{oid}"),InlineKeyboardButton(f"❌ Reject {oid}",callback_data=f"adm_no_{oid}")])
        elif st=="Paid": kb.append([InlineKeyboardButton(f"🚚 Dispatch {oid}",callback_data=f"adm_go_{oid}")])
    kb+=[
        [InlineKeyboardButton("➕ Add Product", callback_data="adm_addprod"), InlineKeyboardButton("✏️ Edit Tiers", callback_data="adm_tiers")],
        [InlineKeyboardButton(f"💬 Messages ({unread} unread)" if unread else "💬 Messages", callback_data="adm_messages")],
        [InlineKeyboardButton("📢 New Announcement", callback_data="adm_announce")],
    ]
    await u.message.reply_text("🔧 <b>Admin Dashboard</b>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))

async def adm_confirm(u, ctx):
    q=u.callback_query; await q.answer(); oid=q.data[7:]
    c=db(); cur=c.cursor(); cur.execute("UPDATE orders SET status='Paid' WHERE id=?",(oid,)); cur.execute("SELECT user_id FROM orders WHERE id=?",(oid,)); row=cur.fetchone(); c.commit(); c.close()
    if row: await ctx.bot.send_message(row[0], f"✅ Payment confirmed for <code>{oid}</code>! 🌟 Leave a review when it arrives.", parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⭐ Leave a Review",callback_data=f"review_{oid}")]]))
    await q.edit_message_text(f"✅ Confirmed {oid}")

async def adm_reject(u, ctx):
    q=u.callback_query; await q.answer(); oid=q.data[7:]
    c=db(); cur=c.cursor(); cur.execute("UPDATE orders SET status='Rejected' WHERE id=?",(oid,)); cur.execute("SELECT user_id FROM orders WHERE id=?",(oid,)); row=cur.fetchone(); c.commit(); c.close()
    if row: await ctx.bot.send_message(row[0], f"❌ Payment for <code>{oid}</code> was rejected. Contact support.", parse_mode="HTML")
    await q.edit_message_text(f"❌ Rejected {oid}")

async def adm_dispatch(u, ctx):
    q=u.callback_query; await q.answer(); oid=q.data[7:]
    c=db(); cur=c.cursor(); cur.execute("UPDATE orders SET status='Dispatched' WHERE id=?",(oid,)); cur.execute("SELECT user_id FROM orders WHERE id=?",(oid,)); row=cur.fetchone(); c.commit(); c.close()
    if row: await ctx.bot.send_message(row[0], f"🚚 Order <code>{oid}</code> dispatched! 📬", parse_mode="HTML")
    await q.edit_message_text(f"🚚 Dispatched {oid}")

async def adm_messages(u, ctx):
    q=u.callback_query; await q.answer()
    if not is_admin(u): return
    c=db(); cur=c.cursor(); cur.execute("SELECT id,username,message,reply FROM messages ORDER BY id DESC LIMIT 15"); rows=cur.fetchall(); c.close()
    if not rows: await q.edit_message_text("📭 No messages.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back",callback_data="admin_back")]])); return
    txt="💬 <b>Messages</b>\n\n"+"".join(f"#{r[0]} @{r[1]}\n📩 {r[2]}\n{'✅ '+r[3] if r[3] else '⏳ Unreplied'}\n/reply {r[0]} &lt;text&gt;\n\n" for r in rows)
    if len(txt)>4000: txt=txt[:4000]+"…"
    await q.edit_message_text(txt, parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back",callback_data="admin_back")]]))

# ── ADD PRODUCT ───────────────────────────────────────────────────────────────
async def addprod_start(u, ctx):
    if not is_admin(u): return
    await u.message.reply_text("📸 Send the product photo:"); return ADD_PHOTO

async def addprod_photo(u, ctx):
    if not u.message.photo: await u.message.reply_text("⚠️ Please send a photo."); return ADD_PHOTO
    ctx.user_data["ph"]=u.message.photo[-1].file_id; await u.message.reply_text("📝 Enter product title:"); return ADD_TITLE

async def addprod_title(u, ctx):
    ctx.user_data["nm"]=u.message.text.strip(); await u.message.reply_text("📄 Enter description:"); return ADD_DESC

async def addprod_desc(u, ctx):
    ctx.user_data["ds"]=u.message.text.strip(); await u.message.reply_text("📦 Enter stock (1–1000):"); return ADD_QTY

async def addprod_qty(u, ctx):
    try: qty=int(u.message.text.strip()); assert 1<=qty<=1000
    except: await u.message.reply_text("⚠️ Enter a number 1–1000:"); return ADD_QTY
    d=ctx.user_data; c=db(); cur=c.cursor()
    cur.execute("INSERT INTO products(name,description,photo,stock,tiers) VALUES(?,?,?,?,?)",(d["nm"],d["ds"],d["ph"],qty,json.dumps(DEFAULT_TIERS))); c.commit(); c.close()
    await u.message.reply_photo(d["ph"], caption=f"✅ <b>Added!</b>\n🌿 {d['nm']}\n📦 Stock: {qty}", parse_mode="HTML"); return ConversationHandler.END

# ── EDIT TIERS ────────────────────────────────────────────────────────────────
async def adm_list_tiers(u, ctx):
    q=u.callback_query; await q.answer()
    c=db(); cur=c.cursor(); cur.execute("SELECT id,name FROM products"); rows=cur.fetchall(); c.close()
    if not rows: await q.edit_message_text("😔 No products.", reply_markup=InlineKeyboardMarkup([back()])); return
    kb=[[InlineKeyboardButton(f"🌿 {r[1]}",callback_data=f"edtier_{r[0]}")] for r in rows]+[back()]
    await q.edit_message_text("✏️ Select product to edit tiers:", reply_markup=InlineKeyboardMarkup(kb))

async def adm_show_tiers(u, ctx):
    q=u.callback_query; await q.answer(); pid=int(q.data.split("_")[1]); ctx.user_data["tpid"]=pid
    c=db(); cur=c.cursor(); cur.execute("SELECT name,tiers FROM products WHERE id=?",(pid,)); row=cur.fetchone(); c.close()
    tiers=json.loads(row[1])
    await q.message.reply_text(f"✏️ <b>Tiers for {row[0]}</b>\n\n"+"\n".join(ft(t) for t in tiers)+"\n\nSend new tiers as <code>qty,price</code> per line:\n<code>1,10\n3.5,5\n7,4</code>\n\nOr /cancel", parse_mode="HTML")
    return EDIT_TIERS

async def save_tiers(u, ctx):
    pid=ctx.user_data.get("tpid"); lines=u.message.text.strip().splitlines(); new=[]; errs=[]
    for i,line in enumerate(lines,1):
        p=line.strip().split(",")
        if len(p)!=2: errs.append(f"Line {i}: need qty,price"); continue
        try: q2,pr=float(p[0]),float(p[1]); assert q2>0 and pr>0; new.append({"qty":q2,"price":pr})
        except: errs.append(f"Line {i}: invalid numbers")
    if errs or not new: await u.message.reply_text("❌ Errors:\n"+"\n".join(errs or ["No valid tiers."])+"\n\nRetry or /cancel"); return EDIT_TIERS
    new.sort(key=lambda t:t["qty"]); c=db(); cur=c.cursor()
    cur.execute("UPDATE products SET tiers=? WHERE id=?",(json.dumps(new),pid)); c.commit(); c.close()
    await u.message.reply_text("✅ <b>Tiers updated!</b>\n\n"+"\n".join(ft(t) for t in new), parse_mode="HTML"); return ConversationHandler.END

async def cancel(u, ctx):
    await u.message.reply_text("🚫 Cancelled.", reply_markup=menu()); return ConversationHandler.END

# ── ROUTER ────────────────────────────────────────────────────────────────────
async def router(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    data=u.callback_query.data
    if   data=="menu":               await u.callback_query.edit_message_text("🏠 Main Menu", reply_markup=menu())
    elif data=="products":           await show_products(u,ctx)
    elif data.startswith("prod_"):   await show_product(u,ctx)
    elif data=="basket":             await view_basket(u,ctx)
    elif data=="orders":             await view_orders(u,ctx)
    elif data=="pub_reviews":        await pub_reviews(u,ctx)
    elif data=="announcements":      await show_announcements(u,ctx)
    elif data.startswith("pick_"):   await pick_weight(u,ctx)
    elif data.startswith("remove_"): await remove_item(u,ctx)
    elif data.startswith("paid_"):   await user_paid(u,ctx)
    elif data.startswith("adm_ok_"): await adm_confirm(u,ctx)
    elif data.startswith("adm_no_"): await adm_reject(u,ctx)
    elif data.startswith("adm_go_"): await adm_dispatch(u,ctx)
    elif data=="adm_messages":       await adm_messages(u,ctx)
    elif data=="adm_tiers" and is_admin(u):    await adm_list_tiers(u,ctx)
    elif data=="adm_addprod" and is_admin(u):  await u.callback_query.message.reply_text("💡 Use /addproduct to add a product.")
    elif data=="admin_back" and is_admin(u):   await u.callback_query.edit_message_text("🔧 Use /admin to open the dashboard.")
    elif data.startswith("co_ship_"):          await co_set_ship(u,ctx)
    elif data=="co_refresh":                   await co_refresh(u,ctx)
    elif data=="co_confirm":                   await co_confirm(u,ctx)

# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    init_db()
    app=ApplicationBuilder().token(TOKEN).build()

    def conv(entry, states, **kw):
        return ConversationHandler(entry_points=entry, states=states,
            fallbacks=[CommandHandler("cancel",cancel)], per_message=False, **kw)

    app.add_handler(CommandHandler("start",  start))
    app.add_handler(CommandHandler("admin",  admin_panel))
    app.add_handler(CommandHandler("reply",  admin_reply_cmd))

    app.add_handler(conv([CallbackQueryHandler(review_start,  pattern="^review_")],
        {PICK_STARS:[CallbackQueryHandler(pick_stars,pattern="^stars_")],
         WRITE_REVIEW:[MessageHandler(filters.TEXT&~filters.COMMAND,save_review)]}))

    app.add_handler(conv([CallbackQueryHandler(contact_start, pattern="^contact_vendor$")],
        {ASK_CONTACT:[MessageHandler(filters.TEXT&~filters.COMMAND,contact_save)]}))

    app.add_handler(conv([CallbackQueryHandler(adm_ann_start, pattern="^adm_announce$")],
        {ASK_ANN_TITLE:[MessageHandler(filters.TEXT&~filters.COMMAND,adm_ann_title)],
         ASK_ANN_BODY: [MessageHandler(filters.TEXT&~filters.COMMAND,adm_ann_body)]}))

    app.add_handler(conv([CallbackQueryHandler(checkout_start,pattern="^checkout$")], {}))

    app.add_handler(conv([CallbackQueryHandler(co_setname,    pattern="^co_setname$")],
        {CO_NAME:[MessageHandler(filters.TEXT&~filters.COMMAND,co_recv_name)]}, allow_reentry=True))
    app.add_handler(conv([CallbackQueryHandler(co_setaddr,    pattern="^co_setaddr$")],
        {CO_ADDR:[MessageHandler(filters.TEXT&~filters.COMMAND,co_recv_addr)]}, allow_reentry=True))
    app.add_handler(conv([CallbackQueryHandler(co_setdiscount,pattern="^co_setdiscount$")],
        {CO_DISC:[MessageHandler(filters.TEXT&~filters.COMMAND,co_recv_disc)]}, allow_reentry=True))

    app.add_handler(conv([CommandHandler("addproduct",addprod_start)],
        {ADD_PHOTO:[MessageHandler(filters.PHOTO,addprod_photo)],
         ADD_TITLE:[MessageHandler(filters.TEXT&~filters.COMMAND,addprod_title)],
         ADD_DESC: [MessageHandler(filters.TEXT&~filters.COMMAND,addprod_desc)],
         ADD_QTY:  [MessageHandler(filters.TEXT&~filters.COMMAND,addprod_qty)]}))

    app.add_handler(conv([CallbackQueryHandler(adm_show_tiers,pattern="^edtier_")],
        {EDIT_TIERS:[MessageHandler(filters.TEXT&~filters.COMMAND,save_tiers)]}))

    app.add_handler(CallbackQueryHandler(router))

    print("🚀 Bot running...")
    app.run_polling()

if __name__=="__main__":
    main()
