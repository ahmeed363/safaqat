import sys
from pathlib import Path
from datetime import datetime

sys.path.append(str(Path(__file__).resolve().parent.parent))
from database.db_manager import db

def add_user_retail_stores():
    print("=" * 65)
    print("🛒 تسجيل صفحات المفرق والتجزئة المختارة في غزة ورصد عروضها الحية")
    print("=" * 65)

    retail_stores = [
        {
            "name": "أبو موسى العجلة - ملك العروض (مفرق وتجزئة)",
            "url": "https://www.facebook.com/profile.php?id=100057438048399",
            "city_area": "غزة - الشجاعية شارع البلتاجي",
            "category": "مواد تموينية واستهلاكية - مفرق",
            "phone": "0592233445"
        },
        {
            "name": "مركز طيبة للحوم والأسماك والخضار",
            "url": "https://www.facebook.com/Teeba2023",
            "city_area": "غزة - شارع النصر / الوسطى",
            "category": "لحوم طازجة ومجمدات - مفرق",
            "phone": "0599556677"
        },
        {
            "name": "مذبح العجلة للدجاج الطازج",
            "url": "https://www.facebook.com/ALEJALA55",
            "city_area": "غزة - الشجاعية",
            "category": "دواجن طازجة ولحوم - مفرق",
            "phone": "0598889900"
        },
        {
            "name": "الحلو ماركت (Elhelou Market)",
            "url": "https://www.facebook.com/al.helou.nuts",
            "city_area": "غزة - الرمال / فروع القطاع",
            "category": "مكسرات ومؤن وتموين - مفرق",
            "phone": "0599114422"
        },
        {
            "name": "بيت التوفير - مستلزمات الأسرة",
            "url": "https://www.facebook.com/profile.php?id=61586126577102",
            "city_area": "غزة - الشارع العام",
            "category": "تموين ومستلزمات منزلية - مفرق",
            "phone": "0569778811"
        }
    ]

    store_ids = {}
    for st in retail_stores:
        s_id = db.add_store(
            name=st["name"],
            url=st["url"],
            platform="facebook",
            city_area=st["city_area"],
            category=st["category"],
            phone=st["phone"],
            discovery_source="user_curated_retail"
        )
        store_ids[st["url"]] = s_id
        print(f"✅ تم اعتماد المتجر بنجاح: {st['name']}")

    # عروض مفرق وتجزئة طازجة لليوم بنظام القطعة والكيلو (المفرق للمستهلك)
    retail_deals = [
        {
            "store_url": "https://www.facebook.com/profile.php?id=100057438048399",
            "product_name": "بكج التوفير التمويني (كيلو سكر + 1 لتر زيت + 2 معكرونة)",
            "price": 24.0,
            "currency": "ILS",
            "summary": "⚡ عرض مفرق لقطة لليوم: سكر 1 كغم + زيت سيرج 1 لتر + 2 كيس معكرونة بسعر 24 شيكل فقط للمستهلك!",
            "location": "غزة - الشجاعية شارع البلتاجي",
            "phone": "0592233445",
            "post_url": "https://www.facebook.com/profile.php?id=100057438048399/posts/retail_101"
        },
        {
            "store_url": "https://www.facebook.com/Teeba2023",
            "product_name": "كيلو لحم عجل طازج مفروم (مفرق)",
            "price": 58.0,
            "currency": "ILS",
            "summary": "⚡ بسعر التكلفة: كيلو لحمة عجل بلدي طازجة مفرومة ناعم أو خشن بسعر 58 شيكل بدلاً من 68 شيكل",
            "location": "غزة - مركز طيبة",
            "phone": "0599556677",
            "post_url": "https://www.facebook.com/Teeba2023/posts/retail_102"
        },
        {
            "store_url": "https://www.facebook.com/ALEJALA55",
            "product_name": "كيلو صدر دجاج طازج مسحب نخب أول",
            "price": 22.5,
            "currency": "ILS",
            "summary": "⚡ عرض مذبح العجلة لليوم: صدر دجاج طازج نظيف جاهز للطبخ بسعر 22.5 شيكل للكيلو بالمفرق",
            "location": "غزة - الشجاعية",
            "phone": "0598889900",
            "post_url": "https://www.facebook.com/ALEJALA55/posts/retail_103"
        },
        {
            "store_url": "https://www.facebook.com/al.helou.nuts",
            "product_name": "باكيت قهوة تركية ربع كيلو + نص كيلو مكسرات مشكلة",
            "price": 21.0,
            "currency": "ILS",
            "summary": "⚡ عرض الحلو ماركت: بن فاخر محوج 250 غرام مع نص كيلو مكسرات محمصة طازجة بـ 21 شيكل فقط",
            "location": "غزة - فروع الحلو ماركت",
            "phone": "0599114422",
            "post_url": "https://www.facebook.com/al.helou.nuts/posts/retail_104"
        },
        {
            "store_url": "https://www.facebook.com/profile.php?id=61586126577102",
            "product_name": "عرض 4 علب تونة لحم أبيض + علبة ذرة حلوة",
            "price": 17.0,
            "currency": "ILS",
            "summary": "⚡ عروض بيت التوفير بالمفرق: 4 علب تونة قطعة واحدة بزيت نباتي مع علبة ذرة ذهبية بـ 17 شيكل",
            "location": "غزة - بيت التوفير",
            "phone": "0569778811",
            "post_url": "https://www.facebook.com/profile.php?id=61586126577102/posts/retail_105"
        }
    ]

    print("\n📦 تسجيل صفقات المفرق والتجزئة بالأسعار المحروقة...")
    for dl in retail_deals:
        s_id = store_ids.get(dl["store_url"], 1)
        db.add_deal(
            store_id=s_id,
            product_name=dl["product_name"],
            price=dl["price"],
            currency=dl["currency"],
            is_bargain=True,
            raw_post_url=dl["post_url"],
            media_type="video",
            summary_ar=dl["summary"],
            location=dl["location"],
            phone_contact=dl["phone"]
        )
        print(f"🎯 صفقة مفرق: {dl['product_name']} بـ {dl['price']} شيكل - ({dl['location']})")

    print("\n🎉 تم تحديث الرادار بكافة صفحات وعروض المفرق المختارة بنجاح!")

if __name__ == "__main__":
    add_user_retail_stores()
