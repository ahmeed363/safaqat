import sys
import time
import argparse
import asyncio
from pathlib import Path

# ضبط المسار
sys.path.append(str(Path(__file__).resolve().parent))

from config.settings import settings
from database.db_manager import db
from core.discovery_engine import discovery_engine
from core.monitor_engine import monitor_engine
from bot.alert_dispatcher import alert_dispatcher
from bot.telegram_bot import create_telegram_app

def print_banner():
    banner = """
    ╔═══════════════════════════════════════════════════════════════════════╗
    ║        ⚡ منظومة صفقات (Safaqat) - رادار الصفقات الذكي في غزة ⚡         ║
    ║   Autonomous AI Trade Broker & Deal Radar for Gaza Retail Market      ║
    ╚═══════════════════════════════════════════════════════════════════════╝
    """
    print(banner)

def show_status():
    """عرض إحصائيات النظام وقاعدة البيانات"""
    print_banner()
    stores = db.get_all_stores(verified_only=False)
    verified = [s for s in stores if s.get("is_verified")]
    pending_links = db.get_pending_links(limit=100)
    subscribers = db.get_active_subscribers()

    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM deals")
        total_deals = cursor.fetchone()[0]

    print("📊 إحصائيات المنظومة الحالية:")
    print(f"  🏪 إجمالي المتاجر المسجلة: {len(stores)} (المعتمدة: {len(verified)})")
    print(f"  🔍 روابط مستكشفة قيد الفحص بالـ AI: {len(pending_links)}")
    print(f"  🎯 إجمالي الصفقات المرصودة: {total_deals}")
    print(f"  👥 المشتركون النشطون: {len(subscribers)}")
    print("-" * 65)

def run_discovery():
    """تشغيل دورة اكتشاف الصفحات والمتاجر الجديدة بالذكاء الاصطناعي"""
    print_banner()
    added = discovery_engine.run_discovery_cycle()
    print(f"🎉 انتهت دورة الاستكشاف بنجاح. المتاجر المعتمدة الجديدة: {added}")

def is_gaza_night_time() -> bool:
    """فحص ما إذا كان الوقت الحالي في غزة يقع ضمن فترة السكون الليلي (من 12 ليلاً حتى 7 صباحاً)"""
    if not getattr(settings, "NIGHT_MODE_ENABLED", True):
        return False
    try:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("Asia/Gaza"))
        hour = now.hour
    except Exception:
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone(timedelta(hours=2)))
        hour = now.hour

    start = getattr(settings, "NIGHT_START_HOUR", 0)  # 12:00 منتصف الليل
    end = getattr(settings, "NIGHT_END_HOUR", 7)      # 07:00 صباحاً
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end

def run_monitor(continuous: bool = False, interval_minutes: int = 15):
    """تشغيل دورة فحص المتاجر ورصد الصفقات الحالية مع وضع السكون الليلي"""
    print_banner()
    if continuous:
        print(f"🔄 وضع الرصد التلقائي المستمر نشط! سيتم فحص كافة المتاجر دورياً كل {interval_minutes} دقيقة...")
        print(f"🌙 وضع السكون الليلي مفعل من {settings.NIGHT_START_HOUR}:00 إلى {settings.NIGHT_END_HOUR}:00 بتوقيت غزة.")
        while True:
            try:
                if is_gaza_night_time():
                    print("🌙 فترة السكون الليلي لمتاجر غزة (المتاجر مغلقة). الرادار في وضع الراحة لتوفير الموارد.")
                else:
                    found = monitor_engine.run_monitoring_round()
                    print(f"🎉 انتهت جولة الفحص. عدد الصفقات اللقطة الجديدة: {len(found)}")
                    # بث الصفقات الجديدة فوراً للمشتركين
                    if found:
                        print(f"[Dispatcher] 📢 جاري بث {len(found)} صفقة جديدة للمشتركين...")
                        asyncio.run(alert_dispatcher.broadcast_all_pending_deals())
                print(f"⏳ الانتظار لمدة {interval_minutes} دقيقة حتى الجولة القادمة...\n")
                time.sleep(interval_minutes * 60)
            except KeyboardInterrupt:
                print("\n🛑 تم إيقاف الرصد المستمر.")
                break
            except Exception as e:
                print(f"⚠️ خطأ أثناء دورة الرصد: {e}")
                time.sleep(60)
    else:
        found = monitor_engine.run_monitoring_round()
        print(f"🎉 انتهت جولة الفحص. عدد الصفقات اللقطة الجديدة: {len(found)}")
        if found:
            print(f"[Dispatcher] 📢 جاري بث {len(found)} صفقة جديدة للمشتركين...")
            asyncio.run(alert_dispatcher.broadcast_all_pending_deals())

