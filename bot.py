# -*- coding: utf-8 -*-
# ╔══════════════════════════════════════════════════════════════╗
# ║        PhiVara Network — v5.0 NEXT GENERATION               ║
# ║  BUG FIXES:                                                 ║
# ║  • Product add: photo→title→description clean flow          ║
# ║  • Reviews store vendor_id + product + vendor name         ║
# ║  • DB persistence: INSERT OR IGNORE — data survives redeploy║
# ║  • Admins/vendors/products never wiped on redeploy          ║
# ║  • Review text stored correctly with all metadata           ║
# ║  19 UPGRADES:                                               ║
# ║  1.  DB persistence + safe migrations                       ║
# ║  2.  Max-use discount codes                                 ║
# ║  3.  Auto bulk discount at checkout                         ║
# ║  4.  Product view counter                                   ║
# ║  5.  Per-product average rating on product page             ║
# ║  6.  Reviews show vendor + product name                     ║
# ║  7.  Full admin panel all buttons working                   ║
# ║  8.  Platform settings panel (/set command)                 ║
# ║  9.  Weekly report panel                                    ║
# ║  10. Disputes panel                                         ║
# ║  11. /set command for platform settings                     ║
# ║  12. Clean 3-step product add flow                          ║
# ║  13. Auto LTC payment detection (blockchain poll)           ║
# ║  14. Pending payment reminders (every 2h)                   ║
# ║  15. Daily revenue report to admin                          ║
# ║  16. Low stock alert to vendor                              ║
# ║  17. Edit product name (not just description)               ║
# ║  18. /top command — top selling products                    ║
# ║  19. Product copy — duplicate a product                     ║
# ╚══════════════════════════════════════════════════════════════╝

import os, json, logging, requests, html as hl, time
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler
from uuid import uuid4
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton as _IB
from telegram.ext import (ApplicationBuilder, CommandHandler, CallbackQueryHandler,
                           MessageHandler, ContextTypes, filters)
import os
import psycopg2

DB = os.getenv("DATABASE_URL")

def db():
    return psycopg2.connect(DB, sslmode='require')

def IB(t, c): return _IB(text=t, callback_data=c)

# ── CONFIG ─────────────────────────────────────────────────────────────────────
TOKEN        = os.getenv("TOKEN")
ADMIN_ID     = 7773622161
CHANNEL_ID   = -1003833257976
PLATFORM_LTC = "ltc1qv4u6vr0gzp9g4lq0g3qev939vdnwxghn5gtnfc"

# ── POSTGRESQL ─────────────────────────────────────────────────────────────────
# Railway: add a PostgreSQL plugin to your service — DATABASE_URL is set automatically
DATABASE_URL = os.getenv("DATABASE_URL", "")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable not set. Add a PostgreSQL plugin in Railway.")

def db():
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
    conn.autocommit = False
    return conn

def _sql(s):
    """Convert SQLite ? placeholders to PostgreSQL %s"""
    return s.replace("?", "%s")

def q1(s, p=()):
    conn = db()
    try:
        cur = conn.cursor()
        cur.execute(_sql(s), p)
        r = cur.fetchone()
        return dict(r) if r else None
    finally:
        conn.close()

def qa(s, p=()):
    conn = db()
    try:
        cur = conn.cursor()
        cur.execute(_sql(s), p)
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()

def qx(s, p=()):
    conn = db()
    try:
        cur = conn.cursor()
        cur.execute(_sql(s), p)
        conn.commit()
    except Exception as e:
        conn.rollback(); raise
    finally:
        conn.close()

def qxi(s, p=()):
    """Execute INSERT and return the generated id via RETURNING id"""
    conn = db()
    try:
        cur = conn.cursor()
        # Add RETURNING id if not present
        sql = _sql(s)
        if "RETURNING" not in sql.upper():
            sql = sql.rstrip(";") + " RETURNING id"
        cur.execute(sql, p)
        r = cur.fetchone()
        conn.commit()
        return r["id"] if r else None
    except Exception as e:
        conn.rollback(); raise
    finally:
        conn.close()

def gs(k, d=""):
    r = q1("SELECT value FROM settings WHERE key=%s", (k,))
    return r["value"] if r else d

def ss(k, v):
    qx("INSERT INTO settings(key,value) VALUES(%s,%s) ON CONFLICT(key) DO UPDATE SET value=%s", (k, v, v))

print("🗄️  Database: PostgreSQL (DATABASE_URL configured)")

SHIP = {
    "tracked24": {"label": "📦 Tracked24", "price": 5.0,  "ltc": True},
    "drop":      {"label": "📍 Local Drop",  "price": 0.0,  "ltc": False},
}
TIERS = [
    {"qty":1,   "price":10.0},  {"qty":3.5, "price":35.0},
    {"qty":7,   "price":60.0},  {"qty":14,  "price":110.0},
    {"qty":28,  "price":200.0}, {"qty":56,  "price":380.0},
]
STARS      = {1:"⭐",2:"⭐⭐",3:"⭐⭐⭐",4:"⭐⭐⭐⭐",5:"⭐⭐⭐⭐⭐"}
VIP_LEVELS = [("Diamond","💎",1500),("Gold","🥇",500),("Silver","🥈",200),("Bronze","🥉",50)]
RPP        = 5
LTC_CACHE  = {"rate": 0.0, "ts": 0}

logging.basicConfig(level=logging.WARNING)

# ── DATABASE ───────────────────────────────────────────────────────────────────
def db():
    c = psycopg2.connect(DB); c.row_factory = psycopg2.Row; return c

def q1(s, p=()):
    c = db(); r = c.execute(s, p).fetchone(); c.close()
    return dict(r) if r else None

def qa(s, p=()):
    c = db(); r = c.execute(s, p).fetchall(); c.close()
    return [dict(x) for x in r]

def qx(s, p=()):
    c = db(); c.execute(s, p); c.commit(); c.close()

# qxi defined above in PostgreSQL section

def gs(k, d=""): r = q1("SELECT value FROM settings WHERE key=?", (k,)); return r["value"] if r else d
def ss(k, v):    qx("INSERT INTO settings(key,value) VALUES(?,?)", (k, v))

def init_db():
    """Create all tables if they don't exist, then seed default data."""
    conn = db(); cur = conn.cursor()
    tables = [
        """CREATE TABLE IF NOT EXISTS users(
            user_id BIGINT PRIMARY KEY, username TEXT,
            joined TIMESTAMP DEFAULT NOW(),
            banned INTEGER DEFAULT 0, vip_tier TEXT DEFAULT 'standard',
            language TEXT DEFAULT 'en')""",
        """CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT)""",
        """CREATE TABLE IF NOT EXISTS admins(user_id BIGINT PRIMARY KEY, username TEXT)""",
        """CREATE TABLE IF NOT EXISTS vendors(
            id SERIAL PRIMARY KEY, name TEXT,
            emoji TEXT DEFAULT '🏪', description TEXT DEFAULT '',
            ltc_addr TEXT, commission_pct REAL DEFAULT 10,
            admin_user_id BIGINT, active INTEGER DEFAULT 1,
            banner_photo TEXT DEFAULT '')""",
        """CREATE TABLE IF NOT EXISTS products(
            id SERIAL PRIMARY KEY,
            vendor_id INTEGER DEFAULT 1, name TEXT, description TEXT,
            photo TEXT, hidden INTEGER DEFAULT 0,
            tiers TEXT DEFAULT '[]', category_id INTEGER DEFAULT 0,
            stock INTEGER DEFAULT -1, featured INTEGER DEFAULT 0,
            views INTEGER DEFAULT 0, created_at TIMESTAMP DEFAULT NOW())""",
        """CREATE TABLE IF NOT EXISTS categories(
            id SERIAL PRIMARY KEY,
            vendor_id INTEGER DEFAULT 1, name TEXT, emoji TEXT DEFAULT '🌿')""",
        """CREATE TABLE IF NOT EXISTS cart(
            id SERIAL PRIMARY KEY,
            user_id BIGINT, product_id INTEGER,
            vendor_id INTEGER DEFAULT 1, qty REAL, price REAL,
            created_at TIMESTAMP DEFAULT NOW())""",
        """CREATE TABLE IF NOT EXISTS orders(
            id TEXT PRIMARY KEY, user_id BIGINT,
            vendor_id INTEGER DEFAULT 1, cust_name TEXT, address TEXT,
            summary TEXT DEFAULT '', gbp REAL,
            vendor_gbp REAL DEFAULT 0, platform_gbp REAL DEFAULT 0,
            ltc REAL DEFAULT 0, ltc_rate REAL DEFAULT 0,
            ltc_addr TEXT DEFAULT '', status TEXT DEFAULT 'Pending',
            ship TEXT DEFAULT 'tracked24',
            created_at TIMESTAMP DEFAULT NOW(),
            rate_expires TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS order_notes(order_id TEXT PRIMARY KEY, note TEXT)""",
        """CREATE TABLE IF NOT EXISTS order_timeline(
            id SERIAL PRIMARY KEY,
            order_id TEXT, event TEXT,
            created_at TIMESTAMP DEFAULT NOW())""",
        """CREATE TABLE IF NOT EXISTS drop_chats(
            id SERIAL PRIMARY KEY,
            order_id TEXT, user_id BIGINT, sender TEXT,
            message TEXT, created_at TIMESTAMP DEFAULT NOW())""",
        """CREATE TABLE IF NOT EXISTS messages(
            id SERIAL PRIMARY KEY,
            user_id BIGINT, username TEXT,
            vendor_id INTEGER DEFAULT 1,
            message TEXT, reply TEXT,
            created_at TIMESTAMP DEFAULT NOW())""",
        """CREATE TABLE IF NOT EXISTS reviews(
            id SERIAL PRIMARY KEY,
            order_id TEXT UNIQUE, user_id BIGINT,
            vendor_id INTEGER DEFAULT 1,
            product_name TEXT DEFAULT '',
            vendor_name TEXT DEFAULT '',
            stars INTEGER, text TEXT,
            created_at TIMESTAMP DEFAULT NOW())""",
        """CREATE TABLE IF NOT EXISTS announcements(
            id SERIAL PRIMARY KEY,
            vendor_id INTEGER DEFAULT 0,
            title TEXT, body TEXT, photo TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT NOW())""",
        """CREATE TABLE IF NOT EXISTS discount_codes(
            code TEXT PRIMARY KEY, vendor_id INTEGER DEFAULT 1,
            pct REAL, active INTEGER DEFAULT 1, expires TEXT,
            uses INTEGER DEFAULT 0, max_uses INTEGER DEFAULT -1)""",
        """CREATE TABLE IF NOT EXISTS loyalty(
            user_id BIGINT PRIMARY KEY,
            points INTEGER DEFAULT 0, credit REAL DEFAULT 0,
            lifetime INTEGER DEFAULT 0)""",
        """CREATE TABLE IF NOT EXISTS referrals(
            code TEXT PRIMARY KEY, owner_id BIGINT,
            count INTEGER DEFAULT 0, earnings REAL DEFAULT 0)""",
        """CREATE TABLE IF NOT EXISTS review_reminders(
            order_id TEXT PRIMARY KEY, user_id BIGINT, dispatched TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS customer_notes(
            user_id BIGINT PRIMARY KEY, note TEXT)""",
        """CREATE TABLE IF NOT EXISTS wishlist(
            user_id BIGINT, product_id INTEGER,
            PRIMARY KEY(user_id, product_id))""",
        """CREATE TABLE IF NOT EXISTS flash_sales(
            id SERIAL PRIMARY KEY,
            product_id INTEGER UNIQUE, pct REAL,
            expires TIMESTAMP, active INTEGER DEFAULT 1)""",
        """CREATE TABLE IF NOT EXISTS disputes(
            id SERIAL PRIMARY KEY,
            order_id TEXT, user_id BIGINT,
            reason TEXT, reply TEXT DEFAULT '',
            status TEXT DEFAULT 'Open',
            created_at TIMESTAMP DEFAULT NOW())""",
        """CREATE TABLE IF NOT EXISTS vendor_balances(
            vendor_id INTEGER PRIMARY KEY,
            owed REAL DEFAULT 0, paid REAL DEFAULT 0)""",
        """CREATE TABLE IF NOT EXISTS payout_requests(
            id SERIAL PRIMARY KEY,
            vendor_id INTEGER, amount REAL, ltc_addr TEXT,
            status TEXT DEFAULT 'Pending',
            created_at TIMESTAMP DEFAULT NOW())""",
        """CREATE TABLE IF NOT EXISTS ltc_transactions(
            txid TEXT PRIMARY KEY, order_id TEXT,
            amount_ltc REAL, confirmed INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT NOW())""",
        """CREATE TABLE IF NOT EXISTS price_alerts(
            id SERIAL PRIMARY KEY,
            user_id BIGINT, product_id INTEGER,
            target_price REAL, active INTEGER DEFAULT 1)""",
        """CREATE TABLE IF NOT EXISTS bundles(
            id SERIAL PRIMARY KEY,
            vendor_id INTEGER DEFAULT 1, name TEXT,
            description TEXT DEFAULT '', product_ids TEXT,
            price REAL, active INTEGER DEFAULT 1)""",
    ]
    for t in tables:
        try: cur.execute(t); conn.commit()
        except Exception as e: conn.rollback(); print(f"Table error: {e}")

    # Seed default data — ON CONFLICT DO NOTHING = safe on every redeploy
    seeds = [
        ("INSERT INTO admins(user_id,username) VALUES(%s,%s) ON CONFLICT DO NOTHING ON CONFLICT DO NOTHING",
         (7773622161, "owner")),
        ("INSERT INTO vendors(id,name,emoji,description,ltc_addr,commission_pct,admin_user_id) "
         "VALUES(1,%s,%s,%s,%s,10,%s) ON CONFLICT DO NOTHING",
         ("Donny's Shop","🌿","Premium quality. Every time.","ltc1qv4u6vr0gzp9g4lq0g3qev939vdnwxghn5gtnfc",7773622161)),
        ("INSERT INTO discount_codes(code,vendor_id,pct,active) VALUES(%s,1,0.10,1) ON CONFLICT DO NOTHING",
         ("SAVE10",)),
        ("INSERT INTO settings(key,value) VALUES(%s,%s) ON CONFLICT DO NOTHING", ("home_extra","")),
        ("INSERT INTO settings(key,value) VALUES(%s,%s) ON CONFLICT DO NOTHING", ("min_order","0")),
        ("INSERT INTO settings(key,value) VALUES(%s,%s) ON CONFLICT DO NOTHING", ("bulk_threshold","100")),
        ("INSERT INTO settings(key,value) VALUES(%s,%s) ON CONFLICT DO NOTHING", ("bulk_pct","5")),
    ]
    for sql, params in seeds:
        try: cur.execute(sql, params); conn.commit()
        except Exception as e: conn.rollback(); print(f"Seed error: {e}")

    # Auto-increment vendors sequence to avoid id conflicts
    try:
        cur.execute("SELECT setval('vendors_id_seq', GREATEST((SELECT MAX(id) FROM vendors), 1))")
        conn.commit()
    except: conn.rollback()

    conn.close()
    print("✅ Database initialised")

# ── CORE HELPERS ───────────────────────────────────────────────────────────────
def is_admin(uid):        return uid == ADMIN_ID or bool(q1("SELECT 1 FROM admins WHERE user_id=?", (uid,)))
def is_known(uid):        return bool(q1("SELECT 1 FROM users WHERE user_id=?", (uid,)))
def is_banned(uid):       r = q1("SELECT banned FROM users WHERE user_id=?", (uid,)); return bool(r and r.get("banned"))
def get_vendor(uid):      return q1("SELECT * FROM vendors WHERE admin_user_id=? AND active=1", (uid,))
def is_vendor_admin(uid): return not is_admin(uid) and bool(get_vendor(uid))
def get_vid(ctx, uid):
    # 1. If they are a vendor admin, always use their vendor ID
    v = get_vendor(uid)
    if v:
        ctx.user_data["cur_vid"] = v["id"]  # keep in sync
        return v["id"]
    # 2. Platform admin may have selected a vendor
    if ctx.user_data.get("cur_vid"):
        return ctx.user_data["cur_vid"]
    # 3. Default to vendor 1
    return 1
def fq(q): return f"{int(q)}g" if q == int(q) else f"{q}g"
def ft(t):
    ppg = round(t["price"] / t["qty"], 2) if t["qty"] else t["price"]
    return f"⚖️ {fq(t['qty'])} · £{t['price']:.2f} (£{ppg}/g)"
def KM(*rows): return InlineKeyboardMarkup(list(rows))
def back_kb():   return KM([IB("⬅️ Back", "menu")])
def cancel_kb(): return KM([IB("❌ Cancel", "menu")])

def ltc_price(force=False):
    now = time.time()
    if not force and LTC_CACHE["rate"] > 0 and now - LTC_CACHE["ts"] < 120:
        return LTC_CACHE["rate"]
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price?ids=litecoin&vs_currencies=gbp",
            timeout=8).json()["litecoin"]["gbp"]
        LTC_CACHE["rate"] = r; LTC_CACHE["ts"] = now; return r
    except:
        return LTC_CACHE["rate"] if LTC_CACHE["rate"] > 0 else 60.0

def is_open():    n = datetime.now(); return n.weekday() < 6 and n.hour < 11
def open_badge(): return "🟢 <b>Open</b> · Orders close 11am Mon–Sat" if is_open() else "🔴 <b>Closed</b> · Next working day"

def gdisc(code, vid=1):
    r = q1("SELECT pct,expires,uses,max_uses FROM discount_codes WHERE code=? AND active=1 AND vendor_id=?",
            (code.upper(), vid))
    if not r: return None
    if r.get("expires"):
        try:
            if datetime.fromisoformat(r["expires"]) < datetime.now():
                qx("UPDATE discount_codes SET active=0 WHERE code=?", (code.upper(),)); return None
        except: pass
    # UPGRADE 2: Max-use codes
    if r.get("max_uses", -1) != -1 and r.get("uses", 0) >= r["max_uses"]:
        return None
    return r["pct"]

def use_disc(code):
    qx("UPDATE discount_codes SET uses=uses+1 WHERE code=?", (code.upper(),))

def get_loyalty(uid):
    return q1("SELECT points,credit,lifetime FROM loyalty WHERE user_id=?", (uid,)) or \
           {"points": 0, "credit": 0.0, "lifetime": 0}

def add_points(uid, gbp):
    # 25 points flat per order · 500 points = £50 store credit
    pts = 25; lo = get_loyalty(uid)
    np = lo["points"] + pts; lf = lo["lifetime"] + pts
    m = np // 500; cr = m * 50.0; np = np % 500
    qx("INSERT INTO loyalty(user_id,points,credit,lifetime) VALUES(?,?,?,?) "
       "ON CONFLICT(user_id) DO UPDATE SET points=?,credit=credit+?,lifetime=?",
       (uid, np, cr, lf, np, cr, lf))
    return pts, cr

def get_ref(uid):
    r = q1("SELECT code FROM referrals WHERE owner_id=?", (uid,))
    if r: return r["code"]
    c = str(uid)[-4:] + str(uuid4())[:4].upper()
    qx("INSERT INTO referrals(code,owner_id) VALUES(?,?)", (c, uid)); return c

def credit_ref(ref_code, new_uid):
    r = q1("SELECT owner_id,count FROM referrals WHERE code=? AND owner_id!=?", (ref_code, new_uid))
    if not r: return None
    n = r["count"] + 1; qx("UPDATE referrals SET count=? WHERE code=?", (n, ref_code))
    return r["owner_id"], n

def fmt_chat(oid):
    msgs = qa("SELECT sender,message,created_at FROM drop_chats WHERE order_id=? ORDER BY created_at", (oid,))
    if not msgs: return "<i>No messages yet.</i>"
    return "\n\n".join(
        ("<b>👤 You</b>" if m["sender"] == "user" else "<b>🏪 Vendor</b>") +
        f" <i>{str(m['created_at'])[:16]}</i>\n{hl.escape(m['message'])}" for m in msgs)

def add_timeline(oid, event):
    qx("INSERT INTO order_timeline(order_id,event) VALUES(?,?)", (oid, event))

def purge():
    c = (datetime.now() - timedelta(days=30)).isoformat()
    qx("DELETE FROM drop_chats WHERE created_at<?", (c,))
    qx("DELETE FROM cart WHERE created_at<?", (c,))

def credit_vendor_balance(vid, amount):
    qx("INSERT INTO vendor_balances(vendor_id,owed) VALUES(?,?) "
       "ON CONFLICT(vendor_id) DO UPDATE SET owed=owed+?", (vid, amount, amount))

