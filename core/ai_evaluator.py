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

def fast_rule_based_deal_parse(text: str, store_name: str = "") -> Optional[Dict[str, Any]]:
    """مستخرج احتياطي فائق السرعة والموثوقية لقراءة العروض الصريحة والأسعار"""
    norm = normalize_digits(text)
    pattern = r'(?:بسعر|السعر|بس|بـ|سعرها|سعر|العلبة بس|الكرتونة بس)\s*[:=]?\s*(\d+(?:\.\d+)?)\s*(?:شيكل|شواكل|ش)'
    m = re.search(pattern, norm)
    if not m:
        m = re.search(r'(\d+(?:\.\d+)?)\s*(?:شيكل|شواكل)', norm)
    
    if m:
        price = float(m.group(1))
        lines = [l.strip() for l in text.split('\n') if l.strip() and not l.strip().startswith(('#', '💳', '📍', '♦️', '📞'))]
        product = ""
        for line in lines:
            line_norm = normalize_digits(line)
            price_int_str = str(int(price)) if price.is_integer() else str(price)
            if price_int_str in line_norm and ('شيكل' in line or 'شواكل' in line or 'ش' in line):
                clean_l = re.sub(r'[\U00010000-\U0010ffff]|[\u2600-\u27bf]', '', line).strip()
                clean_l = re.split(r'بسعر|السعر|بس\s+\d|متوفر|متوفرة|بـ\s+\d', clean_l)[0].strip(' .،:-!')
                if clean_l and len(clean_l) >= 4 and clean_l not in ["العبوة", "الكرتونة", "الحجم"]:
                    product = clean_l
                    break
        if not product and lines:
            for l in lines:
                clean_l = re.sub(r'[\U00010000-\U0010ffff]|[\u2600-\u27bf]', '', l).strip(' .،:-!')
                if len(clean_l) >= 5 and not clean_l.endswith('؟'):
                    product = clean_l
                    break
        if not product and lines:
            product = re.sub(r'[\U00010000-\U0010ffff]|[\u2600-\u27bf]', '', lines[0]).strip(' .،:-!')

        loc_match = re.search(r'📍\s*([^\n]+)', text)
        location = loc_match.group(1).strip() if loc_match else ""

        deal_item = {
            "product_name": product[:45] if product else "عرض تجاري",
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
    return None

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
        استخراج كافة الصفقات والأسعار المذكورة في المنشور (يدعم تعدد الأصناف)
        """
        self._ensure_client()
        prompt = f"""
        أنت وكيل ذكي خبير بأسواق غزة ومحلات التجزئة. اقرأ المنشور التالي لتاجر:
        اسم المتجر: {store_name}
        نص المنشور:
        {post_text}

        المطلوب: استخراج **كافة الأصناف والسلع والأسعار** المذكورة في المنشور بصيغة JSON.
        إذا ذُكر أكثر من صنف (مثلاً: سمك سلطان + سمك دنيس + كبدة)، استخرج كل صنف بشكل منفصل تماماً في قائمة deals:
        {{
            "has_deals": true,
            "deals": [
                {{
                    "product_name": "اسم الصنف الأول",
                    "price": 37.0,
                    "currency": "ILS",
                    "is_bargain": true,
                    "confidence_score": 0.95,
                    "summary_ar": "ملخص جذاب للصنف وسعره",
                    "location": "المكان الفعلي المذكور",
                    "phone_contact": "رقم الهاتف إن وجد"
                }},
                {{
                    "product_name": "اسم الصنف الثاني",
                    "price": 45.0,
                    "currency": "ILS",
                    "is_bargain": true,
                    "confidence_score": 0.95,
                    "summary_ar": "ملخص جذاب للصنف وسعره",
                    "location": "المكان الفعلي المذكور",
                    "phone_contact": "رقم الهاتف إن وجد"
                }}
            ]
        }}
        إذا لم يتضمن المنشور بيع أو أسعار، اجعل has_deals: false وقائمة deals فارغة.
        """
        # محاولة الاستخراج أولاً عبر الذكاء الاصطناعي، مع استخدام المستخرج السريع كصمام أمان
        for attempt in range(2):
            try:
                response = self.client.models.generate_content(
                    model=settings.GEMINI_MODEL,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=0.1
                    )
                )
                data = json.loads(response.text)
                if "deals" in data and data["deals"]:
                    return {
                        "is_deal": True,
                        "deals": data["deals"],
                        **data["deals"][0]
                    }
                elif data.get("is_deal"):
                    return {"is_deal": True, "deals": [data], **data}
                
                # إذا لم يجد الذكاء الاصطناعي صفقة، نتأكد بالمستخرج القاعدي السريع
                rule_res = fast_rule_based_deal_parse(post_text, store_name)
                if rule_res:
                    return rule_res

                return {"is_deal": False, "deals": []}
            except Exception as e:
                err_str = str(e)
                if ("429" in err_str or "RESOURCE_EXHAUSTED" in err_str) and attempt < 1:
                    print(f"[AI Evaluator] ⏳ تم بلوغ الحد المؤقت للطلبات (429)، استخدام المستخرج السريع كبديل فوري...")
                    rule_res = fast_rule_based_deal_parse(post_text, store_name)
                    if rule_res:
                        return rule_res
                    time.sleep(10)
                    continue

                # في حال أي استثناء أو خطأ بالشبكة، المستخرج القاعدي هو خط الدفاع المضمون
                rule_res = fast_rule_based_deal_parse(post_text, store_name)
                if rule_res:
                    return rule_res
                return {"is_deal": False, "deals": [], "summary_ar": str(e)}

        rule_res = fast_rule_based_deal_parse(post_text, store_name)
        return rule_res if rule_res else {"is_deal": False, "deals": []}

ai_evaluator = AIEvaluator()
