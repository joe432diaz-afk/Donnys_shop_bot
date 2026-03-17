# -*- coding: utf-8 -*-
# PhiVara Network — Multi-Vendor Telegram Bot — v3.0 POWER EDITION
# 32-Feature Upgrade
import os,json,logging,requests,sqlite3,html as hl,re
from threading import Thread
from http.server import HTTPServer,BaseHTTPRequestHandler
from uuid import uuid4
from datetime import datetime,timedelta
from telegram import Update,InlineKeyboardMarkup,InlineKeyboardButton as _IB
from telegram.ext import ApplicationBuilder,CommandHandler,CallbackQueryHandler,MessageHandler,ContextTypes,filters

def IB(t,c): return _IB(text=t,callback_data=c)
TOKEN=os.getenv("TOKEN"); ADMIN_ID=7773622161; CHANNEL_ID=-1003833257976
DB_DIR="/app/data"; DB=f"{DB_DIR}/shop.db"; os.makedirs(DB_DIR,exist_ok=True)
SHIP={"tracked24":{"label":"📦 Tracked24","price":5.0,"ltc":True},"drop":{"label":"📍 Local Drop","price":0.0,"ltc":False}}
TIERS=[{"qty":1,"price":10.0},{"qty":3.5,"price":35.0},{"qty":7,"price":60.0},{"qty":14,"price":110.0},{"qty":28,"price":200.0},{"qty":56,"price":380.0}]
STARS={1:"⭐",2:"⭐⭐",3:"⭐⭐⭐",4:"⭐⭐⭐⭐",5:"⭐⭐⭐⭐⭐"}; RPP=5
VIP_TIERS=[("🥉 Bronze",0),("🥈 Silver",150),("🥇 Gold",500),("💎 Diamond",1000)]
logging.basicConfig(level=logging.WARNING)

def db(): c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; return c
def q1(s,p=()):
    c=db(); r=c.execute(s,p).fetchone(); c.close(); return dict(r) if r else None
def qa(s,p=()):
    c=db(); r=c.execute(s,p).fetchall(); c.close(); return [dict(x) for x in r]
def qx(s,p=()):
    c=db(); c.execute(s,p); c.commit(); c.close()
def qxi(s,p=()):
    c=db(); cur=c.execute(s,p); r=cur.lastrowid; c.commit(); c.close(); return r
def gs(k,d=""): r=q1("SELECT value FROM settings WHERE key=?",(k,)); return r["value"] if r else d
def ss(k,v): qx("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)",(k,v))

def init_db():
    c=db(); cur=c.cursor()
    cur.executescript("""
    CREATE TABLE IF NOT EXISTS users(user_id INTEGER PRIMARY KEY,username TEXT,joined DATETIME DEFAULT CURRENT_TIMESTAMP,banned INTEGER DEFAULT 0,welcome_sent INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);
    CREATE TABLE IF NOT EXISTS admins(user_id INTEGER PRIMARY KEY,username TEXT);
    CREATE TABLE IF NOT EXISTS vendors(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,emoji TEXT DEFAULT '🏪',description TEXT DEFAULT '',ltc_addr TEXT,commission_pct REAL DEFAULT 10,admin_user_id INTEGER,active INTEGER DEFAULT 1,min_order REAL DEFAULT 0,est_delivery TEXT DEFAULT '1-2 days');
    CREATE TABLE IF NOT EXISTS products(id INTEGER PRIMARY KEY AUTOINCREMENT,vendor_id INTEGER DEFAULT 1,name TEXT,description TEXT,photo TEXT,hidden INTEGER DEFAULT 0,tiers TEXT DEFAULT '[]',category_id INTEGER DEFAULT 0,stock INTEGER DEFAULT -1,featured INTEGER DEFAULT 0,views INTEGER DEFAULT 0,flash_price REAL DEFAULT 0,flash_until TEXT DEFAULT '');
    CREATE TABLE IF NOT EXISTS categories(id INTEGER PRIMARY KEY AUTOINCREMENT,vendor_id INTEGER DEFAULT 1,name TEXT,emoji TEXT DEFAULT '🌿');
    CREATE TABLE IF NOT EXISTS cart(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,product_id INTEGER,vendor_id INTEGER DEFAULT 1,qty REAL,price REAL,created_at DATETIME DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS orders(id TEXT PRIMARY KEY,user_id INTEGER,vendor_id INTEGER DEFAULT 1,cust_name TEXT,address TEXT,summary TEXT DEFAULT '',gbp REAL,vendor_gbp REAL DEFAULT 0,platform_gbp REAL DEFAULT 0,ltc REAL DEFAULT 0,ltc_addr TEXT DEFAULT '',ltc_rate REAL DEFAULT 0,status TEXT DEFAULT 'Pending',ship TEXT DEFAULT 'tracked24',created_at DATETIME DEFAULT CURRENT_TIMESTAMP,paid_at TEXT DEFAULT '',dispatched_at TEXT DEFAULT '',cancelled_at TEXT DEFAULT '',est_delivery TEXT DEFAULT '');
    CREATE TABLE IF NOT EXISTS order_notes(order_id TEXT PRIMARY KEY,note TEXT);
    CREATE TABLE IF NOT EXISTS drop_chats(id INTEGER PRIMARY KEY AUTOINCREMENT,order_id TEXT,user_id INTEGER,sender TEXT,message TEXT,created_at DATETIME DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,username TEXT,vendor_id INTEGER DEFAULT 1,message TEXT,reply TEXT,created_at DATETIME DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS reviews(order_id TEXT PRIMARY KEY,user_id INTEGER,vendor_id INTEGER DEFAULT 1,stars INTEGER,text TEXT,created_at DATETIME DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS announcements(id INTEGER PRIMARY KEY AUTOINCREMENT,vendor_id INTEGER DEFAULT 0,title TEXT,body TEXT,photo TEXT DEFAULT '',send_at TEXT DEFAULT '',created_at DATETIME DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS discount_codes(code TEXT PRIMARY KEY,vendor_id INTEGER DEFAULT 1,pct REAL,active INTEGER DEFAULT 1,expires TEXT,uses_left INTEGER DEFAULT -1);
    CREATE TABLE IF NOT EXISTS loyalty(user_id INTEGER PRIMARY KEY,points INTEGER DEFAULT 0,credit REAL DEFAULT 0,lifetime INTEGER DEFAULT 0,total_spent REAL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS referrals(code TEXT PRIMARY KEY,owner_id INTEGER,count INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS review_reminders(order_id TEXT PRIMARY KEY,user_id INTEGER,dispatched DATETIME);
    CREATE TABLE IF NOT EXISTS customer_notes(user_id INTEGER PRIMARY KEY,note TEXT);
    CREATE TABLE IF NOT EXISTS wishlist(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,product_id INTEGER,added DATETIME DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS saved_addresses(user_id INTEGER PRIMARY KEY,address TEXT);
    CREATE TABLE IF NOT EXISTS payouts(id INTEGER PRIMARY KEY AUTOINCREMENT,vendor_id INTEGER,amount REAL,note TEXT,created_at DATETIME DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS faq(id INTEGER PRIMARY KEY AUTOINCREMENT,question TEXT,answer TEXT,vendor_id INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS payment_proofs(order_id TEXT PRIMARY KEY,file_id TEXT,submitted_at DATETIME DEFAULT CURRENT_TIMESTAMP);
    """)
    cur.execute("INSERT OR IGNORE INTO admins(user_id,username) VALUES(?,'owner')",(ADMIN_ID,))
    cur.execute("INSERT OR IGNORE INTO vendors(id,name,emoji,description,ltc_addr,commission_pct,admin_user_id,est_delivery) VALUES(1,'Donny''s Shop','🌿','Premium quality. Every time.','ltc1qv4u6vr0gzp9g4lq0g3qev939vdnwxghn5gtnfc',10,?,?)",(ADMIN_ID,"1-2 working days"))
    cur.execute("INSERT OR IGNORE INTO discount_codes(code,vendor_id,pct,active) VALUES('SAVE10',1,0.10,1)")
    c.commit(); c.close()

# ── Helpers ────────────────────────────────────────────────────────────────────
def is_admin(uid): return uid==ADMIN_ID or bool(q1("SELECT 1 FROM admins WHERE user_id=?",(uid,)))
def is_known(uid): return bool(q1("SELECT 1 FROM users WHERE user_id=?",(uid,)))
def is_banned(uid): r=q1("SELECT banned FROM users WHERE user_id=?",(uid,)); return bool(r and r.get("banned",0))
def get_vendor(uid): return q1("SELECT * FROM vendors WHERE admin_user_id=? AND active=1",(uid,))
def is_vendor_admin(uid): return not is_admin(uid) and bool(get_vendor(uid))
def get_vid(ctx,uid):
    v=get_vendor(uid)
    if v: return v["id"]
    return ctx.user_data.get("cur_vid",1)
def fq(q): return f"{int(q)}g" if q==int(q) else f"{q}g"
def ft(t,flash=0):
    ppg=round(t["price"]/t["qty"],2) if t["qty"] else t["price"]
    if flash and flash<t["price"]: return f"⚡ {fq(t['qty'])} · <s>£{t['price']:.2f}</s> <b>£{flash:.2f}</b> FLASH"
    return f"⚖️ {fq(t['qty'])} · £{t['price']:.2f} (£{ppg}/g)"
def KM(*rows): return InlineKeyboardMarkup(list(rows))
def back_kb(): return KM([IB("⬅️ Back","menu")])
def cancel_kb(): return KM([IB("❌ Cancel","menu")])

# FEATURE 1: Cached LTC price with timestamp
_ltc_cache={"price":60.0,"ts":0}
def ltc_price():
    global _ltc_cache
    if datetime.now().timestamp()-_ltc_cache["ts"]<300:
        return _ltc_cache["price"]
    try:
        p=requests.get("https://api.coingecko.com/api/v3/simple/price?ids=litecoin&vs_currencies=gbp",timeout=8).json()["litecoin"]["gbp"]
        _ltc_cache={"price":p,"ts":datetime.now().timestamp()}; return p
    except: return _ltc_cache["price"]

def is_open():
    if gs("store_closed","0")=="1": return False  # FEATURE 2: Manual close
    n=datetime.now(); return n.weekday()<6 and n.hour<11
def open_badge():
    if gs("store_closed","0")=="1": return "🔴 <b>Temporarily Closed</b> · Back soon"
    return "🟢 <b>Open</b> · Orders close 11am Mon–Sat" if is_open() else "🔴 <b>Closed</b> · Next working day"

def gdisc(code,vid=1):
    r=q1("SELECT pct,expires,uses_left FROM discount_codes WHERE code=? AND active=1 AND vendor_id=?",(code.upper(),vid))
    if not r: return None
    if r.get("expires"):
        try:
            if datetime.fromisoformat(r["expires"])<datetime.now(): qx("UPDATE discount_codes SET active=0 WHERE code=?",(code.upper(),)); return None
        except: pass
    if r.get("uses_left",- 1)==0: return None
    return r["pct"]
def use_disc(code):
    r=q1("SELECT uses_left FROM discount_codes WHERE code=?",(code.upper(),))
    if r and r.get("uses_left",-1)>0: qx("UPDATE discount_codes SET uses_left=uses_left-1 WHERE code=?",(code.upper(),))

def get_loyalty(uid): return q1("SELECT points,credit,lifetime,total_spent FROM loyalty WHERE user_id=?",(uid,)) or {"points":0,"credit":0.0,"lifetime":0,"total_spent":0.0}
def add_points(uid,gbp):
    pts=int(gbp)*2; lo=get_loyalty(uid); np=lo["points"]+pts; lf=lo["lifetime"]+pts; m=np//100; cr=m*25.0; np=np%100; ts=lo["total_spent"]+gbp
    qx("INSERT INTO loyalty(user_id,points,credit,lifetime,total_spent) VALUES(?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET points=?,credit=credit+?,lifetime=?,total_spent=?",(uid,np,cr,lf,ts,np,cr,lf,ts)); return pts,cr

# FEATURE 3: VIP tier
def get_vip(uid):
    lo=get_loyalty(uid); spent=lo.get("total_spent",0); tier="🥉 Bronze"
    for name,thresh in VIP_TIERS:
        if spent>=thresh: tier=name
    return tier

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
    return "\n\n".join(f"<b>{'👤 You' if m['sender']=='user' else '🏪 Vendor'}</b> <i>{str(m['created_at'])[:16]}</i>\n{hl.escape(m['message'])}" for m in msgs)
def purge(): c=(datetime.now()-timedelta(days=30)).isoformat(); qx("DELETE FROM drop_chats WHERE created_at<?",(c,)); qx("DELETE FROM cart WHERE created_at<?",(c,))

# FEATURE 4: Stats engine
def get_stats(vid=None):
    vf=f" AND vendor_id={vid}" if vid else ""
    base=f"WHERE status IN ('Paid','Dispatched'){vf}"
    tot=q1(f"SELECT COUNT(*) as c,COALESCE(SUM(gbp),0) as s FROM orders {base}") or {"c":0,"s":0}
    today=datetime.now().strftime("%Y-%m-%d")
    td=q1(f"SELECT COUNT(*) as c,COALESCE(SUM(gbp),0) as s FROM orders {base} AND created_at>=?",(today,)) or {"c":0,"s":0}
    week=(datetime.now()-timedelta(days=7)).isoformat()
    wk=q1(f"SELECT COUNT(*) as c,COALESCE(SUM(gbp),0) as s FROM orders {base} AND created_at>=?",(week,)) or {"c":0,"s":0}
    pending=q1(f"SELECT COUNT(*) as c FROM orders WHERE status='Pending'{vf}") or {"c":0}
    avg=q1(f"SELECT COALESCE(AVG(gbp),0) as a FROM orders {base}") or {"a":0}
    top=qa(f"SELECT summary,COUNT(*) as c FROM orders {base} GROUP BY summary ORDER BY c DESC LIMIT 5")
    users=q1("SELECT COUNT(*) as c FROM users WHERE banned=0") or {"c":0}
    return tot,td,wk,pending,avg,top,users

# FEATURE 5: Full invoice builder — fixes LTC display
def build_invoice(oid):
    o=q1("SELECT * FROM orders WHERE id=?",(oid,))
    if not o: return None,None
    v=q1("SELECT * FROM vendors WHERE id=?",(o["vendor_id"],)) or {}
    sep="━━━━━━━━━━━━━━━━━━━━"
    sl=SHIP.get(o["ship"],{}).get("label",o["ship"])
    em={"Pending":"🕐 Pending","Paid":"✅ Confirmed","Dispatched":"🚚 Dispatched","Rejected":"❌ Rejected","Cancelled":"🚫 Cancelled"}
    status=em.get(o["status"],o["status"])
    inv=(f"🧾 <b>INVOICE</b>\n"
         f"{v.get('emoji','🏪')} <b>{hl.escape(v.get('name','Vendor'))}</b> via PhiVara Network\n{sep}\n"
         f"📋 Order: <code>{oid}</code>\n"
         f"📅 {str(o['created_at'])[:16]}\n"
         f"🔖 Status: {status}\n{sep}\n"
         f"👤 {hl.escape(o['cust_name'])}\n"
         f"🏠 {hl.escape(o['address'])}\n"
         f"🚚 {sl}\n")
    if o.get("est_delivery"): inv+=f"📬 Est. delivery: {hl.escape(o['est_delivery'])}\n"
    inv+=f"{sep}\n📦 <b>Items:</b>\n{hl.escape(o['summary'])}\n{sep}\n"
    inv+=f"💷 <b>Total: £{o['gbp']:.2f}</b>\n"
    # FEATURE 5: Always show LTC payment block if applicable
    if o.get("ltc",0)>0 and o.get("ltc_addr"):
        rate=o.get("ltc_rate",0)
        inv+=(f"\n{sep}\n"
              f"💎 <b>PAYMENT DETAILS</b>\n{sep}\n"
              f"💠 Amount: <b>{o['ltc']} LTC</b>\n"
              f"💷 Value: £{o['gbp']:.2f}" +(f" (rate: £{rate:.2f}/LTC)" if rate else "")+"\n\n"
              f"📤 <b>Send to this address:</b>\n"
              f"<code>{o['ltc_addr']}</code>\n\n"
              f"⚠️ <i>Send EXACT amount shown. Different amount = delayed order.</i>")
    if o["status"]=="Paid" and o.get("paid_at"): inv+=f"\n\n✅ <i>Payment received {str(o['paid_at'])[:16]}</i>"
    if o["status"]=="Dispatched" and o.get("dispatched_at"): inv+=f"\n\n🚚 <i>Dispatched {str(o['dispatched_at'])[:16]}</i>"
    # keyboard based on status
    kb=[]
    if o["status"]=="Pending" and o.get("ltc",0)>0: kb.append([IB("✅ I Have Paid",f"paid_{oid}")])
    if o["status"]=="Pending": kb.append([IB("🚫 Cancel Order",f"cancel_order_{oid}")])
    if o["ship"]=="drop" and o["status"] in ("Pending","Paid","Dispatched"): kb.append([IB("💬 Drop Chat",f"dcv_{oid}")])
    if o["status"] in ("Paid","Dispatched"): kb.append([IB("⭐ Leave Review",f"review_{oid}")])
    kb.append([IB("📦 My Orders","orders"),IB("🏠 Menu","menu")])
    return inv,InlineKeyboardMarkup(kb)

