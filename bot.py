# -*- coding: utf-8 -*-
import os,json,logging,requests,sqlite3,html as hl
from threading import Thread
from http.server import HTTPServer,BaseHTTPRequestHandler
from uuid import uuid4
from datetime import datetime,timedelta
from telegram import Update,InlineKeyboardMarkup,InlineKeyboardButton as IB
from telegram.ext import ApplicationBuilder,CommandHandler,CallbackQueryHandler,MessageHandler,ContextTypes,filters

TOKEN=os.getenv("TOKEN"); ADMIN_ID=7773622161; CHANNEL_ID=-1003833257976
LTC_ADDR="ltc1qv4u6vr0gzp9g4lq0g3qev939vdnwxghn5gtnfc"
DB_DIR="/app/data"; DB=f"{DB_DIR}/shop.db"; os.makedirs(DB_DIR,exist_ok=True)
SHIP={"tracked24":{"label":"📦 Tracked24","price":5.0,"ltc":True},"drop":{"label":"📍 Local Drop","price":0.0,"ltc":False}}
TIERS=[{"qty":1,"price":10.0},{"qty":3.5,"price":35.0},{"qty":7,"price":60.0},{"qty":14,"price":110.0},{"qty":28,"price":200.0},{"qty":56,"price":380.0}]
STARS={1:"⭐",2:"⭐⭐",3:"⭐⭐⭐",4:"⭐⭐⭐⭐",5:"⭐⭐⭐⭐⭐"}; RPP=5
logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s",level=logging.WARNING)
def db():
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; return c
def q1(s,p=()):
    c=db(); r=c.execute(s,p).fetchone(); c.close(); return dict(r) if r else None
def qa(s,p=()):
    c=db(); r=c.execute(s,p).fetchall(); c.close(); return [dict(x) for x in r]
def qx(s,p=()):
    c=db(); c.execute(s,p); c.commit(); c.close()
def qxi(s,p=()):
    c=db(); cur=c.execute(s,p); r=cur.lastrowid; c.commit(); c.close(); return r
def gs(k,d=""):
    r=q1("SELECT value FROM settings WHERE key=?",(k,)); return r["value"] if r else d
def ss(k,v): qx("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)",(k,v))

def init_db():
    c=db(); cur=c.cursor()
    cur.executescript("""
    CREATE TABLE IF NOT EXISTS users(user_id INTEGER PRIMARY KEY,username TEXT,joined DATETIME DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);
    CREATE TABLE IF NOT EXISTS admins(user_id INTEGER PRIMARY KEY,username TEXT);
    CREATE TABLE IF NOT EXISTS products(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,description TEXT,photo TEXT,hidden INTEGER DEFAULT 0,tiers TEXT DEFAULT '[]',category_id INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS categories(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,emoji TEXT DEFAULT '🌿');
    CREATE TABLE IF NOT EXISTS cart(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,product_id INTEGER,qty REAL,price REAL,created_at DATETIME DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS orders(id TEXT PRIMARY KEY,user_id INTEGER,cust_name TEXT,address TEXT,summary TEXT DEFAULT '',gbp REAL,ltc REAL DEFAULT 0,status TEXT DEFAULT 'Pending',ship TEXT DEFAULT 'tracked24',created_at DATETIME DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS order_notes(order_id TEXT PRIMARY KEY,note TEXT);
    CREATE TABLE IF NOT EXISTS drop_chats(id INTEGER PRIMARY KEY AUTOINCREMENT,order_id TEXT,user_id INTEGER,sender TEXT,message TEXT,created_at DATETIME DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,username TEXT,message TEXT,reply TEXT,created_at DATETIME DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS reviews(order_id TEXT PRIMARY KEY,user_id INTEGER,stars INTEGER,text TEXT,created_at DATETIME DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS announcements(id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT,body TEXT,photo TEXT DEFAULT '',created_at DATETIME DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS discount_codes(code TEXT PRIMARY KEY,pct REAL,active INTEGER DEFAULT 1,expires TEXT);
    CREATE TABLE IF NOT EXISTS loyalty(user_id INTEGER PRIMARY KEY,points INTEGER DEFAULT 0,credit REAL DEFAULT 0,lifetime INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS referrals(code TEXT PRIMARY KEY,owner_id INTEGER,count INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS review_reminders(order_id TEXT PRIMARY KEY,user_id INTEGER,dispatched DATETIME);
    """)
    cur.execute("INSERT OR IGNORE INTO admins(user_id,username) VALUES(?,'owner')",(ADMIN_ID,))
    cur.execute("INSERT OR IGNORE INTO discount_codes(code,pct,active) VALUES('SAVE10',0.10,1)")
    for s in ["ALTER TABLE products ADD COLUMN category_id INTEGER DEFAULT 0","ALTER TABLE products ADD COLUMN hidden INTEGER DEFAULT 0","ALTER TABLE orders ADD COLUMN created_at DATETIME DEFAULT CURRENT_TIMESTAMP","ALTER TABLE orders ADD COLUMN ltc REAL DEFAULT 0","ALTER TABLE discount_codes ADD COLUMN expires TEXT"]:
        try: cur.execute(s)
        except: pass
    c.commit(); c.close()
def is_admin(uid): return uid==ADMIN_ID or bool(q1("SELECT 1 FROM admins WHERE user_id=?",(uid,)))
def is_known(uid): return bool(q1("SELECT 1 FROM users WHERE user_id=?",(uid,)))
def fq(q): return f"{int(q)}g" if q==int(q) else f"{q}g"
def ft(t): ppg=round(t["price"]/t["qty"],2) if t["qty"] else t["price"]; return f"⚖️ {fq(t['qty'])} · £{t['price']:.2f} (£{ppg}/g)"
def KM(*rows): return InlineKeyboardMarkup(list(rows))
def ltc_price():
    try: return requests.get("https://api.coingecko.com/api/v3/simple/price?ids=litecoin&vs_currencies=gbp",timeout=8).json()["litecoin"]["gbp"]
    except: return 60.0
def is_open():
    n=datetime.now(); return n.weekday()<6 and n.hour<11
def open_badge():
    return "🟢 <b>Open</b> · Orders close 11am Mon–Sat" if is_open() else "🔴 <b>Closed</b> · Next working day"

def gdisc(c):
    r=q1("SELECT pct,expires FROM discount_codes WHERE code=? AND active=1",(c.upper(),))
    if not r: return None
    if r.get("expires"):
        try:
            if datetime.fromisoformat(r["expires"])<datetime.now(): qx("UPDATE discount_codes SET active=0 WHERE code=?",(c.upper(),)); return None
        except: pass
    return r["pct"]

def get_loyalty(uid):
    return q1("SELECT points,credit,lifetime FROM loyalty WHERE user_id=?",(uid,)) or {"points":0,"credit":0.0,"lifetime":0}

def add_points(uid,gbp):
    pts=int(gbp)*2; lo=get_loyalty(uid); np=lo["points"]+pts; lf=lo["lifetime"]+pts; m=np//100; cr=m*25.0; np=np%100; qx("INSERT INTO loyalty(user_id,points,credit,lifetime) VALUES(?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET points=?,credit=credit+?,lifetime=?",(uid,np,cr,lf,np,cr,lf)); return pts,cr

def get_ref(uid):
    r=q1("SELECT code FROM referrals WHERE owner_id=?",(uid,))
    if r: return r["code"]
    c=str(uid)[-4:]+str(uuid4())[:4].upper(); qx("INSERT OR IGNORE INTO referrals(code,owner_id) VALUES(?,?)",(c,uid)); return c

def credit_ref(ref_code,new_uid):
    r=q1("SELECT owner_id,count FROM referrals WHERE code=? AND owner_id!=?",(ref_code,new_uid))
    if not r: return None
    n=r["count"]+1; qx("UPDATE referrals SET count=? WHERE code=?",(n,ref_code)); return r["owner_id"],n

def fmt_chat(oid):
    msgs=qa("SELECT sender,message,created_at FROM drop_chats WHERE order_id=? ORDER BY created_at",(oid,))
    if not msgs: return "<i>No messages yet.</i>"
    return "\n\n".join(f"<b>{'👤 You' if m['sender']=='user' else '🏪 Donny'}</b> <i>{str(m['created_at'])[:16]}</i>\n{hl.escape(m['message'])}" for m in msgs)

def purge():
    c=(datetime.now()-timedelta(days=30)).isoformat(); qx("DELETE FROM drop_chats WHERE created_at<?",(c,)); qx("DELETE FROM cart WHERE created_at<?",(c,))

def menu():
    return KM([IB("🛍️  Shop Now","shop")],
              [IB("🧺  Basket","basket"),IB("📦  My Orders","orders")],
              [IB("⭐  Reviews","reviews_0"),IB("📢  News","news")],
              [IB("🎁  Loyalty","loyalty"),IB("🔗  Refer & Earn","my_ref")],
              [IB("💬  Contact Us","contact")])

def back_kb(): return KM([IB("⬅️ Back","menu")])
def cancel_kb(): return KM([IB("❌ Cancel","menu")])

def co_kb(ud):
    n,a,s,dp=ud.get("co_name"),ud.get("co_addr"),ud.get("co_ship"),ud.get("co_disc_pct",0)
    al="✅ Address set" if a else ("📍 Not needed" if s=="drop" else "🏠 Delivery Address")
    rows=[[IB(f"✅ {hl.escape(n)}" if n else "👤 Your Name","co_name")],[IB(al,"co_addr")],
          [IB(("✅ " if s=="tracked24" else "")+"📦 Tracked24 (+£5)","co_ship_tracked24"),
           IB(("✅ " if s=="drop" else "")+"📍 Local Drop (Free)","co_ship_drop")],
          [IB(f"🏷️ {ud.get('co_disc_code')} ({int(dp*100)}% off) ✅" if dp else "🏷️ Discount Code","co_disc")]]
    if n and s and (a or s=="drop"): rows.append([IB("🛒 Place Order","co_confirm")])
    rows.append([IB("❌ Cancel","menu")]); return InlineKeyboardMarkup(rows)

