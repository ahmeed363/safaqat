import sys
from pathlib import Path

# إضافة المسار الرئيسي للمشروع
sys.path.append(str(Path(__file__).resolve().parent.parent))

from database.db_manager import db

def seed_initial_gaza_stores():
    """
    تغذية قاعدة البيانات بالمتاجر الأولية في قطاع غزة
    (طاقة شمسية، مواد تموينية، إلكترونيات، جملة) في مختلف المناطق
    """
    initial_stores = [
        {
            "name": "شركة البركة للطاقة البديلة والإنفرترات",
            "url": "https://www.facebook.com/albaraka.solar.gaza",
            "city_area": "دير البلح",
            "category": "طاقة شمسية وبطاريات",
            "phone": "0599123456",
            "discovery_source": "initial_seed"
        },
        {
            "name": "محلات الأقصى للتجارة العامة وتوزيع المواد الغذائية",
            "url": "https://www.facebook.com/alaqsa.trade.khanyounis",
            "city_area": "خانيونس",
            "category": "مواد غذائية وجملة",
            "phone": "0599654321",
            "discovery_source": "initial_seed"
        },
        {
            "name": "المهندس للمولدات وبطاريات الجل والكهرباء",
            "url": "https://www.facebook.com/almohandes.generators.gaza",
            "city_area": "الوسطى - النصيرات",
            "category": "مولدات وكهرباء",
            "phone": "0569112233",
            "discovery_source": "initial_seed"
        },
        {
            "name": "سوبر ماركت النور - عروض السلع الأساسية",
            "url": "https://www.facebook.com/alnoor.market.rafah",
            "city_area": "رفح",
            "category": "تموين وسلع أساسية",
            "phone": "0598778899",
            "discovery_source": "initial_seed"
        },
        {
            "name": "سنتر الهواتف ومستلزمات الشحن السريع",
            "url": "https://www.facebook.com/phone.center.deiralbalah",
            "city_area": "دير البلح",
            "category": "إلكترونيات وشواحن",
            "phone": "0599334455",
            "discovery_source": "initial_seed"
        }
    ]

    print("🌱 جاري إضافة المتاجر الأولية إلى قاعدة البيانات...")
    count = 0
    for store in initial_stores:
        db.add_store(
            name=store["name"],
            url=store["url"],
            platform="facebook",
            city_area=store["city_area"],
            category=store["category"],
            phone=store["phone"],
            discovery_source=store["discovery_source"]
        )
        count += 1

    print(f"✅ تمت إضافة {count} متجر بنجاح لقائمة المراقبة النشطة!")

    # إضافة صفقة تجريبية أولية للتأكد من عمل الرادار
    db.add_deal(
        store_id=1,
        product_name="لوح طاقة جينكو 580 واط نخب أول",
        price=395.0,
        currency="ILS",
        is_bargain=True,
        raw_post_url="https://www.facebook.com/albaraka.solar.gaza/videos/987654321",
        media_type="video",
        summary_ar="⚡ سعر حرق: وصل اليوم ألواح جينكو 580 واط نخب أول كفالة سنتين بسعر 395 شيكل فقط",
        location="دير البلح - شارع السلام",
        phone_contact="0599123456"
    )
    print("✅ تمت إضافة صفقة نموذجية مؤكدة لتجربة البث.")

if __name__ == "__main__":
    seed_initial_gaza_stores()