def menu():
    ltc=ltc_price()
    return KM([IB("🏪  Browse Vendors","vendors")],
              [IB("🧺  Basket","basket"),IB("📦  My Orders","orders")],
              [IB("⭐  Reviews","reviews_0"),IB("📢  News","news")],
              [IB("🎁  Loyalty & VIP","loyalty"),IB("🔗  Refer & Earn","my_ref")],
              [IB("❤️  Wishlist","wishlist"),IB("🔍  Search","search_prompt")],
              [IB("❓  FAQ","faq_list"),IB("💬  Contact","contact")],
              [IB(f"💠 LTC: £{ltc:.2f}","ltc_rate")])

async def safe_edit(q,text,**kw):
    try: await q.edit_message_text(text,**kw)
    except:
        try: await q.message.delete()
        except: pass
        await q.message.reply_text(text,**kw)

# ── USER FLOWS ─────────────────────────────────────────────────────────────────
async def cmd_start(u:Update,ctx:ContextTypes.DEFAULT_TYPE):
    purge(); uid=u.effective_user.id
    if is_banned(uid): await u.message.reply_text("🚫 You are banned from this platform."); return
    is_new=not is_known(uid)
    qx("INSERT OR IGNORE INTO users(user_id,username) VALUES(?,?)",(uid,u.effective_user.username or ""))
    if is_new and ctx.args:
        r_=credit_ref(ctx.args[0],uid)
        if r_:
            owner_id,cnt=r_
            try: await ctx.bot.send_message(owner_id,"🎉 Free reward incoming!" if cnt%15==0 else f"🔗 +1 ref · {cnt} total · {15-(cnt%15)} more")
            except: pass
    # FEATURE 6: Welcome gift for new users
    if is_new:
        welcome_code="WELCOME15"
        qx("INSERT OR IGNORE INTO discount_codes(code,vendor_id,pct,active,uses_left) VALUES(?,1,0.15,1,1)",(welcome_code,))
        try:
            await ctx.bot.send_message(uid,f"🎁 <b>Welcome Gift!</b>\n\nHere's 15% off your first order:\n<code>{welcome_code}</code>\n\n<i>One use only — applied at checkout.</i>",parse_mode="HTML")
        except: pass
    name=hl.escape(u.effective_user.first_name or "there"); extra=gs("home_extra"); el=f"\n\n{extra}" if extra else ""
    await u.message.reply_text(
        f"🔷 <b>Welcome to PhiVara Network, {name}.</b>\n━━━━━━━━━━━━━━━━━━━━\n\n{open_badge()}\n🕙 <b>Mon–Sat · Orders close 11am</b>\n\n"
        f"Your trusted multi-vendor marketplace.{el}\n\n🏪 Verified Vendors · 🔒 Discreet · ⭐ 5-Star\n\n👇 <b>Tap Browse Vendors</b>",
        parse_mode="HTML",reply_markup=menu())

async def show_vendors(u,ctx):
    q=u.callback_query; vs=qa("SELECT * FROM vendors WHERE active=1 ORDER BY id")
    if not vs: await safe_edit(q,"🏪 No vendors yet.",reply_markup=back_kb()); return
    txt="🔷 <b>PhiVara Network</b>\n\nChoose a vendor:\n\n"+"".join(f"{v['emoji']} <b>{hl.escape(v['name'])}</b>\n<i>{hl.escape(v['description'])}</i>\n📬 {v.get('est_delivery','1-2 days')}\n\n" for v in vs)
    await safe_edit(q,txt,parse_mode="HTML",reply_markup=InlineKeyboardMarkup([[IB(f"{v['emoji']} {v['name']}",f"vend_{v['id']}")] for v in vs]+[[IB("⬅️ Back","menu")]]))

async def show_vendor(u,ctx):
    q=u.callback_query; vid=int(q.data.split("_")[1]); v=q1("SELECT * FROM vendors WHERE id=? AND active=1",(vid,))
    if not v: await safe_edit(q,"❌ Vendor not found.",reply_markup=back_kb()); return
    cats=qa("SELECT * FROM categories WHERE vendor_id=? ORDER BY id",(vid,)); kb=[]
    featured=qa("SELECT id,name FROM products WHERE hidden=0 AND vendor_id=? AND featured=1 ORDER BY id",(vid,))
    if featured: kb+=[[IB(f"⭐ {r['name']}",f"prod_{r['id']}")] for r in featured]
    if cats:
        kb+=[[IB(f"{c['emoji']} {c['name']}",f"cat_{c['id']}")] for c in cats]
        unc=qa("SELECT id,name FROM products WHERE hidden=0 AND vendor_id=? AND featured=0 AND (category_id=0 OR category_id IS NULL) ORDER BY id",(vid,))
        if unc: kb+=[[IB(f"🌿 {r['name']}",f"prod_{r['id']}")] for r in unc]
    else:
        prods=qa("SELECT id,name FROM products WHERE hidden=0 AND vendor_id=? ORDER BY featured DESC,id",(vid,))
        kb+=[[IB(f"{'⭐' if r.get('featured') else '🌿'} {r['name']}",f"prod_{r['id']}")] for r in prods] or [[IB("No products yet","noop")]]
    # FEATURE 7: Trending products
    trending=qa("SELECT id,name FROM products WHERE hidden=0 AND vendor_id=? ORDER BY views DESC LIMIT 3",(vid,))
    if trending: kb+=[[IB(f"🔥 {r['name']}",f"prod_{r['id']}")] for r in trending[:1]]
    kb+=[[IB("⬅️ Back","vendors")]]; desc=f"\n<i>{hl.escape(v['description'])}</i>" if v.get("description") else ""
    min_o=f"\n💷 Min order: £{v['min_order']:.2f}" if v.get("min_order",0)>0 else ""
    await safe_edit(q,f"{v['emoji']} <b>{hl.escape(v['name'])}</b>{desc}{min_o}",parse_mode="HTML",reply_markup=InlineKeyboardMarkup(kb))

async def show_category(u,ctx):
    q=u.callback_query; cid=int(q.data.split("_")[1]); cat=q1("SELECT * FROM categories WHERE id=?",(cid,))
    if not cat: await safe_edit(q,"❌ Not found.",reply_markup=back_kb()); return
    vid=cat.get("vendor_id",1); prods=qa("SELECT id,name,featured,flash_price,flash_until FROM products WHERE hidden=0 AND category_id=? ORDER BY featured DESC,id",(cid,))
    def plabel(r):
        if r.get("flash_price",0)>0 and r.get("flash_until","") and r["flash_until"]>datetime.now().isoformat(): return f"⚡ {r['name']}"
        return ("⭐ " if r.get("featured") else "🌿 ")+r["name"]
    kb=[[IB(plabel(r),f"prod_{r['id']}")] for r in prods]+[[IB("⬅️ Back",f"vend_{vid}")]]
    await safe_edit(q,f"{cat['emoji']} <b>{hl.escape(cat['name'])}</b>",parse_mode="HTML",reply_markup=InlineKeyboardMarkup(kb if prods else [[IB("No products here","noop")],[IB("⬅️ Back",f"vend_{vid}")]]))