def co_summary(ud,uid=None):
    s=ud.get("co_ship"); sub=ud.get("co_sub",0); dp=ud.get("co_disc_pct",0)
    sp=SHIP[s]["price"] if s else 0; sl=SHIP[s]["label"] if s else "—"
    disc=round(sub*dp,2); total=round(sub-disc+sp,2); addr=ud.get("co_addr") or ("Not required" if s=="drop" else "—")
    cr=get_loyalty(uid)["credit"] if uid else 0; dl=f"🏷️ {ud.get('co_disc_code','')} -£{disc:.2f}\n" if dp else ""; cl=f"💳 £{cr:.2f} credit\n" if cr>0 else ""
    hint="📍 <i>Local drop — local only.</i>" if s=="drop" else ("📦 <i>Enter address above.</i>" if s=="tracked24" else "<i>Select delivery method.</i>")
    return f"🛒 <b>Checkout</b>\n━━━━━━━━━━━━━━━━━━━━\n👤 {hl.escape(ud.get('co_name') or '—')}\n🏠 {hl.escape(addr)}\n🚚 {sl}\n{cl}{dl}━━━━━━━━━━━━━━━━━━━━\n💰 <b>Total: £{total:.2f}</b>\n\n{hint}",total

def dc_user_kb(oid,closed=False):
    return KM([IB("🔓 Reopen Chat",f"dco_{oid}")],[IB("⬅️ Back","orders")]) if closed else KM([IB("✉️ Send Message",f"dcm_{oid}")],[IB("🔒 Close Chat",f"dcc_{oid}"),IB("⬅️ Back","orders")])
def dc_admin_kb(oid): return KM([IB("↩️ Reply",f"dcr_{oid}"),IB("🔒 Close",f"dcac_{oid}"),IB("📋 History",f"dch_{oid}")])

async def safe_edit(q,text,**kw):
    try: await q.edit_message_text(text,**kw)
    except:
        try: await q.message.delete()
        except: pass
        await q.message.reply_text(text,**kw)

async def cmd_start(u:Update,ctx:ContextTypes.DEFAULT_TYPE):
    try: purge()
    except: pass
    uid=u.effective_user.id; print(f"👤 /start from {uid}"); is_new=not q1("SELECT 1 FROM users WHERE user_id=?",(uid,))
    qx("INSERT OR IGNORE INTO users(user_id,username) VALUES(?,?)",(uid,u.effective_user.username or ""))
    if is_new and ctx.args:
        result=credit_ref(ctx.args[0],uid)
        if result:
            owner_id,cnt=result
            try:
                msg="🎉 FREE 3.5g Lemon Cherry Gelato incoming! 🌿" if cnt%15==0 else f"🔗 +1 referral! {cnt} total · {15-(cnt%15)} more = FREE 3.5g"
                await ctx.bot.send_message(owner_id,msg)
                if cnt%15==0: await ctx.bot.send_message(ADMIN_ID,f"🎁 {owner_id} hit {cnt} refs — send FREE 3.5g LCG.")
            except: pass
    name=hl.escape(u.effective_user.first_name or "there"); extra=gs("home_extra"); el=f"\n\n{extra}" if extra else ""
    await u.message.reply_text(
        f"🌿 <b>Welcome to Donny's Shop, {name}.</b>\n━━━━━━━━━━━━━━━━━━━━\n\n{open_badge()}\n🕙 <b>Mon–Sat · Orders close 11am</b>\n\n"
        f"Premium quality. Every time.{el}\n\n📦 Tracked · 📍 Local Drop · 🔒 Discreet · ⭐ 5-Star\n\n👇 <b>Tap Shop Now</b>",
        parse_mode="HTML",reply_markup=menu())
async def show_shop(u,ctx):
    q=u.callback_query; cats=qa("SELECT * FROM categories ORDER BY id"); kb=[]
    if cats:
        kb=[[IB(f"{c['emoji']} {c['name']}",f"cat_{c['id']}")] for c in cats]
        unc=qa("SELECT id,name FROM products WHERE hidden=0 AND (category_id=0 OR category_id IS NULL) ORDER BY id")
        if unc: kb+=[[IB(f"🌿 {r['name']}",f"prod_{r['id']}")] for r in unc]
    else:
        prods=qa("SELECT id,name FROM products WHERE hidden=0 ORDER BY id")
        kb=[[IB(f"🌿 {r['name']}",f"prod_{r['id']}")] for r in prods] or [[IB("No products yet","noop")]]
    await safe_edit(q,"🛍️ <b>Shop</b>\n\nChoose a product:",parse_mode="HTML",reply_markup=InlineKeyboardMarkup(kb+[[IB("⬅️ Back","menu")]]))
async def show_category(u,ctx):
    q=u.callback_query; cid=int(q.data.split("_")[1])
    cat=q1("SELECT * FROM categories WHERE id=?",(cid,))
    if not cat: await safe_edit(q,"❌ Category not found.",reply_markup=back_kb()); return
    prods=qa("SELECT id,name FROM products WHERE hidden=0 AND category_id=? ORDER BY id",(cid,))
    kb=[[IB(f"🌿 {r['name']}",f"prod_{r['id']}")] for r in prods]+[[IB("⬅️ Back","shop")]]
    txt=f"{cat['emoji']} <b>{hl.escape(cat['name'])}</b>" if prods else f"😔 No products in {cat['name']} yet."
    await safe_edit(q,txt,parse_mode="HTML",reply_markup=InlineKeyboardMarkup(kb))

async def show_product(u,ctx):
    q=u.callback_query; pid=int(q.data.split("_")[1]); row=q1("SELECT * FROM products WHERE id=? AND hidden=0",(pid,))
    if not row: await safe_edit(q,"❌ Product not available.",reply_markup=back_kb()); return
    tiers=json.loads(row["tiers"]) if row.get("tiers") else TIERS[:]
    btns=[IB(ft(t),f"pick_{pid}_{t['qty']}_{t['price']}") for t in tiers]
    kb=[btns[i:i+2] for i in range(0,len(btns),2)]+[[IB("🧺 Basket","basket"),IB("⬅️ Back","shop")]]
    cap=f"🌿 <b>{hl.escape(row['name'])}</b>\n\n{hl.escape(row['description'])}\n\n"+"".join(ft(t)+"\n" for t in tiers)
    try: await q.message.delete()
    except: pass
    if row.get("photo"): await ctx.bot.send_photo(q.message.chat_id,row["photo"],caption=cap[:1020],parse_mode="HTML",reply_markup=InlineKeyboardMarkup(kb))
    else: await q.message.reply_text(cap[:4000],parse_mode="HTML",reply_markup=InlineKeyboardMarkup(kb))
async def pick_weight(u,ctx):
    q=u.callback_query; p=q.data.split("_"); pid,qty,price=int(p[1]),float(p[2]),float(p[3])
    row=q1("SELECT name FROM products WHERE id=? AND hidden=0",(pid,))
    if not row: await q.answer("❌ Product no longer available.",show_alert=True); return
    qx("INSERT INTO cart(user_id,product_id,qty,price) VALUES(?,?,?,?)",(q.from_user.id,pid,qty,price))
    await q.answer(f"✅ {fq(qty)} of {row['name']} added! (£{price:.2f})",show_alert=True)

async def view_basket(u,ctx):
    q=u.callback_query; uid=q.from_user.id; items=qa("SELECT cart.id,products.name,cart.qty,cart.price FROM cart JOIN products ON cart.product_id=products.id WHERE cart.user_id=? ORDER BY cart.id",(uid,))
    if not items: await safe_edit(q,"🧺 Basket empty.",reply_markup=KM([IB("🛍️ Shop","shop")],[IB("⬅️ Back","menu")])); return
    total=sum(r["price"] for r in items)
    txt="🧺 <b>Basket</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"+"".join(f"• {hl.escape(r['name'])} {fq(r['qty'])} — £{r['price']:.2f}\n" for r in items)+f"\n━━━━━━━━━━━━━━━━━━━━\n💰 <b>Total: £{total:.2f}</b>"
    await safe_edit(q,txt,parse_mode="HTML",reply_markup=InlineKeyboardMarkup([[IB(f"🗑️ {r['name']} {fq(r['qty'])}",f"rm_{r['id']}")] for r in items]+[[IB("💳 Checkout","checkout")],[IB("⬅️ Back","menu")]]))
async def remove_item(u,ctx):
    q=u.callback_query; qx("DELETE FROM cart WHERE id=? AND user_id=?",(int(q.data.split("_")[1]),q.from_user.id)); await view_basket(u,ctx)

async def checkout_start(u,ctx):
    q=u.callback_query; uid=q.from_user.id; prices=qa("SELECT price FROM cart WHERE user_id=?",(uid,))
    if not prices: await safe_edit(q,"🧺 Basket empty.",reply_markup=menu()); return
    ctx.user_data.update({"co_name":None,"co_addr":None,"co_ship":None,"co_disc_code":None,"co_disc_pct":0,"co_credit":0.0,"co_sub":round(sum(r["price"] for r in prices),2),"wf":None})
    t,_=co_summary(ctx.user_data,uid); await safe_edit(q,t,parse_mode="HTML",reply_markup=co_kb(ctx.user_data))
async def co_name_start(u,ctx):
    q=u.callback_query; ctx.user_data["wf"]="co_name"; await safe_edit(q,"👤 Enter your full name:",reply_markup=KM([IB("❌ Cancel","co_refresh")]))

async def co_addr_start(u,ctx):
    q=u.callback_query
    if ctx.user_data.get("co_ship")=="drop": await safe_edit(q,"📍 No address needed. Tap Skip or type a rough area.",reply_markup=KM([IB("⏭️ Skip","co_addr_skip")],[IB("❌ Cancel","co_refresh")]))
    else: ctx.user_data["wf"]="co_addr"; await safe_edit(q,"🏠 Enter your full delivery address:",reply_markup=KM([IB("❌ Cancel","co_refresh")]))

async def co_addr_skip(u,ctx):
    q=u.callback_query; ctx.user_data["co_addr"]=""; ctx.user_data["wf"]=None; t,_=co_summary(ctx.user_data,q.from_user.id); await safe_edit(q,t,parse_mode="HTML",reply_markup=co_kb(ctx.user_data))

