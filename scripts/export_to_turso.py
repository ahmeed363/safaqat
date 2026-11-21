import os
import sys
import sqlite3
import argparse
from pathlib import Path

# Add project root to sys.path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from config.settings import settings

def migrate_to_turso(turso_url: str = "", turso_token: str = ""):
    """رفع كافة المتاجر والصفقات الحالية من safaqat.db المحلي إلى قاعدة بيانات Turso السحابية"""
    import libsql_client

    db_url = turso_url or os.environ.get("TURSO_DATABASE_URL")
    token = turso_token or os.environ.get("TURSO_AUTH_TOKEN")

    if not db_url or not token:
        print("❌ خطأ: يرجى تمرير رابط وقاعدة بيانات Turso والتوكن.")
        print("مثال: python scripts/export_to_turso.py --url <URL> --token <TOKEN>")
        return

    print("🚀 بدء الاتصال بسحابة Turso...")
    client = libsql_client.create_client_sync(url=db_url, auth_token=token)

    # 1. إنشاء الجداول في السحابة
    print("📦 إنشاء الجداول في سحابة Turso...")
    schema_statements = [
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
            broadcasted_at TIMESTAMP,
            FOREIGN KEY (store_id) REFERENCES stores (id)
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

    for stmt in schema_statements:
        client.execute(stmt)

    print("✅ تم إنشاء الجداول بنجاح.")

    # 2. نقل البيانات من الملف المحلي safaqat.db
    local_db_path = "safaqat.db"
    if not os.path.exists(local_db_path):
        print(f"⚠️ الملف المحلي {local_db_path} غير موجود.")
        return

    local_conn = sqlite3.connect(local_db_path)
    local_conn.row_factory = sqlite3.Row
    c = local_conn.cursor()

    # نقل المتاجر
    c.execute("SELECT * FROM stores")
    stores = c.fetchall()
    print(f"🏪 جاري نقل {len(stores)} متجراً معتمداً إلى السحابة...")
    for s in stores:
        client.execute(
            """INSERT INTO stores (id, name, url, platform, city_area, category, phone, is_verified, discovery_source, created_at, last_checked_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET name=excluded.name, city_area=excluded.city_area, phone=excluded.phone, url=excluded.url;
            """,
            [s["id"], s["name"], s["url"], s["platform"], s["city_area"], s["category"], s["phone"], s["is_verified"], s["discovery_source"], s["created_at"], s["last_checked_at"]]
        )

    # نقل الصفقات
    c.execute("SELECT * FROM deals")
    deals = c.fetchall()
    print(f"🛍️ جاري نقل {len(deals)} صفقة إلى السحابة...")
    for d in deals:
        client.execute(
            """INSERT INTO deals (id, store_id, product_name, price, currency, is_bargain, confidence_score, raw_post_url, media_type, summary_ar, location, phone_contact, image_url, post_time_text, creation_time, created_at, broadcasted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET price=excluded.price, product_name=excluded.product_name, image_url=excluded.image_url;
            """,
            [d["id"], d["store_id"], d["product_name"], d["price"], d["currency"], d["is_bargain"], d["confidence_score"], d["raw_post_url"], d["media_type"], d["summary_ar"], d["location"], d["phone_contact"], d["image_url"], d["post_time_text"], d["creation_time"], d["created_at"], d["broadcasted_at"]]
        )

    # نقل المشتركين
    c.execute("SELECT * FROM subscribers")
    subs = c.fetchall()
    print(f"👥 جاري نقل {len(subs)} مشترك إلى السحابة...")
    for sub in subs:
        client.execute(
            """INSERT INTO subscribers (id, telegram_chat_id, username, full_name, category_preference, area_preference, subscription_status, trial_ends_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET subscription_status=excluded.subscription_status, trial_ends_at=excluded.trial_ends_at;
            """,
            [sub["id"], sub["telegram_chat_id"], sub["username"], sub["full_name"], sub["category_preference"], sub["area_preference"], sub["subscription_status"], sub["trial_ends_at"], sub["created_at"]]
        )

    print("\n🎉 اكتمل نقل كافة البيانات إلى سحابة Turso بنجاح تام!")
    print("قاعدة بياناتك الآن آمنة وسحابية ولن تضيع أبداً.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="تصدير قاعدة بيانات safaqat.db إلى Turso")
    parser.add_argument("--url", default="", help="Turso Database URL")
    parser.add_argument("--token", default="", help="Turso Auth Token")
    args = parser.parse_args()
    migrate_to_turso(turso_url=args.url, turso_token=args.token)