async def show_product(u,ctx):
    q=u.callback_query; pid=int(q.data.split("_")[1]); row=q1("SELECT * FROM products WHERE id=? AND hidden=0",(pid,))
    if not row: await safe_edit(q,"❌ Not available.",reply_markup=back_kb()); return
    # FEATURE 7: Increment view count
    qx("UPDATE products SET views=views+1 WHERE id=?",(pid,))
    tiers=json.loads(row["tiers"]) if row.get("tiers") else TIERS[:]; vid=row.get("vendor_id",1)
    # FEATURE 8: Flash sale check
    flash=0
    if row.get("flash_price",0)>0 and row.get("flash_until","") and row["flash_until"]>datetime.now().isoformat():
        flash=row["flash_price"]; remaining=datetime.fromisoformat(row["flash_until"])-datetime.now()
        mins=int(remaining.total_seconds()//60)
    stock=row.get("stock",-1); stock_txt=""
    if stock==0: await safe_edit(q,"❌ Out of stock.",reply_markup=KM([IB("❤️ Add to Wishlist",f"wish_add_{pid}")],[IB("⬅️ Back",f"vend_{vid}")])); return
    elif 0<stock<=5: stock_txt=f"\n⚠️ <b>Only {stock} left!</b>"
    uid=q.from_user.id; in_wish=bool(q1("SELECT 1 FROM wishlist WHERE user_id=? AND product_id=?",(uid,pid)))
    btns=[IB(ft(t,flash),f"pick_{pid}_{t['qty']}_{flash if flash and flash<t['price'] else t['price']}") for t in tiers]
    kb=[btns[i:i+2] for i in range(0,len(btns),2)]
    kb+=[[IB("❤️ Remove Wishlist" if in_wish else "🤍 Add to Wishlist",f"wish_tog_{pid}")]]
    kb+=[[IB("🧺 Basket","basket"),IB("⬅️ Back",f"vend_{vid}")]]
    flash_txt=f"\n⚡ <b>FLASH SALE — {mins}min left!</b>" if flash else ""
    cap=f"{'⭐ ' if row.get('featured') else '🌿 '}<b>{hl.escape(row['name'])}</b>{flash_txt}{stock_txt}\n\n{hl.escape(row['description'])}\n\n"+"".join(ft(t,flash)+"\n" for t in tiers)
    try: await q.message.delete()
    except: pass
    if row.get("photo"): await ctx.bot.send_photo(q.message.chat_id,row["photo"],caption=cap[:1020],parse_mode="HTML",reply_markup=InlineKeyboardMarkup(kb))
    else: await q.message.reply_text(cap[:4000],parse_mode="HTML",reply_markup=InlineKeyboardMarkup(kb))

async def pick_weight(u,ctx):
    q=u.callback_query; p=q.data.split("_"); pid,qty,price=int(p[1]),float(p[2]),float(p[3])
    row=q1("SELECT name,vendor_id,stock FROM products WHERE id=? AND hidden=0",(pid,))
    if not row: await q.answer("❌ Not available.",show_alert=True); return
    if row.get("stock",-1)==0: await q.answer("❌ Out of stock.",show_alert=True); return
    qx("INSERT INTO cart(user_id,product_id,vendor_id,qty,price) VALUES(?,?,?,?,?)",(q.from_user.id,pid,row.get("vendor_id",1),qty,price))
    await q.answer(f"✅ {fq(qty)} of {row['name']} added! (£{price:.2f})",show_alert=True)

async def view_basket(u,ctx):
    q=u.callback_query; uid=q.from_user.id
    items=qa("SELECT cart.id,products.name,cart.qty,cart.price,cart.vendor_id FROM cart JOIN products ON cart.product_id=products.id WHERE cart.user_id=? ORDER BY cart.id",(uid,))
    if not items: await safe_edit(q,"🧺 Basket empty.",reply_markup=KM([IB("🏪 Browse","vendors")],[IB("⬅️ Back","menu")])); return
    total=sum(r["price"] for r in items)
    txt="🧺 <b>Basket</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"+"".join(f"• {hl.escape(r['name'])} {fq(r['qty'])} — £{r['price']:.2f}\n" for r in items)+f"\n━━━━━━━━━━━━━━━━━━━━\n💰 <b>Total: £{total:.2f}</b>"
    await safe_edit(q,txt,parse_mode="HTML",reply_markup=InlineKeyboardMarkup([[IB(f"🗑️ {r['name']} {fq(r['qty'])}",f"rm_{r['id']}")] for r in items]+[[IB("🗑️ Clear All","clear_cart"),IB("💳 Checkout","checkout")]]+[[IB("⬅️ Back","menu")]]))

async def remove_item(u,ctx): q=u.callback_query; qx("DELETE FROM cart WHERE id=? AND user_id=?",(int(q.data.split("_")[1]),q.from_user.id)); await view_basket(u,ctx)
async def clear_cart(u,ctx): q=u.callback_query; qx("DELETE FROM cart WHERE user_id=?",(q.from_user.id,)); await view_basket(u,ctx)

def co_kb(ud):
    n,a,s,dp=ud.get("co_name"),ud.get("co_addr"),ud.get("co_ship"),ud.get("co_disc_pct",0)
    al="✅ Address set" if a else ("📍 Not needed" if s=="drop" else "🏠 Enter Address")
    rows=[[IB(f"✅ {hl.escape(n)}" if n else "👤 Your Name","co_name")],[IB(al,"co_addr")],
          [IB(("✅ " if s=="tracked24" else "")+"📦 Tracked24 (+£5)","co_ship_tracked24"),IB(("✅ " if s=="drop" else "")+"📍 Local Drop (Free)","co_ship_drop")],
          [IB(f"🏷️ {ud.get('co_disc_code')} ✅" if dp else "🏷️ Discount Code","co_disc")]]
    if n and s and (a or s=="drop"): rows.append([IB("🛒 Place Order","co_confirm")])
    rows.append([IB("❌ Cancel","menu")]); return InlineKeyboardMarkup(rows)

def co_summary(ud,uid=None):
    s=ud.get("co_ship"); sub=ud.get("co_sub",0); dp=ud.get("co_disc_pct",0)
    sp=SHIP[s]["price"] if s else 0; sl=SHIP[s]["label"] if s else "—"
    disc=round(sub*dp,2); total=round(sub-disc+sp,2); addr=ud.get("co_addr") or ("Not required" if s=="drop" else "—")
    cr=get_loyalty(uid)["credit"] if uid else 0
    dl=f"🏷️ {ud.get('co_disc_code','')} -£{disc:.2f}\n" if dp else ""
    cl=f"💳 £{cr:.2f} loyalty credit available\n" if cr>0 else ""
    hint="📍 <i>Local drop.</i>" if s=="drop" else ("📦 <i>Enter address above.</i>" if s=="tracked24" else "<i>Select delivery method.</i>")
    ltc_est=round(total/ltc_price(),6); ltc_line=f"\n💠 ≈ {ltc_est} LTC" if s=="tracked24" else ""
    return f"🛒 <b>Checkout</b>\n━━━━━━━━━━━━━━━━━━━━\n👤 {hl.escape(ud.get('co_name') or '—')}\n🏠 {hl.escape(addr)}\n🚚 {sl}\n{cl}{dl}━━━━━━━━━━━━━━━━━━━━\n💰 <b>Total: £{total:.2f}</b>{ltc_line}\n\n{hint}",total

async def checkout_start(u,ctx):
    q=u.callback_query; uid=q.from_user.id
    items=qa("SELECT vendor_id,price FROM cart WHERE user_id=?",(uid,))
    if not items: await safe_edit(q,"🧺 Basket empty.",reply_markup=menu()); return
    vids=list(set(r["vendor_id"] for r in items))
    if len(vids)>1: await safe_edit(q,"⚠️ <b>Mixed vendors</b>\n\nCheckout one vendor at a time.",parse_mode="HTML",reply_markup=KM([IB("🗑️ Clear Basket","clear_cart")],[IB("⬅️ Back","basket")])); return
    vid=vids[0]; v=q1("SELECT min_order FROM vendors WHERE id=?",(vid,)); sub=round(sum(r["price"] for r in items),2)
    if v and v.get("min_order",0)>0 and sub<v["min_order"]:
        await safe_edit(q,f"⚠️ Minimum order is £{v['min_order']:.2f}\n\nYour basket: £{sub:.2f}",reply_markup=KM([IB("🛒 Keep Shopping",f"vend_{vid}")],[IB("⬅️ Back","basket")])); return
    # FEATURE 9: Autofill saved address
    saved=q1("SELECT address FROM saved_addresses WHERE user_id=?",(uid,))
    ctx.user_data.update({"co_name":None,"co_addr":saved["address"] if saved else None,"co_ship":None,"co_disc_code":None,"co_disc_pct":0,"co_sub":sub,"co_vid":vid,"wf":None})
    t,_=co_summary(ctx.user_data,uid); await safe_edit(q,t,parse_mode="HTML",reply_markup=co_kb(ctx.user_data))

async def co_name_start(u,ctx):
    q=u.callback_query; ctx.user_data["wf"]="co_name"; await safe_edit(q,"👤 Enter your full name:",reply_markup=KM([IB("❌ Cancel","co_refresh")]))
async def co_addr_start(u,ctx):
    q=u.callback_query
    if ctx.user_data.get("co_ship")=="drop":
        await safe_edit(q,"📍 No address needed.",reply_markup=KM([IB("⏭️ Skip","co_addr_skip")],[IB("❌ Cancel","co_refresh")]))
    else:
        saved=q1("SELECT address FROM saved_addresses WHERE user_id=?",(q.from_user.id,))
        kb=[]; 
        if saved: kb.append([IB(f"📌 Use saved: {saved['address'][:30]}","co_addr_saved")])
        kb+=[[IB("⏭️ Skip","co_addr_skip")],[IB("❌ Cancel","co_refresh")]]
        ctx.user_data["wf"]="co_addr"; await safe_edit(q,"🏠 Enter delivery address:",reply_markup=InlineKeyboardMarkup(kb))
async def co_addr_saved(u,ctx):
    q=u.callback_query; uid=q.from_user.id; saved=q1("SELECT address FROM saved_addresses WHERE user_id=?",(uid,))
    if saved: ctx.user_data.update({"co_addr":saved["address"],"wf":None})
    t,_=co_summary(ctx.user_data,uid); await safe_edit(q,t,parse_mode="HTML",reply_markup=co_kb(ctx.user_data))
async def co_addr_skip(u,ctx):
    q=u.callback_query; ctx.user_data.update({"co_addr":"","wf":None}); t,_=co_summary(ctx.user_data,q.from_user.id); await safe_edit(q,t,parse_mode="HTML",reply_markup=co_kb(ctx.user_data))
async def co_disc_start(u,ctx):
    q=u.callback_query; ctx.user_data["wf"]="co_disc"; vid=ctx.user_data.get("co_vid",1)
    codes=qa("SELECT code,pct FROM discount_codes WHERE active=1 AND vendor_id=?",(vid,))
    hint=", ".join(f"<code>{r['code']}</code> ({int(r['pct']*100)}% off)" for r in codes) if codes else "None active"
    await safe_edit(q,f"🏷️ Enter discount code:\n{hint}",parse_mode="HTML",reply_markup=KM([IB("❌ Cancel","co_refresh")]))
async def co_ship_cb(u,ctx):
    q=u.callback_query; ctx.user_data["co_ship"]=q.data.split("co_ship_")[1]; t,_=co_summary(ctx.user_data,q.from_user.id); await safe_edit(q,t,parse_mode="HTML",reply_markup=co_kb(ctx.user_data))
async def co_refresh_cb(u,ctx):
    q=u.callback_query; ctx.user_data["wf"]=None; t,_=co_summary(ctx.user_data,q.from_user.id); await safe_edit(q,t,parse_mode="HTML",reply_markup=co_kb(ctx.user_data))

async def co_confirm(u,ctx):
    q=u.callback_query; uid=q.from_user.id; ud=ctx.user_data
    name,addr,sk=ud.get("co_name"),ud.get("co_addr") or "",ud.get("co_ship")
    if not name or not sk: await q.answer("⚠️ Enter name and select delivery.",show_alert=True); return
    if sk=="tracked24" and not addr: await q.answer("⚠️ Enter delivery address.",show_alert=True); return
    vid=ud.get("co_vid",1); vendor=q1("SELECT * FROM vendors WHERE id=?",(vid,))
    if not vendor: await safe_edit(q,"❌ Vendor error.",reply_markup=menu()); return
    items=qa("SELECT products.name,cart.qty,cart.price,cart.product_id FROM cart JOIN products ON cart.product_id=products.id WHERE cart.user_id=? AND cart.vendor_id=?",(uid,vid))
    if not items: await safe_edit(q,"🧺 Basket empty.",reply_markup=menu()); return
    summary=", ".join(f"{r['name']} {fq(r['qty'])}" for r in items)
    sub=round(sum(r["price"] for r in items),2)
    dp=ud.get("co_disc_pct",0); sp=SHIP[sk]["price"]; needs_ltc=SHIP[sk]["ltc"]
    disc=round(sub*dp,2); gbp=round(sub-disc+sp,2)
    com=vendor.get("commission_pct",10)/100; platform_gbp=round(gbp*com,2); vendor_gbp=round(gbp-platform_gbp,2)
    ltc_rate=ltc_price(); ltc=round(gbp/ltc_rate,6) if needs_ltc else 0.0
    ltc_addr=vendor.get("ltc_addr",""); oid=str(uuid4())[:8].upper(); addr_disp=addr or "Local Drop"
    est=vendor.get("est_delivery","1-2 working days")
    qx("INSERT INTO orders(id,user_id,vendor_id,cust_name,address,summary,gbp,vendor_gbp,platform_gbp,ltc,ltc_addr,ltc_rate,status,ship,est_delivery) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
       (oid,uid,vid,name,addr_disp,summary,gbp,vendor_gbp,platform_gbp,ltc,ltc_addr,ltc_rate,"Pending",sk,est))
    qx("DELETE FROM cart WHERE user_id=? AND vendor_id=?",(uid,vid))
    if ud.get("co_disc_code"): use_disc(ud["co_disc_code"])
    # Decrement stock
    for r in items:
        p=q1("SELECT stock FROM products WHERE id=?",(r["product_id"],))
        if p and p.get("stock",-1)>0: qx("UPDATE products SET stock=stock-1 WHERE id=?",(r["product_id"],))
    # FEATURE 9: Save address
    if addr and sk=="tracked24":
        qx("INSERT OR REPLACE INTO saved_addresses(user_id,address) VALUES(?,?)",(uid,addr))
    if sk=="drop": qx("INSERT INTO drop_chats(order_id,user_id,sender,message) VALUES(?,?,?,?)",(oid,uid,"vendor",f"👋 Hi {hl.escape(name)}! Order received. Message us to arrange pickup."))
    uname=q.from_user.username or str(uid)
    sl=SHIP[sk]["label"]
    notif=(f"🛒 <b>NEW ORDER — {oid}</b>\n{vendor['emoji']} {hl.escape(vendor['name'])}\n"
           f"👤 {hl.escape(name)} (@{uname}) · 🏠 {hl.escape(addr_disp)}\n"
           f"📦 {summary} · 🚚 {sl} · 💷 £{gbp:.2f}"+(f" · 💠 {ltc} LTC" if ltc else "")+
           f"\n💰 Vendor: £{vendor_gbp:.2f} · Platform: £{platform_gbp:.2f}")
    try: await ctx.bot.send_message(CHANNEL_ID,notif,parse_mode="HTML")
    except: pass
    adm_kb=InlineKeyboardMarkup([[IB("✅ Confirm",f"adm_ok_{oid}"),IB("❌ Reject",f"adm_no_{oid}")]]+([[IB("💬 Chat",f"dch_{oid}")]] if sk=="drop" else []))
    notify_ids=[ADMIN_ID]
    if vendor.get("admin_user_id") and vendor["admin_user_id"]!=ADMIN_ID: notify_ids.append(vendor["admin_user_id"])
    for rid in notify_ids:
        try: await ctx.bot.send_message(rid,notif,parse_mode="HTML",reply_markup=adm_kb)
        except: pass
    for k in [k for k in list(ud) if k.startswith("co_")]: ud.pop(k)
    try: await q.message.delete()
    except: pass
    # FEATURE 5: Build and send full invoice immediately
    inv,ikb=build_invoice(oid)
    await q.message.reply_text(inv,parse_mode="HTML",reply_markup=ikb)

# FEATURE 10: Order cancellation by customer
async def cancel_order(u,ctx):
    q=u.callback_query; oid=q.data.split("cancel_order_")[1]; uid=q.from_user.id
    row=q1("SELECT status,created_at,vendor_id FROM orders WHERE id=? AND user_id=?",(oid,uid))
    if not row: await q.answer("❌ Not found.",show_alert=True); return
    if row["status"]!="Pending": await q.answer("❌ Can only cancel pending orders.",show_alert=True); return
    created=datetime.fromisoformat(str(row["created_at"]))
    if datetime.now()-created>timedelta(minutes=30): await q.answer("❌ Cancellation window (30 min) has passed.",show_alert=True); return
    qx("UPDATE orders SET status='Cancelled',cancelled_at=? WHERE id=?",(datetime.now().isoformat(),oid))
    vendor=q1("SELECT admin_user_id FROM vendors WHERE id=?",(row["vendor_id"],))
    notify=[ADMIN_ID]+([vendor["admin_user_id"]] if vendor and vendor.get("admin_user_id") and vendor["admin_user_id"]!=ADMIN_ID else [])
    for rid in notify:
        try: await ctx.bot.send_message(rid,f"🚫 Order <code>{oid}</code> cancelled by customer.",parse_mode="HTML")
        except: pass
    await safe_edit(q,f"🚫 Order <code>{oid}</code> cancelled.\n\nIf you paid, contact us for a refund.",parse_mode="HTML",reply_markup=KM([IB("💬 Contact","contact")],[IB("📦 Orders","orders")]))

async def view_orders(u,ctx):
    q=u.callback_query; uid=q.from_user.id
    rows=qa("SELECT id,gbp,status,ship,summary,vendor_id,created_at FROM orders WHERE user_id=? ORDER BY rowid DESC LIMIT 20",(uid,))
    if not rows: await safe_edit(q,"📭 No orders yet!",reply_markup=KM([IB("🏪 Browse","vendors")],[IB("⬅️ Back","menu")])); return
    sm={"Pending":("🕐","Pending"),"Paid":("✅","Confirmed"),"Dispatched":("🚚","Dispatched"),"Rejected":("❌","Rejected"),"Cancelled":("🚫","Cancelled")}
    txt="📦 <b>Your Orders</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"; kb=[]
    for o in rows:
        icon,lbl=sm.get(o["status"],("📋",o["status"])); dp="📍" if o["ship"]=="drop" else "📦"
        v=q1("SELECT name,emoji FROM vendors WHERE id=?",(o["vendor_id"],)); vtxt=f" · {v['emoji']} {v['name']}" if v else ""
        txt+=f"{icon} <b>{o['id']}</b> · {lbl}{vtxt} · {dp} · 💷 £{o['gbp']:.2f}\n{hl.escape(o['summary'][:50])}\n\n"
        kb.append([IB(f"🧾 View Invoice {o['id']}",f"view_invoice_{o['id']}")])
        if o["ship"]=="drop" and o["status"] in ("Pending","Paid","Dispatched"):
            kb.append([IB(("🔒 Closed Chat" if gs("cc_"+o["id"],"0")=="1" else "💬 Drop Chat")+" — "+o["id"],"dcv_"+o["id"])])
    await safe_edit(q,txt[:4000],parse_mode="HTML",reply_markup=InlineKeyboardMarkup(kb+[[IB("⬅️ Back","menu")]]))

# FEATURE 5: View invoice from orders list
async def view_invoice(u,ctx):
    q=u.callback_query; oid=q.data.split("view_invoice_")[1]; uid=q.from_user.id
    row=q1("SELECT user_id FROM orders WHERE id=?",(oid,))
    if not row or (row["user_id"]!=uid and not is_admin(uid) and not is_vendor_admin(uid)): await q.answer("❌ Not found.",show_alert=True); return
    inv,kb=build_invoice(oid)
    if not inv: await q.answer("❌ Invoice not found.",show_alert=True); return
    try: await q.message.delete()
    except: pass
    await q.message.reply_text(inv,parse_mode="HTML",reply_markup=kb)

async def user_paid(u,ctx):
    q=u.callback_query; oid=q.data[5:]; row=q1("SELECT * FROM orders WHERE id=?",(oid,))
    if not row: await safe_edit(q,"❌ Not found.",reply_markup=back_kb()); return
    vendor=q1("SELECT admin_user_id FROM vendors WHERE id=?",(row["vendor_id"],))
    notif=(f"💰 <b>PAYMENT CLAIM — {oid}</b>\n"
           f"👤 {hl.escape(row['cust_name'])} · {row['summary']}\n"
           f"💷 £{row['gbp']:.2f}" +(f" | 💠 {row['ltc']} LTC" if row.get('ltc',0)>0 else "")+
           (f"\n📤 Address: <code>{row['ltc_addr']}</code>" if row.get('ltc_addr') else ""))
    adm_kb=InlineKeyboardMarkup([[IB("✅ Confirm",f"adm_ok_{oid}"),IB("❌ Reject",f"adm_no_{oid}")]])
    notify_ids=[ADMIN_ID]
    if vendor and vendor.get("admin_user_id") and vendor["admin_user_id"]!=ADMIN_ID: notify_ids.append(vendor["admin_user_id"])
    for rid in notify_ids:
        try: await ctx.bot.send_message(rid,notif,parse_mode="HTML",reply_markup=adm_kb)
        except: pass
    # Show full invoice with payment submitted message
    inv,ikb=build_invoice(oid)
    await safe_edit(q,f"⏳ <b>Payment Submitted — Awaiting Confirmation</b>\n\n{inv}",parse_mode="HTML",reply_markup=KM([IB("📦 My Orders","orders")]))

# FEATURE 11: Payment proof photo upload
async def payment_proof_prompt(u,ctx):
    q=u.callback_query; oid=q.data.split("proof_")[1]
    ctx.user_data.update({"proof_oid":oid,"wf":"payment_proof"})
    await safe_edit(q,f"📸 Send a screenshot of your payment for order <code>{oid}</code>:",parse_mode="HTML",reply_markup=cancel_kb())

# FEATURE 12: LTC rate display
async def show_ltc_rate(u,ctx):
    q=u.callback_query; p=ltc_price()
    await q.answer(f"💠 LTC = £{p:.2f} GBP (live)",show_alert=True)

# FEATURE 13: Wishlist
async def view_wishlist(u,ctx):
    q=u.callback_query; uid=q.from_user.id
    items=qa("SELECT wishlist.product_id,products.name,products.hidden FROM wishlist JOIN products ON wishlist.product_id=products.id WHERE wishlist.user_id=? ORDER BY wishlist.id DESC",(uid,))
    if not items: await safe_edit(q,"❤️ Wishlist empty.\n\nTap 🤍 on any product to save it.",reply_markup=back_kb()); return
    kb=[[IB(("🌿 " if not r["hidden"] else "❌ ")+r["name"],f"prod_{r['product_id']}")] for r in items]
    kb+=[[IB("🗑️ Clear Wishlist","wish_clear")],[IB("⬅️ Back","menu")]]
    await safe_edit(q,"❤️ <b>Your Wishlist</b>",parse_mode="HTML",reply_markup=InlineKeyboardMarkup(kb))
async def wish_toggle(u,ctx):
    q=u.callback_query; uid=q.from_user.id; pid=int(q.data.split("wish_tog_")[1])
    exists=q1("SELECT id FROM wishlist WHERE user_id=? AND product_id=?",(uid,pid))
    if exists: qx("DELETE FROM wishlist WHERE user_id=? AND product_id=?",(uid,pid)); await q.answer("💔 Removed from wishlist",show_alert=False)
    else: qx("INSERT OR IGNORE INTO wishlist(user_id,product_id) VALUES(?,?)",(uid,pid)); await q.answer("❤️ Added to wishlist!",show_alert=False)
    await show_product(u,ctx)
async def wish_add(u,ctx):
    q=u.callback_query; uid=q.from_user.id; pid=int(q.data.split("wish_add_")[1])
    qx("INSERT OR IGNORE INTO wishlist(user_id,product_id) VALUES(?,?)",(uid,pid)); await q.answer("❤️ Added to wishlist!",show_alert=True)
async def wish_clear(u,ctx):
    q=u.callback_query; qx("DELETE FROM wishlist WHERE user_id=?",(q.from_user.id,)); await q.answer("🗑️ Cleared",show_alert=False); await view_wishlist(u,ctx)

# FEATURE 14: FAQ
async def faq_list(u,ctx):
    q=u.callback_query; rows=qa("SELECT id,question FROM faq ORDER BY id")
    if not rows: await safe_edit(q,"❓ No FAQs yet.\n\nContact us for help.",reply_markup=KM([IB("💬 Contact","contact")],[IB("⬅️ Back","menu")])); return
    await safe_edit(q,"❓ <b>Frequently Asked Questions</b>\n\nTap a question:",parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[IB(r["question"][:50],f"faq_{r['id']}")] for r in rows]+[[IB("⬅️ Back","menu")]]))
async def faq_answer(u,ctx):
    q=u.callback_query; fid=int(q.data.split("faq_")[1]); row=q1("SELECT question,answer FROM faq WHERE id=?",(fid,))
    if not row: await q.answer(); return
    await safe_edit(q,f"❓ <b>{hl.escape(row['question'])}</b>\n\n{hl.escape(row['answer'])}",parse_mode="HTML",
        reply_markup=KM([IB("⬅️ Back","faq_list")],[IB("💬 Still need help?","contact")]))

async def show_reviews(u,ctx):
    q=u.callback_query; page=int(q.data.split("_")[1])
    ms=datetime.now().replace(day=1,hour=0,minute=0,second=0,microsecond=0).isoformat()
    total=q1("SELECT COUNT(*) as c FROM reviews WHERE created_at>=?",(ms,))["c"]
    avg=q1("SELECT AVG(stars) as a FROM reviews WHERE created_at>=?",(ms,)); avg_s=f" · ⭐ {avg['a']:.1f} avg" if avg and avg["a"] else ""
    rows=qa("SELECT stars,text FROM reviews WHERE created_at>=? ORDER BY created_at DESC LIMIT ? OFFSET ?",(ms,RPP,page*RPP))
    if not rows and page==0: await safe_edit(q,"💬 No reviews this month yet.",reply_markup=back_kb()); return
    txt=f"⭐ <b>Reviews ({total}){avg_s}</b>\n\n"+"".join(f"{STARS.get(r['stars'],'')}\n{hl.escape(r['text'])}\n\n" for r in rows)
    pages=(total-1)//RPP if total else 0; nav=([IB("◀️",f"reviews_{page-1}")] if page>0 else [])+([IB("▶️",f"reviews_{page+1}")] if page<pages else [])
    await safe_edit(q,txt[:4000],parse_mode="HTML",reply_markup=InlineKeyboardMarkup(([nav] if nav else [])+[[IB("⬅️ Back","menu")]]))

async def review_start(u,ctx):
    q=u.callback_query; oid=q.data[7:]
    if not q1("SELECT 1 FROM orders WHERE id=? AND user_id=? AND status IN ('Paid','Dispatched')",(oid,q.from_user.id)): await q.answer("⚠️ Not eligible.",show_alert=True); return
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