def get_vendor_balance(vid):
    return q1("SELECT owed,paid FROM vendor_balances WHERE vendor_id=?", (vid,)) or \
           {"owed": 0.0, "paid": 0.0}

def vip_label(uid):
    r = q1("SELECT vip_tier FROM users WHERE user_id=?", (uid,))
    tier = r["vip_tier"] if r else "standard"
    for n, em, _ in VIP_LEVELS:
        if tier == n: return f" {em} {n}"
    return ""

def update_vip_tier(uid):
    spend = (q1("SELECT COALESCE(SUM(gbp),0) as s FROM orders WHERE user_id=? AND status IN ('Paid','Dispatched')",
                (uid,)) or {"s": 0})["s"]
    new_tier = "standard"
    for n, em, thresh in VIP_LEVELS:
        if spend >= thresh: new_tier = n; break
    old = (q1("SELECT vip_tier FROM users WHERE user_id=?", (uid,)) or {}).get("vip_tier", "standard")
    if new_tier != old:
        qx("UPDATE users SET vip_tier=? WHERE user_id=?", (new_tier, uid)); return new_tier
    return None

def flash_pct(pid):
    r = q1("SELECT pct,expires FROM flash_sales WHERE product_id=? AND active=1", (pid,))
    if not r: return None
    if r.get("expires"):
        try:
            if datetime.fromisoformat(r["expires"]) < datetime.now():
                qx("UPDATE flash_sales SET active=0 WHERE product_id=?", (pid,)); return None
        except: pass
    return r["pct"]

# ── INVOICE BUILDER ────────────────────────────────────────────────────────────
def build_invoice(order_id):
    o = q1("SELECT * FROM orders WHERE id=?", (order_id,))
    if not o: return None, None
    vendor = q1("SELECT * FROM vendors WHERE id=?", (o["vendor_id"],))
    sep = "━━━━━━━━━━━━━━━━━━━━"
    sl = SHIP.get(o["ship"], {}).get("label", o["ship"])
    needs_ltc = SHIP.get(o["ship"], {}).get("ltc", False)
    rate_txt = ""
    if o.get("rate_expires"):
        try:
            exp = datetime.fromisoformat(str(o["rate_expires"]))
            secs = int((exp - datetime.now()).total_seconds())
            if secs > 0:
                rate_txt = f"\n⏱️ Rate valid: <b>{secs//60}m {secs%60}s</b>"
            else:
                rate_txt = "\n⚠️ Rate may have expired — contact us"
        except: pass
    txt = (f"🧾 <b>INVOICE</b>\n{sep}\n"
           f"🏪 <b>{hl.escape(vendor['name'] if vendor else 'PhiVara')}</b>\n"
           f"<i>via PhiVara Network</i>\n{sep}\n"
           f"📋 Order: <code>{o['id']}</code>\n"
           f"📅 {str(o['created_at'])[:16]}\n{sep}\n"
           f"👤 {hl.escape(o['cust_name'])}\n"
           f"🏠 {hl.escape(o['address'])}\n"
           f"🚚 {sl}\n{sep}\n"
           f"🛍️ {hl.escape(o['summary'])}\n{sep}\n"
           f"💷 <b>Total: £{o['gbp']:.2f}</b>\n")
    if needs_ltc:
        ltc_amt = o.get("ltc", 0)
        ltc_rate = o.get("ltc_rate", 0)
        txt += (f"{sep}\n💎 <b>PAYMENT DETAILS</b>\n{sep}\n"
                f"💠 Send exactly: <b>{ltc_amt:.6f} LTC</b>\n")
        if ltc_rate > 0:
            txt += f"📊 Rate: £{ltc_rate:.2f} per LTC{rate_txt}\n"
        txt += (f"\n📤 <b>Send to:</b>\n<code>{PLATFORM_LTC}</code>\n\n"
                f"⚠️ <i>Exact amount only. Auto-detected on-chain.\n"
                f"Tap below once sent as backup.</i>")
        if o["status"] == "Pending":
            kb = KM([IB("✅ I Have Paid", f"paid_{o['id']}")],
                    [IB("🔄 Refresh Rate", f"refresh_rate_{o['id']}")],
                    [IB("📦 My Orders", "orders")])
        else:
            kb = KM([IB("📦 My Orders", "orders")])
    else:
        txt += f"\n📍 Local drop — arrange pickup below."
        kb = KM([IB("💬 Arrange Pickup", f"dcv_{o['id']}")], [IB("📦 My Orders", "orders")])
    return txt, kb

# ── UI HELPERS ─────────────────────────────────────────────────────────────────
def menu():
    return KM(
        [IB("🏪  Browse Vendors", "vendors")],
        [IB("🧺  Basket", "basket"),      IB("📦  My Orders", "orders")],
        [IB("⭐  Reviews", "reviews_0"),   IB("📢  News", "news")],
        [IB("🎁  Loyalty", "loyalty"),     IB("🔗  Refer & Earn", "my_ref")],
        [IB("❤️  Wishlist", "wishlist"),   IB("🔍  Search", "search_prompt")],
        [IB("💬  Contact", "contact")]
    )

def co_kb(ud):
    n, a, s, dp = ud.get("co_name"), ud.get("co_addr"), ud.get("co_ship"), ud.get("co_disc_pct", 0)
    al = "✅ Address set" if a else ("📍 Not needed" if s == "drop" else "🏠 Enter Address")
    rows = [
        [IB(("✅ " + hl.escape(n)) if n else "👤 Your Name", "co_name")],
        [IB(al, "co_addr")],
        [IB(("✅ " if s == "tracked24" else "") + "📦 Tracked24 (+£5)", "co_ship_tracked24"),
         IB(("✅ " if s == "drop" else "") + "📍 Local Drop (Free)", "co_ship_drop")],
        [IB(("🏷️ " + str(ud.get("co_disc_code", "")) + " ✅") if dp else "🏷️ Discount Code", "co_disc")],
    ]
    if n and s and (a or s == "drop"): rows.append([IB("🛒 Place Order", "co_confirm")])
    rows.append([IB("❌ Cancel", "menu")])
    return InlineKeyboardMarkup(rows)

def co_summary(ud, uid=None):
    s = ud.get("co_ship"); sub = ud.get("co_sub", 0); dp = ud.get("co_disc_pct", 0)
    sp = SHIP[s]["price"] if s else 0; sl = SHIP[s]["label"] if s else "—"
    disc = round(sub * dp, 2)
    # UPGRADE 3: Auto bulk discount
    bulk_thresh = float(gs("bulk_threshold", "100"))
    bulk_pct    = float(gs("bulk_pct", "5"))
    bulk_disc   = round((sub - disc) * bulk_pct / 100, 2) if (sub - disc) >= bulk_thresh else 0
    total = round(sub - disc - bulk_disc + sp, 2)
    addr = ud.get("co_addr") or ("Not required" if s == "drop" else "—")
    dl = (f"🏷️ {ud.get('co_disc_code', '')} -£{disc:.2f}\n") if dp else ""
    bl = f"📦 Bulk deal -£{bulk_disc:.2f}\n" if bulk_disc else ""
    hint = ("📍 <i>Local drop.</i>" if s == "drop" else
            "📦 <i>Enter address above.</i>" if s == "tracked24" else
            "<i>Select delivery method.</i>")
    return (f"🛒 <b>Checkout</b>\n━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 {hl.escape(ud.get('co_name') or '—')}\n"
            f"🏠 {hl.escape(addr)}\n🚚 {sl}\n{dl}{bl}"
            f"━━━━━━━━━━━━━━━━━━━━\n💰 <b>Total: £{total:.2f}</b>\n\n{hint}"), total

def dc_user_kb(oid, closed=False):
    return KM([IB("🔓 Reopen Chat", f"dco_{oid}")], [IB("⬅️ Back", "orders")]) if closed \
        else KM([IB("✉️ Send Message", f"dcm_{oid}")], [IB("🔒 Close Chat", f"dcc_{oid}"), IB("⬅️ Back", "orders")])

def dc_admin_kb(oid):
    return KM([IB("↩️ Reply", f"dcr_{oid}"), IB("🔒 Close", f"dcac_{oid}"), IB("📋 History", f"dch_{oid}")])

async def safe_edit(q, text, **kw):
    try: await q.edit_message_text(text, **kw)
    except:
        try: await q.message.delete()
        except: pass
        await q.message.reply_text(text, **kw)

# ══════════════════════════════════════════════════════════════════════════════
# USER HANDLERS
# ══════════════════════════════════════════════════════════════════════════════
async def cmd_start(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    purge(); uid = u.effective_user.id
    if is_banned(uid): await u.message.reply_text("🚫 You are banned."); return
    is_new = not q1("SELECT 1 FROM users WHERE user_id=?", (uid,))
    qx("INSERT INTO users(user_id,username) VALUES(?,?)",
       (uid, u.effective_user.username or ""))
    if is_new and ctx.args:
        r_ = credit_ref(ctx.args[0], uid)
        if r_:
            owner, cnt = r_
            try: await ctx.bot.send_message(
                owner, "🎉 Referral reward incoming!" if cnt % 15 == 0
                else f"🔗 +1 ref · {cnt} total · {15-(cnt%15)} more for reward")
            except: pass
    name = hl.escape(u.effective_user.first_name or "there")
    vip = vip_label(uid); extra = gs("home_extra"); el = f"\n\n{extra}" if extra else ""
    await u.message.reply_text(
        f"🔷 <b>Welcome, {name}{vip}!</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{open_badge()}\n🕙 <b>Mon–Sat · Orders close 11am</b>\n\n"
        f"Your trusted marketplace.{el}\n\n"
        f"🏪 Verified Vendors · 🔒 Discreet · ⭐ 5-Star\n\n👇 <b>Tap Browse Vendors</b>",
        parse_mode="HTML", reply_markup=menu())

async def show_vendors(u, ctx):
    q = u.callback_query
    vs = qa("SELECT * FROM vendors WHERE active=1 ORDER BY id")
    if not vs: await safe_edit(q, "🏪 No vendors yet.", reply_markup=back_kb()); return
    txt = ("🔷 <b>PhiVara Network</b>\n\nChoose a vendor:\n\n" +
           "".join(f"{v['emoji']} <b>{hl.escape(v['name'])}</b>\n"
                   f"<i>{hl.escape(v['description'])}</i>\n\n" for v in vs))
    await safe_edit(q, txt, parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            [[IB(f"{v['emoji']} {v['name']}", f"vend_{v['id']}")] for v in vs] +
            [[IB("⬅️ Back", "menu")]]))

async def show_vendor(u, ctx):
    q = u.callback_query; vid = int(q.data.split("_")[1])
    v = q1("SELECT * FROM vendors WHERE id=? AND active=1", (vid,))
    if not v: await safe_edit(q, "❌ Vendor not found.", reply_markup=back_kb()); return
    cats = qa("SELECT * FROM categories WHERE vendor_id=? ORDER BY id", (vid,)); kb = []
    featured = qa("SELECT id,name FROM products WHERE hidden=0 AND vendor_id=? AND featured=1 ORDER BY id", (vid,))
    if featured: kb += [[IB(f"⭐ {r['name']}", f"prod_{r['id']}")] for r in featured]
    if cats:
        kb += [[IB(f"{c['emoji']} {c['name']}", f"cat_{c['id']}")] for c in cats]
        unc = qa("SELECT id,name FROM products WHERE hidden=0 AND vendor_id=? AND featured=0 "
                 "AND (category_id=0 OR category_id IS NULL) ORDER BY id", (vid,))
        if unc: kb += [[IB(f"🌿 {r['name']}", f"prod_{r['id']}")] for r in unc]
    else:
        prods = qa("SELECT id,name FROM products WHERE hidden=0 AND vendor_id=? AND featured=0 ORDER BY id", (vid,))
        kb += [[IB(f"🌿 {r['name']}", f"prod_{r['id']}")] for r in prods] or [[IB("No products yet", "noop")]]
    kb += [[IB("⬅️ Back", "vendors")]]
    desc = f"\n<i>{hl.escape(v['description'])}</i>" if v.get("description") else ""
    await safe_edit(q, f"{v['emoji']} <b>{hl.escape(v['name'])}</b>{desc}",
        parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))

async def show_category(u, ctx):
    q = u.callback_query; cid = int(q.data.split("_")[1])
    cat = q1("SELECT * FROM categories WHERE id=?", (cid,))
    if not cat: await safe_edit(q, "❌ Not found.", reply_markup=back_kb()); return
    vid = cat.get("vendor_id", 1)
    prods = qa("SELECT id,name,featured FROM products WHERE hidden=0 AND category_id=? ORDER BY featured DESC,id", (cid,))
    kb = [[IB(("⭐ " if r.get("featured") else "🌿 ") + r["name"], f"prod_{r['id']}")] for r in prods] + \
         [[IB("⬅️ Back", f"vend_{vid}")]]
    await safe_edit(q, f"{cat['emoji']} <b>{hl.escape(cat['name'])}</b>", parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            kb if prods else [[IB("No products here", "noop")], [IB("⬅️ Back", f"vend_{vid}")]]))

async def show_product(u, ctx):
    q = u.callback_query; pid = int(q.data.split("_")[1])
    row = q1("SELECT * FROM products WHERE id=? AND hidden=0", (pid,))
    if not row: await safe_edit(q, "❌ Not available.", reply_markup=back_kb()); return
    # UPGRADE 4: Track product views
    qx("UPDATE products SET views=COALESCE(views,0)+1 WHERE id=?", (pid,))
    tiers = json.loads(row["tiers"]) if row.get("tiers") else TIERS[:]
    vid = row.get("vendor_id", 1); stock = row.get("stock", -1); stock_txt = ""
    if stock == 0:
        await safe_edit(q, f"❌ <b>{hl.escape(row['name'])}</b> is out of stock.", parse_mode="HTML",
            reply_markup=KM([IB("❤️ Wishlist", f"wish_add_{pid}")],
                            [IB("⬅️ Back", f"vend_{vid}")])); return
    elif 0 < stock <= 5: stock_txt = f"\n⚠️ <b>Only {stock} left!</b>"
    fp = flash_pct(pid); flash_txt = ""
    if fp:
        tiers = [{"qty": t["qty"], "price": round(t["price"] * (1 - fp), 2)} for t in tiers]
        flash_txt = f"\n🔥 <b>FLASH SALE — {int(fp*100)}% OFF!</b>"
    # UPGRADE 5: Show product rating
    avg_row = q1("SELECT AVG(stars) as a, COUNT(*) as c FROM reviews WHERE product_name=?", (row["name"],))
    rating_txt = ""
    if avg_row and avg_row.get("c", 0) > 0:
        rating_txt = f"\n⭐ {avg_row['a']:.1f}/5 ({avg_row['c']} reviews)"
    btns = [IB(ft(t), f"pick_{pid}_{t['qty']}_{t['price']}") for t in tiers]
    kb = [btns[i:i+2] for i in range(0, len(btns), 2)] + \
         [[IB("🧺 Basket", "basket"), IB("❤️ Wishlist", f"wish_add_{pid}")],
          [IB("⬅️ Back", f"vend_{vid}")]]
    cap = (("⭐ " if row.get("featured") else "🌿 ") +
           f"<b>{hl.escape(row['name'])}</b>" + flash_txt + stock_txt + rating_txt +
           f"\n\n{hl.escape(row['description'] or '')}\n\n" +
           "".join(ft(t) + "\n" for t in tiers))
    try: await q.message.delete()
    except: pass
    if row.get("photo"):
        await ctx.bot.send_photo(q.message.chat_id, row["photo"],
            caption=cap[:1020], parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
    else:
        await q.message.reply_text(cap[:4000], parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))

async def pick_weight(u, ctx):
    q = u.callback_query; p = q.data.split("_")
    pid, qty, price = int(p[1]), float(p[2]), float(p[3])
    row = q1("SELECT name,vendor_id,stock FROM products WHERE id=? AND hidden=0", (pid,))
    if not row: await q.answer("❌ Not available.", show_alert=True); return
    if row.get("stock", -1) == 0: await q.answer("❌ Out of stock.", show_alert=True); return
    qx("INSERT INTO cart(user_id,product_id,vendor_id,qty,price) VALUES(?,?,?,?,?)",
       (q.from_user.id, pid, row.get("vendor_id", 1), qty, price))
    await q.answer(f"✅ {fq(qty)} of {row['name']} added! (£{price:.2f})", show_alert=True)

async def view_basket(u, ctx):
    q = u.callback_query; uid = q.from_user.id
    items = qa("SELECT cart.id,products.name,cart.qty,cart.price,cart.vendor_id "
               "FROM cart JOIN products ON cart.product_id=products.id "
               "WHERE cart.user_id=? ORDER BY cart.id", (uid,))
    if not items:
        await safe_edit(q, "🧺 Basket empty.",
            reply_markup=KM([IB("🏪 Browse", "vendors")], [IB("⬅️ Back", "menu")])); return
    total = sum(r["price"] for r in items)
    txt = ("🧺 <b>Basket</b>\n━━━━━━━━━━━━━━━━━━━━\n\n" +
           "".join(f"• {hl.escape(r['name'])} {fq(r['qty'])} — £{r['price']:.2f}\n" for r in items) +
           f"\n━━━━━━━━━━━━━━━━━━━━\n💰 <b>Total: £{total:.2f}</b>")
    await safe_edit(q, txt, parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            [[IB(f"🗑️ {r['name']} {fq(r['qty'])}", f"rm_{r['id']}")] for r in items] +
            [[IB("💳 Checkout", "checkout")], [IB("⬅️ Back", "menu")]]))

async def remove_item(u, ctx):
    q = u.callback_query
    qx("DELETE FROM cart WHERE id=? AND user_id=?", (int(q.data.split("_")[1]), q.from_user.id))
    await view_basket(u, ctx)

async def clear_cart(u, ctx):
    q = u.callback_query; qx("DELETE FROM cart WHERE user_id=?", (q.from_user.id,))
    await view_basket(u, ctx)

# ── CHECKOUT ───────────────────────────────────────────────────────────────────
async def checkout_start(u, ctx):
    q = u.callback_query; uid = q.from_user.id
    items = qa("SELECT vendor_id,price FROM cart WHERE user_id=?", (uid,))
    if not items: await safe_edit(q, "🧺 Basket empty.", reply_markup=menu()); return
    vids = list(set(r["vendor_id"] for r in items))
    if len(vids) > 1:
        await safe_edit(q, "⚠️ <b>Mixed vendors</b>\n\nCheckout one vendor at a time.", parse_mode="HTML",
            reply_markup=KM([IB("🗑️ Clear", "clear_cart")], [IB("⬅️ Back", "basket")])); return
    vid = vids[0]
    min_order = float(gs("min_order", "0"))
    sub = round(sum(r["price"] for r in items), 2)
    if min_order > 0 and sub < min_order:
        await safe_edit(q, f"⚠️ Minimum order is <b>£{min_order:.2f}</b>.", parse_mode="HTML",
            reply_markup=back_kb()); return
    ctx.user_data.update({"co_name": None, "co_addr": None, "co_ship": None,
                          "co_disc_code": None, "co_disc_pct": 0,
                          "co_sub": sub, "co_vid": vid, "wf": None})
    t, _ = co_summary(ctx.user_data, uid)
    await safe_edit(q, t, parse_mode="HTML", reply_markup=co_kb(ctx.user_data))

async def co_name_start(u, ctx):
    q = u.callback_query; ctx.user_data["wf"] = "co_name"
    await safe_edit(q, "👤 Enter your full name:", reply_markup=KM([IB("❌ Cancel", "co_refresh")]))

async def co_addr_start(u, ctx):
    q = u.callback_query
    if ctx.user_data.get("co_ship") == "drop":
        await safe_edit(q, "📍 No address needed.",
            reply_markup=KM([IB("⏭️ Skip", "co_addr_skip")], [IB("❌ Cancel", "co_refresh")]))
    else:
        ctx.user_data["wf"] = "co_addr"
        await safe_edit(q, "🏠 Enter delivery address:", reply_markup=KM([IB("❌ Cancel", "co_refresh")]))

async def co_addr_skip(u, ctx):
    q = u.callback_query; ctx.user_data["co_addr"] = ""; ctx.user_data["wf"] = None
    t, _ = co_summary(ctx.user_data, q.from_user.id)
    await safe_edit(q, t, parse_mode="HTML", reply_markup=co_kb(ctx.user_data))