async def co_disc_start(u,ctx):
    q=u.callback_query; ctx.user_data["wf"]="co_disc"
    codes=qa("SELECT code,pct FROM discount_codes WHERE active=1")
    hint=", ".join(f"<code>{r['code']}</code> ({int(r['pct']*100)}% off)" for r in codes) if codes else "No active codes"
    await safe_edit(q,f"🏷️ <b>Enter discount code</b>\n\nAvailable: {hint}",parse_mode="HTML",reply_markup=KM([IB("❌ Cancel","co_refresh")]))

async def co_ship_cb(u,ctx):
    q=u.callback_query; ctx.user_data["co_ship"]=q.data.split("co_ship_")[1]; t,_=co_summary(ctx.user_data,q.from_user.id); await safe_edit(q,t,parse_mode="HTML",reply_markup=co_kb(ctx.user_data))

async def co_refresh_cb(u,ctx):
    q=u.callback_query; ctx.user_data["wf"]=None; t,_=co_summary(ctx.user_data,q.from_user.id); await safe_edit(q,t,parse_mode="HTML",reply_markup=co_kb(ctx.user_data))

async def co_confirm(u,ctx):
    q=u.callback_query; uid=q.from_user.id; ud=ctx.user_data
    name,addr,sk=ud.get("co_name"),ud.get("co_addr") or "",ud.get("co_ship")
    if not name: await q.answer("⚠️ Please enter your name first.",show_alert=True); return
    if not sk: await q.answer("⚠️ Please select a delivery method.",show_alert=True); return
    if sk=="tracked24" and not addr: await q.answer("⚠️ Please enter your delivery address.",show_alert=True); return
    items=qa("SELECT products.name,cart.qty,cart.price FROM cart JOIN products ON cart.product_id=products.id WHERE cart.user_id=?",(uid,))
    if not items: await safe_edit(q,"🧺 Your basket is empty.",reply_markup=menu()); return
    item_lines="\n".join(f"  • {hl.escape(r['name'])} {fq(r['qty'])} — £{r['price']:.2f}" for r in items); summary=", ".join(f"{r['name']} {fq(r['qty'])}" for r in items)
    sub=round(sum(r["price"] for r in items),2); dp=ud.get("co_disc_pct",0); sp=SHIP[sk]["price"]; sl=SHIP[sk]["label"]; needs_ltc=SHIP[sk]["ltc"]
    disc=round(sub*dp,2); gbp=round(sub-disc+sp,2); ltc=round(gbp/ltc_price(),6) if needs_ltc else 0.0; oid=str(uuid4())[:8].upper(); addr_disp=addr or "Local Drop"
    qx("INSERT INTO orders(id,user_id,cust_name,address,summary,gbp,ltc,status,ship) VALUES(?,?,?,?,?,?,?,?,?)",(oid,uid,name,addr_disp,summary,gbp,ltc,"Pending",sk))
    qx("DELETE FROM cart WHERE user_id=?",(uid,))
    if sk=="drop": qx("INSERT INTO drop_chats(order_id,user_id,sender,message) VALUES(?,?,?,?)",(oid,uid,"vendor",f"👋 Hi {hl.escape(name)}! Order received. Message to arrange pickup."))
    uname=q.from_user.username or str(uid)
    notif=f"🛒 <b>NEW ORDER {oid}</b>\n👤 {hl.escape(name)} (@{uname}) · 🏠 {hl.escape(addr_disp)}\n📦 {summary} · 🚚 {sl} · 💷 £{gbp:.2f}{f' | {ltc} LTC' if needs_ltc else ''}"
    await ctx.bot.send_message(CHANNEL_ID,notif,parse_mode="HTML")
    adm_kb=InlineKeyboardMarkup([[IB("✅ Confirm",f"adm_ok_{oid}"),IB("❌ Reject",f"adm_no_{oid}")]]+([[IB("💬 Chat",f"dch_{oid}")]] if sk=="drop" else []))
    try: await ctx.bot.send_message(ADMIN_ID,notif,parse_mode="HTML",reply_markup=adm_kb)
    except: pass
    disc_l=f"🏷️ {ud.get('co_disc_code','')} -£{disc:.2f}\n" if dp else ""; ship_l=f"🚚 +£{sp:.2f}\n" if sp else ""
    sep2="━━━━━━━━━━━━━━━━━━━━"
    invoice=f"🧾 <b>INVOICE — Donny's Shop</b>\n{sep2}\n📋 <b>Order {oid}</b> · {datetime.now().strftime('%d/%m/%Y %H:%M')}\n{sep2}\n👤 {hl.escape(name)} · 🏠 {hl.escape(addr_disp)} · 🚚 {sl}\n{sep2}\n<b>Items:</b>\n{item_lines}\n{sep2}\n💷 £{sub:.2f}\n{disc_l}{ship_l}💰 <b>TOTAL: £{gbp:.2f}</b>\n{sep2}\n"
    if needs_ltc:
        invoice+=f"\n📤 Send <b>{ltc} LTC</b> to:\n<code>{LTC_ADDR}</code>\n\n⚠️ <i>Exact amount only. Tap I Have Paid once sent.</i>"
        kb=KM([IB("✅ I Have Paid",f"paid_{oid}")],[IB("📦 My Orders","orders")])
    else:
        invoice+="\n📍 Tap below to chat with Donny and arrange your pickup.\n⚠️ <i>Local customers only — non-local orders refunded.</i>"
        kb=KM([IB("💬 Chat with Donny — Arrange Pickup",f"dcv_{oid}")],[IB("📦 My Orders","orders")])
    for k in [k for k in list(ud) if k.startswith("co_")]: ud.pop(k)
    try: await q.message.delete()
    except: pass
    await q.message.reply_text(invoice,parse_mode="HTML",reply_markup=kb)

async def view_orders(u,ctx):
    q=u.callback_query; uid=q.from_user.id
    rows=qa("SELECT id,gbp,status,ship,summary FROM orders WHERE user_id=? ORDER BY rowid DESC",(uid,))
    if not rows: await safe_edit(q,"📭 No orders yet — shop now! 🛍️",parse_mode="HTML",reply_markup=KM([IB("🛍️ Shop","shop")],[IB("⬅️ Back","menu")])); return
    sm={"Pending":("🕐","Pending"),"Paid":("✅","Confirmed"),"Dispatched":("🚚","Dispatched"),"Rejected":("❌","Rejected")}
    txt="📦 <b>Your Orders</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"; kb=[]
    for o in rows:
        icon,lbl=sm.get(o["status"],("📋",o["status"]))
        txt+=f"{icon} <b>Order {o['id']}</b> · {lbl} · {'📍' if o['ship']=='drop' else '📦'} · 💷 £{o['gbp']:.2f}\n{hl.escape(o['summary'])}\n\n"
        if o["ship"]=="drop" and o["status"] in ("Pending","Paid","Dispatched"):
            closed=gs(f"cc_{o['id']}","0")=="1"
            kb.append([IB(f"{'🔒 Closed' if closed else '💬 Drop Chat'} — {o['id']}",f"dcv_{o['id']}")])
    await safe_edit(q,txt[:4000],parse_mode="HTML",reply_markup=InlineKeyboardMarkup(kb+[[IB("⬅️ Back","menu")]]))
async def user_paid(u,ctx):
    q=u.callback_query; oid=q.data[5:]
    row=q1("SELECT ship,cust_name,summary,gbp,ltc,address FROM orders WHERE id=?",(oid,))
    if not row: await safe_edit(q,"❌ Order not found.",reply_markup=back_kb()); return
    sl=SHIP.get(row["ship"],{}).get("label",row["ship"])
    await ctx.bot.send_message(ADMIN_ID,f"💰 <b>PAYMENT CLAIM</b> — <code>{oid}</code>\n👤 {hl.escape(row['cust_name'])} · {row['summary']}\n💷 £{row['gbp']:.2f} | {row['ltc']} LTC",parse_mode="HTML",reply_markup=InlineKeyboardMarkup([[IB("✅ Confirm",f"adm_ok_{oid}"),IB("❌ Reject",f"adm_no_{oid}")]]))
    await safe_edit(q,f"⏳ <b>Payment Submitted</b>\n━━━━━━━━━━━━━━━━━━━━\n📋 Order <code>{oid}</code>\n🛍️ {hl.escape(row['summary'])}\n🚚 {sl}\n💰 £{row['gbp']:.2f} | {row['ltc']} LTC\n━━━━━━━━━━━━━━━━━━━━\n✅ Payment received — awaiting admin confirmation.",parse_mode="HTML",reply_markup=KM([IB("📦 My Orders","orders")]))
async def show_reviews(u,ctx):
    q=u.callback_query; page=int(q.data.split("_")[1])
    ms=datetime.now().replace(day=1,hour=0,minute=0,second=0,microsecond=0).isoformat()
    total=q1("SELECT COUNT(*) as c FROM reviews WHERE created_at>=?",(ms,))["c"]
    rows=qa("SELECT stars,text FROM reviews WHERE created_at>=? ORDER BY created_at DESC LIMIT ? OFFSET ?",(ms,RPP,page*RPP))
    if not rows and page==0: await safe_edit(q,"💬 No reviews this month yet.",reply_markup=back_kb()); return
    txt=f"⭐ <b>Reviews of the Month</b> ({total})\n\n"+"".join(f"{STARS.get(r['stars'],'')}\n{hl.escape(r['text'])}\n\n" for r in rows)
    pages=(total-1)//RPP if total else 0
    nav=([IB("◀️",f"reviews_{page-1}")] if page>0 else [])+([IB("▶️",f"reviews_{page+1}")] if page<pages else [])
    await safe_edit(q,txt[:4000],parse_mode="HTML",reply_markup=InlineKeyboardMarkup(([nav] if nav else [])+[[IB("⬅️ Back","menu")]]))
