import sqlite3
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from config.settings import settings

def _turso_sync(query: str, params: tuple = ()):
    """مزامنة الاستعلام في الخلفية مع Turso Cloud لحماية البيانات من الضياع"""
    try:
        from database.turso_sync import sync_query_to_turso
        sync_query_to_turso(query, list(params))
    except Exception as e:
        pass

class DatabaseManager:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = str(db_path or settings.DATABASE_PATH)
        self.init_database()

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_database(self):
        """تهيئة جداول قاعدة البيانات المحلية SQLite"""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # 1. جدول المتاجر المؤكدة (Stores)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS stores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                url TEXT UNIQUE NOT NULL,
                platform TEXT DEFAULT 'facebook',
                city_area TEXT,
                category TEXT,
                phone TEXT,
                is_verified INTEGER DEFAULT 1,
                is_partner INTEGER DEFAULT 0,
                discovery_source TEXT DEFAULT 'manual',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_checked_at TIMESTAMP
            );
            """)

            cursor.execute("PRAGMA table_info(stores)")
            store_cols = {row[1] for row in cursor.fetchall()}
            if "is_partner" not in store_cols:
                cursor.execute("ALTER TABLE stores ADD COLUMN is_partner INTEGER DEFAULT 0")

            # 2. جدول الروابط المستكشفة للتحقق منها لاحقاً (Discovered Links)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS discovered_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT UNIQUE NOT NULL,
                source_type TEXT,
                discovered_from TEXT,
                status TEXT DEFAULT 'pending', -- pending, approved, rejected
                ai_reason TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """)

            # 3. جدول الصفقات المكتشفة (Deals)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS deals (
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
                post_time_text TEXT DEFAULT '',
                creation_time INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                broadcasted_at TIMESTAMP,
                FOREIGN KEY (store_id) REFERENCES stores (id)
            );
            """)

            cursor.execute("PRAGMA table_info(deals)")
            deal_cols = {row[1] for row in cursor.fetchall()}
            if "post_time_text" not in deal_cols:
                cursor.execute("ALTER TABLE deals ADD COLUMN post_time_text TEXT DEFAULT ''")
            if "creation_time" not in deal_cols:
                cursor.execute("ALTER TABLE deals ADD COLUMN creation_time INTEGER DEFAULT 0")

            # 4. جدول المشتركين في بوت التليجرام (Subscribers)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS subscribers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_chat_id TEXT UNIQUE NOT NULL,
                username TEXT,
                full_name TEXT,
                category_preference TEXT DEFAULT 'all',
                area_preference TEXT DEFAULT 'all',
                subscription_status TEXT DEFAULT 'trial', -- trial, active, expired
                trial_ends_at TIMESTAMP,
                referred_by TEXT,
                referral_count INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """)

            # ترقية الجدول الحالي إن لزم الأمر
            cursor.execute("PRAGMA table_info(subscribers)")
            sub_cols = {row[1] for row in cursor.fetchall()}
            if "referred_by" not in sub_cols:
                cursor.execute("ALTER TABLE subscribers ADD COLUMN referred_by TEXT")
            if "referral_count" not in sub_cols:
                cursor.execute("ALTER TABLE subscribers ADD COLUMN referral_count INTEGER DEFAULT 0")

            # 5. جدول تنبيهات الأسعار المخصصة للمشتركين (Price Watches)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS price_watches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id TEXT NOT NULL,
                keyword TEXT NOT NULL,
                area_filter TEXT DEFAULT 'الكل',
                max_price REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(chat_id, keyword)
            );
            """)

            # 6. جدول تحليلات البحث والزيارات (Analytics Events)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS analytics_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                value TEXT NOT NULL,
                source TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """)

            # 7. جدول عروض التجار المرسلة مباشرة للمراجعة (Merchant Submissions)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS merchant_submissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                store_name TEXT NOT NULL,
                city_area TEXT NOT NULL,
                phone TEXT DEFAULT '',
                product_name TEXT NOT NULL,
                price REAL NOT NULL,
                currency TEXT DEFAULT 'ILS',
                notes TEXT DEFAULT '',
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """)

            conn.commit()

    # --- عمليات المتاجر (Stores) ---

    def add_store(self, name: str, url: str, platform: str = "facebook", 
                  city_area: str = "غزة", category: str = "عام", 
                  phone: str = "", discovery_source: str = "manual") -> int:
        """إضافة متجر جديد لقائمة المراقبة"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO stores (name, url, platform, city_area, category, phone, discovery_source)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                name=excluded.name,
                city_area=excluded.city_area,
                category=excluded.category,
                phone=excluded.phone
            """, (name, url, platform, city_area, category, phone, discovery_source))
            conn.commit()
            last_id = cursor.lastrowid
            _turso_sync("""
            INSERT INTO stores (name, url, platform, city_area, category, phone, discovery_source)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                name=excluded.name,
                city_area=excluded.city_area,
                category=excluded.category,
                phone=excluded.phone
            """, (name, url, platform, city_area, category, phone, discovery_source))
            return last_id

    def get_all_stores(self, verified_only: bool = True) -> List[Dict[str, Any]]:
        """جلب جميع المتاجر المسجلة"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            query = "SELECT * FROM stores WHERE is_verified = 1" if verified_only else "SELECT * FROM stores"
            cursor.execute(query)
            return [dict(row) for row in cursor.fetchall()]

    def update_store_checked_time(self, store_id: int):
        """تحديث وقت آخر فحص للمتجر"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE stores SET last_checked_at = CURRENT_TIMESTAMP WHERE id = ?", (store_id,))
            conn.commit()

    def update_store(self, store_id: int, name: str, city_area: str, category: str, phone: str, url: str = "") -> bool:
        """تعديل بيانات متجر (الاسم، العنوان والمنطقة، التصنيف، ورقم الجوال)"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if url:
                cursor.execute("""
                UPDATE stores 
                SET name = ?, city_area = ?, category = ?, phone = ?, url = ?
                WHERE id = ?
                """, (name, city_area, category, phone, url, store_id))
                _turso_sync("UPDATE stores SET name = ?, city_area = ?, category = ?, phone = ?, url = ? WHERE id = ?", (name, city_area, category, phone, url, store_id))
            else:
                cursor.execute("""
                UPDATE stores 
                SET name = ?, city_area = ?, category = ?, phone = ?
                WHERE id = ?
                """, (name, city_area, category, phone, store_id))
                _turso_sync("UPDATE stores SET name = ?, city_area = ?, category = ?, phone = ? WHERE id = ?", (name, city_area, category, phone, store_id))
            conn.commit()
            return cursor.rowcount > 0

    # --- عمليات الروابط المستكشفة (Discovered Links) ---

    def add_discovered_link(self, url: str, source_type: str, discovered_from: str = "") -> bool:
        """إضافة رابط محتمل تم العثور عليه في مجموعة أو بحث"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("""
                INSERT INTO discovered_links (url, source_type, discovered_from)
                VALUES (?, ?, ?)
                """, (url, source_type, discovered_from))
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False  # الرابط مسجل مسبقاً

    def get_pending_links(self, limit: int = 20) -> List[Dict[str, Any]]:
        """جلب الروابط قيد الانتظار لفحصها بالذكاء الاصطناعي"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM discovered_links WHERE status = 'pending' LIMIT ?", (limit,))
            return [dict(row) for row in cursor.fetchall()]

    def update_link_status(self, link_id: int, status: str, ai_reason: str = ""):
        """تحديث حالة الرابط المستكشف بعد فحص الـ AI"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            UPDATE discovered_links 
            SET status = ?, ai_reason = ? 
            WHERE id = ?
            """, (status, ai_reason, link_id))
            conn.commit()

    # --- عمليات الصفقات (Deals) ---

    def add_deal(self, store_id: Optional[int], product_name: str, price: float, 
                 raw_post_url: str, summary_ar: str, location: str = "", 
                 phone_contact: str = "", currency: str = "ILS", 
                 is_bargain: bool = True, media_type: str = "video",
                 post_time_text: str = "", creation_time: int = 0,
                 image_url: str = "") -> Optional[int]:
        """إضافة صفقة جديدة مكتشفة مع طابع الوقت الفعلي للنشر ورابط الصورة إن توفر"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("""
                INSERT INTO deals (store_id, product_name, price, currency, is_bargain, 
                                  raw_post_url, media_type, summary_ar, location, phone_contact, 
                                  post_time_text, creation_time, image_url)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (store_id, product_name, price, currency, int(is_bargain), 
                      raw_post_url, media_type, summary_ar, location, phone_contact, 
                      post_time_text, int(creation_time or 0), image_url))
                conn.commit()
                last_id = cursor.lastrowid
                _turso_sync("""
                INSERT INTO deals (store_id, product_name, price, currency, is_bargain, 
                                  raw_post_url, media_type, summary_ar, location, phone_contact, 
                                  post_time_text, creation_time, image_url)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (store_id, product_name, price, currency, int(is_bargain), 
                      raw_post_url, media_type, summary_ar, location, phone_contact, 
                      post_time_text, int(creation_time or 0), image_url))
                return last_id
            except sqlite3.IntegrityError:
                return None  # الصفقة مسجلة مسبقاً

    def is_post_deal_exists(self, post_url: str) -> bool:
        """التحقق مما إذا كان المنشور مسجلاً مسبقاً في جدول الصفقات لتفادي إعادة استدعاء الذكاء الاصطناعي"""
        if not post_url:
            return False
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM deals WHERE raw_post_url LIKE ? LIMIT 1", (f"{post_url}%",))
            return cursor.fetchone() is not None

    def get_unbroadcasted_deals(self) -> List[Dict[str, Any]]:
        """جلب الصفقات التي لم يتم بثها للمشتركين بعد"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            SELECT d.*, s.name as store_name 
            FROM deals d
            LEFT JOIN stores s ON d.store_id = s.id
            WHERE d.broadcasted_at IS NULL AND d.is_bargain = 1
            ORDER BY d.created_at ASC
            """)
            return [dict(row) for row in cursor.fetchall()]

    def mark_deal_broadcasted(self, deal_id: int):
        """تحديث حالة الصفقة بأنها بُثت للمشتركين محلياً وسحابياً"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE deals SET broadcasted_at = CURRENT_TIMESTAMP WHERE id = ?", (deal_id,))
            conn.commit()
        _turso_sync("UPDATE deals SET broadcasted_at = CURRENT_TIMESTAMP WHERE id = ?", (deal_id,))

    # --- عمليات المشتركين (Subscribers) ---

    def register_subscriber(self, chat_id: str, username: str = "", full_name: str = "") -> Dict[str, Any]:
        """تسجيل مشترك جديد وإعطاؤه أسبوع تجربة مجانية مع مزامنة سحابية دائمة"""
        trial_period_days = 7
        trial_end = datetime.now() + timedelta(days=trial_period_days)
        trial_str = trial_end.strftime("%Y-%m-%d %H:%M:%S")
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO subscribers (telegram_chat_id, username, full_name, trial_ends_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(telegram_chat_id) DO UPDATE SET
                username=excluded.username,
                full_name=excluded.full_name
            """, (str(chat_id), username, full_name, trial_str))
            conn.commit()

            cursor.execute("SELECT * FROM subscribers WHERE telegram_chat_id = ?", (str(chat_id),))
            res = dict(cursor.fetchone())

        # مزامنة المشترك سحابياً مع Turso لمنع فقدانه نهائياً عند إعادة تشغيل السيرفر
        _turso_sync("""
        INSERT INTO subscribers (telegram_chat_id, username, full_name, trial_ends_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(telegram_chat_id) DO UPDATE SET
            username=excluded.username,
            full_name=excluded.full_name
        """, (str(chat_id), username, full_name, trial_str))

        return res

    def get_active_subscribers(self) -> List[Dict[str, Any]]:
        """جلب المشتركين النشطين (في وضع الإطلاق المجاني يشمل كل غير المنتهين لضمان استمرار البث)"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if getattr(settings, "FREE_LAUNCH_MODE", True):
                cursor.execute("""
                SELECT * FROM subscribers 
                WHERE COALESCE(subscription_status, 'trial') != 'expired'
                """)
            else:
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                cursor.execute("""
                SELECT * FROM subscribers 
                WHERE subscription_status = 'active' 
                   OR (subscription_status = 'trial' AND trial_ends_at >= ?)
                """, (now,))
            return [dict(row) for row in cursor.fetchall()]

    def get_system_stats(self) -> Dict[str, Any]:
        """إحصائيات شاملة للمنظومة لمدير النظام"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM subscribers")
            total_subs = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM subscribers WHERE subscription_status = 'trial'")
            trial_subs = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM subscribers WHERE subscription_status = 'active'")
            paid_subs = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM stores WHERE is_verified = 1")
            verified_stores = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM deals WHERE is_bargain = 1")
            total_deals = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM deals WHERE post_time_text LIKE 'اليوم%' OR created_at >= date('now')")
            today_deals = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM deals WHERE image_url IS NOT NULL AND length(image_url) > 0")
            deals_with_images = cursor.fetchone()[0]

            return {
                "total_subs": total_subs,
                "trial_subs": trial_subs,
                "paid_subs": paid_subs,
                "verified_stores": verified_stores,
                "total_deals": total_deals,
                "today_deals": today_deals,
                "deals_with_images": deals_with_images
            }

    def get_recent_subscribers(self, limit: int = 10) -> List[Dict[str, Any]]:
        """جلب أحدث المشتركين المسجلين في البوت"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM subscribers ORDER BY id DESC LIMIT ?", (limit,))
            return [dict(row) for row in cursor.fetchall()]

    def delete_deal(self, deal_id: int) -> bool:
        """حذف صفقة من قاعدة البيانات"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM deals WHERE id = ?", (deal_id,))
            conn.commit()
            _turso_sync("DELETE FROM deals WHERE id = ?", (deal_id,))
            return cursor.rowcount > 0

    def toggle_store_status(self, store_id: int) -> Optional[int]:
        """تفعيل أو تعطيل متجر من المراقبة"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE stores SET is_verified = 1 - is_verified WHERE id = ?", (store_id,))
            conn.commit()
            _turso_sync("UPDATE stores SET is_verified = 1 - is_verified WHERE id = ?", (store_id,))
            cursor.execute("SELECT is_verified FROM stores WHERE id = ?", (store_id,))
            row = cursor.fetchone()
            return row[0] if row else None

    def toggle_store_partner(self, store_id: int) -> Optional[int]:
        """ترقية أو إلغاء تمييز متجر كشريك رسمي (⭐ أولوية في البوت والويب)"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE stores SET is_partner = 1 - COALESCE(is_partner, 0) WHERE id = ?", (store_id,))
            conn.commit()
            _turso_sync("UPDATE stores SET is_partner = 1 - COALESCE(is_partner, 0) WHERE id = ?", (store_id,))
            cursor.execute("SELECT COALESCE(is_partner, 0) FROM stores WHERE id = ?", (store_id,))
            row = cursor.fetchone()
            return row[0] if row else None

    def update_deal(self, deal_id: int, product_name: str, price: float, summary_ar: str = "", location: str = "") -> bool:
        """تعديل بيانات صفقة"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            UPDATE deals 
            SET product_name = ?, price = ?, summary_ar = ?, location = ?
            WHERE id = ?
            """, (product_name, price, summary_ar, location, deal_id))
            conn.commit()
            _turso_sync("""
            UPDATE deals 
            SET product_name = ?, price = ?, summary_ar = ?, location = ?
            WHERE id = ?
            """, (product_name, price, summary_ar, location, deal_id))
            return cursor.rowcount > 0

    def delete_store(self, store_id: int) -> bool:
        """حذف متجر من قاعدة البيانات"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM deals WHERE store_id = ?", (store_id,))
            cursor.execute("DELETE FROM stores WHERE id = ?", (store_id,))
            conn.commit()
            _turso_sync("DELETE FROM deals WHERE store_id = ?", (store_id,))
            _turso_sync("DELETE FROM stores WHERE id = ?", (store_id,))
            return cursor.rowcount > 0

    def extend_subscriber_trial(self, chat_id: str, days: int = 7) -> bool:
        """تمديد فترة تجربة المشترك"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT trial_ends_at FROM subscribers WHERE telegram_chat_id = ?", (str(chat_id),))
            row = cursor.fetchone()
            if not row:
                return False
            curr_str = row[0]
            try:
                base_dt = datetime.strptime(curr_str, "%Y-%m-%d %H:%M:%S")
                if base_dt < datetime.now():
                    base_dt = datetime.now()
            except Exception:
                base_dt = datetime.now()
            new_dt = base_dt + timedelta(days=days)
            new_date_str = new_dt.strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute("""
            UPDATE subscribers 
            SET trial_ends_at = ?, subscription_status = 'trial'
            WHERE telegram_chat_id = ?
            """, (new_date_str, str(chat_id)))
            conn.commit()
            _turso_sync("UPDATE subscribers SET trial_ends_at = ?, subscription_status = 'trial' WHERE telegram_chat_id = ?", (new_date_str, str(chat_id)))
            return True

    def update_subscriber_status(self, chat_id: str, status: str) -> bool:
        """تحديث حالة اشتراك المشترك (active, trial, expired)"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE subscribers SET subscription_status = ? WHERE telegram_chat_id = ?", (status, str(chat_id)))
            conn.commit()
            _turso_sync("UPDATE subscribers SET subscription_status = ? WHERE telegram_chat_id = ?", (status, str(chat_id)))
            return cursor.rowcount > 0

    def record_referral(self, new_user_chat_id: str, inviter_chat_id: str) -> Optional[Dict[str, Any]]:
        """تسجيل إحالة مشترك جديد ومكافأة الداعي بزيادة رصيد دعواته"""
        new_cid = str(new_user_chat_id).strip()
        inv_cid = str(inviter_chat_id).strip()
        if not new_cid or not inv_cid or new_cid == inv_cid:
            return None

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT referred_by, (julianday('now') - julianday(created_at)) * 86400 AS age_sec
                FROM subscribers WHERE telegram_chat_id = ?
            """, (new_cid,))
            new_row = cursor.fetchone()
            if not new_row or new_row[0] or (new_row[1] is not None and new_row[1] > 300):
                return None  # مسجل مسبقاً بدعوة أو عضو قديم

            cursor.execute("SELECT * FROM subscribers WHERE telegram_chat_id = ?", (inv_cid,))
            inv_row = cursor.fetchone()
            if not inv_row:
                return None

            cursor.execute("UPDATE subscribers SET referred_by = ? WHERE telegram_chat_id = ?", (inv_cid, new_cid))
            cursor.execute("UPDATE subscribers SET referral_count = COALESCE(referral_count, 0) + 1 WHERE telegram_chat_id = ?", (inv_cid,))
            conn.commit()

            cursor.execute("SELECT * FROM subscribers WHERE telegram_chat_id = ?", (inv_cid,))
            updated_inviter = dict(cursor.fetchone())

        _turso_sync("UPDATE subscribers SET referred_by = ? WHERE telegram_chat_id = ?", (inv_cid, new_cid))
        _turso_sync("UPDATE subscribers SET referral_count = COALESCE(referral_count, 0) + 1 WHERE telegram_chat_id = ?", (inv_cid,))
        return updated_inviter

    def get_subscriber(self, chat_id: str) -> Optional[Dict[str, Any]]:
        """جلب بيانات مشترك محدد"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM subscribers WHERE telegram_chat_id = ?", (str(chat_id),))
            row = cursor.fetchone()
            return dict(row) if row else None

    # --- تنبيهات الأسعار المخصصة (Price Watches) ---

    def add_price_watch(self, chat_id: str, keyword: str, area_filter: str = "الكل", max_price: Optional[float] = None) -> bool:
        """إضافة أو تحديث تنبيه سعر لمشترك"""
        kw = str(keyword or "").strip()[:60]
        if len(kw) < 2:
            return False
        area = str(area_filter or "الكل").strip()[:40]
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO price_watches (chat_id, keyword, area_filter, max_price)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(chat_id, keyword) DO UPDATE SET
                area_filter = excluded.area_filter,
                max_price = excluded.max_price
            """, (str(chat_id), kw, area, max_price))
            conn.commit()
        _turso_sync("""
        INSERT INTO price_watches (chat_id, keyword, area_filter, max_price)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(chat_id, keyword) DO UPDATE SET
            area_filter = excluded.area_filter,
            max_price = excluded.max_price
        """, (str(chat_id), kw, area, max_price))
        return True

    def get_user_watches(self, chat_id: str) -> List[Dict[str, Any]]:
        """جلب قائمة السلع التي يتابعها المشترك"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM price_watches WHERE chat_id = ? ORDER BY id DESC", (str(chat_id),))
            return [dict(r) for r in cursor.fetchall()]

    def remove_price_watch(self, chat_id: str, watch_id: int) -> bool:
        """إلغاء تنبيه سعر محدد للمشترك"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM price_watches WHERE id = ? AND chat_id = ?", (watch_id, str(chat_id)))
            conn.commit()
            removed = cursor.rowcount > 0
        if removed:
            _turso_sync("DELETE FROM price_watches WHERE id = ? AND chat_id = ?", (watch_id, str(chat_id)))
        return removed

    def find_matching_watch_chat_ids(self, product_name: str, area_text: str = "", price: float = 0) -> Dict[str, List[str]]:
        """إرجاع خريطة {chat_id: [matched_keywords]} للمشتركين المهتمين بهذه السلعة"""
        p_low = str(product_name or "").lower()
        a_low = str(area_text or "").lower()
        if not p_low:
            return {}
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT chat_id, keyword, area_filter, max_price FROM price_watches")
            watches = [dict(r) for r in cursor.fetchall()]

        matches: Dict[str, List[str]] = {}
        for w in watches:
            kw = str(w.get("keyword") or "").strip().lower()
            if not kw or kw not in p_low:
                continue
            af = str(w.get("area_filter") or "الكل").strip()
            if af and af != "الكل" and af.lower() not in a_low:
                continue
            mp = w.get("max_price")
            try:
                if mp is not None and float(price or 0) > float(mp):
                    continue
            except Exception:
                pass
            cid = str(w["chat_id"])
            matches.setdefault(cid, []).append(w["keyword"])
        return matches

    # --- التحليلات (Analytics) ---

    def log_analytics_event(self, event_type: str, value: str, source: str = ""):
        """تسجيل عملية بحث أو زيارة صفحة لقياس اهتمام المستخدمين"""
        ev = str(event_type or "").strip()[:30]
        val = str(value or "").strip()[:80]
        src = str(source or "").strip()[:30]
        if not ev or not val:
            return
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO analytics_events (event_type, value, source) VALUES (?, ?, ?)",
                    (ev, val, src)
                )
                conn.commit()
            _turso_sync(
                "INSERT INTO analytics_events (event_type, value, source) VALUES (?, ?, ?)",
                (ev, val, src)
            )
        except Exception:
            pass

    def get_analytics_summary(self, days: int = 7) -> Dict[str, Any]:
        """ملخص أكثر كلمات البحث، زيارات الموقع والبوت، وتفاصيل متابعي الأسعار خلال آخر N أيام"""
        since = f"-{int(days)} days"
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT value AS keyword, COUNT(*) AS cnt
                FROM analytics_events
                WHERE event_type = 'search' AND created_at >= datetime('now', ?)
                GROUP BY LOWER(value)
                ORDER BY cnt DESC
                LIMIT 10
            """, (since,))
            top_searches = [dict(r) for r in cursor.fetchall()]

            cursor.execute("""
                SELECT COALESCE(NULLIF(source, ''), 'direct') AS source, COUNT(*) AS cnt
                FROM analytics_events
                WHERE event_type = 'visit' AND created_at >= datetime('now', ?)
                GROUP BY COALESCE(NULLIF(source, ''), 'direct')
                ORDER BY cnt DESC
            """, (since,))
            visits_by_source = [dict(r) for r in cursor.fetchall()]

            cursor.execute("SELECT COUNT(*) FROM price_watches")
            total_watches = cursor.fetchone()[0]

            cursor.execute("""
                SELECT pw.id, pw.chat_id, pw.keyword, pw.area_filter, pw.created_at,
                       COALESCE(s.full_name, 'مشترك') AS full_name,
                       COALESCE(s.username, '') AS username
                FROM price_watches pw
                LEFT JOIN subscribers s ON s.telegram_chat_id = pw.chat_id
                ORDER BY pw.id DESC
                LIMIT 50
            """)
            watches_details = [dict(r) for r in cursor.fetchall()]

            cursor.execute("""
                SELECT COUNT(*) AS total, COUNT(DISTINCT source) AS unique_users
                FROM analytics_events
                WHERE event_type = 'bot_visit' AND created_at >= datetime('now', ?)
            """, (since,))
            bv_row = cursor.fetchone()
            bot_visits_total = bv_row[0] if bv_row else 0
            bot_unique_visitors = bv_row[1] if bv_row else 0

            cursor.execute("""
                SELECT COUNT(*) FROM analytics_events
                WHERE (event_type = 'bot_unlock' OR (event_type = 'bot_visit' AND value LIKE 'deal_%'))
                  AND created_at >= datetime('now', ?)
            """, (since,))
            bot_unlocks = cursor.fetchone()[0]

            cursor.execute("""
                SELECT
                    CASE
                        WHEN value LIKE 'deal_%' THEN 'كشف عرض من /gaza'
                        WHEN value = 'web_offers_bar' THEN 'شريط الاشتراك في /gaza'
                        WHEN value = 'channel_teaser' THEN 'قناة @gaza_safaqat'
                        WHEN value LIKE 'ref_%' THEN 'دعوة صديق'
                        ELSE 'دخول مباشر للبوت'
                    END AS ref_label,
                    COUNT(*) AS cnt
                FROM analytics_events
                WHERE event_type = 'bot_visit' AND created_at >= datetime('now', ?)
                GROUP BY ref_label
                ORDER BY cnt DESC
            """, (since,))
            bot_visits_by_ref = [dict(r) for r in cursor.fetchall()]

            cursor.execute("""
                SELECT ae.source AS chat_id, ae.value AS ref_param, ae.created_at,
                       COALESCE(s.full_name, 'مشترك') AS full_name,
                       COALESCE(s.username, '') AS username
                FROM analytics_events ae
                LEFT JOIN subscribers s ON s.telegram_chat_id = ae.source
                WHERE ae.event_type = 'bot_visit' AND ae.created_at >= datetime('now', ?)
                ORDER BY ae.id DESC
                LIMIT 15
            """, (since,))
            recent_bot_visitors = [dict(r) for r in cursor.fetchall()]

            cursor.execute("""
                SELECT COALESCE(NULLIF(source, ''), 'bot') AS src, COUNT(*) AS cnt
                FROM analytics_events
                WHERE event_type = 'search' AND created_at >= datetime('now', ?)
                GROUP BY COALESCE(NULLIF(source, ''), 'bot')
            """, (since,))
            search_by_platform = {r[0]: r[1] for r in cursor.fetchall()}

            cursor.execute("SELECT COUNT(*) FROM merchant_submissions WHERE status = 'pending'")
            pending_submissions = cursor.fetchone()[0]

        return {
            "days": days,
            "top_searches": top_searches,
            "visits_by_source": visits_by_source,
            "total_visits": sum(v["cnt"] for v in visits_by_source),
            "total_searches": sum(s["cnt"] for s in top_searches),
            "total_watches": total_watches,
            "watches_details": watches_details,
            "bot_visits_total": bot_visits_total,
            "bot_unique_visitors": bot_unique_visitors,
            "bot_unlocks": bot_unlocks,
            "bot_visits_by_ref": bot_visits_by_ref,
            "recent_bot_visitors": recent_bot_visitors,
            "search_by_platform": search_by_platform,
            "pending_submissions": pending_submissions,
        }

    # --- عروض التجار المباشرة (Merchant Submissions) ---

    def create_merchant_submission(
        self, store_name: str, city_area: str, phone: str,
        product_name: str, price: float, currency: str = "ILS", notes: str = ""
    ) -> int:
        """حفظ عرض مقدم مباشرة من تاجر بانتظار موافقة الإدارة"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO merchant_submissions (store_name, city_area, phone, product_name, price, currency, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (store_name.strip(), city_area.strip(), phone.strip(), product_name.strip(), float(price), currency.strip(), notes.strip()))
            conn.commit()
            sid = cursor.lastrowid
        _turso_sync("""
        INSERT INTO merchant_submissions (store_name, city_area, phone, product_name, price, currency, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (store_name.strip(), city_area.strip(), phone.strip(), product_name.strip(), float(price), currency.strip(), notes.strip()))
        return sid

    def get_merchant_submissions(self, status: str = "pending") -> List[Dict[str, Any]]:
        """جلب عروض التجار المرسلة"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if status == "all":
                cursor.execute("SELECT * FROM merchant_submissions ORDER BY id DESC LIMIT 50")
            else:
                cursor.execute("SELECT * FROM merchant_submissions WHERE status = ? ORDER BY id DESC LIMIT 50", (status,))
            return [dict(r) for r in cursor.fetchall()]

    def approve_merchant_submission(self, submission_id: int) -> Optional[int]:
        """اعتماد عرض تاجر وتحويله مباشرة إلى صفقة حية في الرادار"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM merchant_submissions WHERE id = ? AND status = 'pending'", (submission_id,))
            row = cursor.fetchone()
            if not row:
                return None
            sub = dict(row)

            # البحث عن متجر مطابق أو إنشاؤه وإغلاق المعاملة قبل add_deal
            cursor.execute("SELECT id FROM stores WHERE name = ? LIMIT 1", (sub["store_name"],))
            st = cursor.fetchone()
            if st:
                store_id = st[0]
            else:
                pseudo_url = f"https://safaqat-pi7r.onrender.com/merchant/{submission_id}"
                cursor.execute("""
                INSERT INTO stores (name, url, platform, city_area, category, phone, is_verified, discovery_source)
                VALUES (?, ?, 'merchant_direct', ?, 'عروض التجار', ?, 1, 'merchant_portal')
                """, (sub["store_name"], pseudo_url, sub["city_area"], sub["phone"]))
                store_id = cursor.lastrowid
                conn.commit()
                _turso_sync("""
                INSERT INTO stores (name, url, platform, city_area, category, phone, is_verified, discovery_source)
                VALUES (?, ?, 'merchant_direct', ?, 'عروض التجار', ?, 1, 'merchant_portal')
                """, (sub["store_name"], pseudo_url, sub["city_area"], sub["phone"]))

        raw_url = f"https://safaqat-pi7r.onrender.com/gaza?sub={submission_id}"
        summary = sub.get("notes") or f"عرض مباشر من {sub['store_name']} في {sub['city_area']}"
        deal_id = self.add_deal(
            store_id=store_id,
            product_name=sub["product_name"],
            price=sub["price"],
            raw_post_url=raw_url,
            summary_ar=summary,
            location=sub["city_area"],
            phone_contact=sub["phone"],
            currency=sub.get("currency") or "ILS",
            is_bargain=True,
            media_type="direct",
            post_time_text="اليوم مباشر ⚡",
            creation_time=int(datetime.now().timestamp()),
        )
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE merchant_submissions SET status = 'approved' WHERE id = ?", (submission_id,))
            conn.commit()
        _turso_sync("UPDATE merchant_submissions SET status = 'approved' WHERE id = ?", (submission_id,))
        return deal_id

    def reject_merchant_submission(self, submission_id: int) -> bool:
        """رفض عرض تاجر مرسل"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE merchant_submissions SET status = 'rejected' WHERE id = ?", (submission_id,))
            conn.commit()
            ok = cursor.rowcount > 0
        if ok:
            _turso_sync("UPDATE merchant_submissions SET status = 'rejected' WHERE id = ?", (submission_id,))
        return ok

db = DatabaseManager()