async def co_disc_start(u, ctx):
    q = u.callback_query; ctx.user_data["wf"] = "co_disc"; vid = ctx.user_data.get("co_vid", 1)
    codes = qa("SELECT code,pct FROM discount_codes WHERE active=1 AND vendor_id=?", (vid,))
    hint = ", ".join(f"<code>{r['code']}</code> ({int(r['pct']*100)}% off)" for r in codes) if codes else "None active"
    await safe_edit(q, f"🏷️ Enter discount code:\n{hint}", parse_mode="HTML",
        reply_markup=KM([IB("❌ Cancel", "co_refresh")]))

async def co_ship_cb(u, ctx):
    q = u.callback_query; ctx.user_data["co_ship"] = q.data.split("co_ship_")[1]
    t, _ = co_summary(ctx.user_data, q.from_user.id)
    await safe_edit(q, t, parse_mode="HTML", reply_markup=co_kb(ctx.user_data))

async def co_refresh_cb(u, ctx):
    q = u.callback_query; ctx.user_data["wf"] = None
    t, _ = co_summary(ctx.user_data, q.from_user.id)
    await safe_edit(q, t, parse_mode="HTML", reply_markup=co_kb(ctx.user_data))

async def co_confirm(u, ctx):
    q = u.callback_query; uid = q.from_user.id; ud = ctx.user_data
    name, addr, sk = ud.get("co_name"), ud.get("co_addr") or "", ud.get("co_ship")
    if not name or not sk: await q.answer("⚠️ Enter name and select delivery.", show_alert=True); return
    if sk == "tracked24" and not addr: await q.answer("⚠️ Enter delivery address.", show_alert=True); return
    vid = ud.get("co_vid", 1); vendor = q1("SELECT * FROM vendors WHERE id=?", (vid,))
    if not vendor: await safe_edit(q, "❌ Vendor error.", reply_markup=menu()); return
    items = qa("SELECT products.name,cart.qty,cart.price,cart.product_id FROM cart "
               "JOIN products ON cart.product_id=products.id "
               "WHERE cart.user_id=? AND cart.vendor_id=?", (uid, vid))
    if not items: await safe_edit(q, "🧺 Basket empty.", reply_markup=menu()); return
    summary = ", ".join(r["name"] + " " + fq(r["qty"]) for r in items)
    sub = round(sum(r["price"] for r in items), 2)
    dp = ud.get("co_disc_pct", 0); sp = SHIP[sk]["price"]; needs_ltc = SHIP[sk]["ltc"]
    disc = round(sub * dp, 2)
    bulk_thresh = float(gs("bulk_threshold", "100")); bulk_pct = float(gs("bulk_pct", "5"))
    bulk_disc = round((sub - disc) * bulk_pct / 100, 2) if (sub - disc) >= bulk_thresh else 0
    gbp = round(sub - disc - bulk_disc + sp, 2)
    com = vendor.get("commission_pct", 10) / 100
    platform_gbp = round(gbp * com, 2); vendor_gbp = round(gbp - platform_gbp, 2)
    rate = ltc_price(force=True); ltc = round(gbp / rate, 6) if needs_ltc else 0.0
    rate_expires = (datetime.now() + timedelta(minutes=30)).isoformat() if needs_ltc else None
    oid = str(uuid4())[:8].upper(); addr_disp = addr or "Local Drop"
    qx("INSERT INTO orders(id,user_id,vendor_id,cust_name,address,summary,gbp,"
       "vendor_gbp,platform_gbp,ltc,ltc_rate,ltc_addr,status,ship,rate_expires) "
       "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
       (oid, uid, vid, name, addr_disp, summary, gbp,
        vendor_gbp, platform_gbp, ltc, rate, PLATFORM_LTC, "Pending", sk, rate_expires))
    add_timeline(oid, "Order placed")
    qx("DELETE FROM cart WHERE user_id=? AND vendor_id=?", (uid, vid))
    if ud.get("co_disc_code"): use_disc(ud["co_disc_code"])
    for r in items:
        p = q1("SELECT stock FROM products WHERE id=?", (r["product_id"],))
        if p and p.get("stock", -1) > 0:
            qx("UPDATE products SET stock=stock-1 WHERE id=?", (r["product_id"],))
    if sk == "drop":
        qx("INSERT INTO drop_chats(order_id,user_id,sender,message) VALUES(?,?,?,?)",
           (oid, uid, "vendor", f"👋 Hi {hl.escape(name)}! Order received. Message to arrange pickup."))
    uname = q.from_user.username or str(uid)
    notif = (f"🛒 <b>NEW ORDER — {oid}</b>\n{vendor['emoji']} {hl.escape(vendor['name'])}\n"
             f"👤 {hl.escape(name)} (@{uname}) · 🏠 {hl.escape(addr_disp)}\n"
             f"📦 {summary} · 🚚 {SHIP[sk]['label']} · 💷 £{gbp:.2f}\n"
             f"💰 Vendor: £{vendor_gbp:.2f} · Platform: £{platform_gbp:.2f}")
    try: await ctx.bot.send_message(CHANNEL_ID, notif, parse_mode="HTML")
    except: pass
    adm_kb = InlineKeyboardMarkup(
        [[IB("✅ Confirm", f"adm_ok_{oid}"), IB("❌ Reject", f"adm_no_{oid}")]] +
        ([[IB("💬 Chat", f"dch_{oid}")]] if sk == "drop" else []))
    notify_ids = [ADMIN_ID]
    if vendor.get("admin_user_id") and vendor["admin_user_id"] != ADMIN_ID:
        notify_ids.append(vendor["admin_user_id"])
    for rid in notify_ids:
        try: await ctx.bot.send_message(rid, notif, parse_mode="HTML", reply_markup=adm_kb)
        except: pass
    for k in [k for k in list(ud) if k.startswith("co_")]: ud.pop(k)
    try: await q.message.delete()
    except: pass
    invoice_txt, invoice_kb = build_invoice(oid)
    if invoice_txt:
        await ctx.bot.send_message(uid, invoice_txt, parse_mode="HTML", reply_markup=invoice_kb)

async def refresh_rate_cb(u, ctx):
    q = u.callback_query; oid = q.data.split("_", 2)[2]; uid = q.from_user.id
    o = q1("SELECT * FROM orders WHERE id=? AND user_id=? AND status='Pending'", (oid, uid))
    if not o: await q.answer("❌ Cannot refresh.", show_alert=True); return
    rate = ltc_price(force=True); ltc = round(o["gbp"] / rate, 6)
    rate_expires = (datetime.now() + timedelta(minutes=30)).isoformat()
    qx("UPDATE orders SET ltc=?,ltc_rate=?,rate_expires=? WHERE id=?", (ltc, rate, rate_expires, oid))
    add_timeline(oid, f"Rate refreshed: £{rate:.2f}/LTC = {ltc:.6f} LTC")
    await q.answer("✅ Rate refreshed!", show_alert=True)
    invoice_txt, invoice_kb = build_invoice(oid)
    try: await q.edit_message_text(invoice_txt, parse_mode="HTML", reply_markup=invoice_kb)
    except:
        try: await q.message.delete()
        except: pass
        await ctx.bot.send_message(uid, invoice_txt, parse_mode="HTML", reply_markup=invoice_kb)

async def view_orders(u, ctx):
    q = u.callback_query; uid = q.from_user.id
    rows = qa("SELECT id,gbp,status,ship,summary,vendor_id,ltc FROM orders WHERE user_id=? ORDER BY id DESC", (uid,))
    if not rows:
        await safe_edit(q, "📭 No orders yet!",
            reply_markup=KM([IB("🏪 Browse", "vendors")], [IB("⬅️ Back", "menu")])); return
    sm = {"Pending": ("🕐","Pending"), "Paid": ("✅","Confirmed"),
          "Dispatched": ("🚚","Dispatched"), "Rejected": ("❌","Rejected")}
    txt = "📦 <b>Your Orders</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"; kb = []
    for o in rows:
        icon, lbl = sm.get(o["status"], ("📋", o["status"]))
        dp = "📍" if o["ship"] == "drop" else "📦"
        v = q1("SELECT name,emoji FROM vendors WHERE id=?", (o["vendor_id"],))
        vtxt = (f" · {v['emoji']} {v['name']}") if v else ""
        txt += f"{icon} <b>{o['id']}</b> · {lbl}{vtxt} · {dp} · £{o['gbp']:.2f}\n{hl.escape(o['summary'])}\n\n"
        if o["ship"] == "drop" and o["status"] in ("Pending","Paid","Dispatched"):
            kb.append([IB(("🔒" if gs("cc_"+o["id"],"0")=="1" else "💬") + " Chat — " + o["id"], "dcv_"+o["id"])])
        if o["status"] == "Pending" and o.get("ltc", 0) > 0:
            kb.append([IB(f"🧾 Invoice — {o['id']}", f"show_invoice_{o['id']}")])
        kb.append([IB(f"📍 Track — {o['id']}", f"timeline_{o['id']}")])
    await safe_edit(q, txt[:4000], parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(kb + [[IB("⬅️ Back", "menu")]]))

async def view_timeline(u, ctx):
    q = u.callback_query; oid = q.data.split("_")[1]; uid = q.from_user.id
    if not is_admin(uid) and not q1("SELECT 1 FROM orders WHERE id=? AND user_id=?", (oid, uid)):
        await q.answer("❌ Not found.", show_alert=True); return
    o = q1("SELECT status,gbp,summary,ship,ltc FROM orders WHERE id=?", (oid,))
    events = qa("SELECT event,created_at FROM order_timeline WHERE order_id=? ORDER BY created_at", (oid,))
    txt = (f"📍 <b>Order {oid}</b>\n━━━━━━━━━━━━━━━━━━━━\n"
           f"Status: <b>{o['status']}</b> · 💷 £{o['gbp']:.2f}\n\n")
    txt += "\n".join(f"• {e['event']}\n  <i>{str(e['created_at'])[:16]}</i>" for e in events) if events else "<i>No events yet.</i>"
    kb_rows = []
    if o["status"] == "Pending" and o.get("ltc", 0) > 0:
        kb_rows.append([IB("🧾 View Invoice", f"show_invoice_{oid}")])
    kb_rows.append([IB("⬅️ Back", "orders")])
    await safe_edit(q, txt[:4000], parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb_rows))

async def show_invoice_cb(u, ctx):
    q = u.callback_query; oid = q.data.split("show_invoice_")[1]; uid = q.from_user.id
    if not is_admin(uid) and not q1("SELECT 1 FROM orders WHERE id=? AND user_id=?", (oid, uid)):
        await q.answer("❌ Not found.", show_alert=True); return
    invoice_txt, invoice_kb = build_invoice(oid)
    try: await q.message.delete()
    except: pass
    await ctx.bot.send_message(uid, invoice_txt, parse_mode="HTML", reply_markup=invoice_kb)

async def user_paid(u, ctx):
    q = u.callback_query; oid = q.data[5:]
    row = q1("SELECT ship,cust_name,summary,gbp,ltc,vendor_id FROM orders WHERE id=?", (oid,))
    if not row: await safe_edit(q, "❌ Not found.", reply_markup=back_kb()); return
    sl = SHIP.get(row["ship"], {}).get("label", row["ship"])
    vendor = q1("SELECT admin_user_id FROM vendors WHERE id=?", (row["vendor_id"],))
    notif = (f"💰 <b>MANUAL PAYMENT CLAIM — {oid}</b>\n"
             f"👤 {hl.escape(row['cust_name'])} · {row['summary']}\n"
             f"💷 £{row['gbp']:.2f} · 💠 {row['ltc']:.6f} LTC\n"
             f"📤 Platform: <code>{PLATFORM_LTC}</code>")
    adm_kb = InlineKeyboardMarkup([[IB("✅ Confirm", f"adm_ok_{oid}"), IB("❌ Reject", f"adm_no_{oid}")]])
    notify_ids = [ADMIN_ID]
    if vendor and vendor.get("admin_user_id") and vendor["admin_user_id"] != ADMIN_ID:
        notify_ids.append(vendor["admin_user_id"])
    for rid in notify_ids:
        try: await ctx.bot.send_message(rid, notif, parse_mode="HTML", reply_markup=adm_kb)
        except: pass
    await safe_edit(q,
        f"⏳ <b>Payment Submitted</b>\n━━━━━━━━━━━━━━━━━━━━\n"
        f"📋 Order <code>{oid}</code>\n🛍️ {hl.escape(row['summary'])}\n"
        f"🚚 {sl} · 💷 £{row['gbp']:.2f}\n"
        f"💠 {row['ltc']:.6f} LTC → <code>{PLATFORM_LTC}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n✅ Awaiting verification.",
        parse_mode="HTML", reply_markup=KM([IB("📦 My Orders", "orders")]))

# ── REVIEWS — UPGRADE 6: Store vendor name + product name ─────────────────────
async def show_reviews(u, ctx):
    q = u.callback_query; page = int(q.data.split("_")[1])
    ms = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
    total = q1("SELECT COUNT(*) as c FROM reviews WHERE created_at>=?", (ms,))["c"]
    rows = qa("SELECT stars,text,vendor_name,product_name FROM reviews "
              "WHERE created_at>=? ORDER BY created_at DESC LIMIT ? OFFSET ?",
              (ms, RPP, page * RPP))
    if not rows and page == 0:
        await safe_edit(q, "💬 No reviews this month yet.", reply_markup=back_kb()); return
    txt = f"⭐ <b>Reviews of the Month</b> ({total})\n\n"
    for r in rows:
        vn = hl.escape(r.get("vendor_name","")) if r.get("vendor_name") else ""
        pn = hl.escape(r.get("product_name","")) if r.get("product_name") else ""
        meta = ""
        if vn and pn: meta = f"🏪 {vn} · 🌿 {pn}\n"
        elif vn:      meta = f"🏪 {vn}\n"
        txt += f"{STARS.get(r['stars'],'')} {meta}{hl.escape(r['text'])}\n\n"
    pages = (total - 1) // RPP if total else 0
    nav = ([IB("◀️", f"reviews_{page-1}")] if page > 0 else []) + \
          ([IB("▶️", f"reviews_{page+1}")] if page < pages else [])
    await safe_edit(q, txt[:4000], parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(([nav] if nav else []) + [[IB("⬅️ Back", "menu")]]))

async def review_start(u, ctx):
    q = u.callback_query; oid = q.data[7:]
    if not q1("SELECT 1 FROM orders WHERE id=? AND user_id=? AND status IN ('Paid','Dispatched')",
              (oid, q.from_user.id)):
        await q.answer("⚠️ Not eligible.", show_alert=True); return
    ctx.user_data["rev_order"] = oid
    await safe_edit(q, "⭐ Rate your order:",
        reply_markup=KM([IB("⭐ 1","stars_1"),IB("⭐⭐ 2","stars_2"),IB("⭐⭐⭐ 3","stars_3")],
                        [IB("⭐⭐⭐⭐ 4","stars_4"),IB("⭐⭐⭐⭐⭐ 5","stars_5")],
                        [IB("❌ Cancel","menu")]))

async def pick_stars(u, ctx):
    q = u.callback_query; s = int(q.data.split("_")[1])
    ctx.user_data.update({"rev_stars": s, "wf": "review_text"})
    await safe_edit(q, f"✨ {STARS[s]}\n\n✏️ Write your review:", parse_mode="HTML", reply_markup=cancel_kb())

# ── WISHLIST ───────────────────────────────────────────────────────────────────
async def view_wishlist(u, ctx):
    q = u.callback_query; uid = q.from_user.id
    items = qa("SELECT products.id,products.name FROM wishlist "
               "JOIN products ON wishlist.product_id=products.id "
               "WHERE wishlist.user_id=? AND products.hidden=0", (uid,))
    if not items: await safe_edit(q, "❤️ Wishlist empty.", reply_markup=back_kb()); return
    txt = "❤️ <b>Your Wishlist</b>\n\n" + "".join(f"• {hl.escape(r['name'])}\n" for r in items)
    kb = [[IB(f"🌿 {r['name']}", f"prod_{r['id']}"), IB("🗑️", f"wish_rm_{r['id']}")] for r in items] + \
         [[IB("⬅️ Back", "menu")]]
    await safe_edit(q, txt, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))

async def wishlist_add(u, ctx):
    q = u.callback_query; uid = q.from_user.id; pid = int(q.data.split("_")[2])
    qx("INSERT INTO wishlist(user_id,product_id) VALUES(?,?)", (uid, pid))
    await q.answer("❤️ Added to wishlist!", show_alert=True)

async def wishlist_rm(u, ctx):
    q = u.callback_query; uid = q.from_user.id; pid = int(q.data.split("_")[2])
    qx("DELETE FROM wishlist WHERE user_id=? AND product_id=?", (uid, pid))
    await view_wishlist(u, ctx)

# ── NEWS / LOYALTY / REF ───────────────────────────────────────────────────────
async def show_news(u, ctx):
    q = u.callback_query
    rows = qa("SELECT id,title,body,photo,created_at FROM announcements ORDER BY id DESC LIMIT 5")
    if not rows: await safe_edit(q, "📢 No announcements yet.", reply_markup=back_kb()); return
    first = rows[0]
    txt = (f"📢 <b>{hl.escape(first['title'])}</b>\n\n{hl.escape(first['body'])}\n"
           f"<i>{str(first['created_at'])[:10]}</i>")
    if len(rows) > 1:
        txt += "\n\n<b>Previous:</b>\n" + \
               "".join(f"• {hl.escape(r['title'])} <i>{str(r['created_at'])[:10]}</i>\n" for r in rows[1:])
    kb = InlineKeyboardMarkup([[IB("⬅️ Back", "menu")]])
    if first.get("photo"):
        try: await q.message.delete()
        except: pass
        await ctx.bot.send_photo(q.message.chat_id, first["photo"],
            caption=txt[:1020], parse_mode="HTML", reply_markup=kb)
    else:
        await safe_edit(q, txt[:4000], parse_mode="HTML", reply_markup=kb)

