import sys
import argparse
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))
from database.db_manager import db

def main():
    parser = argparse.ArgumentParser(description="إضافة متجر حقيقي جديد لقائمة مراقبة رادار صفقات غزة")
    parser.add_argument("--name", required=True, help="اسم المتجر (مثال: محلات البركة للطاقة)")
    parser.add_argument("--url", required=True, help="رابط صفحة الفيسبوك أو البروفايل")
    parser.add_argument("--city", default="غزة", help="المنطقة أو المدينة (دير البلح، خانيونس، رفح، الخ)")
    parser.add_argument("--category", default="عام", help="التصنيف (طاقة شمسية، مواد تموينية، إلكترونيات، الخ)")
    parser.add_argument("--phone", default="", help="رقم الهاتف أو الواتساب")

    args = parser.parse_args()

    store_id = db.add_store(
        name=args.name,
        url=args.url,
        platform="facebook",
        city_area=args.city,
        category=args.category,
        phone=args.phone,
        discovery_source="manual_admin"
    )

    print(f"✅ تم تسجيل المتجر بنجاح برقم معرف (ID: {store_id})")
    print(f"🏪 الاسم: {args.name}")
    print(f"🔗 الرابط: {args.url}")
    print(f"📍 المنطقة: {args.city}")
    print(f"🏷️ التصنيف: {args.category}")
    print("📡 أصبح المتجر الآن تحت المراقبة اللحظية للرادار!")

if __name__ == "__main__":
    main()
