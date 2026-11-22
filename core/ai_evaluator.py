import os
import json
import time
import re
from typing import Dict, Any, Optional
from pathlib import Path
from google import genai
from google.genai import types
from config.settings import settings

HINDI_TO_ARABIC = str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789')

def normalize_digits(text: str) -> str:
    """تحويل الأرقام المشرقية (الهندية) إلى أرقام عربية قياسية"""
    return text.translate(HINDI_TO_ARABIC)

INVALID_STANDALONE_WORDS = {
    'الكيس', 'كيس', 'أكياس', 'الباكيت', 'باكيت', 'العلبة', 'علبة',
    'عبوات', 'عبوة', 'الكرتونة', 'كرتونة', 'الحجم', 'الكيلو', 'كيلو', 'كيلوجرام',
    'حبة', 'حبات', 'قطعة', 'قطع', 'السعر', 'سعر', 'أسعار', 'عروض', 'عرض', 'سعرنا',
    'الأسعار', 'وصل', 'وصلنا', 'جديد', 'مسا الخير', 'مساء الخير', 'صباح الخير', 'التفاصيل',
    'تخفيضات', 'بضاعة', 'متوفر', 'متوفرة', 'شيكل', 'شواكل', 'ش', 'فقط', 'الكمية', 'كميات',
    'موجود', 'موجودة', 'طعم', 'مميز', 'جودة', 'بتستاهل', 'الجودة', 'الطزاجة', 'الطعم', 'الحلو'
}

def is_invalid_product_name(name: str) -> bool:
    """فحص ما إذا كان اسم السلعة المستخرج غير مفهوم أو مجرد عبوة/وزن/سعر أو عبارة ترويجية وليس سلعة حقيقية"""
    if not name or len(name.strip()) < 3:
        return True
    norm = normalize_digits(name).replace('ـ', '').replace('ی', 'ي').strip()
    if any(phrase in norm for phrase in (
        'سعر الكيلو', 'سعر العلبة', 'سعر الكيس', 'سعر الحبة', 'كيلو بـ', 'الكيس بـ',
        'العلبة بـ', 'سعرنا', 'الأسعار بتبدا', 'حبة فقط', 'عبوات بـ', 'مسا الخير',
        'مساء الخير', 'فقط بـ', 'بـ ', 'شيكل فقط', 'طعم مميز', 'بأحلى الأسعار',
        'الجودة والطزاجة', 'الطعم الحلو', 'إذا ريحة', 'مين بده', 'مين بدّه', 'فطوركم',
        'ساندويش البرغر بيكمل', 'شو بتحب', 'لمسة صغيرة', 'عرووووض', 'عروووض', 'عروضنا', 'عروض',
        'بضائع نخب', 'مش ضروري', 'رجع من جديد', 'أحلى مع', 'طعم أطباقكم', 'بتستاهل التجربة',
        'بتكمّل طعم', 'إلها عنوان', 'أسعار الفواكه والخضروات', 'قسم المجمدات', 'الفرع الأول',
        'المجنونة', 'المجنونه', 'حصرية وقوية', 'حصرية', 'نخب النخب', 'محرقة', 'تخفيضات',
        'بشرى سارة', 'حرق الأسعار', 'لا تفوتكم', 'أسعارنا', 'وصل حديثاً', 'وصلت اليوم', 'وصل اليوم',
        'قسم المنظفات', 'قسم اللحوم', 'قسم الأجبان', 'قسم الخضار', 'أقوى العروض'
    )):
        return True
    if any(norm.startswith(p) for p in ('عرض ', 'عروض ', 'عرووض ', 'عرووووض ', 'قسم ', 'أقوى ')):
        return True
    if norm.endswith('؟') or norm.endswith('?') or any(q in norm for q in ('شو بتحب', 'مين بده', 'مين بدّه')):
        return True
    clean = re.sub(r'[\d\.\-،…!؟\(\)]+', '', norm).strip()
    tokens = [t for t in re.split(r'\s+', clean) if t and t not in ('ب', 'في', 'من', 'و', 'فقط', 'الـ')]
    if not tokens:
        return True
    if all(t in INVALID_STANDALONE_WORDS for t in tokens):
        return True
    return False