async def show_loyalty(u, ctx):
    q = u.callback_query; uid = q.from_user.id; lo = get_loyalty(uid); pts = lo["points"]
    bar = "█" * (pts // 50) + "░" * (10 - pts // 50)
    remaining = 500 - pts; orders_needed = -(-remaining // 25)  # ceiling division
    await safe_edit(q,
        f"🎁 <b>Loyalty Rewards</b>\n━━━━━━━━━━━━━━━━━━━━{vip_label(uid)}\n\n"
        f"⭐ <b>{pts}/500 pts</b>\n[{bar}]\n"
        f"{remaining} more pts = <b>£50 store credit</b>\n"
        f"(~{orders_needed} more orders)\n\n"
        f"💳 Available credit: <b>£{lo['credit']:.2f}</b>\n"
        f"🏆 Lifetime pts: <b>{lo['lifetime']}</b>\n\n"
        f"<i>25 pts per order · 500 pts = £50 credit</i>",
        parse_mode="HTML", reply_markup=back_kb())

async def show_my_ref(u, ctx):
    q = u.callback_query; uid = q.from_user.id; rc = get_ref(uid)
    cnt = (q1("SELECT count FROM referrals WHERE owner_id=?", (uid,)) or {}).get("count", 0)
    nxt = 15 - (cnt % 15) if cnt % 15 else 15
    bn = (await ctx.bot.get_me()).username
    await safe_edit(q,
        f"🔗 <b>Your Referral Link</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<code>https://t.me/{bn}?start={rc}</code>\n\n"
        f"👥 <b>{cnt}</b> referred · {nxt} more = FREE reward 🎁",
        parse_mode="HTML", reply_markup=back_kb())

async def search_prompt(u, ctx):
    q = u.callback_query; ctx.user_data["wf"] = "search"
    await safe_edit(q, "🔍 Enter search term:", reply_markup=cancel_kb())

async def contact_start(u, ctx):
    q = u.callback_query
    vs = qa("SELECT id,name,emoji FROM vendors WHERE active=1 ORDER BY id")
    if len(vs) == 1:
        ctx.user_data.update({"wf": "contact", "contact_vid": vs[0]["id"]})
        await safe_edit(q, "💬 Type your message:", reply_markup=cancel_kb()); return
    await safe_edit(q, "💬 Contact which vendor?",
        reply_markup=InlineKeyboardMarkup(
            [[IB(f"{v['emoji']} {v['name']}", f"contact_vid_{v['id']}")] for v in vs] +
            [[IB("⬅️ Back", "menu")]]))

async def contact_vendor(u, ctx):
    q = u.callback_query; vid = int(q.data.split("_")[2])
    ctx.user_data.update({"wf": "contact", "contact_vid": vid})
    await safe_edit(q, "💬 Type your message:", reply_markup=cancel_kb())

# ── DROP CHAT ──────────────────────────────────────────────────────────────────
async def dropchat_view(u, ctx):
    q = u.callback_query; oid = q.data[4:]; closed = gs("cc_"+oid, "0") == "1"
    o = q1("SELECT summary,gbp FROM orders WHERE id=?", (oid,))
    hdr = (f"💬 <b>Drop Chat — Order {oid}</b>\n━━━━━━━━━━━━━━━━━━━━\n" +
           (f"🛍️ {hl.escape(o['summary'])} · 💷 £{o['gbp']:.2f}\n" if o else "") +
           ("🔒 <i>Chat closed.</i>\n" if closed else "") +
           "━━━━━━━━━━━━━━━━━━━━\n\n")
    try: await q.message.delete()
    except: pass
    await q.message.reply_text(f"{hdr}{fmt_chat(oid)}"[:4000], parse_mode="HTML",
        reply_markup=dc_user_kb(oid, closed))

async def dropchat_msg_start(u, ctx):
    q = u.callback_query; oid = q.data[4:]
    ctx.user_data.update({"dc_oid": oid, "wf": "drop_msg_user"})
    try: await q.message.delete()
    except: pass
    await q.message.reply_text(f"💬 <b>Order {oid}</b>\n\n✉️ Type your message:",
        parse_mode="HTML", reply_markup=KM([IB("❌ Cancel", f"dcv_{oid}")]))

async def dropchat_reply_start(u, ctx):
    q = u.callback_query; uid = q.from_user.id
    if not is_admin(uid) and not is_vendor_admin(uid): return
    oid = q.data[4:]; ctx.user_data.update({"dc_oid": oid, "wf": "drop_msg_admin"})
    o = q1("SELECT cust_name FROM orders WHERE id=?", (oid,))
    await safe_edit(q,
        f"↩️ Reply to {oid}" + (f" — {hl.escape(o['cust_name'])}" if o else "") +
        f"\n━━━━━━━━━━━━━━━━━━━━\n\n{fmt_chat(oid)}\n\n✏️ Type reply:",
        parse_mode="HTML", reply_markup=KM([IB("❌ Cancel", "menu")]))

async def dropchat_history(u, ctx):
    q = u.callback_query; uid = q.from_user.id
    if not is_admin(uid) and not is_vendor_admin(uid): return
    oid = q.data[4:]; closed = gs("cc_"+oid, "0") == "1"
    o = q1("SELECT cust_name,summary,gbp FROM orders WHERE id=?", (oid,))
    note = q1("SELECT note FROM order_notes WHERE order_id=?", (oid,))
    hdr = (f"📋 <b>Chat {oid}</b>" +
           (f"\n👤 {hl.escape(o['cust_name'])} | {o['summary']} | 💷 £{o['gbp']:.2f}" if o else "") +
           (f"\n📝 {hl.escape(note['note'])}" if note else ""))
    await safe_edit(q, f"{hdr}\n━━━━━━━━━━━━━━━━━━━━\n\n{fmt_chat(oid)}"[:4000],
        parse_mode="HTML",
        reply_markup=dc_admin_kb(oid) if not closed else KM([IB("🔓 Reopen", f"dco_{oid}")]))

async def dropchat_close(u, ctx):
    q = u.callback_query; oid = q.data.split("_", 1)[1]; ss("cc_"+oid, "1")
    r = q1("SELECT user_id FROM orders WHERE id=?", (oid,))
    if r:
        try: await ctx.bot.send_message(r["user_id"], f"🔒 Chat {oid} closed.", reply_markup=menu())
        except: pass
    await safe_edit(q, "🔒 Closed.",
        reply_markup=KM([IB("🔓 Reopen", f"dco_{oid}"), IB("⬅️ Back", "menu")]))

async def dropchat_open(u, ctx):
    q = u.callback_query; oid = q.data[4:]; ss("cc_"+oid, "0")
    await safe_edit(q, f"🔓 Chat {oid} reopened.\n\n{fmt_chat(oid)}",
        parse_mode="HTML", reply_markup=dc_user_kb(oid, False))

# ══════════════════════════════════════════════════════════════════════════════
# ADMIN PANEL — UPGRADE 7: Full expanded panel with all buttons
# ══════════════════════════════════════════════════════════════════════════════
async def cmd_admin(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = u.effective_user.id
    # FIX: Always register admin/vendor-admin in users table so message flows work
    qx("INSERT INTO users(user_id,username) VALUES(?,?)",
       (uid, u.effective_user.username or ""))
    if is_vendor_admin(uid):
        v = get_vendor(uid); ctx.user_data["cur_vid"] = v["id"]
        await _vendor_panel(u.message, v); return
    if not is_admin(uid): return
    await _platform_panel(u.message)

async def _platform_panel(msg):
    orders = qa("SELECT id,status,ship FROM orders ORDER BY id DESC LIMIT 30")
    unread = q1("SELECT COUNT(*) as c FROM messages WHERE reply IS NULL")["c"]
    drops = len([o for o in orders if o["ship"] == "drop" and o["status"] in ("Pending","Paid")])
    pending = [o for o in orders if o["status"] == "Pending"]
    paid_tracked = [o for o in orders if o["status"] == "Paid" and o["ship"] != "drop"]
    kb = []
    if pending:
        kb += [[IB(f"✅ {o['id']}", f"adm_ok_{o['id']}"), IB(f"❌ {o['id']}", f"adm_no_{o['id']}")] for o in pending]
    if paid_tracked:
        kb += [[IB(f"🚚 {o['id']}", f"adm_go_{o['id']}")] for o in paid_tracked]
    kb += [
        [IB("➕ Add Product","adm_addprod_go"), IB("🗑️ Remove","adm_rmprod"),    IB("✏️ Edit Desc","adm_editdesc")],
        [IB("⚖️ Tiers","adm_tiers"),           IB("👁️ Hide/Show","adm_hideprod"), IB("📂 Categories","adm_cats")],
        [IB("⭐ Feature","adm_feature"),        IB("📦 Stock","adm_stock"),        IB("🔥 Flash Sale","adm_flash")],
        [IB("🏷️ Discounts","adm_discounts"),   IB("📢 Announce","adm_announce"),  IB("📊 Stats","adm_stats")],
        [IB("🏪 Vendors","adm_vendors"),        IB("➕ Add Vendor","adm_addvendor"),IB("💠 LTC Check","ltccheck_btn")],
        [IB(f"💬 Msgs{(' ('+str(unread)+')') if unread else ''}","adm_msgs"),
         IB(f"📍 Drops{(' ('+str(drops)+')') if drops else ''}","adm_drops"),
         IB("📊 Reviews","adm_rev_0")],
        [IB("💰 Payouts","adm_payouts"),        IB("⚠️ Disputes","adm_disputes"), IB("🚫 Bans","adm_bans")],
        [IB("👥 Admins","adm_admins"),          IB("🏠 Edit Home","adm_edit_home"),IB("📝 Cust Notes","adm_custnotes")],
        [IB("⚙️ Settings","adm_settings"),      IB("📈 Weekly Report","adm_report")],
    ]
    await msg.reply_text("🔷 <b>PhiVara Network — Admin v5.0</b>",
        parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))

async def _vendor_panel(msg, v):
    vid = v["id"]
    orders = qa("SELECT id,status,ship FROM orders WHERE vendor_id=? ORDER BY id DESC LIMIT 30", (vid,))
    unread = q1("SELECT COUNT(*) as c FROM messages WHERE reply IS NULL AND vendor_id=?", (vid,))["c"]
    drops = len([o for o in orders if o["ship"] == "drop" and o["status"] in ("Pending","Paid")])
    pending = [o for o in orders if o["status"] == "Pending"]
    paid_tracked = [o for o in orders if o["status"] == "Paid" and o["ship"] != "drop"]
    bal = get_vendor_balance(vid); kb = []
    if pending:
        kb += [[IB(f"✅ {o['id']}", f"adm_ok_{o['id']}"), IB(f"❌ {o['id']}", f"adm_no_{o['id']}")] for o in pending]
    if paid_tracked:
        kb += [[IB(f"🚚 {o['id']}", f"adm_go_{o['id']}")] for o in paid_tracked]
    kb += [
        [IB("➕ Add Product","adm_addprod_go"), IB("🗑️ Remove","adm_rmprod"),
         IB("✏️ Edit Desc","adm_editdesc"),    IB("⚖️ Tiers","adm_tiers")],
        [IB("👁️ Hide/Show","adm_hideprod"),    IB("📂 Categories","adm_cats"),
         IB("⭐ Feature","adm_feature"),        IB("📦 Stock","adm_stock")],
        [IB("🔥 Flash Sale","adm_flash"),       IB("🏷️ Discounts","adm_discounts"),
         IB("📢 Announce","adm_announce"),      IB("📊 Stats","adm_stats")],
        [IB(f"💬 Msgs{(' ('+str(unread)+')') if unread else ''}","adm_msgs"),
         IB(f"📍 Drops{(' ('+str(drops)+')') if drops else ''}","adm_drops"),
         IB("📊 Reviews","adm_rev_0")],
        [IB(f"💰 Balance £{bal['owed']:.2f}","vendor_balance"),
         IB("📤 Request Payout","vendor_payout_req")],
    ]
    await msg.reply_text(f"{v['emoji']} <b>{hl.escape(v['name'])} — Vendor Panel</b>\nPhiVara Network v5.0",
        parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))

# ── ADMIN ACTIONS ──────────────────────────────────────────────────────────────
async def adm_confirm(u, ctx):
    q = u.callback_query; oid = q.data[7:]
    qx("UPDATE orders SET status='Paid' WHERE id=?", (oid,))
    add_timeline(oid, "Payment confirmed by admin")
    r = q1("SELECT user_id,ship,gbp,vendor_id FROM orders WHERE id=?", (oid,))
    if r:
        vg = (q1("SELECT vendor_gbp FROM orders WHERE id=?", (oid,)) or {}).get("vendor_gbp", 0)
        credit_vendor_balance(r["vendor_id"], vg)
        pts, cr = add_points(r["user_id"], r.get("gbp", 0))
        new_tier = update_vip_tier(r["user_id"])
        lnote = f"\n🎁 +{pts} pts!" + (f" 💳 £{int(cr)} credit!" if cr else "")
        if new_tier: lnote += f"\n🏆 VIP upgrade: {new_tier}!"
        try:
            if r["ship"] == "drop":
                await ctx.bot.send_message(r["user_id"],
                    f"✅ <b>Order {oid} confirmed!</b> Open Drop Chat to arrange.{lnote}",
                    parse_mode="HTML", reply_markup=KM([IB("💬 Drop Chat", f"dcv_{oid}")]))
            else:
                await ctx.bot.send_message(r["user_id"],
                    f"✅ Payment confirmed — <code>{oid}</code>! 🌟{lnote}",
                    parse_mode="HTML", reply_markup=KM([IB("⭐ Leave Review", f"review_{oid}")]))
        except: pass
    await safe_edit(q, f"✅ Order {oid} confirmed.")

async def adm_reject(u, ctx):
    q = u.callback_query; oid = q.data[7:]
    qx("UPDATE orders SET status='Rejected' WHERE id=?", (oid,))
    add_timeline(oid, "Order rejected")
    r = q1("SELECT user_id FROM orders WHERE id=?", (oid,))
    if r:
        try: await ctx.bot.send_message(r["user_id"], f"❌ Order <code>{oid}</code> rejected.", parse_mode="HTML")
        except: pass
    await safe_edit(q, f"❌ Rejected {oid}.")

async def adm_dispatch(u, ctx):
    q = u.callback_query; oid = q.data[7:]
    qx("UPDATE orders SET status='Dispatched' WHERE id=?", (oid,))
    add_timeline(oid, "Order dispatched")
    r = q1("SELECT user_id,summary FROM orders WHERE id=?", (oid,))
    if r:
        o = q1("SELECT * FROM orders WHERE id=?", (oid,))
        vendor = q1("SELECT name,emoji FROM vendors WHERE id=?", (o["vendor_id"],))
        sep = "━━━━━━━━━━━━━━━━━━━━"
        receipt = (f"🚚 <b>ORDER DISPATCHED</b>\n{sep}\n"
                   f"📋 Order <code>{oid}</code>\n"
                   f"🏪 {hl.escape(vendor['name'] if vendor else 'PhiVara')}\n{sep}\n"
                   f"📦 {hl.escape(o['summary'])}\n"
                   f"🏠 {hl.escape(o['address'])}\n"
                   f"🚚 {SHIP.get(o['ship'],{}).get('label',o['ship'])}\n{sep}\n"
                   f"💷 £{o['gbp']:.2f} — <b>PAID ✅</b>\n{sep}\n"
                   f"📬 <i>Your order is on its way!</i>")
        try:
            await ctx.bot.send_message(r["user_id"], receipt, parse_mode="HTML",
                reply_markup=KM([IB("⭐ Leave Review", f"review_{oid}")], [IB("📦 My Orders", "orders")]))
        except: pass
        qx("INSERT INTO review_reminders(order_id,user_id,dispatched) VALUES(?,?,?)",
           (oid, r["user_id"], datetime.now().isoformat()))
    await safe_edit(q, f"🚚 Dispatched {oid}.")

async def adm_stats(u, ctx):
    q = u.callback_query; uid = q.from_user.id
    if is_vendor_admin(uid):
        vid = get_vid(ctx, uid); bal = get_vendor_balance(vid)
        tot = q1("SELECT COUNT(*) as c,COALESCE(SUM(gbp),0) as s,COALESCE(SUM(vendor_gbp),0) as v "
                 "FROM orders WHERE vendor_id=? AND status IN ('Paid','Dispatched')", (vid,)) or {"c":0,"s":0,"v":0}
        td  = q1("SELECT COUNT(*) as c,COALESCE(SUM(gbp),0) as s FROM orders WHERE vendor_id=? "
                 "AND status IN ('Paid','Dispatched') AND created_at>=?",
                 (vid, datetime.now().strftime("%Y-%m-%d"))) or {"c":0,"s":0}
        top = qa("SELECT summary,COUNT(*) as c FROM orders WHERE vendor_id=? "
                 "AND status IN ('Paid','Dispatched') GROUP BY summary ORDER BY c DESC LIMIT 3", (vid,))
        top_txt = "\n".join(f"  • {hl.escape(t['summary'][:40])} ({t['c']}x)" for t in top) or "  None yet"
        txt = (f"📊 <b>Vendor Stats</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
               f"📦 Total: <b>{tot['c']}</b> · 💷 £{tot['s']:.2f}\n"
               f"💰 Your earnings: <b>£{tot['v']:.2f}</b>\n"
               f"☀️ Today: <b>{td['c']}</b> · 💷 £{td['s']:.2f}\n\n"
               f"💳 Balance owed: <b>£{bal['owed']:.2f}</b>\n"
               f"✅ Paid out: <b>£{bal['paid']:.2f}</b>\n\n"
               f"🔥 <b>Top Items:</b>\n{top_txt}")
    else:
        tot   = q1("SELECT COUNT(*) as c,COALESCE(SUM(gbp),0) as s,COALESCE(SUM(platform_gbp),0) as p "
                   "FROM orders WHERE status IN ('Paid','Dispatched')") or {"c":0,"s":0,"p":0}
        td    = q1("SELECT COUNT(*) as c,COALESCE(SUM(gbp),0) as s FROM orders "
                   "WHERE status IN ('Paid','Dispatched') AND created_at>=?",
                   (datetime.now().strftime("%Y-%m-%d"),)) or {"c":0,"s":0}
        pend  = q1("SELECT COUNT(*) as c FROM orders WHERE status='Pending'") or {"c":0}
        users = q1("SELECT COUNT(*) as c FROM users") or {"c":0}
        rate  = ltc_price()
        txt = (f"📊 <b>Platform Stats</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
               f"📦 Total Orders: <b>{tot['c']}</b> · 💷 £{tot['s']:.2f}\n"
               f"💰 Platform commission: <b>£{tot['p']:.2f}</b>\n"
               f"☀️ Today: <b>{td['c']}</b> · 💷 £{td['s']:.2f}\n"
               f"⏳ Pending: <b>{pend['c']}</b>\n"
               f"👥 Total users: <b>{users['c']}</b>\n"
               f"💠 LTC rate: £{rate:.2f}")
    await safe_edit(q, txt, parse_mode="HTML", reply_markup=back_kb())

# UPGRADE 8: Platform settings panel
async def adm_settings_cb(u, ctx):
    q = u.callback_query
    if not is_admin(u.effective_user.id): return
    await safe_edit(q,
        f"⚙️ <b>Platform Settings</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📦 Min order: <b>£{gs('min_order','0')}</b>\n"
        f"🛒 Bulk threshold: <b>£{gs('bulk_threshold','100')}</b>\n"
        f"💸 Bulk discount: <b>{gs('bulk_pct','5')}%</b>\n\n"
        f"<b>To change, use:</b>\n"
        f"/set min_order VALUE\n"
        f"/set bulk_threshold VALUE\n"
        f"/set bulk_pct VALUE",
        parse_mode="HTML", reply_markup=back_kb())

# UPGRADE 9: Weekly report
async def adm_report_cb(u, ctx):
    q = u.callback_query
    if not is_admin(u.effective_user.id): return
    week_ago = (datetime.now() - timedelta(days=7))
    orders = q1("SELECT COUNT(*) as c,COALESCE(SUM(gbp),0) as s,COALESCE(SUM(platform_gbp),0) as p "
                "FROM orders WHERE status IN ('Paid','Dispatched') AND created_at>=?", (week_ago,)) or {"c":0,"s":0,"p":0}
    new_users = q1("SELECT COUNT(*) as c FROM users WHERE joined>=?", (week_ago,)) or {"c":0}
    top = qa("SELECT summary,COUNT(*) as c FROM orders WHERE status IN ('Paid','Dispatched') "
             "AND created_at>=? GROUP BY summary ORDER BY c DESC LIMIT 5", (week_ago,))
    top_txt = "\n".join(f"  • {hl.escape(t['summary'][:40])} ({t['c']}x)" for t in top) or "  None"
    txt = (f"📈 <b>Weekly Report</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
           f"📦 Orders: <b>{orders['c']}</b>\n💷 Revenue: <b>£{orders['s']:.2f}</b>\n"
           f"💰 Platform: <b>£{orders['p']:.2f}</b>\n👥 New users: <b>{new_users['c']}</b>\n\n"
           f"🔥 <b>Top Sellers:</b>\n{top_txt}")
    await safe_edit(q, txt, parse_mode="HTML", reply_markup=back_kb())

async def ltccheck_btn_cb(u, ctx):
    q = u.callback_query
    if not is_admin(u.effective_user.id): return
    try:
        data = requests.get(f"https://api.blockcypher.com/v1/ltc/main/addrs/{PLATFORM_LTC}/balance", timeout=10).json()
        bal_ltc = data.get("balance", 0) / 100000000
        unconf  = data.get("unconfirmed_balance", 0) / 100000000
        rate    = ltc_price()
        await safe_edit(q,
            f"💠 <b>Platform Wallet</b>\n━━━━━━━━━━━━━━━━━━━━\n"
            f"<code>{PLATFORM_LTC}</code>\n\n"
            f"✅ Confirmed: <b>{bal_ltc:.6f} LTC</b> (≈ £{bal_ltc*rate:.2f})\n"
            f"⏳ Unconfirmed: <b>{unconf:.6f} LTC</b>\n"
            f"📊 Rate: £{rate:.2f}/LTC",
            parse_mode="HTML", reply_markup=back_kb())
    except Exception as e:
        await safe_edit(q, f"❌ Could not fetch: {e}", reply_markup=back_kb())

async def adm_vendors(u, ctx):
    q = u.callback_query
    if not is_admin(u.effective_user.id): return
    vs = qa("SELECT * FROM vendors ORDER BY id")
    txt = ("🏪 <b>Vendors</b>\n\n" +
           "".join(("✅" if v["active"] else "❌") +
                   f" <b>{v['emoji']} {hl.escape(v['name'])}</b> · #{v['id']} · {v['commission_pct']}%\n"
                   f"Admin: <code>{v['admin_user_id']}</code>\n\n" for v in vs))
    kb = [[IB(("🚫 Disable" if v["active"] else "✅ Enable") + " " + v["name"], f"togglevend_{v['id']}")] for v in vs] + \
         [[IB("➕ Add Vendor", "adm_addvendor")], [IB("⬅️ Back", "menu")]]
    await safe_edit(q, txt[:4000], parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))

