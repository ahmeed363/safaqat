import os
import sqlite3
import threading
from typing import Optional
from database.turso_client import turso

def sync_from_turso_on_boot(local_db_path: str = "safaqat.db"):
    """
    عند إقلاع السيرفر في Render:
    استيراد أحدث نسخة من البيانات من Turso إلى الملف المحلي لضمان استمرار البيانات وحمايتها من الضياع
    """
    if not turso.is_configured:
        return

    try:
        print("[TursoSync] 🔄 جاري مزامنة قاعدة البيانات من سحابة Turso...")
        local_conn = sqlite3.connect(local_db_path)
        local_conn.row_factory = sqlite3.Row
        c = local_conn.cursor()

        # مزامنة المتاجر
        try:
            stores = turso.query("SELECT * FROM stores;")
            for s in stores:
                c.execute("""
                INSERT INTO stores (id, name, url, platform, city_area, category, phone, is_verified, discovery_source, created_at, last_checked_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET name=excluded.name, city_area=excluded.city_area, phone=excluded.phone, is_verified=excluded.is_verified, url=excluded.url;
                """, [s.get("id"), s.get("name"), s.get("url"), s.get("platform"), s.get("city_area"), s.get("category"), s.get("phone"), s.get("is_verified"), s.get("discovery_source"), s.get("created_at"), s.get("last_checked_at")])
            print(f"[TursoSync] • تم استيراد {len(stores)} متجراً معتمداً من السحابة.")
        except Exception as e:
            print(f"[TursoSync] stores sync note: {e}")

        # مزامنة الصفقات
        try:
            deals = turso.query("SELECT * FROM deals;")
            for d in deals:
                c.execute("""
                INSERT INTO deals (id, store_id, product_name, price, currency, is_bargain, confidence_score, raw_post_url, media_type, summary_ar, location, phone_contact, image_url, post_time_text, creation_time, created_at, broadcasted_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET price=excluded.price, product_name=excluded.product_name, image_url=excluded.image_url, broadcasted_at=COALESCE(deals.broadcasted_at, excluded.broadcasted_at);
                """, [d.get("id"), d.get("store_id"), d.get("product_name"), d.get("price"), d.get("currency"), d.get("is_bargain"), d.get("confidence_score"), d.get("raw_post_url"), d.get("media_type"), d.get("summary_ar"), d.get("location"), d.get("phone_contact"), d.get("image_url"), d.get("post_time_text"), d.get("creation_time"), d.get("created_at"), d.get("broadcasted_at")])
            print(f"[TursoSync] • تم استيراد {len(deals)} صفقة من السحابة.")
        except Exception as e:
            print(f"[TursoSync] deals sync note: {e}")

        # مزامنة المشتركين
        try:
            subs = turso.query("SELECT * FROM subscribers;")
            for sub in subs:
                c.execute("""
                INSERT INTO subscribers (telegram_chat_id, username, full_name, category_preference, area_preference, subscription_status, trial_ends_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(telegram_chat_id) DO UPDATE SET 
                    username=excluded.username,
                    full_name=excluded.full_name,
                    subscription_status=excluded.subscription_status, 
                    trial_ends_at=excluded.trial_ends_at;
                """, [sub.get("telegram_chat_id"), sub.get("username"), sub.get("full_name"), sub.get("category_preference"), sub.get("area_preference"), sub.get("subscription_status"), sub.get("trial_ends_at"), sub.get("created_at")])
            print(f"[TursoSync] • تم استيراد {len(subs)} مشترك من السحابة.")
        except Exception as e:
            print(f"[TursoSync] subscribers sync note: {e}")

        local_conn.commit()
        local_conn.close()
        print("[TursoSync] ✅ تم مزامنة البيانات السحابية بنجاح. أحدث البيانات متاحة ومحفوظة!")

    except Exception as ex:
        print(f"[TursoSync] ⚠️ تعذر المزامنة من Turso: {ex}")

def sync_query_to_turso(query: str, params: list = ()):
    """مزامنة أمر كتابة (INSERT, UPDATE, DELETE) فورياً إلى سحابة Turso في الخلفية"""
    if not turso.is_configured:
        return

    def _run():
        try:
            turso.execute(query, list(params))
        except Exception as e:
            print(f"[TursoSync] ⚠️ خطأ مزامنة مع السحابة: {e}")

    threading.Thread(target=_run, daemon=True).start()
