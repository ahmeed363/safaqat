import os
import sys
import asyncio
import threading
import uvicorn
from pathlib import Path

# Add project root to sys.path
sys.path.append(str(Path(__file__).resolve().parent))

from config.settings import settings
from web.admin_app import app as web_app
from bot.telegram_bot import create_telegram_app
from core.monitor_engine import monitor_engine
from bot.alert_dispatcher import alert_dispatcher

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

def run_monitor_worker():
    """عامل فحص ورصد الصفقات في الخلفية كل 15 دقيقة مع وضع السكون الليلي الذكي"""
    interval_seconds = settings.MONITOR_INTERVAL_MINUTES * 60
    print(f"[CloudWorker] 🔄 بدء تشغيل رادار الفحص الآلي المستمر (كل {settings.MONITOR_INTERVAL_MINUTES} دقيقة)...")
    print(f"[CloudWorker] 🌙 وضع السكون الليلي مفعل من {settings.NIGHT_START_HOUR}:00 إلى {settings.NIGHT_END_HOUR}:00 بتوقيت غزة.")
    while True:
        try:
            if is_gaza_night_time():
                print("[CloudWorker] 🌙 فترة السكون الليلي لمتاجر غزة (المتاجر مغلقة). الرادار في وضع الراحة لتوفير موارد السيرفر.")
            else:
                print("[CloudWorker] 📡 بدء جولة فحص المتاجر في غزة...")
                def on_store_deals_found(deals):
                    print(f"[CloudWorker] ⚡ بث فوري لـ {len(deals)} صفقة رُصدت للتو...")
                    asyncio.run(alert_dispatcher.broadcast_all_pending_deals())

                found = monitor_engine.run_monitoring_round(on_deals_callback=on_store_deals_found)
                print(f"[CloudWorker] 🎯 انتهت جولة الفحص. إجمالي ما تم رصده في هذه الجولة: {len(found)} صفقة.")
                # تأكيد نهائي لبث أي صفقات معلقة
                asyncio.run(alert_dispatcher.broadcast_all_pending_deals())
        except Exception as e:
            print(f"[CloudWorker] ⚠️ خطأ أثناء جولة الرصد: {e}")
        
        # الانتظار حتى الجولة القادمة
        import time
        time.sleep(interval_seconds)

def main():
    print("=" * 65)
    print("⚡ منظومة صفقات غزة (Safaqat Cloud All-in-One Engine) ⚡")
    print("=" * 65)

    # 0. استيراد ومزامنة أحدث البيانات من Turso Cloud
    try:
        from database.turso_sync import sync_from_turso_on_boot
        sync_from_turso_on_boot()
    except Exception as e:
        print(f"[CloudMain] ⚠️ تعذر المزامنة التلقائية: {e}")

    # 1. تشغيل الرادار الآلي في Thread منفصل
    monitor_thread = threading.Thread(target=run_monitor_worker, daemon=True)
    monitor_thread.start()

    # 1.5 تشغيل مجدول المنشورات اليومية التلقائي (صباحاً، عصراً، مساءً بصيغ وتصاميم مختلفة)
    try:
        from core.digest_scheduler import digest_scheduler
        digest_thread = threading.Thread(target=digest_scheduler.run_forever, daemon=True)
        digest_thread.start()
    except Exception as e:
        print(f"[CloudMain] ⚠️ تعذر تشغيل مجدول النشرات: {e}")

    # 2. تشغيل سيرفر الويب وبوت التليجرام عبر lifespan
    port = int(os.environ.get("PORT", 8000))
    host = "0.0.0.0"
    print(f"[CloudWeb] 🌐 تشغيل السيرفر السحابي والبوت على المنفذ {port}...")
    uvicorn.run(web_app, host=host, port=port)

if __name__ == "__main__":
    main()