def clean_product_title(text: str, store_name: str = "") -> str:
    """تنظيف اسم السلعة من عبارات الدعاية والتسويق واسم المتجر"""
    t = re.sub(r'[\U00010000-\U0010ffff]|[\u2600-\u27bf]', '', text).strip(' .،:-!؟')
    t = re.sub(r'^(?:وصل حديثاً|وصلت اليوم|جددنالكم الكمية وبجودة عالية|عرض خاص|عرض|متوفر الآن|متوفرة|بشرى سارة|عروض التوفير|طعم مميز وجودة بتستاهل|الجودة والطزاجة بأحلى الأسعار)\s*', '', t).strip(' .،:-!؟')
    if store_name:
        clean_store = re.sub(r'[|].*', '', store_name).strip()
        t = re.sub(r'\s*(?:من|داخل|في|لدى)\s+' + re.escape(clean_store) + r'.*', '', t, flags=re.IGNORECASE).strip(' .،:-!؟')
    t = re.sub(r'\s*(?:من|داخل|في|لدى)\s+(?:مول|سوبرماركت|مركز|هايبر|ماركت)\s+[\w\s]+', '', t).strip(' .،:-!؟')
    return t

def fast_rule_based_deal_parse(text: str, store_name: str = "") -> Optional[Dict[str, Any]]:
    """مستخرج احتياطي ذكي وفائق الدقة يضمن استخراج اسم السلعة الحقيقي حصراً"""
    norm = normalize_digits(text)
    pattern = r'(?:بسعر|السعر|سعر الكيلو|سعر|بس|بـ)\s*[:=]?\s*(\d+(?:\.\d+)?)\s*(?:شيكل|شواكل|ش|فقط)'
    m = re.search(pattern, norm)
    if not m:
        m = re.search(r'(\d+(?:\.\d+)?)\s*(?:شيكل|شواكل)', norm)
    
    if not m:
        return None

    price = float(m.group(1))
    lines = [l.strip() for l in text.split('\n') if l.strip() and not l.strip().startswith(('#', '💳', '📍', '♦️', '📞', '🛒'))]
    if not lines:
        return None

    product = ""
    # الأولوية 1: فحص سطر السعر نفسه (السلعة تذكر دائماً قبل السعر مباشرة: كبدة خروف مبردة بسعر 33 ش)
    for idx, line in enumerate(lines):
        line_norm = normalize_digits(line)
        price_int_str = str(int(price)) if price.is_integer() else str(price)
        if price_int_str in line_norm and any(w in line_norm for w in ('شيكل', 'شواكل', 'ش', 'سعر', 'بسعر', 'بـ')):
            clean_l = clean_product_title(line, store_name)
            candidate = re.split(r'سعر الكيلو|سعر العلبة|سعر الكيس|بسعر|السعر|بس\s+\d|متوفر|متوفرة|بـ\s*\d|ب\s*\d', clean_l)[0].strip(' .،:-!')
            if not is_invalid_product_name(candidate) and len(candidate) >= 3:
                product = candidate
                break
            # إذا كان سطر السعر مجرد عبوة/سعر (مثل: "سعر الكيلو 6 شيكل")، نبحث في السطر الذي يسبقه مباشرة
            for prev_idx in range(idx - 1, -1, -1):
                prev_clean = clean_product_title(lines[prev_idx], store_name)
                if not is_invalid_product_name(prev_clean) and len(prev_clean) >= 3:
                    product = prev_clean
                    break
            if product:
                break

    # الأولوية 2: فحص السطر الأول فقط إذا لم يكن عنواناً ترويجياً ولم نجد في سطر السعر
    if not product or is_invalid_product_name(product):
        first_clean = clean_product_title(lines[0], store_name)
        if not is_invalid_product_name(first_clean) and len(first_clean) >= 3:
            product = first_clean

    # الأولوية 3: البحث في باقي الأسطر
    if not product or is_invalid_product_name(product):
        for l in lines:
            candidate = clean_product_title(l, store_name)
            if not is_invalid_product_name(candidate) and len(candidate) >= 3 and not candidate.endswith('؟'):
                product = candidate
                break

    # إذا تعذر العثور على اسم سلعة حقيقي مفهوم، نرفض إنشاء صفقة وهمية
    if not product or is_invalid_product_name(product):
        return None

    loc_match = re.search(r'📍\s*([^\n]+)', text)
    location = loc_match.group(1).strip() if loc_match else ""

    deal_item = {
        "product_name": product[:50],
        "price": price,
        "currency": "ILS",
        "is_bargain": True,
        "confidence_score": 0.95,
        "summary_ar": f"عرض {product} بسعر {price} شيكل في {store_name}",
        "location": location,
        "phone_contact": ""
    }
    return {
        "is_deal": True,
        "deals": [deal_item],
        **deal_item
    }