async def adm_addvendor_start(u, ctx):
    q = u.callback_query
    if not is_admin(u.effective_user.id): return
    ctx.user_data["wf"] = "add_vendor"
    await safe_edit(q,
        "🏪 Add Vendor:\n<code>Name|🌿|Description|ltc_addr|commission_%|admin_user_id</code>\n\n"
        "<i>All customer payments route to platform wallet.\n"
        "Vendor ltc_addr used for payouts only.</i>",
        parse_mode="HTML", reply_markup=cancel_kb())

async def adm_togglevend(u, ctx):
    q = u.callback_query
    if not is_admin(u.effective_user.id): return
    vid = int(q.data.split("_")[1]); v = q1("SELECT active FROM vendors WHERE id=?", (vid,))
    if v: qx("UPDATE vendors SET active=? WHERE id=?", (0 if v["active"] else 1, vid))
    await adm_vendors(u, ctx)

async def adm_msgs(u, ctx):
    q = u.callback_query; uid = q.from_user.id
    if not is_admin(uid) and not is_vendor_admin(uid): return
    vid = get_vid(ctx, uid)
    rows = qa("SELECT id,username,message,reply FROM messages WHERE vendor_id=? ORDER BY id DESC LIMIT 15", (vid,))
    if not rows: await safe_edit(q, "📭 No messages.", reply_markup=back_kb()); return
    txt = ("💬 <b>Messages</b>\n\n" +
           "".join(("✅" if r["reply"] else "⏳") +
                   f" #{r['id']} @{r['username'] or '?'}\n{hl.escape(r['message'][:70])}\n/reply {r['id']}\n\n"
                   for r in rows))
    await safe_edit(q, txt[:4000], parse_mode="HTML", reply_markup=back_kb())

async def adm_rev_cb(u, ctx):
    q = u.callback_query
    if not is_admin(u.effective_user.id) and not is_vendor_admin(u.effective_user.id): return
    page = int(q.data.split("adm_rev_")[1])
    total = q1("SELECT COUNT(*) as c FROM reviews")["c"]
    rows = qa("SELECT stars,text,vendor_name,product_name,created_at FROM reviews "
              "ORDER BY created_at DESC LIMIT ? OFFSET ?", (RPP, page * RPP))
    if not rows and page == 0: await safe_edit(q, "📭 No reviews.", reply_markup=back_kb()); return
    txt = f"📊 <b>All Reviews</b> ({total})\n\n"
    for r in rows:
        meta = ""
        if r.get("vendor_name"): meta += f"🏪 {hl.escape(r['vendor_name'])}"
        if r.get("product_name"): meta += f" · 🌿 {hl.escape(r['product_name'])}"
        if meta: meta = meta.strip() + "\n"
        txt += f"{STARS.get(r['stars'],'')} · {str(r['created_at'])[:10]}\n{meta}{hl.escape(r['text'])}\n\n"
    pages = (total - 1) // RPP if total else 0
    nav = ([IB("◀️", f"adm_rev_{page-1}")] if page > 0 else []) + \
          ([IB("▶️", f"adm_rev_{page+1}")] if page < pages else [])
    await safe_edit(q, txt[:4000], parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(([nav] if nav else []) + [[IB("⬅️ Back", "menu")]]))

async def adm_drops(u, ctx):
    q = u.callback_query; uid = q.from_user.id
    if not is_admin(uid) and not is_vendor_admin(uid): return
    vid = get_vid(ctx, uid)
    rows = qa("SELECT o.id,o.cust_name,o.status,"
              "(SELECT COUNT(*) FROM drop_chats d WHERE d.order_id=o.id) as msgs "
              "FROM orders o WHERE o.ship='drop' AND o.vendor_id=? ORDER BY o.id DESC LIMIT 20", (vid,))
    if not rows: await safe_edit(q, "📍 No drop orders.", reply_markup=back_kb()); return
    em = {"Pending":"⏳","Paid":"✅","Dispatched":"🚚","Rejected":"❌"}
    kb = [[IB(("🔒" if gs("cc_"+o["id"],"0")=="1" else "💬") +
              f" {o['id']} · {o['cust_name']} {em.get(o['status'],'')} ({o['msgs']})",
              f"dch_{o['id']}")] for o in rows] + [[IB("⬅️ Back", "menu")]]
    await safe_edit(q, "📍 <b>Drop Orders</b>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))

async def adm_note_start(u, ctx):
    q = u.callback_query
    if not is_admin(u.effective_user.id) and not is_vendor_admin(u.effective_user.id): return
    oid = q.data[9:]; ctx.user_data.update({"note_oid": oid, "wf": "order_note"})
    note = q1("SELECT note FROM order_notes WHERE order_id=?", (oid,))
    await q.message.reply_text(
        f"📝 Note for {oid} — current: <i>{hl.escape(note['note']) if note else 'none'}</i>\n\nType note:",
        parse_mode="HTML")

async def adm_edit_home(u, ctx):
    q = u.callback_query
    if not is_admin(u.effective_user.id): return
    cur = gs("home_extra"); ctx.user_data["wf"] = "edit_home"
    await safe_edit(q, f"🏠 Current: <i>{hl.escape(cur) if cur else 'None'}</i>\n\n"
                    "Type new text or <code>clear</code>:", parse_mode="HTML", reply_markup=cancel_kb())

async def adm_admins(u, ctx):
    q = u.callback_query
    if not is_admin(u.effective_user.id): return
    rows = qa("SELECT user_id,username FROM admins ORDER BY id")
    txt = ("👥 <b>Admins</b>\n\n" +
           "".join(("👑" if r["user_id"] == ADMIN_ID else "🔑") +
                   f" <code>{r['user_id']}</code> @{r['username'] or '?'}\n" for r in rows))
    kb = [[IB("➕ Add", "adm_addadmin")]] + \
         [[IB(f"🗑️ {r['username'] or r['user_id']}", f"adm_rmadmin_{r['user_id']}")] for r in rows if r["user_id"] != ADMIN_ID] + \
         [[IB("⬅️ Back", "menu")]]
    await safe_edit(q, txt, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))

async def adm_addadmin_start(u, ctx):
    q = u.callback_query
    if not is_admin(u.effective_user.id): return
    ctx.user_data["wf"] = "add_admin"
    await safe_edit(q, "➕ Send numeric Telegram user_id:", reply_markup=cancel_kb())

async def adm_rmadmin(u, ctx):
    q = u.callback_query
    if not is_admin(u.effective_user.id): return
    uid = int(q.data.split("adm_rmadmin_")[1])
    if uid == ADMIN_ID: await q.answer("❌ Cannot remove owner.", show_alert=True); return
    r = q1("SELECT username FROM admins WHERE user_id=?", (uid,))
    qx("DELETE FROM admins WHERE user_id=?", (uid,))
    await q.answer(f"✅ Removed {r['username'] if r else uid}", show_alert=True)
    await adm_admins(u, ctx)

async def adm_bans(u, ctx):
    q = u.callback_query
    if not is_admin(u.effective_user.id): return
    rows = qa("SELECT user_id,username FROM users WHERE banned=1")
    txt = ("🚫 <b>Banned Users</b>\n\n" +
           ("".join(f"• <code>{r['user_id']}</code> @{r['username'] or '?'}\n" for r in rows) if rows else "None."))
    kb = [[IB("🚫 Ban User", "adm_ban_start")]] + \
         [[IB(f"✅ Unban {r['username'] or r['user_id']}", f"unban_{r['user_id']}")] for r in rows] + \
         [[IB("⬅️ Back", "menu")]]
    await safe_edit(q, txt, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))

async def adm_ban_start(u, ctx):
    q = u.callback_query
    if not is_admin(u.effective_user.id): return
    ctx.user_data["wf"] = "ban_user"; await safe_edit(q, "🚫 Enter user_id to ban:", reply_markup=cancel_kb())

async def adm_unban(u, ctx):
    q = u.callback_query
    if not is_admin(u.effective_user.id): return
    uid = int(q.data.split("_")[1]); qx("UPDATE users SET banned=0 WHERE user_id=?", (uid,))
    await q.answer("✅ Unbanned", show_alert=True); await adm_bans(u, ctx)

async def adm_custnotes(u, ctx):
    q = u.callback_query
    if not is_admin(u.effective_user.id): return
    ctx.user_data["wf"] = "custnote_uid"; await safe_edit(q, "📝 Enter user_id:", reply_markup=cancel_kb())

async def adm_discounts(u, ctx):
    q = u.callback_query; uid = q.from_user.id
    if not is_admin(uid) and not is_vendor_admin(uid): return
    vid = get_vid(ctx, uid)
    rows = qa("SELECT code,pct,active,expires,uses,max_uses FROM discount_codes WHERE vendor_id=? ORDER BY code", (vid,))
    txt = ("🏷️ <b>Discount Codes</b>\n\n" +
           "".join(("✅ " if r["active"] else "❌ ") +
                   "<code>" + r["code"] + "</code> " + str(int(r["pct"]*100)) + "%" +
                   (" · exp " + r["expires"][:10] if r.get("expires") else "") +
                   (f" · {r['uses']}/{r['max_uses']} uses" if r.get("max_uses",-1)!=-1 else "") + "\n"
                   for r in rows))
    kb = [[IB(("🚫 " if r["active"] else "✅ ") + r["code"], f"toggledisc_{r['code']}")] for r in rows] + \
         [[IB("➕ Add", "adm_adddisc")], [IB("⬅️ Back", "menu")]]
    await safe_edit(q, txt or "No codes yet.", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))

async def adm_toggledisc(u, ctx):
    q = u.callback_query; c = q.data.split("toggledisc_")[1]
    r = q1("SELECT active FROM discount_codes WHERE code=?", (c,))
    if r: qx("UPDATE discount_codes SET active=? WHERE code=?", (0 if r["active"] else 1, c))
    await adm_discounts(u, ctx)

async def adm_adddisc_start(u, ctx):
    q = u.callback_query; ctx.user_data["wf"] = "disc_code"
    await safe_edit(q,
        "🏷️ Add code:\n<code>CODE,PCT</code> or <code>CODE,PCT,HOURS</code> or <code>CODE,PCT,HOURS,MAXUSES</code>\n"
        "e.g. <code>SAVE20,20</code> or <code>FLASH50,50,4,100</code>",
        parse_mode="HTML", reply_markup=cancel_kb())

async def ann_start(u, ctx):
    q = u.callback_query; ctx.user_data.update({"wf": "ann_title"}); ctx.user_data.pop("ann_photo", "")
    await safe_edit(q, "📢 Enter announcement title:", reply_markup=cancel_kb())

async def adm_cats(u, ctx):
    q = u.callback_query; uid = q.from_user.id
    if not is_admin(uid) and not is_vendor_admin(uid): return
    vid = get_vid(ctx, uid); cats = qa("SELECT * FROM categories WHERE vendor_id=? ORDER BY id", (vid,))
    txt = "📂 <b>Categories</b>\n\n" + ("\n".join(c["emoji"]+" "+c["name"] for c in cats) if cats else "None yet.")
    kb = [[IB(f"✏️ {c['emoji']} {c['name']}", f"cat_assign_{c['id']}")] for c in cats] + \
         [[IB("➕ New", "adm_newcat"), IB("🗑️ Delete", "adm_delcat")], [IB("⬅️ Back", "menu")]]
    await safe_edit(q, txt, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))

async def adm_newcat(u, ctx):
    q = u.callback_query; ctx.user_data["wf"] = "new_cat"
    await safe_edit(q, "📂 Send: <code>🍃 Indoor Strains</code>", parse_mode="HTML", reply_markup=cancel_kb())

async def adm_delcat_list(u, ctx):
    q = u.callback_query; uid = q.from_user.id; vid = get_vid(ctx, uid)
    cats = qa("SELECT * FROM categories WHERE vendor_id=? ORDER BY id", (vid,))
    if not cats: await safe_edit(q, "No categories.", reply_markup=back_kb()); return
    await safe_edit(q, "🗑️ Delete which?",
        reply_markup=InlineKeyboardMarkup(
            [[IB(f"🗑️ {c['emoji']} {c['name']}", f"delcat_{c['id']}")] for c in cats] +
            [[IB("⬅️ Back", "adm_cats")]]))

async def adm_delcat_do(u, ctx):
    q = u.callback_query; cid = int(q.data.split("_")[1])
    qx("UPDATE products SET category_id=0 WHERE category_id=?", (cid,))
    qx("DELETE FROM categories WHERE id=?", (cid,)); await adm_cats(u, ctx)

async def adm_cat_assign(u, ctx):
    q = u.callback_query; cid = int(q.data.split("_")[2])
    cat = q1("SELECT name,emoji FROM categories WHERE id=?", (cid,)); vid = get_vid(ctx, q.from_user.id)
    rows = qa("SELECT id,name,category_id FROM products WHERE vendor_id=? ORDER BY id", (vid,))
    kb = [[IB(("✅ " if r["category_id"] == cid else "○ ") + r["name"], f"togglecat_{r['id']}_{cid}")] for r in rows] + \
         [[IB("✅ Done", "adm_cats")]]
    await safe_edit(q, f"📂 Assign to <b>{cat['emoji']} {cat['name']}</b>:",
        parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))

async def adm_togglecat(u, ctx):
    q = u.callback_query; p = q.data.split("_"); pid, cid = int(p[1]), int(p[2])
    row = q1("SELECT category_id FROM products WHERE id=?", (pid,))
    if row: qx("UPDATE products SET category_id=? WHERE id=?", (0 if row["category_id"] == cid else cid, pid))
    u.callback_query.data = f"cat_assign_{cid}"; await adm_cat_assign(u, ctx)

async def adm_rmprod_list(u, ctx):
    q = u.callback_query; uid = q.from_user.id; vid = get_vid(ctx, uid)
    rows = qa("SELECT id,name FROM products WHERE vendor_id=? ORDER BY id", (vid,))
    if not rows: await safe_edit(q, "No products.", reply_markup=back_kb()); return
    await safe_edit(q, "🗑️ Remove which?",
        reply_markup=InlineKeyboardMarkup(
            [[IB(f"🗑️ {r['name']}", f"rmprod_{r['id']}")] for r in rows] + [[IB("⬅️ Back", "menu")]]))

async def adm_rmprod_confirm(u, ctx):
    q = u.callback_query; pid = int(q.data.split("_")[1])
    r = q1("SELECT name FROM products WHERE id=?", (pid,))
    if r: await safe_edit(q, f"🗑️ Delete <b>{hl.escape(r['name'])}</b>?", parse_mode="HTML",
        reply_markup=KM([IB("✅ Delete", f"rmprod_yes_{pid}"), IB("❌ No", "menu")]))

async def adm_rmprod_do(u, ctx):
    q = u.callback_query; qx("DELETE FROM products WHERE id=?", (int(q.data.split("_")[2]),))
    await safe_edit(q, "✅ Deleted.", reply_markup=back_kb())

async def adm_editdesc_list(u, ctx):
    q = u.callback_query; uid = q.from_user.id; vid = get_vid(ctx, uid)
    rows = qa("SELECT id,name FROM products WHERE vendor_id=? ORDER BY id", (vid,))
    if not rows: await safe_edit(q, "No products.", reply_markup=back_kb()); return
    # UPGRADE 17: Show both Edit Name and Edit Description per product
    kb = []
    for r in rows:
        kb.append([IB(f"📝 Name: {r['name']}", f"editname_{r['id']}"),
                   IB(f"✏️ Desc", f"editdesc_{r['id']}")])
    kb.append([IB("⬅️ Back", "menu")])
    await safe_edit(q, "✏️ <b>Edit Products</b>\n\nTap Name to rename, Desc to edit description:",
        parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))

async def adm_editname_start(u, ctx):
    # UPGRADE 17: Edit product name
    q = u.callback_query; pid = int(q.data.split("_")[1])
    ctx.user_data.update({"edit_name_pid": pid, "wf": "edit_name"})
    r = q1("SELECT name FROM products WHERE id=?", (pid,))
    await safe_edit(q,
        f"📝 <b>Rename Product</b>\n\nCurrent: <b>{hl.escape(r['name'])}</b>\n\nSend new name:",
        parse_mode="HTML", reply_markup=cancel_kb())

async def adm_editdesc_start(u, ctx):
    q = u.callback_query; pid = int(q.data.split("_")[1])
    ctx.user_data.update({"edit_pid": pid, "wf": "edit_desc"})
    r = q1("SELECT name,description FROM products WHERE id=?", (pid,))
    await safe_edit(q,
        f"✏️ <b>Edit: {hl.escape(r['name'])}</b>\n\nCurrent: {hl.escape(r['description'] or '—')}\n\nSend new description:",
        parse_mode="HTML", reply_markup=cancel_kb())

async def adm_hideprod_list(u, ctx):
    q = u.callback_query; uid = q.from_user.id; vid = get_vid(ctx, uid)
    rows = qa("SELECT id,name,hidden FROM products WHERE vendor_id=? ORDER BY id", (vid,))
    if not rows: await safe_edit(q, "No products.", reply_markup=back_kb()); return
    await safe_edit(q, "👁️ <b>Hide / Show Products</b>", parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            [[IB(("👁️ Show" if r["hidden"] else "🙈 Hide") + " " + r["name"], f"togglehide_{r['id']}")] for r in rows] +
            [[IB("⬅️ Back", "menu")]]))

async def adm_togglehide(u, ctx):
    q = u.callback_query; pid = int(q.data.split("_")[1])
    row = q1("SELECT name,hidden FROM products WHERE id=?", (pid,))
    if not row: await q.answer(); return
    qx("UPDATE products SET hidden=? WHERE id=?", (0 if row["hidden"] else 1, pid))
    await q.answer(("Shown" if row["hidden"] else "Hidden") + ": " + row["name"], show_alert=True)
    await adm_hideprod_list(u, ctx)

async def adm_feature_list(u, ctx):
    q = u.callback_query; uid = q.from_user.id; vid = get_vid(ctx, uid)
    rows = qa("SELECT id,name,featured FROM products WHERE vendor_id=? ORDER BY id", (vid,))
    if not rows: await safe_edit(q, "No products.", reply_markup=back_kb()); return
    await safe_edit(q, "⭐ <b>Feature Products</b>", parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            [[IB(("⭐ Unfeature " if r["featured"] else "☆ Feature ") + r["name"], f"togglefeat_{r['id']}")] for r in rows] +
            [[IB("⬅️ Back", "menu")]]))

async def adm_togglefeat(u, ctx):
    q = u.callback_query; pid = int(q.data.split("_")[1])
    row = q1("SELECT featured FROM products WHERE id=?", (pid,))
    if row: qx("UPDATE products SET featured=? WHERE id=?", (0 if row["featured"] else 1, pid))
    await adm_feature_list(u, ctx)

async def adm_stock_list(u, ctx):
    q = u.callback_query; uid = q.from_user.id; vid = get_vid(ctx, uid)
    rows = qa("SELECT id,name,stock FROM products WHERE vendor_id=? ORDER BY id", (vid,))
    if not rows: await safe_edit(q, "No products.", reply_markup=back_kb()); return
    txt = "📦 <b>Stock Levels</b>\n\n" + \
          "".join(f"• {r['name']}: {'∞' if r['stock']==-1 else r['stock']}\n" for r in rows)
    await safe_edit(q, txt, parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            [[IB(f"📦 {r['name']}", f"setstock_{r['id']}")] for r in rows] + [[IB("⬅️ Back", "menu")]]))

async def adm_setstock_start(u, ctx):
    q = u.callback_query; pid = int(q.data.split("_")[1])
    r = q1("SELECT name,stock FROM products WHERE id=?", (pid,))
    ctx.user_data.update({"stock_pid": pid, "wf": "set_stock"})
    await safe_edit(q,
        f"📦 <b>{hl.escape(r['name'])}</b>\nCurrent: {'∞' if r['stock']==-1 else r['stock']}\n\n"
        "Enter new stock (-1 = unlimited):", parse_mode="HTML", reply_markup=cancel_kb())

async def adm_list_tiers(u, ctx):
    q = u.callback_query; uid = q.from_user.id; vid = get_vid(ctx, uid)
    rows = qa("SELECT id,name FROM products WHERE vendor_id=? ORDER BY id", (vid,))
    if not rows: await safe_edit(q, "No products.", reply_markup=back_kb()); return
    await safe_edit(q, "⚖️ Edit tiers for:",
        reply_markup=InlineKeyboardMarkup(
            [[IB(f"⚖️ {r['name']}", f"edtier_{r['id']}")] for r in rows] + [[IB("⬅️ Back", "menu")]]))

