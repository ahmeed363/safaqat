import os
import sys
import sqlite3
from pathlib import Path
from dotenv import load_dotenv

sys.path.append(str(Path(__file__).resolve().parent.parent))
load_dotenv()

from database.turso_client import turso

def main():
    if not turso.is_configured:
        print("❌ Turso is not configured in .env")
        return

    print("🚀 بدء إنشاء الجداول في سحابة Turso...")
    tables = [
        """CREATE TABLE IF NOT EXISTS stores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            url TEXT UNIQUE NOT NULL,
            platform TEXT DEFAULT 'facebook',
            city_area TEXT,
            category TEXT,
            phone TEXT,
            is_verified INTEGER DEFAULT 1,
            discovery_source TEXT DEFAULT 'manual',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_checked_at TIMESTAMP
        );""",
        """CREATE TABLE IF NOT EXISTS deals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            store_id INTEGER,
            product_name TEXT NOT NULL,
            price REAL,
            currency TEXT DEFAULT 'ILS',
            is_bargain INTEGER DEFAULT 1,
            confidence_score REAL DEFAULT 1.0,
            raw_post_url TEXT UNIQUE,
            media_type TEXT DEFAULT 'video',
            summary_ar TEXT,
            location TEXT,
            phone_contact TEXT,
            image_url TEXT,
            post_time_text TEXT,
            creation_time INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            broadcasted_at TIMESTAMP
        );""",
        """CREATE TABLE IF NOT EXISTS subscribers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_chat_id TEXT UNIQUE NOT NULL,
            username TEXT,
            full_name TEXT,
            category_preference TEXT DEFAULT 'all',
            area_preference TEXT DEFAULT 'all',
            subscription_status TEXT DEFAULT 'trial',
            trial_ends_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );""",
        """CREATE TABLE IF NOT EXISTS discovered_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT UNIQUE NOT NULL,
            source_type TEXT,
            discovered_from TEXT,
            status TEXT DEFAULT 'pending',
            ai_reason TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );"""
    ]

    for t in tables:
        turso.execute(t)
    print("✅ تم إنشاء كافة الجداول بنجاح في السحابة.")

    # قراءة البيانات المحلية safaqat.db
    conn = sqlite3.connect("safaqat.db")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # 1. رفع المتاجر (88 متجراً)
    c.execute("SELECT * FROM stores")
    stores = c.fetchall()
    print(f"🏪 جاري نقل {len(stores)} متجراً إلى Turso...")
    store_stmts = []
    for s in stores:
        sql = """INSERT OR REPLACE INTO stores (id, name, url, platform, city_area, category, phone, is_verified, discovery_source, created_at, last_checked_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);"""
        store_stmts.append((sql, [s["id"], s["name"], s["url"], s["platform"], s["city_area"], s["category"], s["phone"], s["is_verified"], s["discovery_source"], s["created_at"], s["last_checked_at"]]))
    
    # تنفيذ على دفعات لتفادي كبر حجم الطلب
    for i in range(0, len(store_stmts), 30):
        turso.execute_batch(store_stmts[i:i+30])
    print(f"✅ تم رفع {len(stores)} متجراً بنجاح!")

    # 2. رفع الصفقات (Deals)
    c.execute("SELECT * FROM deals")
    deals = c.fetchall()
    print(f"🛍️ جاري نقل {len(deals)} صفقة إلى Turso...")
    deal_stmts = []
    for d in deals:
        sql = """INSERT OR REPLACE INTO deals (id, store_id, product_name, price, currency, is_bargain, confidence_score, raw_post_url, media_type, summary_ar, location, phone_contact, image_url, post_time_text, creation_time, created_at, broadcasted_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);"""
        deal_stmts.append((sql, [d["id"], d["store_id"], d["product_name"], d["price"], d["currency"], d["is_bargain"], d["confidence_score"], d["raw_post_url"], d["media_type"], d["summary_ar"], d["location"], d["phone_contact"], d["image_url"], d["post_time_text"], d["creation_time"], d["created_at"], d["broadcasted_at"]]))

    chunk_size = 15
    for i in range(0, len(deal_stmts), chunk_size):
        chunk = deal_stmts[i:i+chunk_size]
        turso.execute_batch(chunk)
        print(f"  • تم رفع {min(i + chunk_size, len(deal_stmts))} من {len(deal_stmts)} صفقة...")
    print(f"✅ تم رفع كافة الصفقات ({len(deals)} صفقة) بنجاح!")

    # 3. رفع المشتركين (Subscribers)
    c.execute("SELECT * FROM subscribers")
    subs = c.fetchall()
    print(f"👥 جاري نقل {len(subs)} مشترك إلى Turso...")
    sub_stmts = []
    for sub in subs:
        sql = """INSERT OR REPLACE INTO subscribers (id, telegram_chat_id, username, full_name, category_preference, area_preference, subscription_status, trial_ends_at, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);"""
        sub_stmts.append((sql, [sub["id"], sub["telegram_chat_id"], sub["username"], sub["full_name"], sub["category_preference"], sub["area_preference"], sub["subscription_status"], sub["trial_ends_at"], sub["created_at"]]))

    if sub_stmts:
        turso.execute_batch(sub_stmts)
    print(f"✅ تم رفع {len(subs)} مشترك بنجاح!")

    # التحقق من الأعداد في Turso
    s_count = turso.query("SELECT COUNT(*) as count FROM stores;")[0]["count"]
    d_count = turso.query("SELECT COUNT(*) as count FROM deals;")[0]["count"]
    print(f"\n🎉 الفحص النهائي في سحابة Turso:")
    print(f"   • المتاجر في السحابة: {s_count}")
    print(f"   • الصفقات في السحابة: {d_count}")
    print("\n🚀 كل بياناتك الآن مخزنة سحابياً بنجاح للأبد!")

if __name__ == "__main__":
    main()