async def review_start(u,ctx):
    q=u.callback_query; oid=q.data[7:]
    if not q1("SELECT 1 FROM orders WHERE id=? AND user_id=? AND status IN ('Paid','Dispatched')",(oid,q.from_user.id)):
        await q.answer("⚠️ Not eligible to review.",show_alert=True); return
    ctx.user_data["rev_order"]=oid
    await safe_edit(q,"⭐ Rate your order:",reply_markup=KM([IB("⭐ 1","stars_1"),IB("⭐⭐ 2","stars_2"),IB("⭐⭐⭐ 3","stars_3")],[IB("⭐⭐⭐⭐ 4","stars_4"),IB("⭐⭐⭐⭐⭐ 5","stars_5")],[IB("❌ Cancel","menu")]))
async def pick_stars(u,ctx):
    q=u.callback_query; s=int(q.data.split("_")[1]); ctx.user_data.update({"rev_stars":s,"wf":"review_text"}); await safe_edit(q,f"✨ {STARS[s]}\n\n✏️ Write your review:",parse_mode="HTML",reply_markup=cancel_kb())

async def show_news(u,ctx):
    q=u.callback_query; rows=qa("SELECT id,title,body,photo,created_at FROM announcements ORDER BY id DESC LIMIT 5")
    if not rows: await safe_edit(q,"📢 No announcements yet.",reply_markup=back_kb()); return
    first=rows[0]; txt=f"📢 <b>{hl.escape(first['title'])}</b>\n\n{hl.escape(first['body'])}\n<i>{str(first['created_at'])[:10]}</i>"
    if len(rows)>1: txt+="\n\n<b>Previous:</b>\n"+"".join(f"• {hl.escape(r['title'])} <i>{str(r['created_at'])[:10]}</i>\n" for r in rows[1:])
    kb=InlineKeyboardMarkup([[IB("⬅️ Back","menu")]])
    if first.get("photo"):
        try: await q.message.delete()
        except: pass
        await ctx.bot.send_photo(q.message.chat_id,first["photo"],caption=txt[:1020],parse_mode="HTML",reply_markup=kb)
    else: await safe_edit(q,txt[:4000],parse_mode="HTML",reply_markup=kb)
