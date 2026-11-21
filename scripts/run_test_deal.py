import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from database.db_manager import db
from core.ai_evaluator import ai_evaluator

def test_pipeline_with_sample_post():
    print("=" * 60)
    print("🧪 اختبار دورة رصد وتحليل الصفقة بالذكاء الاصطناعي (غزة)")
    print("=" * 60)

    # نموذج حقيقي لمنشور/فيديو باللهجة الغزاوية
    sample_gaza_post = (
        "يا هلا بزبائننا الكرام من قلب دير البلح.. وصّلتنا اليوم دفعة جديدة ونخب أول "
        "من ألواح طاقة شمسية جينكو 580 واط وكمان بطاريات جل فيتنامي 150 أمبير. "
        "السعر يا إخوان سعر حرق.. اللوح اليوم بنسلّمكم إياه بـ 410 شيكل كاش، "
        "والبطارية بسعر 630 شيكل. المحل فاتح بدير البلح بجوار دوار البركة، "
        "للحجز الفوري والتوصيل اتصلوا على 0599112233 الكمية محدودة جداً!"
    )

    print(f"\n📝 نص المنشور / تفريغ صوت الفيديو:\n\"{sample_gaza_post}\"\n")

    print("🤖 جاري استخراج الصفقة وتفاصيل الأسعار عبر الذكاء الاصطناعي...")
    
    # في حال وجود مفتاح Gemini
    try:
        deal = ai_evaluator.parse_deal_from_text(
            post_text=sample_gaza_post,
            store_name="البركة للطاقة - دير البلح"
        )
    except Exception as e:
        print(f"⚠️ تنبيه: لم يتم فحص الـ API مباشرة ({e}). سنعرض محاكاة للنتيجة.")
        deal = {
            "is_deal": True,
            "product_name": "لوح طاقة جينكو 580 واط + بطارية جل 150 أمبير",
            "price": 410.0,
            "currency": "ILS",
            "is_bargain": True,
            "confidence_score": 0.98,
            "summary_ar": "⚡ سعر حرق: لوح جينكو 580 واط بـ 410 شيكل وبطارية جل بـ 630 شيكل",
            "location": "دير البلح - بجوار دوار البركة",
            "phone_contact": "0599112233"
        }

    print("\n✅ نتيجة استخراج الصفقة بواسطة AI:")
    print(f"- هل هي صفقة حقيقية؟: {'نعم ✅' if deal.get('is_deal') else 'لا ❌'}")
    print(f"- السلعة: {deal.get('product_name')}")
    print(f"- السعر: {deal.get('price')} {deal.get('currency')}")
    print(f"- هل هو سعر حرق؟: {'نعم 🔥' if deal.get('is_bargain') else 'عادي'}")
    print(f"- الموقع: {deal.get('location')}")
    print(f"- رقم الهاتف: {deal.get('phone_contact')}")
    print(f"- ملخص التنبيه: {deal.get('summary_ar')}")

    # حفظ الصفقة في قاعدة البيانات
    deal_id = db.add_deal(
        store_id=1,
        product_name=deal.get("product_name"),
        price=deal.get("price"),
        currency=deal.get("currency", "ILS"),
        is_bargain=deal.get("is_bargain", True),
        raw_post_url="https://facebook.com/sample_video_gaza_deal",
        media_type="video",
        summary_ar=deal.get("summary_ar"),
        location=deal.get("location"),
        phone_contact=deal.get("phone_contact")
    )

    print(f"\n💾 تم حفظ الصفقة بنجاح في قاعدة البيانات (Deal ID: {deal_id})")

    # معاينة رسالة المشتركين المشفرة المحمية
    protected_telegram_message = (
        f"⚡ **صيد جديد - صفقة لقطة رصدها الرادار** ⚡\n\n"
        f"🛒 **السلعة:** {deal.get('product_name')}\n"
        f"💰 **السعر:** {deal.get('price')} {deal.get('currency')}\n"
        f"🏪 **المتجر:** البركة للطاقة - دير البلح\n"
        f"📍 **الموقع:** {deal.get('location')}\n"
        f"📞 **للتواصل والحجز:** `{deal.get('phone_contact')}`\n\n"
        f"📝 **التفاصيل:** {deal.get('summary_ar')}\n\n"
        f"🔒 *هذه الرسالة محمية وخاصة بك (ممنوع إعادة التوجيه أو النسخ)*"
    )

    print("\n📱 شكل الرسالة التي تصل للمشترك على تليجرام:")
    print("-" * 50)
    print(protected_telegram_message)
    print("-" * 50)

if __name__ == "__main__":
    test_pipeline_with_sample_post()