async def adm_show_tiers(u, ctx):
    q = u.callback_query; pid = int(q.data.split("_")[1])
    ctx.user_data.update({"tpid": pid, "wf": "edit_tiers"})
    r = q1("SELECT name,tiers FROM products WHERE id=?", (pid,))
    tiers = json.loads(r["tiers"]) if r.get("tiers") else TIERS[:]
    await q.message.reply_text(
        f"⚖️ <b>{hl.escape(r['name'])}</b>\n\n" + "".join(ft(t)+"\n" for t in tiers) +
        "\nSend new tiers (qty,price per line) or /cancel", parse_mode="HTML")

async def adm_flash_list(u, ctx):
    q = u.callback_query; uid = q.from_user.id
    if not is_admin(uid) and not is_vendor_admin(uid): return
    vid = get_vid(ctx, uid)
    rows = qa("SELECT id,name FROM products WHERE vendor_id=? ORDER BY id", (vid,))
    if not rows: await safe_edit(q, "No products.", reply_markup=back_kb()); return
    active = qa("SELECT fs.product_id,p.name,fs.pct,fs.expires FROM flash_sales fs "
                "JOIN products p ON fs.product_id=p.id WHERE p.vendor_id=? AND fs.active=1", (vid,))
    active_txt = ("🔥 <b>Active:</b>\n" +
                  "".join(f"• {hl.escape(r['name'])} — {int(r['pct']*100)}% off · exp {str(r['expires'])[:16]}\n"
                          for r in active) + "\n") if active else ""
    await safe_edit(q, f"🔥 <b>Flash Sales</b>\n\n{active_txt}Select product:", parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            [[IB(f"🔥 {r['name']}", f"flash_set_{r['id']}")] for r in rows] + [[IB("⬅️ Back", "menu")]]))

async def adm_flash_set(u, ctx):
    q = u.callback_query; pid = int(q.data.split("_")[2])
    r = q1("SELECT name FROM products WHERE id=?", (pid,))
    ctx.user_data.update({"flash_pid": pid, "wf": "flash_set"})
    await safe_edit(q,
        f"🔥 Flash for <b>{hl.escape(r['name'])}</b>\n\nSend: <code>PCT,HOURS</code>\ne.g. <code>20,4</code>",
        parse_mode="HTML", reply_markup=cancel_kb())

# UPGRADE 10: Disputes panel
async def adm_disputes_cb(u, ctx):
    q = u.callback_query
    if not is_admin(u.effective_user.id): return
    rows = qa("SELECT id,order_id,user_id,reason,status,created_at FROM disputes ORDER BY id DESC LIMIT 20")
    if not rows: await safe_edit(q, "⚠️ No disputes.", reply_markup=back_kb()); return
    txt = ("⚠️ <b>Disputes</b>\n\n" +
           "".join(("🔴" if r["status"]=="Open" else "✅") +
                   f" #{r['id']} — Order {r['order_id']}\n"
                   f"User <code>{r['user_id']}</code>\n{hl.escape(r['reason'][:80])}\n\n" for r in rows))
    open_rows = [r for r in rows if r["status"] == "Open"]
    kb = [[IB(f"✅ Close #{r['id']}", f"dispute_close_{r['id']}")] for r in open_rows] + [[IB("⬅️ Back", "menu")]]
    await safe_edit(q, txt[:4000], parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))

async def dispute_close_cb(u, ctx):
    q = u.callback_query
    if not is_admin(u.effective_user.id): return
    did = int(q.data.split("_")[2])
    r = q1("SELECT user_id,order_id FROM disputes WHERE id=?", (did,))
    qx("UPDATE disputes SET status='Resolved' WHERE id=?", (did,))
    if r:
        try: await ctx.bot.send_message(r["user_id"],
            f"✅ Dispute #{did} for order <code>{r['order_id']}</code> has been resolved.",
            parse_mode="HTML")
        except: pass
    await q.answer("✅ Dispute closed.", show_alert=True); await adm_disputes_cb(u, ctx)

async def vendor_balance_cb(u, ctx):
    q = u.callback_query; uid = q.from_user.id; vid = get_vid(ctx, uid); bal = get_vendor_balance(vid)
    recent = qa("SELECT id,vendor_gbp,created_at FROM orders WHERE vendor_id=? "
                "AND status IN ('Paid','Dispatched') ORDER BY id DESC LIMIT 10", (vid,))
    txt = (f"💰 <b>Your Earnings</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
           f"💳 Owed: <b>£{bal['owed']:.2f}</b>\n✅ Paid: £{bal['paid']:.2f}\n\n"
           "<b>Recent orders:</b>\n" +
           "".join(f"• {o['id']} — £{o['vendor_gbp']:.2f} — {str(o['created_at'])[:10]}\n" for o in recent))
    await safe_edit(q, txt, parse_mode="HTML",
        reply_markup=KM([IB("📤 Request Payout", "vendor_payout_req")], [IB("⬅️ Back", "menu")]))

async def vendor_payout_req(u, ctx):
    q = u.callback_query; uid = q.from_user.id; vid = get_vid(ctx, uid); bal = get_vendor_balance(vid)
    if bal["owed"] < 1.0: await q.answer("No balance to request.", show_alert=True); return
    ctx.user_data.update({"payout_vid": vid, "payout_amount": bal["owed"], "wf": "payout_req"})
    await safe_edit(q,
        f"📤 <b>Request Payout</b>\n\nAmount: <b>£{bal['owed']:.2f}</b>\n\n"
        "Send your LTC wallet address (or 'same' to use address on file):",
        parse_mode="HTML", reply_markup=cancel_kb())

async def adm_payouts(u, ctx):
    q = u.callback_query
    if not is_admin(u.effective_user.id): return
    rows = qa("SELECT pr.id,pr.vendor_id,pr.amount,pr.ltc_addr,pr.status,v.name "
              "FROM payout_requests pr LEFT JOIN vendors v ON pr.vendor_id=v.id ORDER BY pr.id DESC LIMIT 20")
    if not rows: await safe_edit(q, "No payout requests.", reply_markup=back_kb()); return
    txt = ("💰 <b>Payout Requests</b>\n\n" +
           "".join(("⏳" if r["status"]=="Pending" else "✅") +
                   f" #{r['id']} — {hl.escape(r['name'] or '?')} — £{r['amount']:.2f}\n"
                   f"<code>{r['ltc_addr']}</code>\n\n" for r in rows))
    pending_r = [r for r in rows if r["status"] == "Pending"]
    kb = [[IB(f"✅ Pay #{r['id']}", f"payout_ok_{r['id']}"),
           IB(f"❌ #{r['id']}", f"payout_no_{r['id']}")] for r in pending_r] + [[IB("⬅️ Back", "menu")]]
    await safe_edit(q, txt[:4000], parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))

async def payout_approve(u, ctx):
    q = u.callback_query
    if not is_admin(u.effective_user.id): return
    rid = int(q.data.split("_")[2]); r = q1("SELECT * FROM payout_requests WHERE id=?", (rid,))
    if not r: return
    qx("UPDATE payout_requests SET status='Approved' WHERE id=?", (rid,))
    qx("UPDATE vendor_balances SET owed=owed-?,paid=paid+? WHERE vendor_id=?",
       (r["amount"], r["amount"], r["vendor_id"]))
    v = q1("SELECT admin_user_id FROM vendors WHERE id=?", (r["vendor_id"],))
    if v and v.get("admin_user_id"):
        try: await ctx.bot.send_message(v["admin_user_id"],
            f"✅ <b>Payout Approved!</b>\n£{r['amount']:.2f} → <code>{r['ltc_addr']}</code>",
            parse_mode="HTML")
        except: pass
    await safe_edit(q, f"✅ Payout #{rid} approved.", reply_markup=back_kb())

async def payout_reject(u, ctx):
    q = u.callback_query
    if not is_admin(u.effective_user.id): return
    rid = int(q.data.split("_")[2])
    qx("UPDATE payout_requests SET status='Rejected' WHERE id=?", (rid,))
    await safe_edit(q, f"❌ Payout #{rid} rejected.", reply_markup=back_kb())