async def show_loyalty(u,ctx):
    q=u.callback_query; uid=q.from_user.id; lo=get_loyalty(uid)
    pts=lo["points"]; bar="█"*(pts//10)+"░"*(10-pts//10)
    await safe_edit(q,f"🎁 <b>Loyalty Rewards</b>\n━━━━━━━━━━━━━━━━━━━━\n\n⭐ <b>{pts}/100 pts</b>\n[{bar}]\n{100-pts} more = <b>£25 credit</b>\n💳 Available: <b>£{lo['credit']:.2f}</b>\n🏆 Lifetime: <b>{lo['lifetime']} pts</b>\n\n<i>2 pts per £1 · 100 pts = £25 credit</i>",parse_mode="HTML",reply_markup=back_kb())
async def show_my_ref(u,ctx):
    q=u.callback_query; uid=q.from_user.id; rc=get_ref(uid)
    cnt=(q1("SELECT count FROM referrals WHERE owner_id=?",(uid,)) or {}).get("count",0); nxt=15-(cnt%15) if cnt%15 else 15
    bot_name=(await ctx.bot.get_me()).username
    await safe_edit(q,f"🔗 <b>Your Referral Link</b>\n━━━━━━━━━━━━━━━━━━━━\n\n<code>https://t.me/{bot_name}?start={rc}</code>\n\n👥 <b>{cnt}</b> joined · <b>{nxt} more</b> = FREE 3.5g Lemon Cherry Gelato 🌿\n<i>Every 15 refs = FREE 3.5g. Milestones: 15, 30, 45...</i>",parse_mode="HTML",reply_markup=back_kb())
async def contact_start(u,ctx):
    q=u.callback_query; ctx.user_data["wf"]="contact"; await safe_edit(q,"💬 Type your message and we'll get back to you:",parse_mode="HTML",reply_markup=cancel_kb())

async def dropchat_view(u,ctx):
    q=u.callback_query; oid=q.data[4:]; closed=gs(f"cc_{oid}","0")=="1"
    o=q1("SELECT summary,gbp FROM orders WHERE id=?",(oid,))
    hdr=f"💬 <b>Drop Chat — Order {oid}</b>\n━━━━━━━━━━━━━━━━━━━━\n"+(f"🛍️ {hl.escape(o['summary'])} · 💷 £{o['gbp']:.2f}\n" if o else "")+("🔒 <i>Chat closed.</i>\n" if closed else "")+"━━━━━━━━━━━━━━━━━━━━\n\n"
    try: await q.message.delete()
    except: pass
    await q.message.reply_text(f"{hdr}{fmt_chat(oid)}"[:4000],parse_mode="HTML",reply_markup=dc_user_kb(oid,closed))
async def dropchat_msg_start(u,ctx):
    q=u.callback_query; oid=q.data[4:]; ctx.user_data.update({"dc_oid":oid,"wf":"drop_msg_user"})
    try: await q.message.delete()
    except: pass
    await q.message.reply_text(f"💬 <b>Order {oid}</b>\n\n✉️ Type your message:",parse_mode="HTML",reply_markup=KM([IB("❌ Cancel",f"dcv_{oid}")]))

async def dropchat_reply_start(u,ctx):
    q=u.callback_query
    if not is_admin(u.effective_user.id): return
    oid=q.data[4:]; ctx.user_data.update({"dc_oid":oid,"wf":"drop_msg_admin"}); o=q1("SELECT cust_name,summary FROM orders WHERE id=?",(oid,))
    hdr=f"↩️ Reply {oid}"+(f" — {hl.escape(o['cust_name'])} | {o['summary']}" if o else "")
    await safe_edit(q,f"{hdr}\n━━━━━━━━━━━━━━━━━━━━\n\n{fmt_chat(oid)}\n\n✏️ Type reply:",parse_mode="HTML",reply_markup=KM([IB("❌ Cancel","menu")]))

async def dropchat_history(u,ctx):
    q=u.callback_query
    if not is_admin(u.effective_user.id): return
    oid=q.data[4:]; closed=gs(f"cc_{oid}","0")=="1"; o=q1("SELECT cust_name,summary,gbp FROM orders WHERE id=?",(oid,)); note=q1("SELECT note FROM order_notes WHERE order_id=?",(oid,))
    hdr=f"📋 <b>Chat {oid}</b>"+(f"\n👤 {hl.escape(o['cust_name'])} | {o['summary']} | 💷 £{o['gbp']:.2f}" if o else "")+(f"\n📝 {hl.escape(note['note'])}" if note else "")
    await safe_edit(q,f"{hdr}\n━━━━━━━━━━━━━━━━━━━━\n\n{fmt_chat(oid)}"[:4000],parse_mode="HTML",reply_markup=dc_admin_kb(oid) if not closed else KM([IB("🔓 Reopen",f"dco_{oid}")]))

async def dropchat_close(u,ctx):
    q=u.callback_query; oid=q.data.split("_",1)[1]; ss(f"cc_{oid}","1")
    r=q1("SELECT user_id FROM orders WHERE id=?",(oid,))
    if r and is_admin(u.effective_user.id):
        try: await ctx.bot.send_message(r["user_id"],f"🔒 Drop Chat for order {oid} has been closed by the vendor.\nUse Contact Us if you need anything.",reply_markup=menu())
        except: pass
    await safe_edit(q,f"🔒 Chat {oid} closed.",reply_markup=KM([IB("🔓 Reopen",f"dco_{oid}"),IB("⬅️ Back","menu")]))

async def dropchat_open(u,ctx):
    q=u.callback_query; oid=q.data[4:]; ss(f"cc_{oid}","0")
    await safe_edit(q,f"🔓 Chat {oid} reopened.\n\n{fmt_chat(oid)}",parse_mode="HTML",reply_markup=dc_user_kb(oid,False))

async def cmd_admin(u:Update,ctx:ContextTypes.DEFAULT_TYPE):
    if not is_admin(u.effective_user.id): return
    orders=qa("SELECT id,status,ship FROM orders ORDER BY rowid DESC LIMIT 30")
    unread=q1("SELECT COUNT(*) as c FROM messages WHERE reply IS NULL")["c"]
    drops=len([o for o in orders if o["ship"]=="drop" and o["status"] in ("Pending","Paid")])
    kb=[[IB(f"✅ {o['id']}",f"adm_ok_{o['id']}"),IB(f"❌ {o['id']}",f"adm_no_{o['id']}")] for o in orders if o["status"]=="Pending"]+[[IB(f"🚚 {o['id']}",f"adm_go_{o['id']}")] for o in orders if o["status"]=="Paid" and o["ship"]!="drop"]
    kb+=[[IB("➕ Add","adm_addprod"),IB("🗑️ Remove","adm_rmprod"),IB("✏️ Desc","adm_editdesc"),IB("⚖️ Tiers","adm_tiers")],
         [IB("👁️ Hide/Show","adm_hideprod"),IB("📂 Cats","adm_cats"),IB(f"💬 Msgs{f' ({unread})' if unread else ''}","adm_msgs"),IB(f"📍 Drops{f' ({drops})' if drops else ''}","adm_drops")],
         [IB("🏷️ Discounts","adm_discounts"),IB("📢 Announce","adm_announce"),IB("📊 Reviews","adm_rev_0")],
         [IB("👥 Admins","adm_admins"),IB("🏠 Edit Home","adm_edit_home")]]
    await u.message.reply_text("🔧 <b>Admin Panel</b>",parse_mode="HTML",reply_markup=InlineKeyboardMarkup(kb))
async def adm_confirm(u,ctx):
    q=u.callback_query; oid=q.data[7:]; qx("UPDATE orders SET status='Paid' WHERE id=?",(oid,))
    r=q1("SELECT user_id,ship,gbp FROM orders WHERE id=?",(oid,))
    if r:
        pts,cr=add_points(r["user_id"],r.get("gbp",0))
        lnote=f"\n🎁 +{pts} pts!{f' 💳 £{cr:.0f} credit added!' if cr else ''}"
        try:
            if r["ship"]=="drop": await ctx.bot.send_message(r["user_id"],f"✅ <b>Order {oid} confirmed!</b> Open Drop Chat to arrange pickup.{lnote}",parse_mode="HTML",reply_markup=KM([IB("💬 Drop Chat",f"dcv_{oid}")]))
            else: await ctx.bot.send_message(r["user_id"],f"✅ Payment confirmed — <code>{oid}</code>! 🌟{lnote}",parse_mode="HTML",reply_markup=KM([IB("⭐ Leave a Review",f"review_{oid}")]))
        except: pass
    await safe_edit(q,f"✅ Order {oid} confirmed.")
async def adm_reject(u,ctx):
    q=u.callback_query; oid=q.data[7:]; qx("UPDATE orders SET status='Rejected' WHERE id=?",(oid,))
    r=q1("SELECT user_id FROM orders WHERE id=?",(oid,))
    if r:
        try: await ctx.bot.send_message(r["user_id"],f"❌ Order <code>{oid}</code> rejected. Contact us if needed.",parse_mode="HTML")
        except: pass
    await safe_edit(q,f"❌ Rejected {oid}.")

async def adm_dispatch(u,ctx):
    q=u.callback_query; oid=q.data[7:]; qx("UPDATE orders SET status='Dispatched' WHERE id=?",(oid,))
    r=q1("SELECT user_id,summary FROM orders WHERE id=?",(oid,))
    if r:
        try: await ctx.bot.send_message(r["user_id"],f"🚚 <b>Order {oid} dispatched!</b> 📬\n{hl.escape(r['summary'])}",parse_mode="HTML",reply_markup=KM([IB("⭐ Leave a Review",f"review_{oid}")]))
        except: pass
        qx("INSERT OR IGNORE INTO review_reminders(order_id,user_id,dispatched) VALUES(?,?,?)",(oid,r["user_id"],datetime.now().isoformat()))
    await safe_edit(q,f"🚚 Dispatched {oid}.")

async def adm_msgs(u,ctx):
    q=u.callback_query
    if not is_admin(u.effective_user.id): return
    rows=qa("SELECT id,username,message,reply FROM messages ORDER BY id DESC LIMIT 15")
    if not rows: await safe_edit(q,"📭 No messages.",reply_markup=back_kb()); return
    txt="💬 <b>Messages</b>\n\n"+"".join(f"{'✅' if r['reply'] else '⏳'} #{r['id']} @{r['username'] or '?'}\n{hl.escape(r['message'][:70])}\n/reply {r['id']}\n\n" for r in rows)
    await safe_edit(q,txt[:4000],parse_mode="HTML",reply_markup=back_kb())

async def adm_rev_cb(u,ctx):
    q=u.callback_query
    if not is_admin(u.effective_user.id): return
    page=int(q.data.split("adm_rev_")[1]); total=q1("SELECT COUNT(*) as c FROM reviews")["c"]
    rows=qa("SELECT stars,text,created_at FROM reviews ORDER BY created_at DESC LIMIT ? OFFSET ?",(RPP,page*RPP))
    if not rows and page==0: await safe_edit(q,"📭 No reviews yet.",reply_markup=back_kb()); return
    txt=f"📊 <b>All Reviews</b> ({total})\n\n"+"".join(f"{STARS.get(r['stars'],'')} · {str(r['created_at'])[:10]}\n{hl.escape(r['text'])}\n\n" for r in rows)
    pages=(total-1)//RPP if total else 0; nav=([IB("◀️",f"adm_rev_{page-1}")] if page>0 else [])+([IB("▶️",f"adm_rev_{page+1}")] if page<pages else [])
    await safe_edit(q,txt[:4000],parse_mode="HTML",reply_markup=InlineKeyboardMarkup(([nav] if nav else [])+[[IB("⬅️ Back","menu")]]))

async def adm_edit_home(u,ctx):
    q=u.callback_query
    if not is_admin(u.effective_user.id): return
    cur=gs("home_extra"); ctx.user_data["wf"]="edit_home"; await safe_edit(q,f"🏠 Current: <i>{hl.escape(cur) if cur else 'None'}</i>\n\nType new text or <code>clear</code>:",parse_mode="HTML",reply_markup=cancel_kb())

async def adm_admins(u,ctx):
    q=u.callback_query
    if not is_admin(u.effective_user.id): return
    rows=qa("SELECT user_id,username FROM admins ORDER BY rowid")
    txt="👥 <b>Admins</b>\n\n"+"".join(f"{'👑' if r['user_id']==ADMIN_ID else '🔑'} <code>{r['user_id']}</code> @{r['username'] or '?'}\n" for r in rows)
    kb=[[IB("➕ Add","adm_addadmin")]]+[[IB(f"🗑️ {r['username'] or r['user_id']}",f"adm_rmadmin_{r['user_id']}")] for r in rows if r["user_id"]!=ADMIN_ID]+[[IB("⬅️ Back","menu")]]
    await safe_edit(q,txt,parse_mode="HTML",reply_markup=InlineKeyboardMarkup(kb))

async def adm_addadmin_start(u,ctx):
    q=u.callback_query
    if not is_admin(u.effective_user.id): return
    ctx.user_data["wf"]="add_admin"; await safe_edit(q,"➕ Send new admin's numeric Telegram <b>user_id</b>\n<i>(find via @userinfobot)</i>",parse_mode="HTML",reply_markup=cancel_kb())

async def adm_rmadmin(u,ctx):
    q=u.callback_query
    if not is_admin(u.effective_user.id): return
    uid=int(q.data.split("adm_rmadmin_")[1])
    if uid==ADMIN_ID: await q.answer("❌ Cannot remove owner.",show_alert=True); return
    r=q1("SELECT username FROM admins WHERE user_id=?",(uid,)); qx("DELETE FROM admins WHERE user_id=?",(uid,))
    await q.answer(f"✅ Removed {r['username'] if r else uid}",show_alert=True); await adm_admins(u,ctx)

async def adm_note_start(u,ctx):
    q=u.callback_query
    if not is_admin(u.effective_user.id): return
    oid=q.data[9:]; ctx.user_data.update({"note_oid":oid,"wf":"order_note"}); note=q1("SELECT note FROM order_notes WHERE order_id=?",(oid,))
    await q.message.reply_text(f"📝 Note for {oid} — current: <i>{hl.escape(note['note']) if note else 'none'}</i>\n\nType note:",parse_mode="HTML")

async def adm_drop_overview(u,ctx):
    q=u.callback_query
    if not is_admin(u.effective_user.id): return
    rows=qa("SELECT o.id,o.cust_name,o.status,(SELECT COUNT(*) FROM drop_chats d WHERE d.order_id=o.id) as msgs FROM orders o WHERE o.ship='drop' ORDER BY o.rowid DESC LIMIT 20")
    if not rows: await safe_edit(q,"📍 No drop orders.",reply_markup=back_kb()); return
    em={"Pending":"⏳","Paid":"✅","Dispatched":"🚚","Rejected":"❌"}; kb=[[IB(("🔒" if gs(f"cc_{o['id']}","0")=="1" else "💬")+f" {o['id']} · {o['cust_name']} {em.get(o['status'],'')} ({o['msgs']})",f"dch_{o['id']}")] for o in rows]+[[IB("⬅️ Back","menu")]]
    await safe_edit(q,"📍 <b>Drop Orders</b>",parse_mode="HTML",reply_markup=InlineKeyboardMarkup(kb))

async def adm_discounts(u,ctx):
    q=u.callback_query
    if not is_admin(u.effective_user.id): return
    rows=qa("SELECT code,pct,active,expires FROM discount_codes ORDER BY code")
    txt="🏷️ <b>Discount Codes</b>\n\n"+"".join(f"{'✅' if r['active'] else '❌'} <code>{r['code']}</code> {int(r['pct']*100)}%{f' exp {r["expires"][:10]}' if r.get('expires') else ''}\n" for r in rows)
    kb=[[IB(f"{'🚫' if r['active'] else '✅'} {r['code']}",f"toggledisc_{r['code']}")] for r in rows]+[[IB("➕ Add","adm_adddisc")],[IB("⬅️ Back","menu")]]
    await safe_edit(q,txt or "No codes.",parse_mode="HTML",reply_markup=InlineKeyboardMarkup(kb))

async def adm_toggledisc(u,ctx):
    q=u.callback_query; c=q.data.split("toggledisc_")[1]
    r=q1("SELECT active FROM discount_codes WHERE code=?",(c,))
    if r: qx("UPDATE discount_codes SET active=? WHERE code=?",(0 if r["active"] else 1,c))
    await adm_discounts(u,ctx)

async def adm_adddisc_start(u,ctx):
    q=u.callback_query; ctx.user_data["wf"]="disc_code"; await safe_edit(q,"🏷️ Add code: <code>CODE,PCT</code> or <code>CODE,PCT,HOURS</code>\ne.g. <code>SAVE20,20</code> or <code>FLASH50,50,4</code>",parse_mode="HTML",reply_markup=cancel_kb())

async def ann_start(u,ctx):
    q=u.callback_query; ctx.user_data.update({"wf":"ann_title"}); ctx.user_data.pop("ann_photo",""); await safe_edit(q,"📢 Enter announcement title:",reply_markup=cancel_kb())

async def adm_cats(u,ctx):
    q=u.callback_query
    if not is_admin(u.effective_user.id): return
    cats=qa("SELECT * FROM categories ORDER BY id")
    txt="📂 <b>Categories</b>\n\n"+("\n".join(f"{c['emoji']} {c['name']}" for c in cats) if cats else "No categories yet.")
    kb=[[IB(f"✏️ {c['emoji']} {c['name']}",f"cat_assign_{c['id']}")] for c in cats]+[[IB("➕ New Category","adm_newcat"),IB("🗑️ Delete","adm_delcat")],[IB("⬅️ Back","menu")]]
    await safe_edit(q,txt,parse_mode="HTML",reply_markup=InlineKeyboardMarkup(kb))

async def adm_newcat(u,ctx):
    q=u.callback_query; ctx.user_data["wf"]="new_cat"; await safe_edit(q,"📂 Send: <code>🍃 Indoor Strains</code>",parse_mode="HTML",reply_markup=cancel_kb())

async def adm_delcat_list(u,ctx):
    q=u.callback_query; cats=qa("SELECT * FROM categories ORDER BY id")
    if not cats: await safe_edit(q,"No categories to delete.",reply_markup=back_kb()); return
    await safe_edit(q,"🗑️ Delete which category?",reply_markup=InlineKeyboardMarkup([[IB(f"🗑️ {c['emoji']} {c['name']}",f"delcat_{c['id']}")] for c in cats]+[[IB("⬅️ Back","adm_cats")]]))

async def adm_delcat_do(u,ctx):
    q=u.callback_query; cid=int(q.data.split("_")[1])
    qx("UPDATE products SET category_id=0 WHERE category_id=?",(cid,)); qx("DELETE FROM categories WHERE id=?",(cid,))
    await adm_cats(u,ctx)

async def adm_cat_assign(u,ctx):
    q=u.callback_query; cid=int(q.data.split("_")[2]); cat=q1("SELECT name,emoji FROM categories WHERE id=?",(cid,))
    rows=qa("SELECT id,name,category_id FROM products ORDER BY id")
    kb=[[IB(("✅ " if r["category_id"]==cid else "○ ")+r["name"],f"togglecat_{r['id']}_{cid}")] for r in rows]+[[IB("✅ Done","adm_cats")]]
    await safe_edit(q,f"📂 Assign to <b>{cat['emoji']} {cat['name']}</b>:",parse_mode="HTML",reply_markup=InlineKeyboardMarkup(kb))

async def adm_togglecat(u,ctx):
    q=u.callback_query; p=q.data.split("_"); pid,cid=int(p[1]),int(p[2])
    row=q1("SELECT category_id FROM products WHERE id=?",(pid,))
    if row: qx("UPDATE products SET category_id=? WHERE id=?",(0 if row["category_id"]==cid else cid,pid))
    u.callback_query.data=f"cat_assign_{cid}"; await adm_cat_assign(u,ctx)

async def adm_rmprod_list(u,ctx):
    q=u.callback_query; rows=qa("SELECT id,name FROM products ORDER BY id")
    if not rows: await safe_edit(q,"No products.",reply_markup=back_kb()); return
    await safe_edit(q,"🗑️ Remove which product?",reply_markup=InlineKeyboardMarkup([[IB(f"🗑️ {r['name']}",f"rmprod_{r['id']}")] for r in rows]+[[IB("⬅️ Back","menu")]]))

async def adm_rmprod_confirm(u,ctx):
    q=u.callback_query; pid=int(q.data.split("_")[1]); r=q1("SELECT name FROM products WHERE id=?",(pid,))
    if r: await safe_edit(q,f"🗑️ Delete <b>{hl.escape(r['name'])}</b>? Cannot be undone.",parse_mode="HTML",reply_markup=KM([IB("✅ Yes Delete",f"rmprod_yes_{pid}"),IB("❌ No","menu")]))

async def adm_rmprod_do(u,ctx):
    q=u.callback_query; qx("DELETE FROM products WHERE id=?",(int(q.data.split("_")[2]),)); await safe_edit(q,"✅ Deleted.",reply_markup=back_kb())

async def adm_editdesc_list(u,ctx):
    q=u.callback_query; rows=qa("SELECT id,name FROM products ORDER BY id")
    if not rows: await safe_edit(q,"No products.",reply_markup=back_kb()); return
    await safe_edit(q,"✏️ Edit description for:",reply_markup=InlineKeyboardMarkup([[IB(f"✏️ {r['name']}",f"editdesc_{r['id']}")] for r in rows]+[[IB("⬅️ Back","menu")]]))

async def adm_editdesc_start(u,ctx):
    q=u.callback_query; pid=int(q.data.split("_")[1]); ctx.user_data.update({"edit_pid":pid,"wf":"edit_desc"})
    r=q1("SELECT name,description FROM products WHERE id=?",(pid,))
    await safe_edit(q,f"✏️ <b>Edit: {hl.escape(r['name'])}</b>\n\nCurrent: {hl.escape(r['description'] or '—')}\n\nSend new description:",parse_mode="HTML",reply_markup=cancel_kb())

async def adm_hideprod_list(u,ctx):
    q=u.callback_query; rows=qa("SELECT id,name,hidden FROM products ORDER BY id")
    if not rows: await safe_edit(q,"No products.",reply_markup=back_kb()); return
    await safe_edit(q,"👁️ <b>Hide / Show Products</b>",parse_mode="HTML",reply_markup=InlineKeyboardMarkup([[IB(f"{'👁️ Show' if r['hidden'] else '🙈 Hide'} {r['name']}",f"togglehide_{r['id']}")] for r in rows]+[[IB("⬅️ Back","menu")]]))

async def adm_togglehide(u,ctx):
    q=u.callback_query; pid=int(q.data.split("_")[1])
    row=q1("SELECT name,hidden FROM products WHERE id=?",(pid,))
    if not row: await q.answer(); return
    qx("UPDATE products SET hidden=? WHERE id=?",(0 if row["hidden"] else 1,pid))
    await q.answer(f"{'Shown' if row['hidden'] else 'Hidden'}: {row['name']}",show_alert=True)
    await adm_hideprod_list(u,ctx)

async def adm_list_tiers(u,ctx):
    q=u.callback_query; rows=qa("SELECT id,name FROM products ORDER BY id")
    if not rows: await safe_edit(q,"No products.",reply_markup=back_kb()); return
    await safe_edit(q,"⚖️ Edit tiers for:",reply_markup=InlineKeyboardMarkup([[IB(f"⚖️ {r['name']}",f"edtier_{r['id']}")] for r in rows]+[[IB("⬅️ Back","menu")]]))

async def adm_show_tiers(u,ctx):
    q=u.callback_query; pid=int(q.data.split("_")[1]); ctx.user_data.update({"tpid":pid,"wf":"edit_tiers"})
    r=q1("SELECT name,tiers FROM products WHERE id=?",(pid,)); tiers=json.loads(r["tiers"]) if r.get("tiers") else TIERS[:]
    await q.message.reply_text(f"⚖️ <b>{hl.escape(r['name'])}</b>\n\n"+"".join(ft(t)+"\n" for t in tiers)+"\nSend new tiers (qty,price per line) or /cancel",parse_mode="HTML")

async def cmd_reply(u:Update,ctx:ContextTypes.DEFAULT_TYPE):
    if not is_admin(u.effective_user.id): return
    if not ctx.args or len(ctx.args)<2: await u.message.reply_text("Usage: /reply <id> <text>"); return
    try: mid=int(ctx.args[0])
    except: await u.message.reply_text("⚠️ Invalid ID."); return
    msg=" ".join(ctx.args[1:]); row=q1("SELECT user_id,username,message FROM messages WHERE id=?",(mid,))
    if not row: await u.message.reply_text("❌ Not found."); return
    qx("UPDATE messages SET reply=? WHERE id=?",(msg,mid))
    try: await ctx.bot.send_message(row["user_id"],f"💬 <b>Reply from Donny's Shop</b>\n\n<i>Your msg:</i> {hl.escape(row['message'])}\n\n✉️ {hl.escape(msg)}",parse_mode="HTML",reply_markup=menu()); await u.message.reply_text(f"✅ Replied to @{row['username']}.")
    except Exception as e: await u.message.reply_text(f"❌ {e}")
async def cmd_order(u:Update,ctx:ContextTypes.DEFAULT_TYPE):
    if not is_admin(u.effective_user.id): return
    if not ctx.args: await u.message.reply_text("Usage: /order <id>"); return
    oid=ctx.args[0]; row=q1("SELECT * FROM orders WHERE id=?",(oid,))
    if not row: await u.message.reply_text("❌ Not found."); return
    sl=SHIP.get(row["ship"],{}).get("label",row["ship"]); em={"Pending":"⏳","Paid":"✅","Dispatched":"🚚","Rejected":"❌"}
    note=q1("SELECT note FROM order_notes WHERE order_id=?",(oid,)); ntxt=f"\n📝 {hl.escape(note['note'])}" if note else ""
    txt=f"🔖 <b>{oid}</b> {em.get(row['status'],'')}\n👤 {hl.escape(row['cust_name'])}\n🏠 {hl.escape(row['address'])}\n🚚 {sl} · 💷 £{row['gbp']:.2f}{f' | {row[chr(108)+chr(116)+chr(99)]} LTC' if row.get('ltc') else ''}\n{hl.escape(row['summary'])}{ntxt}"
    kb=([[IB("✅ Confirm",f"adm_ok_{oid}"),IB("❌ Reject",f"adm_no_{oid}")]] if row["status"]=="Pending" else [])+([[IB("🚚 Dispatch",f"adm_go_{oid}")]] if row["status"]=="Paid" and row["ship"]!="drop" else [])+([[IB("💬 Drop Chat",f"dch_{oid}")]] if row["ship"]=="drop" else [])+[[IB("📝 Note",f"adm_note_{oid}")]]
    await u.message.reply_text(txt,parse_mode="HTML",reply_markup=InlineKeyboardMarkup(kb))
async def cmd_customer(u:Update,ctx:ContextTypes.DEFAULT_TYPE):
    if not is_admin(u.effective_user.id): return
    if not ctx.args: await u.message.reply_text("Usage: /customer @username or user_id"); return
    arg=ctx.args[0].lstrip("@")
    try: cid=int(arg); row=q1("SELECT user_id,username FROM users WHERE user_id=?",(cid,))
    except: row=q1("SELECT user_id,username FROM users WHERE username=?",(arg,))
    if not row: await u.message.reply_text("❌ Not found."); return
    cid=row["user_id"]; orders=qa("SELECT id,gbp,status,summary FROM orders WHERE user_id=? ORDER BY rowid DESC LIMIT 10",(cid,))
    spent=sum(o["gbp"] for o in orders if o["status"] in ("Paid","Dispatched")); lo=get_loyalty(cid)
    await u.message.reply_text((f"👤 @{hl.escape(row['username'] or str(cid))} (<code>{cid}</code>)\n━━━━━━━━━━━━━━━━━━━━\n💷 £{spent:.2f} · {len(orders)} orders · ⭐ {lo['points']} pts · 💳 £{lo['credit']:.2f}\n\n"+"".join(f"• {o['id']} — {o['status']} — £{o['gbp']:.2f} — {hl.escape(o['summary'][:40])}\n" for o in orders))[:4000],parse_mode="HTML")
async def cmd_myorder(u:Update,ctx:ContextTypes.DEFAULT_TYPE):
    uid=u.effective_user.id
    if not is_known(uid) and not is_admin(uid): await u.message.reply_text("Please /start first."); return
    if not ctx.args: await u.message.reply_text("Usage: /myorder <id>"); return
    oid=ctx.args[0]; row=q1("SELECT * FROM orders WHERE id=? AND user_id=?",(oid,uid))
    if not row: await u.message.reply_text("❌ Not found."); return
    sl=SHIP.get(row["ship"],{}).get("label",row["ship"]); em={"Pending":"🕐","Paid":"✅","Dispatched":"🚚","Rejected":"❌"}
    await u.message.reply_text(f"🧾 <b>Order {oid}</b>\n━━━━━━━━━━━━━━━━━━━━\n{em.get(row['status'],'')} {row['status']}\n👤 {hl.escape(row['cust_name'])}\n🏠 {hl.escape(row['address'])}\n🚚 {sl}\n{hl.escape(row['summary'])}\n💰 £{row['gbp']:.2f}",parse_mode="HTML")

async def cmd_addproduct(u:Update,ctx:ContextTypes.DEFAULT_TYPE):
    if not is_admin(u.effective_user.id): return
    ctx.user_data["wf"]="add_photo"; await u.message.reply_text("📸 Send product photo:")
async def cmd_cancel(u:Update,ctx:ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear(); await u.message.reply_text("🚫 Cancelled.",reply_markup=menu())

async def on_message(u:Update,ctx:ContextTypes.DEFAULT_TYPE):
    uid=u.effective_user.id; txt=(u.message.text or "").strip()
    qx("INSERT OR IGNORE INTO users(user_id,username) VALUES(?,?)",(uid,u.effective_user.username or ""))
    wf=ctx.user_data.get("wf")
    if wf=="co_name":
        ctx.user_data.update({"co_name":txt,"wf":None}); t,_=co_summary(ctx.user_data,uid); await u.message.reply_text(t,parse_mode="HTML",reply_markup=co_kb(ctx.user_data))
    elif wf=="co_addr":
        ctx.user_data.update({"co_addr":txt,"wf":None}); t,_=co_summary(ctx.user_data,uid); await u.message.reply_text(t,parse_mode="HTML",reply_markup=co_kb(ctx.user_data))
    elif wf=="co_disc":
        pct=gdisc(txt)
        if pct: ctx.user_data.update({"co_disc_code":txt.upper(),"co_disc_pct":pct,"wf":None}); await u.message.reply_text(f"✅ Code <b>{txt.upper()}</b> applied — {int(pct*100)}% off!",parse_mode="HTML")
        else: ctx.user_data.update({"co_disc_code":None,"co_disc_pct":0,"wf":None}); await u.message.reply_text("❌ Invalid or expired code.")
        t,_=co_summary(ctx.user_data,uid); await u.message.reply_text(t,parse_mode="HTML",reply_markup=co_kb(ctx.user_data))
    elif wf=="contact":
        uname=u.effective_user.username or str(uid); mid=qxi("INSERT INTO messages(user_id,username,message) VALUES(?,?,?)",(uid,uname,txt))
        await ctx.bot.send_message(ADMIN_ID,f"💬 @{uname} #{mid}\n{hl.escape(txt)}\n/reply {mid}",parse_mode="HTML"); await u.message.reply_text("✅ Message sent!",reply_markup=menu()); ctx.user_data["wf"]=None
    elif wf=="ann_title":
        ctx.user_data.update({"ann_title":txt,"wf":"ann_photo"}); await u.message.reply_text("📸 Send photo or type <b>skip</b>:",parse_mode="HTML")
    elif wf=="ann_photo":
        if txt.lower()=="skip": ctx.user_data["wf"]="ann_body"; await u.message.reply_text("✏️ Enter announcement body:")
        else: await u.message.reply_text("📸 Send photo or type <b>skip</b>:",parse_mode="HTML")
    elif wf=="ann_body":
        title=ctx.user_data.pop("ann_title",""); photo=ctx.user_data.pop("ann_photo","")
        qx("INSERT INTO announcements(title,body,photo) VALUES(?,?,?)",(title,txt,photo))
        uids=qa("SELECT user_id FROM users"); sent=0
        for r in uids:
            try:
                fn=ctx.bot.send_photo(r["user_id"],photo,caption=f"📢 <b>{hl.escape(title)}</b>\n\n{hl.escape(txt)}",parse_mode="HTML") if photo else ctx.bot.send_message(r["user_id"],f"📢 <b>{hl.escape(title)}</b>\n\n{hl.escape(txt)}",parse_mode="HTML")
                await fn; sent+=1
            except: pass
        await u.message.reply_text(f"✅ Broadcast to {sent} users!"); ctx.user_data["wf"]=None
    elif wf=="review_text":
        oid=ctx.user_data.get("rev_order"); s=ctx.user_data.get("rev_stars",5); qx("INSERT OR REPLACE INTO reviews(order_id,user_id,stars,text) VALUES(?,?,?,?)",(oid,uid,s,txt))
        await u.message.reply_text(f"✅ {STARS.get(s,'')} Thanks! 🙏",reply_markup=menu()); ctx.user_data["wf"]=None
    elif wf=="add_title":
        ctx.user_data.update({"nm":txt,"wf":"add_desc"}); await u.message.reply_text("📄 Enter product description:")
    elif wf=="add_desc":
        d=ctx.user_data; d["wf"]=None; qx("INSERT INTO products(name,description,photo,hidden,tiers) VALUES(?,?,?,0,?)",(d["nm"],txt,d.get("ph",""),json.dumps(TIERS)))
        await u.message.reply_text(f"✅ <b>{hl.escape(d['nm'])}</b> added!",parse_mode="HTML",reply_markup=menu())
    elif wf=="edit_desc":
        qx("UPDATE products SET description=? WHERE id=?",(txt,ctx.user_data.get("edit_pid"))); await u.message.reply_text("✅ Updated!",reply_markup=menu()); ctx.user_data["wf"]=None
    elif wf=="edit_tiers":
        pid=ctx.user_data.get("tpid"); new=[]; errs=[]
        for i,line in enumerate(txt.splitlines(),1):
            p=line.strip().split(",")
            try: assert len(p)==2; q2,pr=float(p[0]),float(p[1]); assert q2>0 and pr>0; new.append({"qty":q2,"price":pr})
            except: errs.append(f"Line {i}: invalid")
        if errs or not new: await u.message.reply_text("❌ "+("\n".join(errs or ["No valid tiers."]))+"\n\nRetry or /cancel"); return
        new.sort(key=lambda t:t["qty"]); qx("UPDATE products SET tiers=? WHERE id=?",(json.dumps(new),pid))
        await u.message.reply_text("✅ Tiers:\n"+"".join(ft(t)+"\n" for t in new),parse_mode="HTML",reply_markup=menu()); ctx.user_data["wf"]=None
    elif wf=="drop_msg_user":
        oid=ctx.user_data.get("dc_oid"); uname=u.effective_user.username or str(uid)
        qx("INSERT INTO drop_chats(order_id,user_id,sender,message) VALUES(?,?,?,?)",(oid,uid,"user",txt))
        await ctx.bot.send_message(ADMIN_ID,f"💬 Drop Chat {oid}\n@{uname}: {hl.escape(txt)}",parse_mode="HTML",reply_markup=dc_admin_kb(oid))
        await u.message.reply_text(f"✅ Sent!\n\n💬 <b>Drop Chat — {oid}</b>\n━━━━━━━━━━━━━━━━━━━━\n\n{fmt_chat(oid)}",parse_mode="HTML",reply_markup=dc_user_kb(oid,gs(f"cc_{oid}","0")=="1")); ctx.user_data["wf"]=None
    elif wf=="drop_msg_admin":
        oid=ctx.user_data.get("dc_oid"); row=q1("SELECT user_id FROM orders WHERE id=?",(oid,))
        if not row: await u.message.reply_text("❌ Not found."); ctx.user_data["wf"]=None; return
        qx("INSERT INTO drop_chats(order_id,user_id,sender,message) VALUES(?,?,?,?)",(oid,row["user_id"],"admin",txt))
        try: await ctx.bot.send_message(row["user_id"],f"🏪 <b>Donny's Shop</b>\n━━━━━━━━━━━━━━━━━━━━\n\n{fmt_chat(oid)}",parse_mode="HTML",reply_markup=dc_user_kb(oid,gs(f"cc_{oid}","0")=="1"))
        except: pass
        await u.message.reply_text("✅ Sent.",reply_markup=menu()); ctx.user_data["wf"]=None
    elif wf=="disc_code":
        parts=txt.upper().split(",")
        if len(parts) not in (2,3): await u.message.reply_text("⚠️ Format: CODE,PCT or CODE,PCT,HOURS"); return
        try: dc=parts[0].strip(); pct=float(parts[1].strip())/100; assert 0<pct<=1
        except: await u.message.reply_text("⚠️ Invalid. E.g. SAVE20,20"); return
        exp=(datetime.now()+timedelta(hours=float(parts[2].strip()))).isoformat() if len(parts)==3 else None
        qx("INSERT OR REPLACE INTO discount_codes(code,pct,active,expires) VALUES(?,?,1,?)",(dc,pct,exp))
        await u.message.reply_text(f"✅ <code>{dc}</code> {int(pct*100)}% off{f' · {parts[2]}h' if exp else ''} added!",parse_mode="HTML",reply_markup=menu()); ctx.user_data["wf"]=None
    elif wf=="new_cat":
        parts=txt.split(None,1); emoji,name=(parts[0],parts[1]) if len(parts)==2 and len(parts[0])<=2 else ("🌿",parts[0]) if len(parts)==1 else (None,None)
        if not name: await u.message.reply_text("⚠️ Format: 🍃 Category Name"); return
        qxi("INSERT INTO categories(name,emoji) VALUES(?,?)",(name,emoji)); await u.message.reply_text(f"✅ {emoji} {hl.escape(name)} created!",parse_mode="HTML",reply_markup=menu()); ctx.user_data["wf"]=None
    elif wf=="order_note":
        oid=ctx.user_data.get("note_oid"); qx("INSERT OR REPLACE INTO order_notes(order_id,note) VALUES(?,?)",(oid,txt)); await u.message.reply_text("✅ Note saved.",reply_markup=menu()); ctx.user_data["wf"]=None
    elif wf=="edit_home":
        if not is_admin(uid): ctx.user_data["wf"]=None; return
        val="" if txt.lower()=="clear" else txt; ss("home_extra",val); await u.message.reply_text("✅ Cleared." if not val else f"✅ Updated: <i>{hl.escape(val)}</i>",parse_mode="HTML",reply_markup=menu()); ctx.user_data["wf"]=None
    elif wf=="add_admin":
        if not is_admin(uid): ctx.user_data["wf"]=None; return
        try: new_id=int(txt.strip())
        except: await u.message.reply_text("⚠️ Numeric user_id only (use @userinfobot)."); return
        if q1("SELECT 1 FROM admins WHERE user_id=?",(new_id,)): await u.message.reply_text("⚠️ Already an admin."); ctx.user_data["wf"]=None; return
        qx("INSERT OR IGNORE INTO admins(user_id,username) VALUES(?,?)",(new_id,str(new_id)))
        try: info=await ctx.bot.get_chat(new_id); un=info.username or info.first_name or str(new_id); qx("UPDATE admins SET username=? WHERE user_id=?",(un,new_id))
        except: un=str(new_id)
        await u.message.reply_text(f"✅ {hl.escape(un)} added.",parse_mode="HTML",reply_markup=menu()); ctx.user_data["wf"]=None
    else:
        await u.message.reply_text(f"🌿 <b>Donny's Shop</b>\n\n{open_badge()}\n\n📦 Tracked · 📍 Local Drop · 🔒 Trusted\n\n👇 Tap below to get started.",parse_mode="HTML",reply_markup=menu())

async def on_photo(u:Update,ctx:ContextTypes.DEFAULT_TYPE):
    uid=u.effective_user.id; wf=ctx.user_data.get("wf"); ph=u.message.photo[-1].file_id
    if not is_known(uid): qx("INSERT OR IGNORE INTO users(user_id,username) VALUES(?,?)",(uid,u.effective_user.username or ""))
    if wf=="add_photo": ctx.user_data.update({"ph":ph,"wf":"add_title"}); await u.message.reply_text("📝 Enter the product title:")
    elif wf=="ann_photo": ctx.user_data.update({"ann_photo":ph,"wf":"ann_body"}); await u.message.reply_text("✏️ Now enter the announcement body:")

async def review_reminder_job(ctx:ContextTypes.DEFAULT_TYPE):
    now=datetime.now(); t24=(now-timedelta(hours=24)).isoformat(); t48=(now-timedelta(hours=48)).isoformat()
    for r in qa("SELECT order_id,user_id FROM review_reminders WHERE dispatched<? AND dispatched>?",(t24,t48)):
        qx("DELETE FROM review_reminders WHERE order_id=?",(r["order_id"],))
        if q1("SELECT 1 FROM reviews WHERE order_id=?",(r["order_id"],)): continue
        try: await ctx.bot.send_message(r["user_id"],f"⭐ How was your order <code>{r['order_id']}</code>? Leave a quick review!",parse_mode="HTML",reply_markup=KM([IB("⭐ Review",f"review_{r['order_id']}")]))
        except: pass

async def router(u:Update,ctx:ContextTypes.DEFAULT_TYPE):
    q=u.callback_query; d=q.data; uid=q.from_user.id
    if not is_known(uid) and not is_admin(uid): await q.answer("Please /start the bot first.",show_alert=True); return
    if d.startswith("pick_"):       await pick_weight(u,ctx); return
    if d.startswith("togglehide_"): await adm_togglehide(u,ctx); return
    if d=="noop":                   await q.answer(); return
    await q.answer()
    if   d=="menu":                  await safe_edit(q,f"🌿 <b>Donny's Shop</b>\n━━━━━━━━━━━━━━━━━━━━\n\n{open_badge()}\n🕙 <b>Mon–Sat · Orders close 11am</b>\n\n📦 Tracked · 📍 Local Drop · 🔒 Trusted\n\n👇 <b>What are you looking for?</b>",parse_mode="HTML",reply_markup=menu())
    elif d=="shop":                  await show_shop(u,ctx)
    elif d.startswith("cat_assign_"):await adm_cat_assign(u,ctx)
    elif d.startswith("togglecat_"): await adm_togglecat(u,ctx)
    elif d.startswith("cat_"):       await show_category(u,ctx)
    elif d.startswith("prod_"):      await show_product(u,ctx)
    elif d=="basket":                await view_basket(u,ctx)
    elif d=="orders":                await view_orders(u,ctx)
    elif d.startswith("reviews_"):   await show_reviews(u,ctx)
    elif d=="news":                  await show_news(u,ctx)
    elif d=="contact":               await contact_start(u,ctx)
    elif d.startswith("rm_"):        await remove_item(u,ctx)
    elif d.startswith("paid_"):      await user_paid(u,ctx)
    elif d.startswith("review_"):    await review_start(u,ctx)
    elif d.startswith("stars_"):     await pick_stars(u,ctx)
    elif d=="loyalty":               await show_loyalty(u,ctx)
    elif d=="my_ref":                await show_my_ref(u,ctx)
    elif d=="checkout":              await checkout_start(u,ctx)
    elif d=="co_name":               await co_name_start(u,ctx)
    elif d=="co_addr":               await co_addr_start(u,ctx)
    elif d=="co_addr_skip":          await co_addr_skip(u,ctx)
    elif d=="co_disc":               await co_disc_start(u,ctx)
    elif d.startswith("co_ship_"):   await co_ship_cb(u,ctx)
    elif d=="co_refresh":            await co_refresh_cb(u,ctx)
    elif d=="co_confirm":            await co_confirm(u,ctx)
    elif d.startswith("adm_ok_"):    await adm_confirm(u,ctx)
    elif d.startswith("adm_no_"):    await adm_reject(u,ctx)
    elif d.startswith("adm_go_"):    await adm_dispatch(u,ctx)
    elif d=="adm_msgs":              await adm_msgs(u,ctx)
    elif d=="adm_tiers":             await adm_list_tiers(u,ctx)
    elif d=="adm_rmprod":            await adm_rmprod_list(u,ctx)
    elif d.startswith("rmprod_yes_"):await adm_rmprod_do(u,ctx)
    elif d.startswith("rmprod_"):    await adm_rmprod_confirm(u,ctx)
    elif d=="adm_editdesc":          await adm_editdesc_list(u,ctx)
    elif d.startswith("editdesc_"):  await adm_editdesc_start(u,ctx)
    elif d=="adm_hideprod":          await adm_hideprod_list(u,ctx)
    elif d=="adm_cats":              await adm_cats(u,ctx)
    elif d=="adm_newcat":            await adm_newcat(u,ctx)
    elif d=="adm_delcat":            await adm_delcat_list(u,ctx)
    elif d.startswith("delcat_"):    await adm_delcat_do(u,ctx)
    elif d=="adm_drops":             await adm_drop_overview(u,ctx)
    elif d.startswith("adm_rev_"):   await adm_rev_cb(u,ctx)
    elif d=="adm_discounts":         await adm_discounts(u,ctx)
    elif d.startswith("toggledisc_"):await adm_toggledisc(u,ctx)
    elif d=="adm_adddisc":           await adm_adddisc_start(u,ctx)
    elif d=="adm_announce":          await ann_start(u,ctx)
    elif d=="adm_addprod":
        if is_admin(uid): ctx.user_data["wf"]="add_photo"; await q.message.reply_text("📸 Send the product photo:")
    elif d.startswith("edtier_"):    await adm_show_tiers(u,ctx)
    elif d.startswith("dcv_"):       await dropchat_view(u,ctx)
    elif d.startswith("dch_"):       await dropchat_history(u,ctx)
    elif d.startswith("dcc_"):       await dropchat_close(u,ctx)
    elif d.startswith("dcac_"):      await dropchat_close(u,ctx)
    elif d.startswith("dco_"):       await dropchat_open(u,ctx)
    elif d.startswith("dcm_"):       await dropchat_msg_start(u,ctx)
    elif d.startswith("dcr_"):       await dropchat_reply_start(u,ctx)
    elif d.startswith("adm_note_"):  await adm_note_start(u,ctx)
    elif d=="adm_edit_home":         await adm_edit_home(u,ctx)
    elif d=="adm_admins":            await adm_admins(u,ctx)
    elif d=="adm_addadmin":          await adm_addadmin_start(u,ctx)
    elif d.startswith("adm_rmadmin_"):await adm_rmadmin(u,ctx)


class _Ping(BaseHTTPRequestHandler):
    def do_GET(self): self.send_response(200); self.end_headers(); self.wfile.write(b"ok")
    def log_message(self,*a): pass
def main():
    Thread(target=lambda:HTTPServer(("0.0.0.0",8080),_Ping).serve_forever(),daemon=True).start()
    if not TOKEN: raise RuntimeError("❌ TOKEN not set — add it to Replit Secrets")
    init_db(); app=ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler(["start","Start"],cmd_start))
    for cmd,fn in [("admin",cmd_admin),("reply",cmd_reply),("order",cmd_order),("customer",cmd_customer),("myorder",cmd_myorder),("addproduct",cmd_addproduct),("cancel",cmd_cancel)]:
        app.add_handler(CommandHandler(cmd,fn))
    app.add_handler(CallbackQueryHandler(router))
    app.add_handler(MessageHandler(filters.PHOTO,on_photo))
    app.add_handler(MessageHandler(filters.TEXT&~filters.COMMAND,on_message))
    try: app.job_queue.run_repeating(review_reminder_job,interval=3600,first=300)
    except Exception as e: print(f"⚠️ Job queue not available: {e} — install with pip install python-telegram-bot[job-queue]")
    print("🚀 Donny's Shop — Running"); app.run_polling(drop_pending_updates=True)
if __name__=="__main__":
    main()