# FEATURE 15: VIP tiers in loyalty
async def show_loyalty(u,ctx):
    q=u.callback_query; uid=q.from_user.id; lo=get_loyalty(uid); pts=lo["points"]; vip=get_vip(uid); spent=lo.get("total_spent",0)
    bar="█"*(pts//10)+"░"*(10-pts//10)
    # next tier
    next_tier=""; next_thresh=0
    for name,thresh in VIP_TIERS:
        if spent<thresh: next_tier=name; next_thresh=thresh; break
    next_l=f"\n\n📈 Next VIP: {next_tier} at £{next_thresh:.0f} spent (£{max(0,next_thresh-spent):.0f} to go)" if next_tier else "\n\n💎 Max VIP tier reached!"
    await safe_edit(q,
        f"🎁 <b>Loyalty & VIP</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{vip} <b>VIP Status</b>\n"
        f"💷 Total spent: £{spent:.2f}{next_l}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"⭐ <b>{pts}/100 pts</b>\n[{bar}]\n"
        f"{100-pts} pts to next £25 credit\n"
        f"💳 Available credit: <b>£{lo['credit']:.2f}</b>\n"
        f"🏆 Lifetime: <b>{lo['lifetime']} pts</b>\n\n"
        f"<i>2 pts per £1 spent · 100 pts = £25 credit</i>",
        parse_mode="HTML",reply_markup=back_kb())

async def show_my_ref(u,ctx):
    q=u.callback_query; uid=q.from_user.id; rc=get_ref(uid)
    cnt=(q1("SELECT count FROM referrals WHERE owner_id=?",(uid,)) or {}).get("count",0); nxt=15-(cnt%15) if cnt%15 else 15
    bn=(await ctx.bot.get_me()).username
    await safe_edit(q,
        f"🔗 <b>Refer & Earn</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Share your link:\n<code>https://t.me/{bn}?start={rc}</code>\n\n"
        f"👥 <b>{cnt}</b> referrals · <b>{nxt} more</b> = FREE reward 🎁",
        parse_mode="HTML",reply_markup=KM([IB("🏆 Leaderboard","ref_leaderboard")],[IB("⬅️ Back","menu")]))

# FEATURE 16: Referral leaderboard
async def ref_leaderboard(u,ctx):
    q=u.callback_query; rows=qa("SELECT owner_id,count FROM referrals ORDER BY count DESC LIMIT 10")
    if not rows: await safe_edit(q,"No referrals yet.",reply_markup=back_kb()); return
    medals=["🥇","🥈","🥉"]+["🏅"]*7
    txt="🏆 <b>Referral Leaderboard</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
    for i,r in enumerate(rows):
        u2=q1("SELECT username FROM users WHERE user_id=?",(r["owner_id"],)); un=u2["username"] if u2 and u2.get("username") else str(r["owner_id"])
        txt+=f"{medals[i]} @{hl.escape(un)} · {r['count']} refs\n"
    await safe_edit(q,txt,parse_mode="HTML",reply_markup=back_kb())

# FEATURE 17: Customer spend leaderboard
async def spend_leaderboard(u,ctx):
    q=u.callback_query
    rows=qa("SELECT user_id,COALESCE(total_spent,0) as s FROM loyalty ORDER BY s DESC LIMIT 10")
    if not rows: await safe_edit(q,"No data yet.",reply_markup=back_kb()); return
    medals=["🥇","🥈","🥉"]+["🏅"]*7
    txt="💷 <b>Top Customers</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
    for i,r in enumerate(rows):
        u2=q1("SELECT username FROM users WHERE user_id=?",(r["user_id"],)); un=u2["username"] if u2 and u2.get("username") else "Anonymous"
        txt+=f"{medals[i]} @{hl.escape(un)} · £{r['s']:.2f}\n"
    await safe_edit(q,txt,parse_mode="HTML",reply_markup=back_kb())

async def contact_start(u,ctx):
    q=u.callback_query; vs=qa("SELECT id,name,emoji FROM vendors WHERE active=1 ORDER BY id")
    if len(vs)==1: ctx.user_data.update({"wf":"contact","contact_vid":vs[0]["id"]}); await safe_edit(q,"💬 Type your message:",reply_markup=cancel_kb()); return
    await safe_edit(q,"💬 Contact which vendor?",reply_markup=InlineKeyboardMarkup([[IB(f"{v['emoji']} {v['name']}",f"contact_vid_{v['id']}")] for v in vs]+[[IB("⬅️ Back","menu")]]))
async def contact_vendor(u,ctx):
    q=u.callback_query; vid=int(q.data.split("_")[2]); ctx.user_data.update({"wf":"contact","contact_vid":vid}); await safe_edit(q,"💬 Type your message:",reply_markup=cancel_kb())

async def dropchat_view(u,ctx):
    q=u.callback_query; oid=q.data[4:]; closed=gs("cc_"+oid,"0")=="1"
    o=q1("SELECT summary,gbp FROM orders WHERE id=?",(oid,))
    hdr=f"💬 <b>Drop Chat — {oid}</b>\n━━━━━━━━━━━━━━━━━━━━\n"+(f"🛍️ {hl.escape(o['summary'])} · 💷 £{o['gbp']:.2f}\n" if o else "")+("🔒 <i>Chat closed.</i>\n" if closed else "")+"━━━━━━━━━━━━━━━━━━━━\n\n"
    dc_kb=lambda o,c: KM([IB("🔓 Reopen Chat",f"dco_{o}")],[IB("⬅️ Back","orders")]) if c else KM([IB("✉️ Send Message",f"dcm_{o}")],[IB("🔒 Close Chat",f"dcc_{o}"),IB("⬅️ Back","orders")])
    try: await q.message.delete()
    except: pass
    await q.message.reply_text(f"{hdr}{fmt_chat(oid)}"[:4000],parse_mode="HTML",reply_markup=dc_kb(oid,closed))
async def dropchat_msg_start(u,ctx):
    q=u.callback_query; oid=q.data[4:]; ctx.user_data.update({"dc_oid":oid,"wf":"drop_msg_user"})
    try: await q.message.delete()
    except: pass
    await q.message.reply_text(f"💬 <b>Order {oid}</b>\n\n✉️ Type your message:",parse_mode="HTML",reply_markup=KM([IB("❌ Cancel",f"dcv_{oid}")]))
def dc_admin_kb(oid): return KM([IB("↩️ Reply",f"dcr_{oid}"),IB("🔒 Close",f"dcac_{oid}"),IB("📋 History",f"dch_{oid}")])
async def dropchat_reply_start(u,ctx):
    q=u.callback_query; uid=q.from_user.id
    if not is_admin(uid) and not is_vendor_admin(uid): return
    oid=q.data[4:]; ctx.user_data.update({"dc_oid":oid,"wf":"drop_msg_admin"}); o=q1("SELECT cust_name FROM orders WHERE id=?",(oid,))
    await safe_edit(q,f"↩️ Reply to {oid}"+(f" — {hl.escape(o['cust_name'])}" if o else "")+f"\n━━━━━━━━━━━━━━━━━━━━\n\n{fmt_chat(oid)}\n\n✏️ Type reply:",parse_mode="HTML",reply_markup=KM([IB("❌ Cancel","menu")]))
async def dropchat_history(u,ctx):
    q=u.callback_query; uid=q.from_user.id
    if not is_admin(uid) and not is_vendor_admin(uid): return
    oid=q.data[4:]; closed=gs("cc_"+oid,"0")=="1"; o=q1("SELECT cust_name,summary,gbp FROM orders WHERE id=?",(oid,)); note=q1("SELECT note FROM order_notes WHERE order_id=?",(oid,))
    hdr=f"📋 <b>Chat {oid}</b>"+(f"\n👤 {hl.escape(o['cust_name'])} | {o['summary']} | 💷 £{o['gbp']:.2f}" if o else "")+(f"\n📝 {hl.escape(note['note'])}" if note else "")
    await safe_edit(q,f"{hdr}\n━━━━━━━━━━━━━━━━━━━━\n\n{fmt_chat(oid)}"[:4000],parse_mode="HTML",reply_markup=dc_admin_kb(oid) if not closed else KM([IB("🔓 Reopen",f"dco_{oid}")]))
async def dropchat_close(u,ctx):
    q=u.callback_query; oid=q.data.split("_",1)[1]; ss("cc_"+oid,"1"); r=q1("SELECT user_id FROM orders WHERE id=?",(oid,))
    if r:
        try: await ctx.bot.send_message(r["user_id"],f"🔒 Chat {oid} closed.",reply_markup=menu())
        except: pass
    await safe_edit(q,"🔒 Closed.",reply_markup=KM([IB("🔓 Reopen",f"dco_{oid}"),IB("⬅️ Back","menu")]))
async def dropchat_open(u,ctx):
    q=u.callback_query; oid=q.data[4:]; ss("cc_"+oid,"0")
    dc_kb=KM([IB("✉️ Send Message",f"dcm_{oid}")],[IB("🔒 Close Chat",f"dcc_{oid}"),IB("⬅️ Back","orders")])
    await safe_edit(q,f"🔓 Chat {oid} reopened.\n\n{fmt_chat(oid)}",parse_mode="HTML",reply_markup=dc_kb)

# FEATURE 4: Search
async def search_prompt(u,ctx):
    q=u.callback_query; ctx.user_data["wf"]="search"; await safe_edit(q,"🔍 Enter search term:",reply_markup=cancel_kb())

# ── ADMIN PANEL ────────────────────────────────────────────────────────────────
async def cmd_admin(u:Update,ctx:ContextTypes.DEFAULT_TYPE):
    uid=u.effective_user.id
    if is_vendor_admin(uid):
        v=get_vendor(uid); ctx.user_data["cur_vid"]=v["id"]; await _vendor_panel(u.message,v); return
    if not is_admin(uid): return
    await _platform_panel(u.message)

async def _platform_panel(msg):
    orders=qa("SELECT id,status,ship FROM orders ORDER BY rowid DESC LIMIT 30")
    unread=q1("SELECT COUNT(*) as c FROM messages WHERE reply IS NULL")["c"] or {"c":0}
    if isinstance(unread,dict): unread=unread.get("c",0)
    drops=len([o for o in orders if o["ship"]=="drop" and o["status"] in ("Pending","Paid")])
    pending=[o for o in orders if o["status"]=="Pending"]; paid_tracked=[o for o in orders if o["status"]=="Paid" and o["ship"]!="drop"]
    kb=[]
    if pending: kb+=[[IB(f"✅ {o['id']}",f"adm_ok_{o['id']}"),IB(f"❌ {o['id']}",f"adm_no_{o['id']}")] for o in pending[:5]]
    if paid_tracked: kb+=[[IB(f"🚚 {o['id']}",f"adm_go_{o['id']}")] for o in paid_tracked[:5]]
    kb+=[
        [IB("➕ Add Product","adm_addprod_go"),IB("🗑️ Remove","adm_rmprod"),IB("✏️ Edit Desc","adm_editdesc")],
        [IB("⚖️ Tiers","adm_tiers"),IB("👁️ Hide/Show","adm_hideprod"),IB("📂 Categories","adm_cats")],
        [IB("⭐ Feature","adm_feature"),IB("📦 Stock","adm_stock"),IB("⚡ Flash Sale","adm_flash")],
        [IB("🏷️ Discounts","adm_discounts"),IB("❓ FAQ Mgr","adm_faq"),IB("📢 Announce","adm_announce")],
        [IB("🏪 Vendors","adm_vendors"),IB("➕ Add Vendor","adm_addvendor"),IB("💰 Payouts","adm_payouts")],
        [IB(f"💬 Msgs{(' ('+str(unread)+')') if unread else ''}","adm_msgs"),IB(f"📍 Drops{(' ('+str(drops)+')') if drops else ''}","adm_drops"),IB("📊 Reviews","adm_rev_0")],
        [IB("📊 Stats","adm_stats"),IB("🏆 Leaderboards","adm_leaders"),IB("📤 Export","adm_export")],
        [IB("👥 Admins","adm_admins"),IB("🏠 Edit Home","adm_edit_home"),IB("🔒 Store Open/Close","adm_toggle_store")],
        [IB("🚫 Bans","adm_bans"),IB("📝 Cust Notes","adm_custnotes"),IB("📣 Bulk Message","adm_bulk")],
    ]
    await msg.reply_text("🔷 <b>PhiVara Network — Platform Admin v3.0</b>",parse_mode="HTML",reply_markup=InlineKeyboardMarkup(kb))

async def _vendor_panel(msg,v):
    vid=v["id"]; orders=qa("SELECT id,status,ship FROM orders WHERE vendor_id=? ORDER BY rowid DESC LIMIT 30",(vid,))
    unread_r=q1("SELECT COUNT(*) as c FROM messages WHERE reply IS NULL AND vendor_id=?",(vid,)); unread=unread_r["c"] if unread_r else 0
    drops=len([o for o in orders if o["ship"]=="drop" and o["status"] in ("Pending","Paid")])
    pending=[o for o in orders if o["status"]=="Pending"]; paid_tracked=[o for o in orders if o["status"]=="Paid" and o["ship"]!="drop"]
    kb=[]
    if pending: kb+=[[IB(f"✅ {o['id']}",f"adm_ok_{o['id']}"),IB(f"❌ {o['id']}",f"adm_no_{o['id']}")] for o in pending[:5]]
    if paid_tracked: kb+=[[IB(f"🚚 {o['id']}",f"adm_go_{o['id']}")] for o in paid_tracked[:5]]
    kb+=[
        [IB("➕ Add Product","adm_addprod_go"),IB("🗑️ Remove","adm_rmprod"),IB("✏️ Edit Desc","adm_editdesc"),IB("⚖️ Tiers","adm_tiers")],
        [IB("👁️ Hide/Show","adm_hideprod"),IB("📂 Categories","adm_cats"),IB("⭐ Feature","adm_feature"),IB("📦 Stock","adm_stock")],
        [IB("⚡ Flash Sale","adm_flash"),IB("🏷️ Discounts","adm_discounts"),IB("❓ FAQ","adm_faq"),IB("📊 Stats","adm_stats")],
        [IB(f"💬 Msgs{(' ('+str(unread)+')') if unread else ''}","adm_msgs"),IB(f"📍 Drops{(' ('+str(drops)+')') if drops else ''}","adm_drops"),IB("📢 Announce","adm_announce")],
        [IB("📊 Reviews","adm_rev_0"),IB("📤 Export","adm_export"),IB("💰 Payouts","adm_payouts")],
    ]
    await msg.reply_text(f"{v['emoji']} <b>{hl.escape(v['name'])} — Vendor Panel v3.0</b>",parse_mode="HTML",reply_markup=InlineKeyboardMarkup(kb))

# FEATURE 4: Analytics
async def adm_stats(u,ctx):
    q=u.callback_query; uid=q.from_user.id
    vid=get_vid(ctx,uid) if is_vendor_admin(uid) else None
    tot,td,wk,pending,avg,top,users=get_stats(vid)
    top_txt="\n".join(f"  {i+1}. {hl.escape(t['summary'][:40])} ×{t['c']}" for i,t in enumerate(top)) or "  None yet"
    txt=(f"📊 <b>Analytics Dashboard</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
         f"☀️ Today:  <b>{td['c']}</b> orders · 💷 £{td['s']:.2f}\n"
         f"📅 Week:   <b>{wk['c']}</b> orders · 💷 £{wk['s']:.2f}\n"
         f"📦 All-time: <b>{tot['c']}</b> · 💷 £{tot['s']:.2f}\n"
         f"⏳ Pending: <b>{pending['c']}</b>\n"
         f"📈 Avg order: <b>£{avg['a']:.2f}</b>\n"
         f"👤 Users: <b>{users['c']}</b>\n\n"
         f"🔥 <b>Top Products:</b>\n{top_txt}")
    await safe_edit(q,txt,parse_mode="HTML",reply_markup=KM([IB("🏆 Leaderboards","adm_leaders")],[IB("⬅️ Back","menu")]))

# FEATURE 18: Order export
async def adm_export(u,ctx):
    q=u.callback_query; uid=q.from_user.id
    if not is_admin(uid) and not is_vendor_admin(uid): return
    vid=get_vid(ctx,uid); vf=" AND vendor_id="+str(vid) if is_vendor_admin(uid) else ""
    rows=qa(f"SELECT id,cust_name,address,summary,gbp,status,ship,created_at FROM orders WHERE status IN ('Paid','Dispatched'){vf} ORDER BY created_at DESC LIMIT 100")
    if not rows: await q.answer("No completed orders to export.",show_alert=True); return
    lines=["Order ID | Customer | Address | Items | £GBP | Status | Delivery | Date"]
    lines+=["—"*80]
    for r in rows: lines.append(f"{r['id']} | {r['cust_name']} | {r['address']} | {r['summary']} | £{r['gbp']:.2f} | {r['status']} | {r['ship']} | {str(r['created_at'])[:10]}")
    txt="\n".join(lines)
    await ctx.bot.send_document(uid,document=txt.encode(),filename=f"orders_{datetime.now().strftime('%Y%m%d')}.txt",caption=f"📤 {len(rows)} orders exported")

# FEATURE 19: Payouts tracker
async def adm_payouts(u,ctx):
    q=u.callback_query; uid=q.from_user.id
    if not is_admin(uid) and not is_vendor_admin(uid): return
    vid=get_vid(ctx,uid); rows=qa("SELECT amount,note,created_at FROM payouts WHERE vendor_id=? ORDER BY id DESC LIMIT 10",(vid,))
    paid_out=sum(r["amount"] for r in rows)
    pending_r=q1(f"SELECT COALESCE(SUM(vendor_gbp),0) as s FROM orders WHERE status IN ('Paid','Dispatched') AND vendor_id=?",(vid,)); owed=(pending_r["s"] if pending_r else 0)-paid_out
    txt=(f"💰 <b>Vendor Payouts</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
         f"💷 Total paid out: £{paid_out:.2f}\n"
         f"⏳ Currently owed: £{max(0,owed):.2f}\n\n"
         f"<b>Recent payouts:</b>\n"+("".join(f"• £{r['amount']:.2f} — {hl.escape(r['note'] or '')} · {str(r['created_at'])[:10]}\n" for r in rows) or "None yet."))
    kb=[[IB("➕ Record Payout","adm_addpayout")]]+([[IB("⬅️ Back","menu")]])
    await safe_edit(q,txt,parse_mode="HTML",reply_markup=InlineKeyboardMarkup(kb))
async def adm_addpayout_start(u,ctx):
    q=u.callback_query; ctx.user_data["wf"]="add_payout"; await safe_edit(q,"💰 Enter payout:\n<code>AMOUNT Note</code>\ne.g. <code>250 Weekly payout</code>",parse_mode="HTML",reply_markup=cancel_kb())

# FEATURE 20: Flash sales
async def adm_flash_list(u,ctx):
    q=u.callback_query; uid=q.from_user.id; vid=get_vid(ctx,uid)
    rows=qa("SELECT id,name,flash_price,flash_until FROM products WHERE vendor_id=? ORDER BY id",(vid,))
    if not rows: await safe_edit(q,"No products.",reply_markup=back_kb()); return
    now=datetime.now().isoformat()
    kb=[[IB(("⚡ LIVE: " if r.get("flash_price",0)>0 and r.get("flash_until","")>now else "")+r["name"],f"setflash_{r['id']}")] for r in rows]+[[IB("⬅️ Back","menu")]]
    await safe_edit(q,"⚡ <b>Flash Sales</b>\n\nSelect product to set/clear flash price:",parse_mode="HTML",reply_markup=InlineKeyboardMarkup(kb))
async def adm_setflash_start(u,ctx):
    q=u.callback_query; pid=int(q.data.split("setflash_")[1]); r=q1("SELECT name,flash_price FROM products WHERE id=?",(pid,))
    ctx.user_data.update({"flash_pid":pid,"wf":"set_flash"})
    await safe_edit(q,f"⚡ Flash sale for <b>{hl.escape(r['name'])}</b>\n\nSend: <code>PRICE HOURS</code>\ne.g. <code>7.50 2</code> = £7.50 for 2 hours\n\nOr send <code>clear</code> to remove flash sale.",parse_mode="HTML",reply_markup=cancel_kb())

# FEATURE 2: Manual store toggle
async def adm_toggle_store(u,ctx):
    q=u.callback_query
    if not is_admin(u.effective_user.id): return
    current=gs("store_closed","0"); new="0" if current=="1" else "1"; ss("store_closed",new)
    status="🔴 Store is now CLOSED" if new=="1" else "🟢 Store is now OPEN"
    await q.answer(status,show_alert=True); await safe_edit(q,f"{status}\n\nCustomers will see this in the menu.",reply_markup=back_kb())

# FEATURE 21: Bulk message
async def adm_bulk(u,ctx):
    q=u.callback_query
    if not is_admin(u.effective_user.id): return
    ctx.user_data["wf"]="bulk_msg"; await safe_edit(q,"📣 <b>Bulk Message</b>\n\nType message to send to ALL users.\n\n⚠️ Use sparingly.",parse_mode="HTML",reply_markup=cancel_kb())

# FEATURE 22: Admin leaderboards hub
async def adm_leaders(u,ctx):
    q=u.callback_query
    await safe_edit(q,"🏆 <b>Leaderboards</b>",parse_mode="HTML",reply_markup=KM([IB("💷 Top Spenders","spend_leaderboard")],[IB("🔗 Top Referrers","ref_leaderboard")],[IB("⬅️ Back","menu")]))

async def adm_vendors(u,ctx):
    q=u.callback_query
    if not is_admin(u.effective_user.id): return
    vs=qa("SELECT * FROM vendors ORDER BY id")
    txt="🏪 <b>Vendors</b>\n\n"+"".join(f"{'✅' if v['active'] else '❌'} <b>{v['emoji']} {v['name']}</b> · #{v['id']} · {v['commission_pct']}% cut\nAdmin: <code>{v['admin_user_id']}</code>\nLTC: <code>{v['ltc_addr'] or 'Not set'}</code>\n\n" for v in vs)
    kb=[[IB(f"{'🚫 Disable' if v['active'] else '✅ Enable'} {v['name']}",f"togglevend_{v['id']}")] for v in vs]+[[IB("➕ Add Vendor","adm_addvendor")],[IB("⬅️ Back","menu")]]
    await safe_edit(q,txt[:4000],parse_mode="HTML",reply_markup=InlineKeyboardMarkup(kb))
async def adm_addvendor_start(u,ctx):
    q=u.callback_query
    if not is_admin(u.effective_user.id): return
    ctx.user_data["wf"]="add_vendor"
    await safe_edit(q,"🏪 <b>Add Vendor</b>\n\n<code>Name|🌿|Description|ltc_addr|commission_%|admin_id</code>",parse_mode="HTML",reply_markup=cancel_kb())
async def adm_togglevend(u,ctx):
    q=u.callback_query
    if not is_admin(u.effective_user.id): return
    vid=int(q.data.split("_")[1]); v=q1("SELECT active FROM vendors WHERE id=?",(vid,))
    if v: qx("UPDATE vendors SET active=? WHERE id=?",(0 if v["active"] else 1,vid))
    await adm_vendors(u,ctx)

async def adm_confirm(u,ctx):
    q=u.callback_query; oid=q.data[7:]; qx("UPDATE orders SET status='Paid',paid_at=? WHERE id=?",(datetime.now().isoformat(),oid))
    r=q1("SELECT user_id,ship,gbp FROM orders WHERE id=?",(oid,))
    if r:
        pts,cr=add_points(r["user_id"],r.get("gbp",0)); lnote=f"\n🎁 +{pts} pts!"+(" 💳 £"+str(int(cr))+" credit!" if cr else "")
        inv,ikb=build_invoice(oid)
        try:
            if r["ship"]=="drop": await ctx.bot.send_message(r["user_id"],f"✅ <b>Order {oid} confirmed!</b> Open Drop Chat to arrange.{lnote}\n\n{inv}",parse_mode="HTML",reply_markup=KM([IB("💬 Drop Chat",f"dcv_{oid}")]))
            else: await ctx.bot.send_message(r["user_id"],f"✅ <b>Payment confirmed!</b>{lnote}\n\n{inv}",parse_mode="HTML",reply_markup=KM([IB("⭐ Leave Review",f"review_{oid}"),IB("📦 Orders","orders")]))
        except: pass
    await safe_edit(q,f"✅ Order {oid} confirmed.")

async def adm_reject(u,ctx):
    q=u.callback_query; oid=q.data[7:]; qx("UPDATE orders SET status='Rejected' WHERE id=?",(oid,))
    r=q1("SELECT user_id FROM orders WHERE id=?",(oid,))
    if r:
        try: await ctx.bot.send_message(r["user_id"],f"❌ Order <code>{oid}</code> rejected. Contact us if you sent payment.",parse_mode="HTML",reply_markup=KM([IB("💬 Contact","contact")]))
        except: pass
    await safe_edit(q,f"❌ Rejected {oid}.")

async def adm_dispatch(u,ctx):
    q=u.callback_query; oid=q.data[7:]; qx("UPDATE orders SET status='Dispatched',dispatched_at=? WHERE id=?",(datetime.now().isoformat(),oid))
    r=q1("SELECT user_id,summary FROM orders WHERE id=?",(oid,))
    if r:
        inv,ikb=build_invoice(oid)
        try: await ctx.bot.send_message(r["user_id"],f"🚚 <b>Order {oid} dispatched!</b>\n\n{inv}",parse_mode="HTML",reply_markup=KM([IB("⭐ Leave Review",f"review_{oid}"),IB("📦 Orders","orders")]))
        except: pass
        qx("INSERT OR IGNORE INTO review_reminders(order_id,user_id,dispatched) VALUES(?,?,?)",(oid,r["user_id"],datetime.now().isoformat()))
    await safe_edit(q,f"🚚 Dispatched {oid}.")

async def adm_msgs(u,ctx):
    q=u.callback_query; uid=q.from_user.id
    if not is_admin(uid) and not is_vendor_admin(uid): return
    vid=get_vid(ctx,uid); rows=qa("SELECT id,username,message,reply FROM messages WHERE vendor_id=? ORDER BY id DESC LIMIT 15",(vid,))
    if not rows: await safe_edit(q,"📭 No messages.",reply_markup=back_kb()); return
    txt="💬 <b>Messages</b>\n\n"+"".join(f"{'✅' if r['reply'] else '⏳'} #{r['id']} @{r['username'] or '?'}\n{hl.escape(r['message'][:70])}\n/reply {r['id']}\n\n" for r in rows)
    await safe_edit(q,txt[:4000],parse_mode="HTML",reply_markup=back_kb())

async def adm_rev_cb(u,ctx):
    q=u.callback_query
    if not is_admin(u.effective_user.id) and not is_vendor_admin(u.effective_user.id): return
    page=int(q.data.split("adm_rev_")[1]); total=q1("SELECT COUNT(*) as c FROM reviews")["c"]
    rows=qa("SELECT stars,text,created_at FROM reviews ORDER BY created_at DESC LIMIT ? OFFSET ?",(RPP,page*RPP))
    if not rows and page==0: await safe_edit(q,"📭 No reviews yet.",reply_markup=back_kb()); return
    txt=f"📊 <b>All Reviews</b> ({total})\n\n"+"".join(f"{STARS.get(r['stars'],'')} · {str(r['created_at'])[:10]}\n{hl.escape(r['text'])}\n\n" for r in rows)
    pages=(total-1)//RPP if total else 0; nav=([IB("◀️",f"adm_rev_{page-1}")] if page>0 else [])+([IB("▶️",f"adm_rev_{page+1}")] if page<pages else [])
    await safe_edit(q,txt[:4000],parse_mode="HTML",reply_markup=InlineKeyboardMarkup(([nav] if nav else [])+[[IB("⬅️ Back","menu")]]))

async def adm_drops(u,ctx):
    q=u.callback_query; uid=q.from_user.id
    if not is_admin(uid) and not is_vendor_admin(uid): return
    vid=get_vid(ctx,uid); rows=qa("SELECT o.id,o.cust_name,o.status,(SELECT COUNT(*) FROM drop_chats d WHERE d.order_id=o.id) as msgs FROM orders o WHERE o.ship='drop' AND o.vendor_id=? ORDER BY o.rowid DESC LIMIT 20",(vid,))
    if not rows: await safe_edit(q,"📍 No drop orders.",reply_markup=back_kb()); return
    em={"Pending":"⏳","Paid":"✅","Dispatched":"🚚","Rejected":"❌"}; kb=[[IB(("🔒" if gs("cc_"+o["id"],"0")=="1" else "💬")+f" {o['id']} · {o['cust_name']} {em.get(o['status'],'')} ({o['msgs']})",f"dch_{o['id']}")] for o in rows]+[[IB("⬅️ Back","menu")]]
    await safe_edit(q,"📍 <b>Drop Orders</b>",parse_mode="HTML",reply_markup=InlineKeyboardMarkup(kb))

async def adm_note_start(u,ctx):
    q=u.callback_query
    if not is_admin(u.effective_user.id) and not is_vendor_admin(u.effective_user.id): return
    oid=q.data[9:]; ctx.user_data.update({"note_oid":oid,"wf":"order_note"}); note=q1("SELECT note FROM order_notes WHERE order_id=?",(oid,))
    await q.message.reply_text(f"📝 Note for {oid} — current: <i>{hl.escape(note['note']) if note else 'none'}</i>\n\nType note:",parse_mode="HTML")

async def adm_edit_home(u,ctx):
    q=u.callback_query
    if not is_admin(u.effective_user.id): return
    cur=gs("home_extra"); ctx.user_data["wf"]="edit_home"; await safe_edit(q,f"🏠 Current: <i>{hl.escape(cur) if cur else 'None'}</i>\n\nType new text or <code>clear</code>:",parse_mode="HTML",reply_markup=cancel_kb())

async def adm_admins(u,ctx):
    q=u.callback_query
    if not is_admin(u.effective_user.id): return
    rows=qa("SELECT user_id,username FROM admins ORDER BY rowid")
    txt="👥 <b>Platform Admins</b>\n\n"+"".join(f"{'👑' if r['user_id']==ADMIN_ID else '🔑'} <code>{r['user_id']}</code> @{r['username'] or '?'}\n" for r in rows)
    kb=[[IB("➕ Add Admin","adm_addadmin")]]+[[IB(f"🗑️ {r['username'] or r['user_id']}",f"adm_rmadmin_{r['user_id']}")] for r in rows if r["user_id"]!=ADMIN_ID]+[[IB("⬅️ Back","menu")]]
    await safe_edit(q,txt,parse_mode="HTML",reply_markup=InlineKeyboardMarkup(kb))

async def adm_addadmin_start(u,ctx):
    q=u.callback_query
    if not is_admin(u.effective_user.id): return
    ctx.user_data["wf"]="add_admin"; await safe_edit(q,"➕ Send numeric Telegram user_id:",reply_markup=cancel_kb())

async def adm_rmadmin(u,ctx):
    q=u.callback_query
    if not is_admin(u.effective_user.id): return
    uid=int(q.data.split("adm_rmadmin_")[1])
    if uid==ADMIN_ID: await q.answer("❌ Cannot remove owner.",show_alert=True); return
    r=q1("SELECT username FROM admins WHERE user_id=?",(uid,)); qx("DELETE FROM admins WHERE user_id=?",(uid,))
    await q.answer(f"✅ Removed {r['username'] if r else uid}",show_alert=True); await adm_admins(u,ctx)

async def adm_discounts(u,ctx):
    q=u.callback_query; uid=q.from_user.id
    if not is_admin(uid) and not is_vendor_admin(uid): return
    vid=get_vid(ctx,uid); rows=qa("SELECT code,pct,active,expires,uses_left FROM discount_codes WHERE vendor_id=? ORDER BY code",(vid,))
    def row_txt(r):
        s="✅ " if r["active"] else "❌ "; uses="" if r.get("uses_left",-1)<0 else f" ·{r['uses_left']} uses"
        exp=" · exp "+r["expires"][:10] if r.get("expires") else ""
        return s+"<code>"+r["code"]+"</code> "+str(int(r["pct"]*100))+"%"+uses+exp+"\n"
    txt="🏷️ <b>Discount Codes</b>\n\n"+"".join(row_txt(r) for r in rows)
    kb=[[IB(("🚫 " if r["active"] else "✅ ")+r["code"],f"toggledisc_{r['code']}")] for r in rows]+[[IB("➕ Add Code","adm_adddisc")],[IB("⬅️ Back","menu")]]
    await safe_edit(q,txt or "No codes yet.",parse_mode="HTML",reply_markup=InlineKeyboardMarkup(kb))

async def adm_toggledisc(u,ctx):
    q=u.callback_query; c=q.data.split("toggledisc_")[1]; r=q1("SELECT active FROM discount_codes WHERE code=?",(c,))
    if r: qx("UPDATE discount_codes SET active=? WHERE code=?",(0 if r["active"] else 1,c))
    await adm_discounts(u,ctx)

async def adm_adddisc_start(u,ctx):
    q=u.callback_query; ctx.user_data["wf"]="disc_code"
    await safe_edit(q,"🏷️ Add code:\n<code>CODE,PCT</code> or <code>CODE,PCT,HOURS</code> or <code>CODE,PCT,HOURS,USES</code>\ne.g. <code>VIP30,30,24,50</code>",parse_mode="HTML",reply_markup=cancel_kb())

async def ann_start(u,ctx):
    q=u.callback_query; ctx.user_data.update({"wf":"ann_title"}); ctx.user_data.pop("ann_photo",""); await safe_edit(q,"📢 Enter announcement title:",reply_markup=cancel_kb())

async def adm_cats(u,ctx):
    q=u.callback_query; uid=q.from_user.id
    if not is_admin(uid) and not is_vendor_admin(uid): return
    vid=get_vid(ctx,uid); cats=qa("SELECT * FROM categories WHERE vendor_id=? ORDER BY id",(vid,))
    txt="📂 <b>Categories</b>\n\n"+("\n".join(f"{c['emoji']} {c['name']}" for c in cats) if cats else "None yet.")
    kb=[[IB(f"✏️ {c['emoji']} {c['name']}",f"cat_assign_{c['id']}")] for c in cats]+[[IB("➕ New Category","adm_newcat"),IB("🗑️ Delete","adm_delcat")],[IB("⬅️ Back","menu")]]
    await safe_edit(q,txt,parse_mode="HTML",reply_markup=InlineKeyboardMarkup(kb))

async def adm_newcat(u,ctx):
    q=u.callback_query; ctx.user_data["wf"]="new_cat"; await safe_edit(q,"📂 Send: <code>🍃 Indoor Strains</code>",parse_mode="HTML",reply_markup=cancel_kb())

async def adm_delcat_list(u,ctx):
    q=u.callback_query; uid=q.from_user.id; vid=get_vid(ctx,uid); cats=qa("SELECT * FROM categories WHERE vendor_id=? ORDER BY id",(vid,))
    if not cats: await safe_edit(q,"No categories.",reply_markup=back_kb()); return
    await safe_edit(q,"🗑️ Delete which?",reply_markup=InlineKeyboardMarkup([[IB(f"🗑️ {c['emoji']} {c['name']}",f"delcat_{c['id']}")] for c in cats]+[[IB("⬅️ Back","adm_cats")]]))

async def adm_delcat_do(u,ctx):
    q=u.callback_query; cid=int(q.data.split("_")[1]); qx("UPDATE products SET category_id=0 WHERE category_id=?",(cid,)); qx("DELETE FROM categories WHERE id=?",(cid,)); await adm_cats(u,ctx)

async def adm_cat_assign(u,ctx):
    q=u.callback_query; cid=int(q.data.split("_")[2]); cat=q1("SELECT name,emoji FROM categories WHERE id=?",(cid,)); vid=get_vid(ctx,q.from_user.id)
    rows=qa("SELECT id,name,category_id FROM products WHERE vendor_id=? ORDER BY id",(vid,))
    kb=[[IB(("✅ " if r["category_id"]==cid else "○ ")+r["name"],f"togglecat_{r['id']}_{cid}")] for r in rows]+[[IB("✅ Done","adm_cats")]]
    await safe_edit(q,f"📂 Assign to <b>{cat['emoji']} {cat['name']}</b>:",parse_mode="HTML",reply_markup=InlineKeyboardMarkup(kb))

async def adm_togglecat(u,ctx):
    q=u.callback_query; p=q.data.split("_"); pid,cid=int(p[1]),int(p[2]); row=q1("SELECT category_id FROM products WHERE id=?",(pid,))
    if row: qx("UPDATE products SET category_id=? WHERE id=?",(0 if row["category_id"]==cid else cid,pid))
    u.callback_query.data=f"cat_assign_{cid}"; await adm_cat_assign(u,ctx)

async def adm_rmprod_list(u,ctx):
    q=u.callback_query; uid=q.from_user.id; vid=get_vid(ctx,uid); rows=qa("SELECT id,name FROM products WHERE vendor_id=? ORDER BY id",(vid,))
    if not rows: await safe_edit(q,"No products.",reply_markup=back_kb()); return
    await safe_edit(q,"🗑️ Remove which?",reply_markup=InlineKeyboardMarkup([[IB(f"🗑️ {r['name']}",f"rmprod_{r['id']}")] for r in rows]+[[IB("⬅️ Back","menu")]]))

async def adm_rmprod_confirm(u,ctx):
    q=u.callback_query; pid=int(q.data.split("_")[1]); r=q1("SELECT name FROM products WHERE id=?",(pid,))
    if r: await safe_edit(q,f"🗑️ Delete <b>{hl.escape(r['name'])}</b>?",parse_mode="HTML",reply_markup=KM([IB("✅ Delete",f"rmprod_yes_{pid}"),IB("❌ No","menu")]))

async def adm_rmprod_do(u,ctx):
    q=u.callback_query; qx("DELETE FROM products WHERE id=?",(int(q.data.split("_")[2]),)); await safe_edit(q,"✅ Deleted.",reply_markup=back_kb())

async def adm_editdesc_list(u,ctx):
    q=u.callback_query; uid=q.from_user.id; vid=get_vid(ctx,uid); rows=qa("SELECT id,name FROM products WHERE vendor_id=? ORDER BY id",(vid,))
    if not rows: await safe_edit(q,"No products.",reply_markup=back_kb()); return
    await safe_edit(q,"✏️ Edit description for:",reply_markup=InlineKeyboardMarkup([[IB(f"✏️ {r['name']}",f"editdesc_{r['id']}")] for r in rows]+[[IB("⬅️ Back","menu")]]))

async def adm_editdesc_start(u,ctx):
    q=u.callback_query; pid=int(q.data.split("_")[1]); ctx.user_data.update({"edit_pid":pid,"wf":"edit_desc"}); r=q1("SELECT name,description FROM products WHERE id=?",(pid,))
    await safe_edit(q,f"✏️ <b>Edit: {hl.escape(r['name'])}</b>\n\nCurrent: {hl.escape(r['description'] or '—')}\n\nSend new description:",parse_mode="HTML",reply_markup=cancel_kb())

async def adm_hideprod_list(u,ctx):
    q=u.callback_query; uid=q.from_user.id; vid=get_vid(ctx,uid); rows=qa("SELECT id,name,hidden FROM products WHERE vendor_id=? ORDER BY id",(vid,))
    if not rows: await safe_edit(q,"No products.",reply_markup=back_kb()); return
    await safe_edit(q,"👁️ <b>Hide / Show Products</b>",parse_mode="HTML",reply_markup=InlineKeyboardMarkup([[IB(f"{'👁️ Show' if r['hidden'] else '🙈 Hide'} {r['name']}",f"togglehide_{r['id']}")] for r in rows]+[[IB("⬅️ Back","menu")]]))

async def adm_togglehide(u,ctx):
    q=u.callback_query; pid=int(q.data.split("_")[1]); row=q1("SELECT name,hidden FROM products WHERE id=?",(pid,))
    if not row: await q.answer(); return
    qx("UPDATE products SET hidden=? WHERE id=?",(0 if row["hidden"] else 1,pid)); await q.answer(f"{'Shown' if row['hidden'] else 'Hidden'}: {row['name']}",show_alert=True); await adm_hideprod_list(u,ctx)

async def adm_list_tiers(u,ctx):
    q=u.callback_query; uid=q.from_user.id; vid=get_vid(ctx,uid); rows=qa("SELECT id,name FROM products WHERE vendor_id=? ORDER BY id",(vid,))
    if not rows: await safe_edit(q,"No products.",reply_markup=back_kb()); return
    await safe_edit(q,"⚖️ Edit tiers for:",reply_markup=InlineKeyboardMarkup([[IB(f"⚖️ {r['name']}",f"edtier_{r['id']}")] for r in rows]+[[IB("⬅️ Back","menu")]]))

async def adm_show_tiers(u,ctx):
    q=u.callback_query; pid=int(q.data.split("_")[1]); ctx.user_data.update({"tpid":pid,"wf":"edit_tiers"})
    r=q1("SELECT name,tiers FROM products WHERE id=?",(pid,)); tiers=json.loads(r["tiers"]) if r.get("tiers") else TIERS[:]
    await q.message.reply_text(f"⚖️ <b>{hl.escape(r['name'])}</b>\n\n"+"".join(ft(t)+"\n" for t in tiers)+"\nSend new tiers (qty,price per line) or /cancel",parse_mode="HTML")

async def adm_feature_list(u,ctx):
    q=u.callback_query; uid=q.from_user.id; vid=get_vid(ctx,uid)
    rows=qa("SELECT id,name,featured FROM products WHERE vendor_id=? ORDER BY id",(vid,))
    if not rows: await safe_edit(q,"No products.",reply_markup=back_kb()); return
    await safe_edit(q,"⭐ <b>Feature Products</b>",parse_mode="HTML",reply_markup=InlineKeyboardMarkup([[IB(("⭐ Unfeature " if r["featured"] else "☆ Feature ")+r["name"],f"togglefeat_{r['id']}")] for r in rows]+[[IB("⬅️ Back","menu")]]))

async def adm_togglefeat(u,ctx):
    q=u.callback_query; pid=int(q.data.split("_")[1]); row=q1("SELECT featured FROM products WHERE id=?",(pid,))
    if row: qx("UPDATE products SET featured=? WHERE id=?",(0 if row["featured"] else 1,pid))
    await adm_feature_list(u,ctx)

async def adm_stock_list(u,ctx):
    q=u.callback_query; uid=q.from_user.id; vid=get_vid(ctx,uid)
    rows=qa("SELECT id,name,stock FROM products WHERE vendor_id=? ORDER BY id",(vid,))
    if not rows: await safe_edit(q,"No products.",reply_markup=back_kb()); return
    txt="📦 <b>Stock</b>\n\n"+"".join(f"• {r['name']}: {'∞' if r['stock']==-1 else ('⚠️ '+str(r['stock']) if 0<r['stock']<=5 else str(r['stock']) if r['stock']>0 else '❌ OUT')}\n" for r in rows)
    await safe_edit(q,txt,parse_mode="HTML",reply_markup=InlineKeyboardMarkup([[IB(f"📦 {r['name']}",f"setstock_{r['id']}")] for r in rows]+[[IB("⬅️ Back","menu")]]))

async def adm_setstock_start(u,ctx):
    q=u.callback_query; pid=int(q.data.split("_")[1]); r=q1("SELECT name,stock FROM products WHERE id=?",(pid,))
    ctx.user_data.update({"stock_pid":pid,"wf":"set_stock"})
    await safe_edit(q,f"📦 <b>{hl.escape(r['name'])}</b>\nCurrent: {'∞' if r['stock']==-1 else r['stock']}\n\nEnter stock (-1 = unlimited):",parse_mode="HTML",reply_markup=cancel_kb())

# FEATURE 23: FAQ manager
async def adm_faq(u,ctx):
    q=u.callback_query; uid=q.from_user.id
    if not is_admin(uid) and not is_vendor_admin(uid): return
    rows=qa("SELECT id,question FROM faq ORDER BY id")
    kb=[[IB(f"🗑️ {r['question'][:40]}",f"delfaq_{r['id']}")] for r in rows]+[[IB("➕ Add FAQ","adm_addfaq")],[IB("⬅️ Back","menu")]]
    txt="❓ <b>FAQ Manager</b>\n\n"+("\n".join(f"• {r['question']}" for r in rows) if rows else "No FAQs yet.")
    await safe_edit(q,txt,parse_mode="HTML",reply_markup=InlineKeyboardMarkup(kb))

async def adm_addfaq_start(u,ctx):
    q=u.callback_query; ctx.user_data["wf"]="faq_q"; await safe_edit(q,"❓ Enter the question:",reply_markup=cancel_kb())

async def adm_delfaq(u,ctx):
    q=u.callback_query; fid=int(q.data.split("delfaq_")[1]); qx("DELETE FROM faq WHERE id=?",(fid,)); await adm_faq(u,ctx)

async def adm_bans(u,ctx):
    q=u.callback_query
    if not is_admin(u.effective_user.id): return
    rows=qa("SELECT user_id,username FROM users WHERE banned=1 ORDER BY user_id")
    txt="🚫 <b>Banned Users</b>\n\n"+("".join(f"• <code>{r['user_id']}</code> @{r['username'] or '?'}\n" for r in rows) if rows else "None.")
    kb=[[IB("🚫 Ban User","adm_ban_start")]]+[[IB(f"✅ Unban {r['username'] or r['user_id']}",f"unban_{r['user_id']}")] for r in rows]+[[IB("⬅️ Back","menu")]]
    await safe_edit(q,txt,parse_mode="HTML",reply_markup=InlineKeyboardMarkup(kb))

async def adm_ban_start(u,ctx):
    q=u.callback_query
    if not is_admin(u.effective_user.id): return
    ctx.user_data["wf"]="ban_user"; await safe_edit(q,"🚫 Enter user_id to ban:",reply_markup=cancel_kb())

async def adm_unban(u,ctx):
    q=u.callback_query
    if not is_admin(u.effective_user.id): return
    uid=int(q.data.split("_")[1]); qx("UPDATE users SET banned=0 WHERE user_id=?",(uid,)); await q.answer("✅ Unbanned",show_alert=True); await adm_bans(u,ctx)

async def adm_custnotes(u,ctx):
    q=u.callback_query
    if not is_admin(u.effective_user.id): return
    ctx.user_data["wf"]="custnote_uid"; await safe_edit(q,"📝 Enter user_id:",reply_markup=cancel_kb())

# ── COMMANDS ───────────────────────────────────────────────────────────────────
async def cmd_reply(u:Update,ctx:ContextTypes.DEFAULT_TYPE):
    if not is_admin(u.effective_user.id) and not is_vendor_admin(u.effective_user.id): return
    if not ctx.args or len(ctx.args)<2: await u.message.reply_text("Usage: /reply <id> <text>"); return
    try: mid=int(ctx.args[0])
    except: await u.message.reply_text("⚠️ Invalid ID."); return
    msg=" ".join(ctx.args[1:]); row=q1("SELECT user_id,username,message FROM messages WHERE id=?",(mid,))
    if not row: await u.message.reply_text("❌ Not found."); return
    qx("UPDATE messages SET reply=? WHERE id=?",(msg,mid))
    try: await ctx.bot.send_message(row["user_id"],f"💬 <b>Reply</b>\n<i>{hl.escape(row['message'])}</i>\n\n✉️ {hl.escape(msg)}",parse_mode="HTML",reply_markup=menu()); await u.message.reply_text(f"✅ Replied to @{row['username']}.")
    except Exception as e: await u.message.reply_text(f"❌ {e}")

async def cmd_order(u:Update,ctx:ContextTypes.DEFAULT_TYPE):
    if not is_admin(u.effective_user.id) and not is_vendor_admin(u.effective_user.id): return
    if not ctx.args: await u.message.reply_text("Usage: /order <id>"); return
    oid=ctx.args[0]; inv,kb=build_invoice(oid)
    if not inv: await u.message.reply_text("❌ Not found."); return
    row=q1("SELECT * FROM orders WHERE id=?",(oid,)); note=q1("SELECT note FROM order_notes WHERE order_id=?",(oid,))
    extra=f"\n📝 {hl.escape(note['note'])}" if note else ""
    proof=q1("SELECT file_id FROM payment_proofs WHERE order_id=?",(oid,))
    adm_kb=[]
    if row["status"]=="Pending": adm_kb+=[[IB("✅ Confirm",f"adm_ok_{oid}"),IB("❌ Reject",f"adm_no_{oid}")]]
    if row["status"]=="Paid" and row["ship"]!="drop": adm_kb+=[[IB("🚚 Dispatch",f"adm_go_{oid}")]]
    if row["ship"]=="drop": adm_kb+=[[IB("💬 Chat",f"dch_{oid}")]]
    adm_kb+=[[IB("📝 Note",f"adm_note_{oid}")]]
    if proof: await u.message.reply_photo(proof["file_id"],caption=f"{inv}{extra}",parse_mode="HTML",reply_markup=InlineKeyboardMarkup(adm_kb))
    else: await u.message.reply_text(f"{inv}{extra}",parse_mode="HTML",reply_markup=InlineKeyboardMarkup(adm_kb))

async def cmd_customer(u:Update,ctx:ContextTypes.DEFAULT_TYPE):
    if not is_admin(u.effective_user.id): return
    if not ctx.args: await u.message.reply_text("Usage: /customer @username or user_id"); return
    arg=ctx.args[0].lstrip("@")
    try: cid=int(arg); row=q1("SELECT user_id,username,banned FROM users WHERE user_id=?",(cid,))
    except: row=q1("SELECT user_id,username,banned FROM users WHERE username=?",(arg,))
    if not row: await u.message.reply_text("❌ Not found."); return
    cid=row["user_id"]; orders=qa("SELECT id,gbp,status,summary FROM orders WHERE user_id=? ORDER BY rowid DESC LIMIT 10",(cid,))
    spent=sum(o["gbp"] for o in orders if o["status"] in ("Paid","Dispatched")); lo=get_loyalty(cid); vip=get_vip(cid)
    note=q1("SELECT note FROM customer_notes WHERE user_id=?",(cid,)); banned="🚫 BANNED\n" if row.get("banned") else ""
    txt=(f"{banned}👤 @{hl.escape(row['username'] or str(cid))} (<code>{cid}</code>)\n{vip}\n━━━━━━━━━━━━━━━━━━━━\n💷 £{spent:.2f} · {len(orders)} orders · ⭐ {lo['points']} pts · 💳 £{lo['credit']:.2f}\n")
    if note: txt+=f"📝 {hl.escape(note['note'])}\n"
    txt+="\n"+"".join(f"• {o['id']} — {o['status']} — £{o['gbp']:.2f} — {hl.escape(o['summary'][:40])}\n" for o in orders)
    await u.message.reply_text(txt[:4000],parse_mode="HTML")

async def cmd_myorder(u:Update,ctx:ContextTypes.DEFAULT_TYPE):
    uid=u.effective_user.id
    if not is_known(uid) and not is_admin(uid): await u.message.reply_text("Please /start first."); return
    if not ctx.args: await u.message.reply_text("Usage: /myorder <id>"); return
    oid=ctx.args[0]; row=q1("SELECT user_id FROM orders WHERE id=?",(oid,))
    if not row or (row["user_id"]!=uid and not is_admin(uid)): await u.message.reply_text("❌ Not found."); return
    inv,kb=build_invoice(oid); await u.message.reply_text(inv,parse_mode="HTML",reply_markup=kb)

async def cmd_addproduct(u:Update,ctx:ContextTypes.DEFAULT_TYPE):
    if not is_admin(u.effective_user.id) and not is_vendor_admin(u.effective_user.id): return
    ctx.user_data["wf"]="add_photo"; await u.message.reply_text("📸 Send product photo (or type 'skip'):")

async def cmd_search(u:Update,ctx:ContextTypes.DEFAULT_TYPE):
    if not ctx.args: await u.message.reply_text("Usage: /search <term>"); return
    term="%"+" ".join(ctx.args)+"%"; rows=qa("SELECT id,name FROM products WHERE name LIKE ? AND hidden=0 ORDER BY name",(term,))
    if not rows: await u.message.reply_text("🔍 No products found."); return
    await u.message.reply_text(f"🔍 <b>Results</b>",parse_mode="HTML",reply_markup=InlineKeyboardMarkup([[IB(f"🌿 {r['name']}",f"prod_{r['id']}")] for r in rows]+[[IB("⬅️ Menu","menu")]]))

async def cmd_stats(u:Update,ctx:ContextTypes.DEFAULT_TYPE):
    if not is_admin(u.effective_user.id) and not is_vendor_admin(u.effective_user.id): return
    uid=u.effective_user.id; vid=get_vid(ctx,uid) if is_vendor_admin(uid) else None
    tot,td,wk,pending,avg,top,users=get_stats(vid)
    top_txt="\n".join(f"  {i+1}. {hl.escape(t['summary'][:40])} ×{t['c']}" for i,t in enumerate(top)) or "  None yet"
    await u.message.reply_text(f"📊 <b>Stats</b>\n━━━━━━━━━━━━━━━━━━━━\n☀️ Today: {td['c']} · £{td['s']:.2f}\n📅 Week: {wk['c']} · £{wk['s']:.2f}\n📦 All: {tot['c']} · £{tot['s']:.2f}\n⏳ Pending: {pending['c']}\n📈 Avg: £{avg['a']:.2f}\n👤 Users: {users['c']}\n\n🔥 Top:\n{top_txt}",parse_mode="HTML")

async def cmd_cancel(u:Update,ctx:ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear(); await u.message.reply_text("🚫 Cancelled.",reply_markup=menu())

# ── MESSAGE HANDLER ────────────────────────────────────────────────────────────
async def on_message(u:Update,ctx:ContextTypes.DEFAULT_TYPE):
    uid=u.effective_user.id; txt=(u.message.text or "").strip()
    if is_banned(uid): await u.message.reply_text("🚫 You are banned."); return
    if not is_known(uid) and not is_admin(uid) and not is_vendor_admin(uid): await u.message.reply_text("👋 Please /start first."); return
    wf=ctx.user_data.get("wf")
    if wf=="co_name":
        ctx.user_data.update({"co_name":txt,"wf":None}); t,_=co_summary(ctx.user_data,uid); await u.message.reply_text(t,parse_mode="HTML",reply_markup=co_kb(ctx.user_data))
    elif wf=="co_addr":
        ctx.user_data.update({"co_addr":txt,"wf":None})
        qx("INSERT OR REPLACE INTO saved_addresses(user_id,address) VALUES(?,?)",(uid,txt))
        t,_=co_summary(ctx.user_data,uid); await u.message.reply_text(t,parse_mode="HTML",reply_markup=co_kb(ctx.user_data))
    elif wf=="co_disc":
        vid=ctx.user_data.get("co_vid",1); pct=gdisc(txt,vid)
        if pct: ctx.user_data.update({"co_disc_code":txt.upper(),"co_disc_pct":pct,"wf":None}); await u.message.reply_text(f"✅ {int(pct*100)}% off applied!")
        else: ctx.user_data.update({"co_disc_code":None,"co_disc_pct":0,"wf":None}); await u.message.reply_text("❌ Invalid or expired code.")
        t,_=co_summary(ctx.user_data,uid); await u.message.reply_text(t,parse_mode="HTML",reply_markup=co_kb(ctx.user_data))
    elif wf=="search":
        term="%"+txt+"%"; rows=qa("SELECT id,name FROM products WHERE name LIKE ? AND hidden=0 ORDER BY name",(term,))
        ctx.user_data["wf"]=None
        if not rows: await u.message.reply_text("🔍 No products found.",reply_markup=menu()); return
        await u.message.reply_text(f"🔍 <b>Results for '{hl.escape(txt)}'</b>",parse_mode="HTML",reply_markup=InlineKeyboardMarkup([[IB(f"🌿 {r['name']}",f"prod_{r['id']}")] for r in rows]+[[IB("⬅️ Back","menu")]]))
    elif wf=="contact":
        uname=u.effective_user.username or str(uid); vid=ctx.user_data.get("contact_vid",1)
        mid=qxi("INSERT INTO messages(user_id,username,vendor_id,message) VALUES(?,?,?,?)",(uid,uname,vid,txt))
        vendor=q1("SELECT admin_user_id FROM vendors WHERE id=?",(vid,))
        notify=[ADMIN_ID]+([vendor["admin_user_id"]] if vendor and vendor.get("admin_user_id") and vendor["admin_user_id"]!=ADMIN_ID else [])
        for rid in notify:
            try: await ctx.bot.send_message(rid,f"💬 @{uname} #{mid}\n{hl.escape(txt)}\n/reply {mid}",parse_mode="HTML")
            except: pass
        await u.message.reply_text("✅ Message sent! We'll reply soon.",reply_markup=menu()); ctx.user_data["wf"]=None
    elif wf=="ann_title":
        ctx.user_data.update({"ann_title":txt,"wf":"ann_photo"}); await u.message.reply_text("📸 Send photo or type <b>skip</b>:",parse_mode="HTML")
    elif wf=="ann_photo":
        if txt.lower()=="skip": ctx.user_data["wf"]="ann_body"; await u.message.reply_text("✏️ Enter announcement body:")
        else: await u.message.reply_text("📸 Send photo or type <b>skip</b>:",parse_mode="HTML")
    elif wf=="ann_body":
        title=ctx.user_data.pop("ann_title",""); photo=ctx.user_data.pop("ann_photo",""); vid=get_vid(ctx,uid)
        qx("INSERT INTO announcements(vendor_id,title,body,photo) VALUES(?,?,?,?)",(vid,title,txt,photo))
        uids=qa("SELECT user_id FROM users WHERE banned=0"); sent=0
        for r in uids:
            try:
                fn=ctx.bot.send_photo(r["user_id"],photo,caption=f"📢 <b>{hl.escape(title)}</b>\n\n{hl.escape(txt)}",parse_mode="HTML") if photo else ctx.bot.send_message(r["user_id"],f"📢 <b>{hl.escape(title)}</b>\n\n{hl.escape(txt)}",parse_mode="HTML")
                await fn; sent+=1
            except: pass
        await u.message.reply_text(f"✅ Broadcast to {sent} users!"); ctx.user_data["wf"]=None
    elif wf=="bulk_msg":
        if not is_admin(uid): ctx.user_data["wf"]=None; return
        uids=qa("SELECT user_id FROM users WHERE banned=0"); sent=0
        for r in uids:
            try: await ctx.bot.send_message(r["user_id"],f"📣 <b>Message from PhiVara</b>\n\n{hl.escape(txt)}",parse_mode="HTML"); sent+=1
            except: pass
        await u.message.reply_text(f"✅ Sent to {sent} users.",reply_markup=menu()); ctx.user_data["wf"]=None
    elif wf=="review_text":
        oid=ctx.user_data.get("rev_order"); s=ctx.user_data.get("rev_stars",5); qx("INSERT OR REPLACE INTO reviews(order_id,user_id,stars,text) VALUES(?,?,?,?)",(oid,uid,s,txt))
        await u.message.reply_text(f"✅ {STARS.get(s,'')} Thanks for your review! 🙏",reply_markup=menu()); ctx.user_data["wf"]=None
    elif wf=="add_photo":
        if txt.lower()=="skip": ctx.user_data.update({"ph":"","wf":"add_title"}); await u.message.reply_text("📝 Enter product title:")
        else: await u.message.reply_text("📸 Send a photo or type 'skip':")
    elif wf=="add_title":
        ctx.user_data.update({"nm":txt,"wf":"add_desc"}); await u.message.reply_text("📄 Enter product description:")
    elif wf=="add_desc":
        d=ctx.user_data; vid=get_vid(ctx,uid); d["wf"]=None
        qx("INSERT INTO products(vendor_id,name,description,photo,hidden,tiers,stock) VALUES(?,?,?,?,0,?,?)",(vid,d["nm"],txt,d.get("ph",""),json.dumps(TIERS),-1))
        await u.message.reply_text(f"✅ <b>{hl.escape(d['nm'])}</b> added!",parse_mode="HTML",reply_markup=menu())
    elif wf=="edit_desc":
        qx("UPDATE products SET description=? WHERE id=?",(txt,ctx.user_data.get("edit_pid"))); await u.message.reply_text("✅ Updated!",reply_markup=menu()); ctx.user_data["wf"]=None
    elif wf=="edit_tiers":
        pid=ctx.user_data.get("tpid"); new=[]; errs=[]
        for i,line in enumerate(txt.splitlines(),1):
            p=line.strip().split(",")
            try: assert len(p)==2; q2,pr=float(p[0]),float(p[1]); assert q2>0 and pr>0; new.append({"qty":q2,"price":pr})
            except: errs.append(f"Line {i}: invalid")
        if errs or not new: await u.message.reply_text("❌ "+("\n".join(errs or ["No valid tiers."]))); return
        new.sort(key=lambda t:t["qty"]); qx("UPDATE products SET tiers=? WHERE id=?",(json.dumps(new),pid))
        await u.message.reply_text("✅ Tiers updated.",reply_markup=menu()); ctx.user_data["wf"]=None
    elif wf=="set_stock":
        try: sv=int(txt); assert sv>=-1
        except: await u.message.reply_text("⚠️ Enter a number (-1 for unlimited)."); return
        qx("UPDATE products SET stock=? WHERE id=?",(sv,ctx.user_data.get("stock_pid")))
        await u.message.reply_text(f"✅ Stock set to {'∞' if sv==-1 else sv}.",reply_markup=menu()); ctx.user_data["wf"]=None
    elif wf=="set_flash":
        pid=ctx.user_data.get("flash_pid")
        if txt.lower()=="clear":
            qx("UPDATE products SET flash_price=0,flash_until='' WHERE id=?",(pid,)); await u.message.reply_text("✅ Flash sale cleared.",reply_markup=menu()); ctx.user_data["wf"]=None; return
        parts=txt.split()
        try: fp=float(parts[0]); hrs=float(parts[1]) if len(parts)>1 else 2; assert fp>0
        except: await u.message.reply_text("⚠️ Format: PRICE HOURS (e.g. 7.50 2)"); return
        until=(datetime.now()+timedelta(hours=hrs)).isoformat()
        qx("UPDATE products SET flash_price=?,flash_until=? WHERE id=?",(fp,until,pid))
        await u.message.reply_text(f"⚡ Flash sale set! £{fp:.2f} for {hrs}h.",reply_markup=menu()); ctx.user_data["wf"]=None
    elif wf=="ban_user":
        if not is_admin(uid): ctx.user_data["wf"]=None; return
        try: bid=int(txt.strip())
        except: await u.message.reply_text("⚠️ Enter numeric user_id."); return
        if bid==ADMIN_ID: await u.message.reply_text("❌ Cannot ban owner."); ctx.user_data["wf"]=None; return
        qx("UPDATE users SET banned=1 WHERE user_id=?",(bid,))
        await u.message.reply_text(f"🚫 User <code>{bid}</code> banned.",parse_mode="HTML",reply_markup=menu()); ctx.user_data["wf"]=None
    elif wf=="custnote_uid":
        if not is_admin(uid): ctx.user_data["wf"]=None; return
        try: cid=int(txt.strip())
        except: await u.message.reply_text("⚠️ Enter numeric user_id."); return
        existing=q1("SELECT note FROM customer_notes WHERE user_id=?",(cid,))
        ctx.user_data.update({"custnote_uid":cid,"wf":"custnote_text"})
        await u.message.reply_text(f"📝 Current: <i>{hl.escape(existing['note']) if existing else 'none'}</i>\n\nType new note:",parse_mode="HTML")
    elif wf=="custnote_text":
        cid=ctx.user_data.get("custnote_uid"); qx("INSERT OR REPLACE INTO customer_notes(user_id,note) VALUES(?,?)",(cid,txt))
        await u.message.reply_text("✅ Note saved.",reply_markup=menu()); ctx.user_data["wf"]=None
    elif wf=="drop_msg_user":
        oid=ctx.user_data.get("dc_oid"); uname=u.effective_user.username or str(uid)
        qx("INSERT INTO drop_chats(order_id,user_id,sender,message) VALUES(?,?,?,?)",(oid,uid,"user",txt))
        o=q1("SELECT vendor_id FROM orders WHERE id=?",(oid,)); vendor=q1("SELECT admin_user_id FROM vendors WHERE id=?",(o["vendor_id"],)) if o else None
        notify=[ADMIN_ID]+([vendor["admin_user_id"]] if vendor and vendor.get("admin_user_id") and vendor["admin_user_id"]!=ADMIN_ID else [])
        for rid in notify:
            try: await ctx.bot.send_message(rid,f"💬 Drop Chat {oid}\n@{uname}: {hl.escape(txt)}",parse_mode="HTML",reply_markup=dc_admin_kb(oid))
            except: pass
        dc_kb=KM([IB("✉️ Send Message",f"dcm_{oid}")],[IB("🔒 Close Chat",f"dcc_{oid}"),IB("⬅️ Back","orders")])
        await u.message.reply_text(f"✅ Sent!\n\n{fmt_chat(oid)}",parse_mode="HTML",reply_markup=dc_kb); ctx.user_data["wf"]=None
    elif wf=="drop_msg_admin":
        oid=ctx.user_data.get("dc_oid"); row=q1("SELECT user_id FROM orders WHERE id=?",(oid,))
        if not row: await u.message.reply_text("❌ Not found."); ctx.user_data["wf"]=None; return
        qx("INSERT INTO drop_chats(order_id,user_id,sender,message) VALUES(?,?,?,?)",(oid,row["user_id"],"admin",txt))
        dc_kb=KM([IB("✉️ Send Message",f"dcm_{oid}")],[IB("🔒 Close Chat",f"dcc_{oid}"),IB("⬅️ Back","orders")])
        try: await ctx.bot.send_message(row["user_id"],f"🏪 <b>Vendor</b>\n\n{fmt_chat(oid)}",parse_mode="HTML",reply_markup=dc_kb)
        except: pass
        await u.message.reply_text("✅ Sent.",reply_markup=menu()); ctx.user_data["wf"]=None
    elif wf=="disc_code":
        parts=txt.upper().split(",")
        if len(parts) not in (2,3,4): await u.message.reply_text("⚠️ Format: CODE,PCT or CODE,PCT,HOURS or CODE,PCT,HOURS,USES"); return
        try: dc=parts[0].strip(); pct=float(parts[1].strip())/100; assert 0<pct<=1
        except: await u.message.reply_text("⚠️ Invalid. e.g. SAVE20,20"); return
        exp=(datetime.now()+timedelta(hours=float(parts[2].strip()))).isoformat() if len(parts)>=3 else None
        uses=int(parts[3].strip()) if len(parts)==4 else -1
        vid=get_vid(ctx,uid); qx("INSERT OR REPLACE INTO discount_codes(code,vendor_id,pct,active,expires,uses_left) VALUES(?,?,?,1,?,?)",(dc,vid,pct,exp,uses))
        await u.message.reply_text(f"✅ <code>{dc}</code> {int(pct*100)}% off added!",parse_mode="HTML",reply_markup=menu()); ctx.user_data["wf"]=None
    elif wf=="new_cat":
        parts=txt.split(None,1); emoji,name=(parts[0],parts[1]) if len(parts)==2 and len(parts[0])<=2 else ("🌿",parts[0]) if len(parts)==1 else (None,None)
        if not name: await u.message.reply_text("⚠️ Format: 🍃 Category Name"); return
        vid=get_vid(ctx,uid); qxi("INSERT INTO categories(vendor_id,name,emoji) VALUES(?,?,?)",(vid,name,emoji))
        await u.message.reply_text(f"✅ {emoji} {hl.escape(name)} created!",parse_mode="HTML",reply_markup=menu()); ctx.user_data["wf"]=None
    elif wf=="order_note":
        oid=ctx.user_data.get("note_oid"); qx("INSERT OR REPLACE INTO order_notes(order_id,note) VALUES(?,?)",(oid,txt)); await u.message.reply_text("✅ Note saved.",reply_markup=menu()); ctx.user_data["wf"]=None
    elif wf=="edit_home":
        if not is_admin(uid): ctx.user_data["wf"]=None; return
        val="" if txt.lower()=="clear" else txt; ss("home_extra",val); await u.message.reply_text("✅ Updated.",reply_markup=menu()); ctx.user_data["wf"]=None
    elif wf=="add_admin":
        if not is_admin(uid): ctx.user_data["wf"]=None; return
        try: new_id=int(txt.strip())
        except: await u.message.reply_text("⚠️ Numeric user_id only."); return
        if q1("SELECT 1 FROM admins WHERE user_id=?",(new_id,)): await u.message.reply_text("⚠️ Already admin."); ctx.user_data["wf"]=None; return
        qx("INSERT OR IGNORE INTO admins(user_id,username) VALUES(?,?)",(new_id,str(new_id)))
        try: info=await ctx.bot.get_chat(new_id); un=info.username or info.first_name or str(new_id); qx("UPDATE admins SET username=? WHERE user_id=?",(un,new_id))
        except: un=str(new_id)
        await u.message.reply_text(f"✅ {hl.escape(un)} added.",parse_mode="HTML",reply_markup=menu()); ctx.user_data["wf"]=None
    elif wf=="add_vendor":
        if not is_admin(uid): ctx.user_data["wf"]=None; return
        parts=[p.strip() for p in txt.split("|")]
        if len(parts)!=6: await u.message.reply_text("⚠️ Need: Name|🌿|Desc|ltc|commission%|admin_id"); return
        try: com=float(parts[4]); adm_id=int(parts[5])
        except: await u.message.reply_text("⚠️ Invalid commission or admin_id."); return
        vid=qxi("INSERT INTO vendors(name,emoji,description,ltc_addr,commission_pct,admin_user_id) VALUES(?,?,?,?,?,?)",(parts[0],parts[1],parts[2],parts[3],com,adm_id))
        await u.message.reply_text(f"✅ <b>{hl.escape(parts[0])}</b> added as Vendor #{vid}!",parse_mode="HTML",reply_markup=menu()); ctx.user_data["wf"]=None
    elif wf=="faq_q":
        ctx.user_data.update({"faq_q":txt,"wf":"faq_a"}); await u.message.reply_text("✏️ Now enter the answer:")
    elif wf=="faq_a":
        q_txt=ctx.user_data.pop("faq_q",""); qxi("INSERT INTO faq(question,answer) VALUES(?,?)",(q_txt,txt))
        await u.message.reply_text(f"✅ FAQ added!\nQ: {hl.escape(q_txt)}\nA: {hl.escape(txt)}",parse_mode="HTML",reply_markup=menu()); ctx.user_data["wf"]=None
    elif wf=="add_payout":
        if not is_admin(uid) and not is_vendor_admin(uid): ctx.user_data["wf"]=None; return
        parts=txt.split(None,1)
        try: amt=float(parts[0])
        except: await u.message.reply_text("⚠️ Format: AMOUNT Note"); return
        note=parts[1] if len(parts)>1 else ""; vid=get_vid(ctx,uid)
        qxi("INSERT INTO payouts(vendor_id,amount,note) VALUES(?,?,?)",(vid,amt,note))
        await u.message.reply_text(f"✅ Payout of £{amt:.2f} recorded.",reply_markup=menu()); ctx.user_data["wf"]=None
    elif wf=="payment_proof":
        await u.message.reply_text("📸 Please send a photo as your payment proof."); 
    else:
        await u.message.reply_text("Use /start to open the menu 👇",reply_markup=menu())

async def on_photo(u:Update,ctx:ContextTypes.DEFAULT_TYPE):
    uid=u.effective_user.id; wf=ctx.user_data.get("wf"); ph=u.message.photo[-1].file_id
    if not is_known(uid) and not is_admin(uid) and not is_vendor_admin(uid): return
    if wf=="add_photo": ctx.user_data.update({"ph":ph,"wf":"add_title"}); await u.message.reply_text("📝 Enter product title:")
    elif wf=="ann_photo": ctx.user_data.update({"ann_photo":ph,"wf":"ann_body"}); await u.message.reply_text("✏️ Enter announcement body:")
    elif wf=="payment_proof":
        oid=ctx.user_data.get("proof_oid")
        if not oid: return
        qx("INSERT OR REPLACE INTO payment_proofs(order_id,file_id) VALUES(?,?)",(oid,ph))
        row=q1("SELECT * FROM orders WHERE id=? AND user_id=?",(oid,uid))
        if row:
            vendor=q1("SELECT admin_user_id FROM vendors WHERE id=?",(row["vendor_id"],))
            notify=[ADMIN_ID]+([vendor["admin_user_id"]] if vendor and vendor.get("admin_user_id") and vendor["admin_user_id"]!=ADMIN_ID else [])
            for rid in notify:
                try: await ctx.bot.send_photo(rid,ph,caption=f"📸 Payment proof for order <code>{oid}</code> from {hl.escape(row['cust_name'])}\n💷 £{row['gbp']:.2f}" +(f" | 💠 {row['ltc']} LTC" if row.get('ltc',0)>0 else ""),parse_mode="HTML",reply_markup=InlineKeyboardMarkup([[IB("✅ Confirm",f"adm_ok_{oid}"),IB("❌ Reject",f"adm_no_{oid}")]]))
                except: pass
        await u.message.reply_text("✅ Payment proof submitted!",reply_markup=KM([IB("📦 My Orders","orders")])); ctx.user_data["wf"]=None

# ── BACKGROUND JOBS ────────────────────────────────────────────────────────────
async def review_reminder_job(ctx:ContextTypes.DEFAULT_TYPE):
    now=datetime.now(); t24=(now-timedelta(hours=24)).isoformat(); t48=(now-timedelta(hours=48)).isoformat()
    for r in qa("SELECT order_id,user_id FROM review_reminders WHERE dispatched<? AND dispatched>?",(t24,t48)):
        qx("DELETE FROM review_reminders WHERE order_id=?",(r["order_id"],))
        if q1("SELECT 1 FROM reviews WHERE order_id=?",(r["order_id"],)): continue
        try: await ctx.bot.send_message(r["user_id"],f"⭐ How was your order <code>{r['order_id']}</code>? Leave a quick review!",parse_mode="HTML",reply_markup=KM([IB("⭐ Review",f"review_{r['order_id']}")]))
        except: pass

async def auto_expire_job(ctx:ContextTypes.DEFAULT_TYPE):
    cutoff=(datetime.now()-timedelta(hours=48)).isoformat()
    rows=qa("SELECT id,user_id FROM orders WHERE status='Pending' AND created_at<?",(cutoff,))
    for r in rows:
        qx("UPDATE orders SET status='Rejected' WHERE id=?",(r["id"],))
        try: await ctx.bot.send_message(r["user_id"],f"⏰ Order <code>{r['id']}</code> auto-cancelled (48h no payment).",parse_mode="HTML",reply_markup=menu())
        except: pass

async def low_stock_job(ctx:ContextTypes.DEFAULT_TYPE):
    rows=qa("SELECT id,name,stock,vendor_id FROM products WHERE stock>0 AND stock<=3")
    for r in rows:
        v=q1("SELECT admin_user_id FROM vendors WHERE id=?",(r["vendor_id"],))
        notify=[ADMIN_ID]+([v["admin_user_id"]] if v and v.get("admin_user_id") and v["admin_user_id"]!=ADMIN_ID else [])
        for rid in notify:
            try: await ctx.bot.send_message(rid,f"⚠️ Low stock alert!\n<b>{hl.escape(r['name'])}</b> — only {r['stock']} left.",parse_mode="HTML")
            except: pass

async def flash_expiry_job(ctx:ContextTypes.DEFAULT_TYPE):
    now=datetime.now().isoformat()
    qx("UPDATE products SET flash_price=0,flash_until='' WHERE flash_until!='' AND flash_until<?  AND flash_price>0",(now,))

# ── ROUTER ─────────────────────────────────────────────────────────────────────
async def router(u:Update,ctx:ContextTypes.DEFAULT_TYPE):
    q=u.callback_query; d=q.data; uid=q.from_user.id
    if is_banned(uid): await q.answer("🚫 You are banned.",show_alert=True); return
    if not is_known(uid) and not is_admin(uid) and not is_vendor_admin(uid): await q.answer("❌ Please /start first.",show_alert=True); return
    if d.startswith("pick_"):         await pick_weight(u,ctx); return
    if d.startswith("togglehide_"):   await adm_togglehide(u,ctx); return
    if d.startswith("togglefeat_"):   await adm_togglefeat(u,ctx); return
    if d=="noop":                     await q.answer(); return
    await q.answer()
    if   d=="menu":                   await safe_edit(q,f"🔷 <b>PhiVara Network</b>\n━━━━━━━━━━━━━━━━━━━━\n\n{open_badge()}\n🕙 <b>Mon–Sat · Orders close 11am</b>\n\n💠 LTC: £{ltc_price():.2f} GBP\n\n👇 <b>Browse Vendors</b>",parse_mode="HTML",reply_markup=menu())
    elif d=="vendors":                await show_vendors(u,ctx)
    elif d.startswith("vend_"):       await show_vendor(u,ctx)
    elif d.startswith("cat_assign_"): await adm_cat_assign(u,ctx)
    elif d.startswith("togglecat_"):  await adm_togglecat(u,ctx)
    elif d.startswith("cat_"):        await show_category(u,ctx)
    elif d.startswith("prod_"):       await show_product(u,ctx)
    elif d=="basket":                 await view_basket(u,ctx)
    elif d=="orders":                 await view_orders(u,ctx)
    elif d.startswith("view_invoice_"): await view_invoice(u,ctx)
    elif d.startswith("cancel_order_"): await cancel_order(u,ctx)
    elif d.startswith("reviews_"):    await show_reviews(u,ctx)
    elif d=="news":                   await show_news(u,ctx)
    elif d=="contact":                await contact_start(u,ctx)
    elif d.startswith("contact_vid_"): await contact_vendor(u,ctx)
    elif d.startswith("rm_"):         await remove_item(u,ctx)
    elif d=="clear_cart":             await clear_cart(u,ctx)
    elif d.startswith("paid_"):       await user_paid(u,ctx)
    elif d.startswith("review_"):     await review_start(u,ctx)
    elif d.startswith("stars_"):      await pick_stars(u,ctx)
    elif d=="loyalty":                await show_loyalty(u,ctx)
    elif d=="my_ref":                 await show_my_ref(u,ctx)
    elif d=="ref_leaderboard":        await ref_leaderboard(u,ctx)
    elif d=="spend_leaderboard":      await spend_leaderboard(u,ctx)
    elif d=="adm_leaders":            await adm_leaders(u,ctx)
    elif d=="search_prompt":          await search_prompt(u,ctx)
    elif d=="wishlist":               await view_wishlist(u,ctx)
    elif d.startswith("wish_tog_"):   await wish_toggle(u,ctx)
    elif d.startswith("wish_add_"):   await wish_add(u,ctx)
    elif d=="wish_clear":             await wish_clear(u,ctx)
    elif d=="faq_list":               await faq_list(u,ctx)
    elif d.startswith("faq_"):        await faq_answer(u,ctx)
    elif d=="ltc_rate":               await show_ltc_rate(u,ctx)
    elif d=="checkout":               await checkout_start(u,ctx)
    elif d=="co_name":                await co_name_start(u,ctx)
    elif d=="co_addr":                await co_addr_start(u,ctx)
    elif d=="co_addr_skip":           await co_addr_skip(u,ctx)
    elif d=="co_addr_saved":          await co_addr_saved(u,ctx)
    elif d=="co_disc":                await co_disc_start(u,ctx)
    elif d.startswith("co_ship_"):    await co_ship_cb(u,ctx)
    elif d=="co_refresh":             await co_refresh_cb(u,ctx)
    elif d=="co_confirm":             await co_confirm(u,ctx)
    elif d.startswith("adm_ok_"):     await adm_confirm(u,ctx)
    elif d.startswith("adm_no_"):     await adm_reject(u,ctx)
    elif d.startswith("adm_go_"):     await adm_dispatch(u,ctx)
    elif d=="adm_msgs":               await adm_msgs(u,ctx)
    elif d=="adm_tiers":              await adm_list_tiers(u,ctx)
    elif d=="adm_rmprod":             await adm_rmprod_list(u,ctx)
    elif d.startswith("rmprod_yes_"): await adm_rmprod_do(u,ctx)
    elif d.startswith("rmprod_"):     await adm_rmprod_confirm(u,ctx)
    elif d=="adm_editdesc":           await adm_editdesc_list(u,ctx)
    elif d.startswith("editdesc_"):   await adm_editdesc_start(u,ctx)
    elif d=="adm_hideprod":           await adm_hideprod_list(u,ctx)
    elif d=="adm_cats":               await adm_cats(u,ctx)
    elif d=="adm_newcat":             await adm_newcat(u,ctx)
    elif d=="adm_delcat":             await adm_delcat_list(u,ctx)
    elif d.startswith("delcat_"):     await adm_delcat_do(u,ctx)
    elif d=="adm_drops":              await adm_drops(u,ctx)
    elif d.startswith("adm_rev_"):    await adm_rev_cb(u,ctx)
    elif d=="adm_discounts":          await adm_discounts(u,ctx)
    elif d.startswith("toggledisc_"): await adm_toggledisc(u,ctx)
    elif d=="adm_adddisc":            await adm_adddisc_start(u,ctx)
    elif d=="adm_announce":           await ann_start(u,ctx)
    elif d=="adm_vendors":            await adm_vendors(u,ctx)
    elif d=="adm_addvendor":          await adm_addvendor_start(u,ctx)
    elif d.startswith("togglevend_"): await adm_togglevend(u,ctx)
    elif d=="adm_stats":              await adm_stats(u,ctx)
    elif d=="adm_feature":            await adm_feature_list(u,ctx)
    elif d=="adm_stock":              await adm_stock_list(u,ctx)
    elif d.startswith("setstock_"):   await adm_setstock_start(u,ctx)
    elif d=="adm_flash":              await adm_flash_list(u,ctx)
    elif d.startswith("setflash_"):   await adm_setflash_start(u,ctx)
    elif d=="adm_toggle_store":       await adm_toggle_store(u,ctx)
    elif d=="adm_bulk":               await adm_bulk(u,ctx)
    elif d=="adm_bans":               await adm_bans(u,ctx)
    elif d=="adm_ban_start":          await adm_ban_start(u,ctx)
    elif d.startswith("unban_"):      await adm_unban(u,ctx)
    elif d=="adm_custnotes":          await adm_custnotes(u,ctx)
    elif d=="adm_faq":                await adm_faq(u,ctx)
    elif d=="adm_addfaq":             await adm_addfaq_start(u,ctx)
    elif d.startswith("delfaq_"):     await adm_delfaq(u,ctx)
    elif d=="adm_payouts":            await adm_payouts(u,ctx)
    elif d=="adm_addpayout":          await adm_addpayout_start(u,ctx)
    elif d=="adm_export":             await adm_export(u,ctx)
    elif d=="adm_addprod_go":
        if is_admin(uid) or is_vendor_admin(uid):
            ctx.user_data["wf"]="add_photo"
            try: await q.message.delete()
            except: pass
            await q.message.reply_text("📸 Send product photo (or type 'skip'):")
    elif d.startswith("edtier_"):     await adm_show_tiers(u,ctx)
    elif d.startswith("dcv_"):        await dropchat_view(u,ctx)
    elif d.startswith("dch_"):        await dropchat_history(u,ctx)
    elif d.startswith("dcc_"):        await dropchat_close(u,ctx)
    elif d.startswith("dcac_"):       await dropchat_close(u,ctx)
    elif d.startswith("dco_"):        await dropchat_open(u,ctx)
    elif d.startswith("dcm_"):        await dropchat_msg_start(u,ctx)
    elif d.startswith("dcr_"):        await dropchat_reply_start(u,ctx)
    elif d.startswith("adm_note_"):   await adm_note_start(u,ctx)
    elif d=="adm_edit_home":          await adm_edit_home(u,ctx)
    elif d=="adm_admins":             await adm_admins(u,ctx)
    elif d=="adm_addadmin":           await adm_addadmin_start(u,ctx)
    elif d.startswith("adm_rmadmin_"): await adm_rmadmin(u,ctx)
    elif d.startswith("proof_"):      await payment_proof_prompt(u,ctx)

class _Ping(BaseHTTPRequestHandler):
    def do_GET(self): self.send_response(200); self.end_headers(); self.wfile.write(b"ok")
    def log_message(self,*a): pass

def main():
    Thread(target=lambda:HTTPServer(("0.0.0.0",8080),_Ping).serve_forever(),daemon=True).start()
    init_db(); app=ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler(["start","Start"],cmd_start))
    for cmd,fn in [("admin",cmd_admin),("reply",cmd_reply),("order",cmd_order),("customer",cmd_customer),
                   ("myorder",cmd_myorder),("addproduct",cmd_addproduct),("cancel",cmd_cancel),
                   ("search",cmd_search),("stats",cmd_stats)]:
        app.add_handler(CommandHandler(cmd,fn))
    app.add_handler(CallbackQueryHandler(router))
    app.add_handler(MessageHandler(filters.PHOTO,on_photo))
    app.add_handler(MessageHandler(filters.TEXT&~filters.COMMAND,on_message))
    if app.job_queue:
        app.job_queue.run_repeating(review_reminder_job,interval=3600,first=300)
        app.job_queue.run_repeating(auto_expire_job,interval=3600,first=600)
        app.job_queue.run_repeating(low_stock_job,interval=3600,first=900)
        app.job_queue.run_repeating(flash_expiry_job,interval=300,first=60)
    else: print("⚠️ Job queue not available. pip install python-telegram-bot[job-queue]")
    print("🔷 PhiVara Network v3.0 — Running"); app.run_polling(drop_pending_updates=True)

if __name__=="__main__":
    main()
