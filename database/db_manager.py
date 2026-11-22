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
                discovery_source TEXT DEFAULT 'manual',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_checked_at TIMESTAMP
            );
            """)

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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                broadcasted_at TIMESTAMP,
                FOREIGN KEY (store_id) REFERENCES stores (id)
            );
            """)

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
        """تسجيل مشترك جديد وإعطاؤه أسبوع تجربة مجانية"""
        trial_period_days = 7
        trial_end = datetime.now() + timedelta(days=trial_period_days)
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO subscribers (telegram_chat_id, username, full_name, trial_ends_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(telegram_chat_id) DO UPDATE SET
                username=excluded.username,
                full_name=excluded.full_name
            """, (str(chat_id), username, full_name, trial_end.strftime("%Y-%m-%d %H:%M:%S")))
            conn.commit()

            cursor.execute("SELECT * FROM subscribers WHERE telegram_chat_id = ?", (str(chat_id),))
            return dict(cursor.fetchone())

    def get_active_subscribers(self) -> List[Dict[str, Any]]:
        """جلب المشتركين النشطين (سواء في فترة التجربة أو اشتراك مفعل)"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self.get_connection() as conn:
            cursor = conn.cursor()
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

db = DatabaseManager()