# ── COMMANDS ───────────────────────────────────────────────────────────────────
async def cmd_reply(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(u.effective_user.id) and not is_vendor_admin(u.effective_user.id): return
    if not ctx.args or len(ctx.args) < 2: await u.message.reply_text("Usage: /reply <id> <text>"); return
    try: mid = int(ctx.args[0])
    except: await u.message.reply_text("⚠️ Invalid ID."); return
    msg = " ".join(ctx.args[1:]); row = q1("SELECT user_id,username,message FROM messages WHERE id=?", (mid,))
    if not row: await u.message.reply_text("❌ Not found."); return
    qx("UPDATE messages SET reply=? WHERE id=?", (msg, mid))
    try:
        await ctx.bot.send_message(row["user_id"],
            f"💬 <b>Reply</b>\n<i>{hl.escape(row['message'])}</i>\n\n✉️ {hl.escape(msg)}",
            parse_mode="HTML", reply_markup=menu())
        await u.message.reply_text(f"✅ Replied to @{row['username']}.")
    except Exception as e: await u.message.reply_text(f"❌ {e}")

async def cmd_order(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(u.effective_user.id) and not is_vendor_admin(u.effective_user.id): return
    if not ctx.args: await u.message.reply_text("Usage: /order <id>"); return
    oid = ctx.args[0]; row = q1("SELECT * FROM orders WHERE id=?", (oid,))
    if not row: await u.message.reply_text("❌ Not found."); return
    sl = SHIP.get(row["ship"], {}).get("label", row["ship"])
    em = {"Pending":"⏳","Paid":"✅","Dispatched":"🚚","Rejected":"❌"}
    v  = q1("SELECT name,emoji FROM vendors WHERE id=?", (row["vendor_id"],))
    note = q1("SELECT note FROM order_notes WHERE order_id=?", (oid,))
    txt = ((f"🔖 <b>{oid}</b> {em.get(row['status'],'')}\n" +
            (f"{v['emoji']} {v['name']} via PhiVara\n" if v else "")) +
           f"👤 {hl.escape(row['cust_name'])} · 🏠 {hl.escape(row['address'])}\n"
           f"🚚 {sl} · 💷 £{row['gbp']:.2f}\n"
           f"💠 {row.get('ltc',0):.6f} LTC @ £{row.get('ltc_rate',0):.2f}\n"
           f"📤 <code>{PLATFORM_LTC}</code>\n"
           f"📦 {hl.escape(row['summary'])}\n"
           f"💰 Vendor: £{row.get('vendor_gbp',0):.2f} · Platform: £{row.get('platform_gbp',0):.2f}")
    if note: txt += f"\n📝 {hl.escape(note['note'])}"
    kb = ([[IB("✅ Confirm", f"adm_ok_{oid}"), IB("❌ Reject", f"adm_no_{oid}")]] if row["status"]=="Pending" else []) + \
         ([[IB("🚚 Dispatch", f"adm_go_{oid}")]] if row["status"]=="Paid" and row["ship"]!="drop" else []) + \
         ([[IB("💬 Chat", f"dch_{oid}")]] if row["ship"]=="drop" else []) + \
         [[IB("📝 Note", f"adm_note_{oid}"), IB("🧾 Invoice", f"show_invoice_{oid}")]]
    await u.message.reply_text(txt, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))

# UPGRADE 11: /set command for platform settings
async def cmd_set(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(u.effective_user.id): return
    allowed = ["min_order","bulk_threshold","bulk_pct","home_extra"]
    if not ctx.args or len(ctx.args) < 2:
        await u.message.reply_text(f"Usage: /set <key> <value>\nKeys: {', '.join(allowed)}"); return
    key = ctx.args[0]; val = " ".join(ctx.args[1:])
    if key not in allowed: await u.message.reply_text(f"⚠️ Unknown key."); return
    ss(key, val); await u.message.reply_text(f"✅ {key} = {val}")

async def cmd_invoice(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = u.effective_user.id
    if not is_known(uid) and not is_admin(uid): await u.message.reply_text("Please /start first."); return
    if not ctx.args:
        orders = qa("SELECT id,gbp,ltc FROM orders WHERE user_id=? AND status='Pending' AND ltc>0 ORDER BY id DESC LIMIT 5", (uid,))
        if not orders: await u.message.reply_text("📭 No pending LTC orders.\nUsage: /invoice <order_id>"); return
        kb = [[IB(f"🧾 {o['id']} — £{o['gbp']:.2f} — {o['ltc']:.6f} LTC", f"show_invoice_{o['id']}")] for o in orders]
        await u.message.reply_text("🧾 <b>Pending Invoices</b>", parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(kb)); return
    oid = ctx.args[0].upper()
    if not is_admin(uid) and not q1("SELECT 1 FROM orders WHERE id=? AND user_id=?", (oid, uid)):
        await u.message.reply_text("❌ Order not found."); return
    invoice_txt, invoice_kb = build_invoice(oid)
    if invoice_txt: await u.message.reply_text(invoice_txt, parse_mode="HTML", reply_markup=invoice_kb)
    else: await u.message.reply_text("❌ Order not found.")

async def cmd_customer(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(u.effective_user.id): return
    if not ctx.args: await u.message.reply_text("Usage: /customer @username or user_id"); return
    arg = ctx.args[0].lstrip("@")
    try: cid=int(arg); row=q1("SELECT user_id,username,banned,vip_tier FROM users WHERE user_id=?",(cid,))
    except: row=q1("SELECT user_id,username,banned,vip_tier FROM users WHERE username=?",(arg,))
    if not row: await u.message.reply_text("❌ Not found."); return
    cid=row["user_id"]; orders=qa("SELECT id,gbp,status,summary FROM orders WHERE user_id=? ORDER BY id DESC LIMIT 10",(cid,))
    spent=sum(o["gbp"] for o in orders if o["status"] in ("Paid","Dispatched")); lo=get_loyalty(cid)
    note=q1("SELECT note FROM customer_notes WHERE user_id=?",(cid,))
    banned="🚫 BANNED\n" if row.get("banned") else ""
    tier=row.get("vip_tier","standard")
    txt=(f"{banned}👤 @{hl.escape(row['username'] or str(cid))} (<code>{cid}</code>)\n"
         f"━━━━━━━━━━━━━━━━━━━━\n💷 £{spent:.2f} · {len(orders)} orders · {tier}\n"
         f"⭐ {lo['points']} pts · 💳 £{lo['credit']:.2f}\n")
    if note: txt+=f"📝 {hl.escape(note['note'])}\n"
    txt+="\n"+"".join(f"• {o['id']} — {o['status']} — £{o['gbp']:.2f} — {hl.escape(o['summary'][:40])}\n" for o in orders)
    await u.message.reply_text(txt[:4000],parse_mode="HTML")

async def cmd_myorder(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid=u.effective_user.id
    if not is_known(uid) and not is_admin(uid): await u.message.reply_text("Please /start first."); return
    if not ctx.args: await u.message.reply_text("Usage: /myorder <id>"); return
    oid=ctx.args[0]; row=q1("SELECT * FROM orders WHERE id=? AND user_id=?",(oid,uid))
    if not row: await u.message.reply_text("❌ Not found."); return
    sl=SHIP.get(row["ship"],{}).get("label",row["ship"]); em={"Pending":"🕐","Paid":"✅","Dispatched":"🚚","Rejected":"❌"}
    kb=[[IB("🧾 View Invoice",f"show_invoice_{oid}")]] if row["status"]=="Pending" and row.get("ltc",0)>0 else []
    await u.message.reply_text(
        f"🧾 <b>Order {oid}</b>\n━━━━━━━━━━━━━━━━━━━━\n{em.get(row['status'],'')} {row['status']}\n"
        f"👤 {hl.escape(row['cust_name'])} · 🏠 {hl.escape(row['address'])}\n"
        f"🚚 {sl} · 💷 £{row['gbp']:.2f}\n{hl.escape(row['summary'])}",
        parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb) if kb else None)

async def cmd_search(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args: await u.message.reply_text("Usage: /search <term>"); return
    term="%"+" ".join(ctx.args)+"%"
    rows=qa("SELECT id,name FROM products WHERE (name LIKE ? OR description LIKE ?) AND hidden=0 ORDER BY name",(term,term))
    if not rows: await u.message.reply_text("🔍 No products found."); return
    await u.message.reply_text(f"🔍 <b>{len(rows)} results</b>",parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[IB(f"🌿 {r['name']}",f"prod_{r['id']}")] for r in rows]+[[IB("⬅️ Menu","menu")]]))

# UPGRADE 18: /top — top selling products
async def cmd_top(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = u.effective_user.id
    if not is_admin(uid) and not is_vendor_admin(uid): return
    vid = get_vid(ctx, uid) if is_vendor_admin(uid) else None
    if vid:
        rows = qa("SELECT p.name,p.views,COUNT(o.id) as sales FROM products p "
                  "LEFT JOIN cart c ON c.product_id=p.id "
                  "LEFT JOIN orders o ON o.vendor_id=p.vendor_id AND o.status IN ('Paid','Dispatched') "
                  "WHERE p.vendor_id=? GROUP BY p.id ORDER BY sales DESC,p.views DESC LIMIT 10",(vid,))
    else:
        rows = qa("SELECT p.name,p.views,COUNT(o.id) as sales FROM products p "
                  "LEFT JOIN orders o ON o.vendor_id=p.vendor_id AND o.status IN ('Paid','Dispatched') "
                  "GROUP BY p.id ORDER BY p.views DESC LIMIT 10")
    if not rows: await u.message.reply_text("📊 No data yet."); return
    txt = "🔥 <b>Top Products</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
    medals = ["🥇","🥈","🥉"]+["🏅"]*7
    for i,r in enumerate(rows):
        txt += f"{medals[i]} <b>{hl.escape(r['name'])}</b>\n   👁️ {r['views']} views\n\n"
    await u.message.reply_text(txt,parse_mode="HTML")

# UPGRADE 19: /copy — duplicate a product (admin only)
async def cmd_copy(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = u.effective_user.id
    if not is_admin(uid) and not is_vendor_admin(uid): return
    if not ctx.args: await u.message.reply_text("Usage: /copy <product_id>"); return
    try: pid = int(ctx.args[0])
    except: await u.message.reply_text("⚠️ Numeric product ID required."); return
    r = q1("SELECT * FROM products WHERE id=?", (pid,))
    if not r: await u.message.reply_text("❌ Product not found."); return
    vid = get_vid(ctx, uid) if is_vendor_admin(uid) else r["vendor_id"]
    new_pid = qxi("INSERT INTO products(vendor_id,name,description,photo,hidden,tiers,stock,featured,category_id) "
                  "VALUES(?,?,?,?,0,?,?,?,?)",
                  (vid, r["name"]+" (Copy)", r.get("description",""), r.get("photo",""),
                   r.get("tiers","[]"), -1, 0, r.get("category_id",0)))
    await u.message.reply_text(
        f"✅ Product copied!\n\n<b>{hl.escape(r['name'])} (Copy)</b>\nNew ID: #{new_pid}\n\n"
        f"Use ✏️ Edit Desc or ⚖️ Tiers to customise it.",
        parse_mode="HTML", reply_markup=menu())

async def cmd_dispute(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid=u.effective_user.id
    if not is_known(uid): await u.message.reply_text("Please /start first."); return
    if not ctx.args or len(ctx.args)<2: await u.message.reply_text("Usage: /dispute <order_id> <reason>"); return
    oid=ctx.args[0].upper(); reason=" ".join(ctx.args[1:])
    o=q1("SELECT id,status FROM orders WHERE id=? AND user_id=?",(oid,uid))
    if not o: await u.message.reply_text("❌ Order not found."); return
    if o["status"] not in ("Paid","Dispatched"): await u.message.reply_text("⚠️ Can only dispute confirmed orders."); return
    did=qxi("INSERT INTO disputes(order_id,user_id,reason) VALUES(?,?,?)",(oid,uid,reason))
    try: await ctx.bot.send_message(ADMIN_ID,f"⚠️ <b>DISPUTE #{did}</b>\nOrder <code>{oid}</code>\nUser: <code>{uid}</code>\nReason: {hl.escape(reason)}",parse_mode="HTML")
    except: pass
    await u.message.reply_text(f"⚠️ Dispute #{did} raised for order <code>{oid}</code>. Admin will review within 24h.",parse_mode="HTML")

async def cmd_dbcheck(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Admin command to diagnose database path and verify data is persisting."""
    if not is_admin(u.effective_user.id): return
    import shutil
    vendors  = q1("SELECT COUNT(*) as c FROM vendors") or {"c":0}
    products = q1("SELECT COUNT(*) as c FROM products") or {"c":0}
    users    = q1("SELECT COUNT(*) as c FROM users")    or {"c":0}
    orders   = q1("SELECT COUNT(*) as c FROM orders")   or {"c":0}
    try:
        db_size = os.path.getsize(DB)
        free    = shutil.disk_usage(DB_DIR).free // 1024 // 1024
        disk_txt = f"📁 DB size: {db_size} bytes · Free: {free}MB"
    except: disk_txt = "📁 Could not read disk info"
    await u.message.reply_text(
        f"🗄️ <b>Database Diagnostics</b>\n━━━━━━━━━━━━━━━━━━━━\n"
        f"📍 Path: <code>{DB}</code>\n"
        f"{disk_txt}\n\n"
        f"👥 Users: <b>{users['c']}</b>\n"
        f"🏪 Vendors: <b>{vendors['c']}</b>\n"
        f"🌿 Products: <b>{products['c']}</b>\n"
        f"📦 Orders: <b>{orders['c']}</b>\n\n"
        f"<b>If vendors/products show 0 after adding them:</b>\n"
        f"→ Railway hasn't mounted the volume yet\n"
        f"→ Go to Railway → your service → <b>Settings → Volumes</b>\n"
        f"→ Add volume with mount path: <code>/app/data</code>\n"
        f"→ Redeploy, then run /admin and add your data again\n\n"
        f"<b>Or set this Railway Variable:</b>\n"
        f"<code>DB_PATH=/app/data/shop.db</code>",
        parse_mode="HTML")

async def cmd_ltccheck(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(u.effective_user.id): return
    try:
        data=requests.get(f"https://api.blockcypher.com/v1/ltc/main/addrs/{PLATFORM_LTC}/balance",timeout=10).json()
        bal_ltc=data.get("balance",0)/100000000; unconf=data.get("unconfirmed_balance",0)/100000000; rate=ltc_price()
        await u.message.reply_text(
            f"💠 <b>Platform LTC Wallet</b>\n━━━━━━━━━━━━━━━━━━━━\n<code>{PLATFORM_LTC}</code>\n\n"
            f"✅ Confirmed: <b>{bal_ltc:.6f} LTC</b> (≈ £{bal_ltc*rate:.2f})\n"
            f"⏳ Unconfirmed: <b>{unconf:.6f} LTC</b>\n📊 Rate: £{rate:.2f}",parse_mode="HTML")
    except Exception as e: await u.message.reply_text(f"❌ Could not fetch: {e}")

# UPGRADE 12: /addproduct now a single clean flow via command
async def cmd_addproduct(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(u.effective_user.id) and not is_vendor_admin(u.effective_user.id): return
    ctx.user_data["wf"]="add_photo"
    await u.message.reply_text("📸 <b>Add Product — Step 1/3</b>\n\nSend a product photo, or type <b>skip</b> for no photo.",parse_mode="HTML")

async def cmd_cancel(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear(); await u.message.reply_text("🚫 Cancelled.",reply_markup=menu())

# ══════════════════════════════════════════════════════════════════════════════
# MESSAGE HANDLER — BUG FIXES + ALL FLOWS
# ══════════════════════════════════════════════════════════════════════════════
async def on_message(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid=u.effective_user.id; txt=(u.message.text or "").strip()
    if is_banned(uid): await u.message.reply_text("🚫 You are banned."); return
    # FIX: auto-register admins/vendor-admins so they never hit the "Please /start" wall
    if is_admin(uid) or is_vendor_admin(uid):
        qx("INSERT INTO users(user_id,username) VALUES(?,?)",
           (uid, u.effective_user.username or ""))
    elif not is_known(uid):
        await u.message.reply_text("👋 Please /start first."); return
    wf=ctx.user_data.get("wf")

    if wf=="co_name":
        ctx.user_data.update({"co_name":txt,"wf":None}); t,_=co_summary(ctx.user_data,uid)
        await u.message.reply_text(t,parse_mode="HTML",reply_markup=co_kb(ctx.user_data))

    elif wf=="co_addr":
        ctx.user_data.update({"co_addr":txt,"wf":None}); t,_=co_summary(ctx.user_data,uid)
        await u.message.reply_text(t,parse_mode="HTML",reply_markup=co_kb(ctx.user_data))

    elif wf=="co_disc":
        vid=ctx.user_data.get("co_vid",1); pct=gdisc(txt,vid)
        if pct: ctx.user_data.update({"co_disc_code":txt.upper(),"co_disc_pct":pct,"wf":None}); await u.message.reply_text(f"✅ {int(pct*100)}% off applied!")
        else: ctx.user_data.update({"co_disc_code":None,"co_disc_pct":0,"wf":None}); await u.message.reply_text("❌ Invalid or expired code.")
        t,_=co_summary(ctx.user_data,uid); await u.message.reply_text(t,parse_mode="HTML",reply_markup=co_kb(ctx.user_data))

    elif wf=="search":
        term="%"+txt+"%"; ctx.user_data["wf"]=None
        rows=qa("SELECT id,name FROM products WHERE (name LIKE ? OR description LIKE ?) AND hidden=0 ORDER BY name",(term,term))
        if not rows: await u.message.reply_text("🔍 No products found.",reply_markup=menu()); return
        await u.message.reply_text(f"🔍 <b>{len(rows)} results for '{hl.escape(txt)}'</b>",parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[IB(f"🌿 {r['name']}",f"prod_{r['id']}")] for r in rows]+[[IB("⬅️ Back","menu")]]))

    elif wf=="contact":
        uname=u.effective_user.username or str(uid); vid=ctx.user_data.get("contact_vid",1)
        mid=qxi("INSERT INTO messages(user_id,username,vendor_id,message) VALUES(?,?,?,?)",(uid,uname,vid,txt))
        vendor=q1("SELECT admin_user_id FROM vendors WHERE id=?",(vid,))
        notify=[ADMIN_ID]+([vendor["admin_user_id"]] if vendor and vendor.get("admin_user_id") and vendor["admin_user_id"]!=ADMIN_ID else [])
        for rid in notify:
            try: await ctx.bot.send_message(rid,f"💬 @{uname} #{mid}\n{hl.escape(txt)}\n/reply {mid}",parse_mode="HTML")
            except: pass
        await u.message.reply_text("✅ Message sent!",reply_markup=menu()); ctx.user_data["wf"]=None

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
                fn=(ctx.bot.send_photo(r["user_id"],photo,caption=f"📢 <b>{hl.escape(title)}</b>\n\n{hl.escape(txt)}",parse_mode="HTML")
                    if photo else ctx.bot.send_message(r["user_id"],f"📢 <b>{hl.escape(title)}</b>\n\n{hl.escape(txt)}",parse_mode="HTML"))
                await fn; sent+=1
            except: pass
        await u.message.reply_text(f"✅ Broadcast to {sent} users!"); ctx.user_data["wf"]=None

    elif wf=="review_text":
        # FIX: Store review with vendor + product context, handle None order safely
        import re as _re
        oid=ctx.user_data.get("rev_order"); s=ctx.user_data.get("rev_stars",5)
        o=q1("SELECT vendor_id,summary FROM orders WHERE id=?",(oid,))
        vendor_id=1; vendor_name=""; product_name=""
        if o:
            vendor_id=o.get("vendor_id") or 1
            v=q1("SELECT name FROM vendors WHERE id=?",(vendor_id,))
            if v: vendor_name=v["name"]
            raw=(o.get("summary","") or "").split(",")[0].strip()
            product_name=_re.sub(r'\s+\d+(\.\d+)?g$','',raw).strip()
        qx("INSERT INTO reviews(order_id,user_id,vendor_id,vendor_name,product_name,stars,text) VALUES(?,?,?,?,?,?,?)",
           (oid,uid,vendor_id,vendor_name,product_name,s,txt))
        await u.message.reply_text(f"✅ {STARS.get(s,'')} Thanks for your review! 🙏",reply_markup=menu()); ctx.user_data["wf"]=None

    # UPGRADE 12 FIX: Clean unified product add flow photo→title→description
    elif wf=="add_photo":
        if txt.lower()=="skip":
            ctx.user_data.update({"ph":"","wf":"add_title"})
            await u.message.reply_text("📝 <b>Add Product — Step 2/3</b>\n\nEnter product title:",parse_mode="HTML")
        else:
            await u.message.reply_text("📸 <b>Step 1/3</b>\n\nSend a photo or type <b>skip</b>:",parse_mode="HTML")

    elif wf=="add_title":
        # FIX: was incorrectly jumping to desc — now stores name and goes to description step
        ctx.user_data.update({"nm":txt,"wf":"add_desc"})
        await u.message.reply_text(
            f"📄 <b>Add Product — Step 3/3</b>\n\n"
            f"Product: <b>{hl.escape(txt)}</b>\n\nNow enter the product description:",
            parse_mode="HTML",reply_markup=cancel_kb())

    elif wf=="add_desc":
        d=ctx.user_data; vid=get_vid(ctx,uid); d["wf"]=None
        pid=qxi("INSERT INTO products(vendor_id,name,description,photo,hidden,tiers,stock) VALUES(?,?,?,?,0,?,?)",
                (vid,d["nm"],txt,d.get("ph",""),json.dumps(TIERS),-1))
        await u.message.reply_text(
            f"✅ <b>{hl.escape(d['nm'])}</b> added!\n\n"
            f"Product ID: #{pid}\n"
            f"Use ⚖️ Tiers to set custom pricing, or 📦 Stock to set stock levels.",
            parse_mode="HTML",reply_markup=menu())

    elif wf=="edit_name":
        # UPGRADE 17: Save renamed product
        pid=ctx.user_data.get("edit_name_pid")
        qx("UPDATE products SET name=? WHERE id=?",(txt,pid))
        await u.message.reply_text(f"✅ Product renamed to <b>{hl.escape(txt)}</b>!",
            parse_mode="HTML",reply_markup=menu()); ctx.user_data["wf"]=None

    elif wf=="edit_desc":
        qx("UPDATE products SET description=? WHERE id=?",(txt,ctx.user_data.get("edit_pid")))
        await u.message.reply_text("✅ Description updated!",reply_markup=menu()); ctx.user_data["wf"]=None

    elif wf=="edit_tiers":
        pid=ctx.user_data.get("tpid"); new=[]; errs=[]
        for i,line in enumerate(txt.splitlines(),1):
            p=line.strip().split(",")
            try: assert len(p)==2; q2,pr=float(p[0]),float(p[1]); assert q2>0 and pr>0; new.append({"qty":q2,"price":pr})
            except: errs.append(f"Line {i}: invalid — expected qty,price e.g. 3.5,35")
        if errs or not new: await u.message.reply_text("❌ "+("\n".join(errs or ["No valid tiers."]))); return
        new.sort(key=lambda t:t["qty"])
        qx("UPDATE products SET tiers=? WHERE id=?",(json.dumps(new),pid))
        await u.message.reply_text("✅ Tiers updated:\n"+"".join(ft(t)+"\n" for t in new),
            parse_mode="HTML",reply_markup=menu()); ctx.user_data["wf"]=None

    elif wf=="set_stock":
        try: sv=int(txt); assert sv>=-1
        except: await u.message.reply_text("⚠️ Enter a number (-1 for unlimited)."); return
        qx("UPDATE products SET stock=? WHERE id=?",(sv,ctx.user_data.get("stock_pid")))
        await u.message.reply_text(f"✅ Stock set to {'∞' if sv==-1 else sv}.",reply_markup=menu()); ctx.user_data["wf"]=None

    elif wf=="flash_set":
        parts=txt.split(",")
        try: pct=float(parts[0].strip())/100; hrs=float(parts[1].strip()); assert 0<pct<=1 and hrs>0
        except: await u.message.reply_text("⚠️ Format: PCT,HOURS e.g. 20,4"); return
        pid=ctx.user_data.get("flash_pid"); exp=(datetime.now()+timedelta(hours=hrs)).isoformat()
        qx("INSERT INTO flash_sales(product_id,pct,expires,active) VALUES(?,?,?,1)",(pid,pct,exp))
        r=q1("SELECT name FROM products WHERE id=?",(pid,))
        await u.message.reply_text(f"🔥 Flash sale: {int(pct*100)}% off {r['name'] if r else ''} for {hrs:.0f}h!",
            reply_markup=menu()); ctx.user_data["wf"]=None

    elif wf=="payout_req":
        vid=ctx.user_data.get("payout_vid"); amount=ctx.user_data.get("payout_amount"); ctx.user_data["wf"]=None
        vendor=q1("SELECT ltc_addr FROM vendors WHERE id=?",(vid,))
        ltc_addr=vendor["ltc_addr"] if vendor and txt.lower()=="same" else txt
        rid=qxi("INSERT INTO payout_requests(vendor_id,amount,ltc_addr) VALUES(?,?,?)",(vid,amount,ltc_addr))
        v=q1("SELECT name FROM vendors WHERE id=?",(vid,))
        try: await ctx.bot.send_message(ADMIN_ID,f"💰 <b>PAYOUT REQUEST #{rid}</b>\n{hl.escape(v['name'] if v else '?')} — £{amount:.2f}\n📤 <code>{ltc_addr}</code>",parse_mode="HTML")
        except: pass
        await u.message.reply_text(f"✅ Payout request #{rid} submitted!",reply_markup=menu())

    elif wf=="ban_user":
        if not is_admin(uid): ctx.user_data["wf"]=None; return
        try: bid=int(txt.strip())
        except: await u.message.reply_text("⚠️ Numeric user_id only."); return
        if bid==ADMIN_ID: await u.message.reply_text("❌ Cannot ban owner."); ctx.user_data["wf"]=None; return
        qx("UPDATE users SET banned=1 WHERE user_id=?",(bid,))
        await u.message.reply_text(f"🚫 User <code>{bid}</code> banned.",parse_mode="HTML",reply_markup=menu()); ctx.user_data["wf"]=None

    elif wf=="custnote_uid":
        if not is_admin(uid): ctx.user_data["wf"]=None; return
        try: cid=int(txt.strip())
        except: await u.message.reply_text("⚠️ Numeric user_id."); return
        existing=q1("SELECT note FROM customer_notes WHERE user_id=?",(cid,))
        ctx.user_data.update({"custnote_uid":cid,"wf":"custnote_text"})
        await u.message.reply_text(f"📝 Note for <code>{cid}</code>:\nCurrent: <i>{hl.escape(existing['note']) if existing else 'none'}</i>\n\nType new note:",parse_mode="HTML")

    elif wf=="custnote_text":
        cid=ctx.user_data.get("custnote_uid")
        qx("INSERT INTO customer_notes(user_id,note) VALUES(?,?)",(cid,txt))
        await u.message.reply_text("✅ Note saved.",reply_markup=menu()); ctx.user_data["wf"]=None

    elif wf=="drop_msg_user":
        oid=ctx.user_data.get("dc_oid"); uname=u.effective_user.username or str(uid)
        qx("INSERT INTO drop_chats(order_id,user_id,sender,message) VALUES(?,?,?,?)",(oid,uid,"user",txt))
        o=q1("SELECT vendor_id FROM orders WHERE id=?",(oid,))
        vendor=q1("SELECT admin_user_id FROM vendors WHERE id=?",(o["vendor_id"],)) if o else None
        notify=[ADMIN_ID]+([vendor["admin_user_id"]] if vendor and vendor.get("admin_user_id") and vendor["admin_user_id"]!=ADMIN_ID else [])
        for rid in notify:
            try: await ctx.bot.send_message(rid,f"💬 Drop Chat {oid}\n@{uname}: {hl.escape(txt)}",parse_mode="HTML",reply_markup=dc_admin_kb(oid))
            except: pass
        await u.message.reply_text(f"✅ Sent!\n\n{fmt_chat(oid)}"[:4000],parse_mode="HTML",reply_markup=dc_user_kb(oid,gs("cc_"+oid,"0")=="1"))
        ctx.user_data["wf"]=None

    elif wf=="drop_msg_admin":
        oid=ctx.user_data.get("dc_oid"); row=q1("SELECT user_id FROM orders WHERE id=?",(oid,))
        if not row: await u.message.reply_text("❌ Not found."); ctx.user_data["wf"]=None; return
        qx("INSERT INTO drop_chats(order_id,user_id,sender,message) VALUES(?,?,?,?)",(oid,row["user_id"],"admin",txt))
        try: await ctx.bot.send_message(row["user_id"],f"🏪 <b>Vendor Message</b>\n━━━━━━━━━━━━━━━━━━━━\n\n{fmt_chat(oid)}",parse_mode="HTML",reply_markup=dc_user_kb(oid,gs("cc_"+oid,"0")=="1"))
        except: pass
        await u.message.reply_text("✅ Sent.",reply_markup=menu()); ctx.user_data["wf"]=None

    elif wf=="disc_code":
        # UPGRADE 2: Support max-use codes CODE,PCT,HOURS,MAXUSES
        parts=txt.upper().split(",")
        if len(parts) not in (2,3,4): await u.message.reply_text("⚠️ Format: CODE,PCT or CODE,PCT,HOURS or CODE,PCT,HOURS,MAXUSES"); return
        try:
            dc=parts[0].strip(); pct=float(parts[1].strip())/100; assert 0<pct<=1
            exp=(datetime.now()+timedelta(hours=float(parts[2].strip()))).isoformat() if len(parts)>=3 else None
            max_uses=int(parts[3].strip()) if len(parts)==4 else -1
        except: await u.message.reply_text("⚠️ Invalid format."); return
        vid=get_vid(ctx,uid)
        qx("INSERT INTO discount_codes(code,vendor_id,pct,active,expires,max_uses) VALUES(?,?,?,1,?,?)",
           (dc,vid,pct,exp,max_uses))
        await u.message.reply_text(f"✅ <code>{dc}</code> {int(pct*100)}% off added!",parse_mode="HTML",reply_markup=menu()); ctx.user_data["wf"]=None

    elif wf=="new_cat":
        parts=txt.split(None,1)
        emoji,name=(parts[0],parts[1]) if len(parts)==2 and len(parts[0])<=2 else ("🌿",parts[0]) if len(parts)==1 else (None,None)
        if not name: await u.message.reply_text("⚠️ Format: 🍃 Category Name"); return
        vid=get_vid(ctx,uid); qxi("INSERT INTO categories(vendor_id,name,emoji) VALUES(?,?,?)",(vid,name,emoji))
        await u.message.reply_text(f"✅ {emoji} {hl.escape(name)} created!",parse_mode="HTML",reply_markup=menu()); ctx.user_data["wf"]=None

    elif wf=="order_note":
        oid=ctx.user_data.get("note_oid"); qx("INSERT INTO order_notes(order_id,note) VALUES(?,?)",(oid,txt))
        await u.message.reply_text("✅ Note saved.",reply_markup=menu()); ctx.user_data["wf"]=None

    elif wf=="edit_home":
        if not is_admin(uid): ctx.user_data["wf"]=None; return
        val="" if txt.lower()=="clear" else txt; ss("home_extra",val)
        await u.message.reply_text("✅ Cleared." if not val else f"✅ Updated: <i>{hl.escape(val)}</i>",
            parse_mode="HTML",reply_markup=menu()); ctx.user_data["wf"]=None

    elif wf=="add_admin":
        if not is_admin(uid): ctx.user_data["wf"]=None; return
        try: new_id=int(txt.strip())
        except: await u.message.reply_text("⚠️ Numeric user_id only."); return
        if q1("SELECT 1 FROM admins WHERE user_id=?",(new_id,)): await u.message.reply_text("⚠️ Already admin."); ctx.user_data["wf"]=None; return
        qx("INSERT INTO admins(user_id,username) VALUES(?,?)",(new_id,str(new_id)))
        try:
            info=await ctx.bot.get_chat(new_id); un=info.username or info.first_name or str(new_id)
            qx("UPDATE admins SET username=? WHERE user_id=?",(un,new_id))
        except: un=str(new_id)
        await u.message.reply_text(f"✅ {hl.escape(un)} added as admin.",parse_mode="HTML",reply_markup=menu()); ctx.user_data["wf"]=None

    elif wf=="add_vendor":
        if not is_admin(uid): ctx.user_data["wf"]=None; return
        parts=[p.strip() for p in txt.split("|")]
        if len(parts)!=6: await u.message.reply_text("⚠️ Need: Name|🌿|Description|ltc_address|commission_%|admin_user_id"); return
        try: com=float(parts[4]); adm_id=int(parts[5])
        except: await u.message.reply_text("⚠️ Invalid commission or admin_user_id."); return
        # UPGRADE 1: INSERT OR IGNORE so existing vendor data is preserved
        vid=qxi("INSERT INTO vendors(name,emoji,description,ltc_addr,commission_pct,admin_user_id) VALUES(?,?,?,?,?,?)",
                (parts[0],parts[1],parts[2],parts[3],com,adm_id))
        try:
            await ctx.bot.send_message(adm_id,
                f"🎉 <b>Welcome to PhiVara Network!</b>\n\n"
                f"Your vendor shop <b>{hl.escape(parts[0])}</b> is ready.\n\n"
                f"• Use /admin to manage your shop\n"
                f"• Tap ➕ Add Product to list products\n"
                f"• Commission: {com}% per sale\n"
                f"• Earnings tracked — request payouts any time\n\n"
                f"All customer payments go to platform wallet. Your balance is tracked separately.",
                parse_mode="HTML")
        except: pass
        await u.message.reply_text(f"✅ <b>{hl.escape(parts[0])}</b> added as Vendor #{vid}!",
            parse_mode="HTML",reply_markup=menu()); ctx.user_data["wf"]=None

    else:
        await u.message.reply_text("Use /start to open the menu 👇",reply_markup=menu())

async def on_photo(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid=u.effective_user.id; wf=ctx.user_data.get("wf"); ph=u.message.photo[-1].file_id
    # FIX: auto-register admins/vendor-admins
    if is_admin(uid) or is_vendor_admin(uid):
        qx("INSERT INTO users(user_id,username) VALUES(?,?)",
           (uid, u.effective_user.username or ""))
    elif not is_known(uid): return
    if wf=="add_photo":
        ctx.user_data.update({"ph":ph,"wf":"add_title"})
        await u.message.reply_text("✅ Photo saved!\n\n📝 <b>Step 2/3</b>\n\nEnter product title:",parse_mode="HTML")
    elif wf=="ann_photo":
        ctx.user_data.update({"ann_photo":ph,"wf":"ann_body"})
        await u.message.reply_text("✏️ Enter announcement body:")

# ══════════════════════════════════════════════════════════════════════════════
# BACKGROUND JOBS
# ══════════════════════════════════════════════════════════════════════════════

# UPGRADE 13: Auto LTC payment detection
async def ltc_payment_detector(ctx: ContextTypes.DEFAULT_TYPE):
    pending = qa("SELECT id,ltc,user_id,vendor_id,gbp,vendor_gbp FROM orders WHERE status='Pending' AND ltc>0 AND ship='tracked24'")
    if not pending: return
    try:
        resp = requests.get(f"https://api.blockcypher.com/v1/ltc/main/addrs/{PLATFORM_LTC}/full?limit=50", timeout=15)
        if resp.status_code != 200: return
        txs = resp.json().get("txs", [])
    except: return
    for tx in txs:
        txid = tx.get("hash","")
        if not txid or q1("SELECT 1 FROM ltc_transactions WHERE txid=?", (txid,)): continue
        total_sat = sum(o.get("value",0) for o in tx.get("outputs",[]) if PLATFORM_LTC in o.get("addresses",[]))
        if total_sat == 0: continue
        ltc_received = total_sat / 100000000; confirmations = tx.get("confirmations", 0)
        for order in pending:
            expected = order["ltc"]
            if expected > 0 and abs(ltc_received - expected) / expected < 0.02:
                qx("INSERT INTO ltc_transactions(txid,order_id,amount_ltc,confirmed) VALUES(?,?,?,?)",
                   (txid, order["id"], ltc_received, 1 if confirmations > 0 else 0))
                qx("UPDATE orders SET status='Paid' WHERE id=?", (order["id"],))
                add_timeline(order["id"], f"💠 Auto-detected: {ltc_received:.6f} LTC · {confirmations} confirmations")
                credit_vendor_balance(order["vendor_id"], order["vendor_gbp"])
                pts, cr = add_points(order["user_id"], order["gbp"])
                new_tier = update_vip_tier(order["user_id"])
                vip_note = f"\n🏆 VIP upgrade: {new_tier}!" if new_tier else ""
                try:
                    await ctx.bot.send_message(order["user_id"],
                        f"💠 <b>Payment Auto-Detected!</b>\n━━━━━━━━━━━━━━━━━━━━\n"
                        f"✅ Order <code>{order['id']}</code> confirmed!\n"
                        f"💠 {ltc_received:.6f} LTC received\n"
                        f"🎁 +{pts} loyalty points!{vip_note}",
                        parse_mode="HTML", reply_markup=KM([IB("📦 My Orders","orders")]))
                except: pass
                vendor_row = q1("SELECT admin_user_id FROM vendors WHERE id=?", (order["vendor_id"],))
                notif = (f"💰 <b>AUTO-PAYMENT DETECTED</b>\nOrder <code>{order['id']}</code>\n"
                         f"💠 {ltc_received:.6f} LTC ({confirmations} conf)\nTx: <code>{txid[:30]}...</code>\n"
                         f"💷 Vendor credit: £{order['vendor_gbp']:.2f}")
                notify_ids = [ADMIN_ID]
                if vendor_row and vendor_row.get("admin_user_id") and vendor_row["admin_user_id"] != ADMIN_ID:
                    notify_ids.append(vendor_row["admin_user_id"])
                for rid in notify_ids:
                    try: await ctx.bot.send_message(rid, notif, parse_mode="HTML",
                        reply_markup=InlineKeyboardMarkup([[IB("🚚 Dispatch", f"adm_go_{order['id']}")]]))
                    except: pass
                break

# UPGRADE 14: Pending payment reminders
async def pending_reminder_job(ctx: ContextTypes.DEFAULT_TYPE):
    cutoff = (datetime.now() - timedelta(hours=2)).isoformat()
    cutoff_old = (datetime.now() - timedelta(hours=46)).isoformat()
    rows = qa("SELECT id,user_id,ltc,gbp FROM orders WHERE status='Pending' AND ltc>0 AND created_at<? AND created_at>?",
              (cutoff, cutoff_old))
    for o in rows:
        try:
            invoice_txt, invoice_kb = build_invoice(o["id"])
            if invoice_txt:
                await ctx.bot.send_message(o["user_id"],
                    f"⏰ <b>Payment Reminder</b>\n\n"
                    f"Order <code>{o['id']}</code> is still awaiting payment.\n\n" + invoice_txt,
                    parse_mode="HTML", reply_markup=invoice_kb)
        except: pass

async def review_reminder_job(ctx: ContextTypes.DEFAULT_TYPE):
    now=datetime.now(); t24=(now-timedelta(hours=24)).isoformat(); t48=(now-timedelta(hours=48)).isoformat()
    for r in qa("SELECT order_id,user_id FROM review_reminders WHERE dispatched<? AND dispatched>?",(t24,t48)):
        qx("DELETE FROM review_reminders WHERE order_id=?",(r["order_id"],))
        if q1("SELECT 1 FROM reviews WHERE order_id=?",(r["order_id"],)): continue
        try: await ctx.bot.send_message(r["user_id"],
            f"⭐ How was order <code>{r['order_id']}</code>? Leave a quick review!",
            parse_mode="HTML",reply_markup=KM([IB("⭐ Review",f"review_{r['order_id']}")]))
        except: pass

async def auto_expire_job(ctx: ContextTypes.DEFAULT_TYPE):
    cutoff=(datetime.now()-timedelta(hours=48)).isoformat()
    rows=qa("SELECT id,user_id FROM orders WHERE status='Pending' AND created_at<?",(cutoff,))
    for r in rows:
        qx("UPDATE orders SET status='Rejected' WHERE id=?",(r["id"],))
        add_timeline(r["id"],"Auto-expired after 48h")
        try: await ctx.bot.send_message(r["user_id"],
            f"⏰ Order <code>{r['id']}</code> auto-cancelled (48h no payment).",
            parse_mode="HTML",reply_markup=menu())
        except: pass

# UPGRADE 15: Daily report to admin
async def daily_report_job(ctx: ContextTypes.DEFAULT_TYPE):
    yesterday=(datetime.now()-timedelta(days=1)).strftime("%Y-%m-%d")
    orders=q1("SELECT COUNT(*) as c,COALESCE(SUM(gbp),0) as s,COALESCE(SUM(platform_gbp),0) as p "
              "FROM orders WHERE status IN ('Paid','Dispatched') AND created_at>=? AND created_at<?",
              (yesterday,datetime.now().strftime("%Y-%m-%d"))) or {"c":0,"s":0,"p":0}
    if orders["c"]==0: return
    try:
        await ctx.bot.send_message(ADMIN_ID,
            f"📊 <b>Daily Report — {yesterday}</b>\n━━━━━━━━━━━━━━━━━━━━\n"
            f"📦 Orders: <b>{orders['c']}</b>\n"
            f"💷 Revenue: <b>£{orders['s']:.2f}</b>\n"
            f"💰 Platform cut: <b>£{orders['p']:.2f}</b>",
            parse_mode="HTML")
    except: pass

# UPGRADE 16: Low stock alert
async def low_stock_alert_job(ctx: ContextTypes.DEFAULT_TYPE):
    rows=qa("SELECT id,name,stock,vendor_id FROM products WHERE stock>0 AND stock<=3 AND hidden=0")
    for r in rows:
        vendor=q1("SELECT admin_user_id FROM vendors WHERE id=?",(r["vendor_id"],))
        if not vendor: continue
        notify=[ADMIN_ID]
        if vendor.get("admin_user_id") and vendor["admin_user_id"]!=ADMIN_ID:
            notify.append(vendor["admin_user_id"])
        for rid in notify:
            try: await ctx.bot.send_message(rid,
                f"⚠️ <b>Low Stock Alert</b>\n🌿 {hl.escape(r['name'])} — only <b>{r['stock']}</b> left!",
                parse_mode="HTML")
            except: pass

# ══════════════════════════════════════════════════════════════════════════════
# ROUTER
# ══════════════════════════════════════════════════════════════════════════════
async def router(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q=u.callback_query; d=q.data; uid=q.from_user.id
    if is_banned(uid): await q.answer("🚫 You are banned.",show_alert=True); return
    # FIX: auto-register admin/vendor-admin so they can use all buttons without /start
    if is_admin(uid) or is_vendor_admin(uid):
        qx("INSERT INTO users(user_id,username) VALUES(?,?)",
           (uid, u.effective_user.username or ""))
    elif not is_known(uid):
        await q.answer("❌ Please /start first.",show_alert=True); return
    if d.startswith("pick_"):        await pick_weight(u,ctx); return
    if d.startswith("togglehide_"):  await adm_togglehide(u,ctx); return
    if d.startswith("togglefeat_"):  await adm_togglefeat(u,ctx); return
    if d=="noop": await q.answer(); return
    await q.answer()

    ROUTES = {
        "menu":              lambda: safe_edit(q,f"🔷 <b>PhiVara Network</b>\n━━━━━━━━━━━━━━━━━━━━\n\n{open_badge()}\n🕙 Mon–Sat · Orders close 11am\n\n👇 Browse Vendors",parse_mode="HTML",reply_markup=menu()),
        "vendors":           lambda: show_vendors(u,ctx),
        "basket":            lambda: view_basket(u,ctx),
        "orders":            lambda: view_orders(u,ctx),
        "wishlist":          lambda: view_wishlist(u,ctx),
        "search_prompt":     lambda: search_prompt(u,ctx),
        "contact":           lambda: contact_start(u,ctx),
        "clear_cart":        lambda: clear_cart(u,ctx),
        "loyalty":           lambda: show_loyalty(u,ctx),
        "my_ref":            lambda: show_my_ref(u,ctx),
        "news":              lambda: show_news(u,ctx),
        "checkout":          lambda: checkout_start(u,ctx),
        "co_name":           lambda: co_name_start(u,ctx),
        "co_addr":           lambda: co_addr_start(u,ctx),
        "co_addr_skip":      lambda: co_addr_skip(u,ctx),
        "co_disc":           lambda: co_disc_start(u,ctx),
        "co_refresh":        lambda: co_refresh_cb(u,ctx),
        "co_confirm":        lambda: co_confirm(u,ctx),
        "adm_vendors":       lambda: adm_vendors(u,ctx),
        "adm_addvendor":     lambda: adm_addvendor_start(u,ctx),
        "adm_msgs":          lambda: adm_msgs(u,ctx),
        "adm_tiers":         lambda: adm_list_tiers(u,ctx),
        "adm_rmprod":        lambda: adm_rmprod_list(u,ctx),
        "adm_editdesc":      lambda: adm_editdesc_list(u,ctx),
        "adm_hideprod":      lambda: adm_hideprod_list(u,ctx),
        "adm_cats":          lambda: adm_cats(u,ctx),
        "adm_newcat":        lambda: adm_newcat(u,ctx),
        "adm_delcat":        lambda: adm_delcat_list(u,ctx),
        "adm_drops":         lambda: adm_drops(u,ctx),
        "adm_discounts":     lambda: adm_discounts(u,ctx),
        "adm_adddisc":       lambda: adm_adddisc_start(u,ctx),
        "adm_announce":      lambda: ann_start(u,ctx),
        "adm_stats":         lambda: adm_stats(u,ctx),
        "adm_feature":       lambda: adm_feature_list(u,ctx),
        "adm_stock":         lambda: adm_stock_list(u,ctx),
        "adm_bans":          lambda: adm_bans(u,ctx),
        "adm_ban_start":     lambda: adm_ban_start(u,ctx),
        "adm_custnotes":     lambda: adm_custnotes(u,ctx),
        "adm_edit_home":     lambda: adm_edit_home(u,ctx),
        "adm_admins":        lambda: adm_admins(u,ctx),
        "adm_addadmin":      lambda: adm_addadmin_start(u,ctx),
        "adm_payouts":       lambda: adm_payouts(u,ctx),
        "adm_flash":         lambda: adm_flash_list(u,ctx),
        "adm_disputes":      lambda: adm_disputes_cb(u,ctx),
        "adm_settings":      lambda: adm_settings_cb(u,ctx),
        "adm_report":        lambda: adm_report_cb(u,ctx),
        "vendor_balance":    lambda: vendor_balance_cb(u,ctx),
        "vendor_payout_req": lambda: vendor_payout_req(u,ctx),
        "ltccheck_btn":      lambda: ltccheck_btn_cb(u,ctx),
    }
    if d in ROUTES: await ROUTES[d](); return

    if   d.startswith("vend_"):          await show_vendor(u,ctx)
    elif d.startswith("cat_assign_"):    await adm_cat_assign(u,ctx)
    elif d.startswith("togglecat_"):     await adm_togglecat(u,ctx)
    elif d.startswith("cat_"):           await show_category(u,ctx)
    elif d.startswith("prod_"):          await show_product(u,ctx)
    elif d.startswith("rm_"):            await remove_item(u,ctx)
    elif d.startswith("paid_"):          await user_paid(u,ctx)
    elif d.startswith("review_"):        await review_start(u,ctx)
    elif d.startswith("reviews_"):       await show_reviews(u,ctx)
    elif d.startswith("stars_"):         await pick_stars(u,ctx)
    elif d.startswith("contact_vid_"):   await contact_vendor(u,ctx)
    elif d.startswith("co_ship_"):       await co_ship_cb(u,ctx)
    elif d.startswith("adm_ok_"):        await adm_confirm(u,ctx)
    elif d.startswith("adm_no_"):        await adm_reject(u,ctx)
    elif d.startswith("adm_go_"):        await adm_dispatch(u,ctx)
    elif d.startswith("adm_rev_"):       await adm_rev_cb(u,ctx)
    elif d.startswith("togglevend_"):    await adm_togglevend(u,ctx)
    elif d.startswith("toggledisc_"):    await adm_toggledisc(u,ctx)
    elif d.startswith("rmprod_yes_"):    await adm_rmprod_do(u,ctx)
    elif d.startswith("rmprod_"):        await adm_rmprod_confirm(u,ctx)
    elif d.startswith("editname_"):      await adm_editname_start(u,ctx)
    elif d.startswith("editdesc_"):      await adm_editdesc_start(u,ctx)
    elif d.startswith("delcat_"):        await adm_delcat_do(u,ctx)
    elif d.startswith("setstock_"):      await adm_setstock_start(u,ctx)
    elif d.startswith("edtier_"):        await adm_show_tiers(u,ctx)
    elif d.startswith("flash_set_"):     await adm_flash_set(u,ctx)
    elif d.startswith("unban_"):         await adm_unban(u,ctx)
    elif d.startswith("adm_rmadmin_"):   await adm_rmadmin(u,ctx)
    elif d.startswith("adm_note_"):      await adm_note_start(u,ctx)
    elif d.startswith("payout_ok_"):     await payout_approve(u,ctx)
    elif d.startswith("payout_no_"):     await payout_reject(u,ctx)
    elif d.startswith("dispute_close_"): await dispute_close_cb(u,ctx)
    elif d.startswith("dcv_"):           await dropchat_view(u,ctx)
    elif d.startswith("dch_"):           await dropchat_history(u,ctx)
    elif d.startswith("dcc_"):           await dropchat_close(u,ctx)
    elif d.startswith("dcac_"):          await dropchat_close(u,ctx)
    elif d.startswith("dco_"):           await dropchat_open(u,ctx)
    elif d.startswith("dcm_"):           await dropchat_msg_start(u,ctx)
    elif d.startswith("dcr_"):           await dropchat_reply_start(u,ctx)
    elif d.startswith("wish_add_"):      await wishlist_add(u,ctx)
    elif d.startswith("wish_rm_"):       await wishlist_rm(u,ctx)
    elif d.startswith("show_invoice_"):  await show_invoice_cb(u,ctx)
    elif d.startswith("refresh_rate_"):  await refresh_rate_cb(u,ctx)
    elif d.startswith("timeline_"):      await view_timeline(u,ctx)
    elif d == "adm_addprod_go":
        if is_admin(uid) or is_vendor_admin(uid):
            ctx.user_data["wf"]="add_photo"
            try: await q.message.delete()
            except: pass
            await q.message.reply_text(
                "📸 <b>Add Product — Step 1/3</b>\n\nSend a product photo, or type <b>skip</b> for no photo.",
                parse_mode="HTML")

class _Ping(BaseHTTPRequestHandler):
    def do_GET(self): self.send_response(200); self.end_headers(); self.wfile.write(b"ok")
    def log_message(self, *a): pass

def main():
    Thread(target=lambda: HTTPServer(("0.0.0.0", 8080), _Ping).serve_forever(), daemon=True).start()
    init_db()
    print(f"🔷 PhiVara Network v5.0 — DB at {DB}")

    app = (ApplicationBuilder()
           .token(TOKEN)
           .connect_timeout(30)
           .read_timeout(30)
           .write_timeout(30)
           .build())

    # Global error handler — logs ALL exceptions so nothing is silent
    async def error_handler(update, context):
        import traceback
        tb = "".join(traceback.format_exception(type(context.error), context.error, context.error.__traceback__))
        print(f"❌ ERROR:\n{tb}")
        # Don't crash on Conflict — just log it
        from telegram.error import Conflict
        if isinstance(context.error, Conflict):
            print("⚠️  Conflict: another bot instance is running. Kill old deployments on Railway.")
    app.add_error_handler(error_handler)

    app.add_handler(CommandHandler(["start","Start"], cmd_start))
    for cmd, fn in [
        ("admin",      cmd_admin),
        ("reply",      cmd_reply),
        ("order",      cmd_order),
        ("customer",   cmd_customer),
        ("myorder",    cmd_myorder),
        ("addproduct", cmd_addproduct),
        ("cancel",     cmd_cancel),
        ("search",     cmd_search),
        ("invoice",    cmd_invoice),
        ("dispute",    cmd_dispute),
        ("ltccheck",   cmd_ltccheck),
        ("set",        cmd_set),
        ("top",        cmd_top),
        ("copy",       cmd_copy),
        ("dbcheck",    cmd_dbcheck),
    ]: app.add_handler(CommandHandler(cmd, fn))
    app.add_handler(CallbackQueryHandler(router))
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    if app.job_queue:
        app.job_queue.run_repeating(ltc_payment_detector,  interval=120,   first=60)
        app.job_queue.run_repeating(review_reminder_job,   interval=3600,  first=300)
        app.job_queue.run_repeating(auto_expire_job,       interval=3600,  first=600)
        app.job_queue.run_repeating(pending_reminder_job,  interval=7200,  first=1800)
        app.job_queue.run_repeating(daily_report_job,      interval=86400, first=3600)
        app.job_queue.run_repeating(low_stock_alert_job,   interval=3600,  first=900)
    else:
        print("⚠️ Job queue not available — install python-telegram-bot[job-queue]")
    print("🔷 PhiVara Network v5.0 — Running")
    app.run_polling(
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES,
        close_loop=False,
    )

if __name__ == "__main__":
    main()