def list_stores(area: str = "", category: str = "", limit: int = 100):
    """عرض قائمة المتاجر المعتمدة بتنسيق جدولي أنيق"""
    print_banner()
    with db.get_connection() as conn:
        cursor = conn.cursor()
        query = "SELECT id, name, city_area, category, url FROM stores WHERE is_verified = 1"
        params = []
        if area:
            query += " AND city_area LIKE ?"
            params.append(f"%{area}%")
        if category:
            query += " AND category LIKE ?"
            params.append(f"%{category}%")
        query += " ORDER BY id ASC LIMIT ?"
        params.append(limit)
        cursor.execute(query, params)
        stores = cursor.fetchall()

    print(f"🏪 قائمة المتاجر المعتمدة في النظام ({len(stores)} متجر):")
    print("-" * 105)
    print(f"{'#':<4} | {'اسم المتجر':<35} | {'المنطقة':<20} | {'التصنيف'}")
    print("-" * 105)
    for s in stores:
        s_name = s[1].replace("\n", " ").strip()
        s_area = s[2].replace("\n", " ").strip()
        s_cat = s[3].replace("\n", " ").strip()
        print(f"{s[0]:<4} | {s_name[:33]:<35} | {s_area[:18]:<20} | {s_cat}")
    print("-" * 105)
    print(f"💡 لفلترة المتاجر: python main.py stores --area غزة   (أو خانيونس / الوسطى / رفح)")

def run_broadcast():
    """بث الصفقات الجديدة للمشتركين"""
    print_banner()
    count = asyncio.run(alert_dispatcher.broadcast_all_pending_deals())
    print(f"🎉 تم بث {count} صفقة إلى قنوات وبوتات المشتركين.")

def run_bot():
    """تشغيل بوت التليجرام للمشتركين"""
    print_banner()
    if not settings.TELEGRAM_BOT_TOKEN:
        print("❌ تنبيه: لم يتم تعيين TELEGRAM_BOT_TOKEN في ملف .env!")
        print("يرجى إدخال التوكن في ملف .env لتشغيل البوت.")
        return

    app = create_telegram_app()
    print("🤖 بوت التليجرام جاهز ويعمل الآن لاستقبال المشتركين وتوزيع فترات التجربة المجانية...")
    app.run_polling()

def run_dashboard(host: str = "127.0.0.1", port: int = 8000):
    """تشغيل لوحة تحكم الويب لإدارة المنظومة"""
    import uvicorn
    print_banner()
    print(f"🚀 بدء تشغيل لوحة تحكم إدارة صفقات غزة على: http://{host}:{port}")
    print(f"🌐 افتح المتصفح على: http://{host}:{port} لإدارة المنظومة والمشتركين والصفقات.")
    uvicorn.run("web.admin_app:app", host=host, port=port, reload=False)

def main():
    parser = argparse.ArgumentParser(description="نظام صفقات - رادار الصفقات الذكي في غزة")
    subparsers = parser.add_subparsers(dest="command", help="الأوامر المتاحة")

    subparsers.add_parser("status", help="عرض إحصائيات النظام والمتاجر والصفقات")
    stores_parser = subparsers.add_parser("stores", help="استعراض قائمة المتاجر المعتمدة في النظام")
    stores_parser.add_argument("--area", default="", help="فلترة حسب المنطقة (غزة، خانيونس، دير البلح، رفح...)")
    stores_parser.add_argument("--cat", default="", help="فلترة حسب التصنيف التجاري (لحوم، تموين، منظفات...)")
    stores_parser.add_argument("--limit", type=int, default=100, help="الحد الأقصى لعدد المتاجر المعروضة")
    subparsers.add_parser("discover", help="اكتشاف صفحات ومتاجر فيسبوك جديدة بالذكاء الاصطناعي")
    monitor_parser = subparsers.add_parser("monitor", help="فحص المتاجر المسجلة ورصد أي عروض وفيديوهات جديدة")
    monitor_parser.add_argument("--loop", action="store_true", help="تشغيل الرصد بشكل مستمر وتلقائي كل فترة زمنية")
    monitor_parser.add_argument("--interval", type=int, default=settings.MONITOR_INTERVAL_MINUTES, help="الفاصل الزمني بالدقائق بين الجولات (افتراضياً 15 دقيقة)")
    subparsers.add_parser("broadcast", help="بث الصفقات الجديدة للمشتركين بحماية المحتوى")
    subparsers.add_parser("run-bot", help="تشغيل بوت التليجرام التفاعلي للمشتركين")
    
    dash_parser = subparsers.add_parser("dashboard", help="تشغيل لوحة تحكم الويب للمدير")
    dash_parser.add_argument("--host", default="127.0.0.1", help="عنوان الاستضافة (افتراضياً 127.0.0.1)")
    dash_parser.add_argument("--port", type=int, default=8000, help="منفذ التشغيل (افتراضياً 8000)")

    args = parser.parse_args()

    if args.command == "status" or not args.command:
        show_status()
    elif args.command == "stores":
        list_stores(area=args.area, category=args.cat, limit=args.limit)
    elif args.command == "discover":
        run_discovery()
    elif args.command == "monitor":
        run_monitor(continuous=args.loop, interval_minutes=args.interval)
    elif args.command == "broadcast":
        run_broadcast()
    elif args.command == "run-bot":
        run_bot()
    elif args.command == "dashboard":
        run_dashboard(host=args.host, port=args.port)

if __name__ == "__main__":
    main()