class AIEvaluator:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or settings.GEMINI_API_KEY
        if self.api_key:
            self.client = genai.Client(api_key=self.api_key, http_options={'api_version': 'v1beta'})
        else:
            self.client = None

    def _ensure_client(self):
        if not self.client:
            if settings.GEMINI_API_KEY:
                self.client = genai.Client(api_key=settings.GEMINI_API_KEY, http_options={'api_version': 'v1beta'})
            else:
                raise ValueError("لم يتم ضبط GEMINI_API_KEY في ملف .env!")

    def evaluate_facebook_page(self, page_name: str, page_bio: str, recent_posts: str) -> Dict[str, Any]:
        """
        تقييم صفحة فيسبوك جديدة تم اكتشافها:
        هل هي متجر تجاري حقيقي ينشر بضائع وأسعار في قطاع غزة؟
        """
        self._ensure_client()
        prompt = f"""
        أنت محلل تجاري ذكي خبير في السوق المحلي في قطاع غزة.
        مهمتك فحص بيانات الصفحة التالية وتحديد ما إذا كانت تنتمي لـ (محل، تاجر جملة، أو متجر حقيقي ينشر عروض وسلع وأسعار في غزة):

        اسم الصفحة: {page_name}
        النبذة (Bio): {page_bio}
        عينات من المنشورات الأخيرة:
        {recent_posts}

        المطلوب: أجب بصيغة JSON فقط بهذا الهيكل الدقيق:
        {{
            "is_valid_gaza_shop": true,
            "confidence_score": 0.95,
            "shop_category": "طاقة شمسية وبطاريات",
            "city_area": "دير البلح",
            "phone_number": "059xxxxxxx",
            "reason": "الصفحة لمتجر حقيقي ينشر أسعار بطاريات ومحولات في دير البلح"
        }}
        إذا كانت الصفحة ليست متجراً تجارياً (مثلاً صفحة إخبارية، شخصية، ترفيهية، جمعية خيرية)، اجعل is_valid_gaza_shop: false.
        """

        try:
            response = self.client.models.generate_content(
                model=settings.GEMINI_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.1
                )
            )
            return json.loads(response.text)
        except Exception as e:
            return {
                "is_valid_gaza_shop": False,
                "confidence_score": 0.0,
                "shop_category": "غير معروف",
                "city_area": "غير معروف",
                "phone_number": "",
                "reason": f"خطأ في التحليل: {str(e)}"
            }

    def parse_deal_from_media(self, media_path: str, caption_text: str = "", store_name: str = "") -> Dict[str, Any]:
        """
        الاستماع إلى فيديو أو تسجيل صوتي للتاجر باللهجة الغزاوية المحكية
        واستخراج تفاصيل الصفقة والأسعار بدقة بالغة.
        """
        self._ensure_client()
        media_file_path = Path(media_path)
        if not media_file_path.exists():
            raise FileNotFoundError(f"الملف غير موجود: {media_path}")

        prompt = f"""
        أنت وكيل ذكي خبير في فهم اللهجة الفلسطينية العامية (لهجة أهل قطاع غزة).
        استمع بدقة إلى هذا المقطع (فيديو/صوت) الذي يتحدث فيه تاجر من غزة عن بضاعته.
        اسم المتجر (إن توفر): {store_name}
        النص المكتوب المرافق للفيديو: {caption_text}

        مهمتك:
        1. استخراج السلعة المعروضة ومواصفاتها.
        2. استخراج السعر المذكور في الفيديو/الصوت (عادة بالشيكل ILS أو الدولار USD).
        3. تقييم هل هذا العرض هو "سعر حرق / لقطة" يستحق إرساله للمشتركين.
        4. استخراج رقم الهاتف والموقع إذا تم ذكرهما شفهياً.
        5. كتابة ملخص جذاب ومختصر جداً باللهجة أو العربية الفصحى البسيطة.

        المطلوب: أجب بصيغة JSON فقط بهذا الهيكل:
        {{
            "is_deal": true,
            "product_name": "اسم السلعة بدقة (مثلاً: لوح طاقة جينكو 580 واط)",
            "price": 420.0,
            "currency": "ILS",
            "is_bargain": true,
            "confidence_score": 0.95,
            "summary_ar": "⚡ عرض حرق: لوح جينكو 580 واط بسعر 420 شيكل لدى محل ... في دير البلح",
            "location": "دير البلح - شارع السلام",
            "phone_contact": "059xxxxxxx"
        }}
        إذا لم يكن هناك أي سلعة أو سعر مذكور في الفيديو، اجعل is_deal: false.
        """

        try:
            # رفع الملف إلى Gemini API لمعالجته صوتياً/مرئياً
            uploaded_file = self.client.files.upload(file=str(media_file_path))
            
            response = self.client.models.generate_content(
                model=settings.GEMINI_MODEL,
                contents=[uploaded_file, prompt],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.1
                )
            )
            return json.loads(response.text)
        except Exception as e:
            return {
                "is_deal": False,
                "product_name": "",
                "price": 0.0,
                "currency": "ILS",
                "is_bargain": False,
                "confidence_score": 0.0,
                "summary_ar": f"فشل الاستماع للمقطع: {str(e)}",
                "location": "",
                "phone_contact": ""
            }

    def parse_deal_from_text(self, post_text: str, store_name: str = "") -> Dict[str, Any]:
        """
        استخراج كافة الصفقات والأسعار المذكورة في المنشور بدقة متناهية بالذكاء الاصطناعي مع منع أي أصناف مبهمة
        """
        self._ensure_client()
        prompt = f"""
        أنت وكيل ذكي خبير بأسواق غزة ومحلات التجزئة. اقرأ المنشور التالي لتاجر بدقة شديدة:
        اسم المتجر: {store_name}
        نص المنشور:
        {post_text}

        قواعد حاسمة وإلزامية لاستخراج اسم الصنف (product_name):
        1. يجب أن يكون اسم الصنف (product_name) واضحاً ومحدداً ومفهوماً للسلعة بذاتها (مثل: مفتول البدرساوي، أرز يونجا بسمتي، عسل أسود الرشيدي، سائل جلي، دجاج مبرد، شيبس برينجلز).
        2. يُمنع منعاً باتاً وضع كلمات عامة، أو وحدات وزن وعبوات فقط، أو أرقام، أو نصوص الأسعار كاسم للسلعة، مثل: (الكيس، الكيلو، العلبة، 5 عبوات، 12 حبة، سعرنا 48 شيكل، كيلو بـ 8 شيكل، عرض خاص).
        3. إذا كان السعر مكتوباً بجانب العبوة أو الوزن (مثال: 'الكيس بـ 20 شيكل' أو 'كيلو بـ 8 شيكل')، ابحث في باقي المنشور والأسطر السابقة لتعرف ما هي السلعة المعروضة بالضبط واستخرج اسمها الحقيقي (مثل: مفتول البدرساوي، أرز بسمتي).
        4. إذا لم يكن واضحاً ما هي السلعة المحددة على الإطلاق، لا تعتبرها صفقة (has_deals: false).

        المطلوب: استخراج كافة الأصناف المحددة بصيغة JSON:
        {{
            "has_deals": true,
            "deals": [
                {{
                    "product_name": "اسم السلعة الحقيقي والمحدد",
                    "price": 20.0,
                    "currency": "ILS",
                    "is_bargain": true,
                    "confidence_score": 0.95,
                    "summary_ar": "ملخص واضح وجذاب للصنف وسعره",
                    "location": "المكان الفعلي المذكور إن وجد",
                    "phone_contact": "رقم الهاتف إن وجد"
                }}
            ]
        }}
        إذا لم يتضمن المنشور بيع أو كانت السلعة مجهولة، اجعل has_deals: false وقائمة deals فارغة.
        """
        models_to_try = [
            settings.GEMINI_MODEL,
            "gemini-3.1-flash-lite",
            "gemini-3-flash-preview",
            "gemini-3.5-flash",
            "gemini-2.5-flash"
        ]
        # إزالة التكرار مع الحفاظ على الترتيب
        seen_m = set()
        unique_models = []
        for m in models_to_try:
            if m and m not in seen_m:
                seen_m.add(m)
                unique_models.append(m)
        models_to_try = unique_models
        # محاولة الاستخراج أولاً عبر الذكاء الاصطناعي مع التبديل التلقائي بين النماذج
        for model_name in models_to_try:
            try:
                response = self.client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=0.1
                    )
                )
                data = json.loads(response.text)
                deals_list = data.get("deals", [])
                
                # تصفية أي صنف رديء أو غير مفهوم
                valid_deals = []
                for d in deals_list:
                    p_name = clean_product_title(d.get("product_name", ""))
                    if not is_invalid_product_name(p_name):
                        d["product_name"] = p_name
                        valid_deals.append(d)

                if valid_deals:
                    return {
                        "is_deal": True,
                        "deals": valid_deals,
                        **valid_deals[0]
                    }
                elif not deals_list:
                    # النموذج فحص المنشور ولم يجد صفقات حقيقية
                    return {"is_deal": False, "deals": []}
            except Exception as e:
                err_str = str(e)
                print(f"[AI Evaluator] ⚠️ تنبيه مع النموذج {model_name}: {err_str[:80]}")
                continue

        # خط الدفاع الأخير: المستخرج السريع مع فلتر الجودة الصارم
        rule_res = fast_rule_based_deal_parse(post_text, store_name)
        return rule_res if rule_res else {"is_deal": False, "deals": []}

ai_evaluator = AIEvaluator()
