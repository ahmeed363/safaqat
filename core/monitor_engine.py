import time
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from config.settings import settings
from database.db_manager import db
from core.media_processor import media_processor
from core.ai_evaluator import ai_evaluator

def format_post_timestamp(ctime: Optional[int]) -> str:
    """تحويل طابع الوقت الفعلي لفيسبوك (creation_time) إلى نص عربي دقيق جداً"""
    if not ctime:
        return ""
    try:
        dt = datetime.fromtimestamp(ctime)
        now = datetime.now()
        diff = now - dt
        diff_seconds = diff.total_seconds()

        hour_str = dt.strftime("%I:%M").lstrip("0")
        am_pm = "م" if dt.hour >= 12 else "ص"
        exact_time = f"الساعة {hour_str} {am_pm}"

        # اليوم نفسه
        if dt.date() == now.date():
            if diff_seconds < 60:
                rel = "الآن مباشرة ⚡"
            elif diff_seconds < 3600:
                mins = int(diff_seconds // 60)
                rel = f"قبل {mins} دقيقة ⚡"
            elif diff_seconds < 7200:
                rel = "قبل ساعة واحدة"
            elif diff_seconds < 36000:
                hrs = int(diff_seconds // 3600)
                rel = f"قبل {hrs} ساعات"
            else:
                hrs = int(diff_seconds // 3600)
                rel = f"قبل {hrs} ساعة"
            return f"اليوم {exact_time} ({rel})"

        # أمس
        yesterday = now.date() - timedelta(days=1)
        if dt.date() == yesterday:
            return f"أمس {exact_time}"

        # أقدم من أمس
        days = (now.date() - dt.date()).days
        if days == 2:
            return f"نُشر بتاريخ {dt.strftime('%d/%m/%Y')} {exact_time} (قبل يومين)"
        else:
            return f"نُشر بتاريخ {dt.strftime('%d/%m/%Y')} {exact_time} (قبل {days} أيام)"
    except Exception:
        return ""

class MonitorEngine:
    def __init__(self):
        pass

    def check_store_for_new_deals(self, store: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        فحص متجر معين والبحث عن أي منشورات أو فيديوهات جديدة
        واستخراج الصفقات منها بالذكاء الاصطناعي مع التحقق من تاريخ وتوقيت النشر الحقيقي
        """
        store_id = store["id"]
        store_name = store["name"]
        store_url = store["url"]
        print(f"[Monitor] 📡 فحص المتجر: {store_name} ({store_url})")

        new_deals = []
        
        # جلب المنشورات الحديثة عبر فحص المحتوى والبحث الموجه مع التوقيت الحقيقي
        recent_posts = self._fetch_store_recent_posts(store_url, store_name=store_name)

        for post in recent_posts:
            post_url = post.get("url")
            caption = post.get("caption", "")
            media_type = post.get("type", "video") # video أو text
            post_time_text = post.get("post_time_text", "")
            ctime = post.get("creation_time")

            # سياسة نضارة العروض: تخطي المنشورات القديمة جداً (أكثر من 48 ساعة)
            # لتفادي بث عروض منتهية أو قديمة كمفاجأة جديدة للمشتركين
            if ctime:
                age_seconds = time.time() - ctime
                if age_seconds > 48 * 3600:
                    print(f"[Monitor] ⏳ تم تخطي منشور قديم ({post_time_text or 'أكثر من 48 ساعة'}): {caption[:40]}...")
                    continue

            deal_data = None
            audio_path = None

            try:
                if media_type == "video" and post_url:
                    # تنزيل الصوت وتحليله بالذكاء الاصطناعي (لهجة أهل غزة)
                    audio_path = media_processor.download_audio_from_post(post_url)
                    if audio_path:
                        deal_data = ai_evaluator.parse_deal_from_media(
                            media_path=audio_path,
                            caption_text=caption,
                            store_name=store_name
                        )
                else:
                    # تحليل النص العادي
                    deal_data = ai_evaluator.parse_deal_from_text(
                        post_text=caption,
                        store_name=store_name
                    )
                    time.sleep(4.5) # احترام حدود الـ Rate Limit (13 RPM) لتفادي أي حظر مؤقت

                if deal_data and deal_data.get("is_deal"):
                    extracted_deals = deal_data.get("deals", [deal_data])
                    for item in extracted_deals:
                        if not item.get("is_bargain", True):
                            continue
                        
                        p_name = item.get("product_name", "").strip()
                        from core.ai_evaluator import is_invalid_product_name
                        if is_invalid_product_name(p_name):
                            print(f"[Monitor] 🛑 تم حجب وإلغاء صفقة مبهمة غير صريحة: '{p_name}'")
                            continue

                        unique_url = f"{post_url}#{item.get('product_name')[:20]}" if post_url else f"{store_url}/posts/{int(time.time())}_{item.get('product_name')[:10]}"
                        final_time_text = post_time_text or item.get("post_time_text", "")
                        
                        post_img_url = item.get("image_url") or post.get("image_url", "")
                        deal_id = db.add_deal(
                            store_id=store_id,
                            product_name=item.get("product_name", "سلعة غير محددة"),
                            price=float(item.get("price", 0.0)),
                            currency=item.get("currency", "ILS"),
                            is_bargain=True,
                            raw_post_url=unique_url,
                            media_type=media_type,
                            summary_ar=item.get("summary_ar", ""),
                            location=item.get("location") or store.get("city_area", ""),
                            phone_contact=item.get("phone_contact") or store.get("phone", ""),
                            post_time_text=final_time_text,
                            creation_time=int(ctime or 0),
                            image_url=post_img_url
                        )

                        if deal_id:
                            print(f"[Monitor] 🎯 صيد جديد! تم رصد: {item.get('product_name')} بسعر {item.get('price')} {item.get('currency')} (توقيت النشر: {final_time_text or 'اليوم'})")
                            new_deals.append({
                                **item, 
                                "deal_id": deal_id, 
                                "store_name": store_name,
                                "post_time_text": final_time_text,
                                "raw_post_url": unique_url
                            })

            finally:
                # تنظيف الملفات المؤقتة
                if audio_path:
                    media_processor.cleanup_file(audio_path)

        db.update_store_checked_time(store_id)
        return new_deals

    def run_monitoring_round(self) -> List[Dict[str, Any]]:
        """تشغيل جولة فحص على كافة المتاجر المعتمدة"""
        stores = db.get_all_stores(verified_only=True)
        print(f"[Monitor] 🚀 بدء جولة الفحص على {len(stores)} متجر معتمد في غزة...")
        all_found_deals = []

        for store in stores:
            try:
                deals = self.check_store_for_new_deals(store)
                all_found_deals.extend(deals)
            except Exception as e:
                print(f"[Monitor] ⚠️ خطأ أثناء فحص المتجر {store['name']}: {e}")

        return all_found_deals

    def _fetch_store_recent_posts(self, store_url: str, store_name: str = "") -> List[Dict[str, Any]]:
        """
        استخراج أحدث المنشورات والعروض الحقيقية مع روابط المنشورات الفردية وتوقيت النشر الحقيقي من فيسبوك
        """
        import requests
        import json
        import re

        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
        }

        posts = []
        try:
            resp = requests.get(store_url, headers=headers, timeout=12)
            if resp.status_code != 200:
                print(f"[Monitor] ⚠️ تعذر فتح الصفحة لـ {store_name} (HTTP {resp.status_code})")
                return []

            # 1. بناء خريطة التوقيت creation_time لجميع منشورات الصفحة بدقة
            time_map = {}
            for m in re.finditer(r'"post_id":"(\d+)".*?"creation_time":(\d+)', resp.text):
                time_map[m.group(1)] = int(m.group(2))
            for m in re.finditer(r'"creation_time":(\d+).*?"post_id":"(\d+)"', resp.text):
                time_map[m.group(2)] = int(m.group(1))

            scripts = re.findall(r'<script type="application/json"[^>]*>(.*?)</script>', resp.text, re.DOTALL)
            seen_texts = set()

            for s in scripts:
                if "comet_sections" in s or "feedback" in s or '"message":' in s:
                    try:
                        data = json.loads(s)
                        def search_posts_with_links(obj):
                            if isinstance(obj, dict):
                                if "message" in obj and isinstance(obj["message"], dict) and "text" in obj["message"]:
                                    text = obj["message"]["text"].strip()
                                    post_link = obj.get("permalink_url") or obj.get("url") or obj.get("wwwURL") or store_url
                                    pid = str(obj.get("post_id") or obj.get("id") or "")

                                    # جلب توقيت النشر الفعلي creation_time
                                    ctime = obj.get("creation_time") or time_map.get(pid)
                                    if not ctime and pid:
                                        digits = re.findall(r'\d{10,20}', pid)
                                        for d in digits:
                                            if d in time_map:
                                                ctime = time_map[d]
                                                break
                                    if not ctime and post_link:
                                        digits = re.findall(r'\d{10,20}', post_link)
                                        for d in digits:
                                            if d in time_map:
                                                ctime = time_map[d]
                                                break

                                    post_time_text = format_post_timestamp(ctime)

                                    # استخراج صورة العرض الأصلية إن توفرت
                                    img_url = ""
                                    def extract_img(node):
                                        nonlocal img_url
                                        if img_url:
                                            return
                                        if isinstance(node, dict):
                                            if "image" in node and isinstance(node["image"], dict) and "uri" in node["image"]:
                                                u = node["image"]["uri"]
                                                if any(d in u for d in ["lookaside", "scontent", "fbcdn"]):
                                                    img_url = u
                                                    return
                                            if "photo_image" in node and isinstance(node["photo_image"], dict) and "uri" in node["photo_image"]:
                                                img_url = node["photo_image"]["uri"]
                                                return
                                            for v in node.values():
                                                extract_img(v)
                                        elif isinstance(node, list):
                                            for item in node:
                                                extract_img(item)
                                    extract_img(obj)

                                    if len(text) >= 15 and text not in seen_texts:
                                        deal_keywords = ["شيكل", "سعر", "أسعار", "عروض", "عرض", "كيلو", "تخفيض", "حرق", "توفير", "خصم", "مفرق", "وصلنا", "طازج", "شواكل"]
                                        if any(kw in text for kw in deal_keywords):
                                            seen_texts.add(text)
                                            posts.append({
                                                "url": post_link,
                                                "caption": text,
                                                "type": "text",
                                                "creation_time": ctime,
                                                "post_time_text": post_time_text,
                                                "image_url": img_url
                                            })
                                for v in obj.values():
                                    search_posts_with_links(v)
                            elif isinstance(obj, list):
                                for item in obj:
                                    search_posts_with_links(item)
                        search_posts_with_links(data)
                    except Exception:
                        pass

            if not posts:
                for s in scripts:
                    matches = re.findall(r'"message":\s*\{\s*"text":\s*"([^"]+)"\s*\}', s)
                    for raw in matches:
                        try:
                            clean_text = json.loads(f'"{raw}"')
                        except Exception:
                            clean_text = raw.encode('utf-8', errors='ignore').decode('utf-8', errors='ignore')

                        clean_text = clean_text.strip()
                        if len(clean_text) < 15 or clean_text in seen_texts:
                            continue

                        deal_keywords = ["شيكل", "سعر", "أسعار", "عروض", "عرض", "كيلو", "تخفيض", "حرق", "توفير", "خصم", "مفرق", "وصلنا", "طازج"]
                        if any(kw in clean_text for kw in deal_keywords):
                            seen_texts.add(clean_text)
                            posts.append({
                                "url": store_url,
                                "caption": clean_text,
                                "type": "text",
                                "creation_time": None,
                                "post_time_text": ""
                            })

            print(f"[Monitor] 📥 تم رصد {len(posts)} منشور عروض حقيقي من صفحة {store_name}")

        except Exception as e:
            print(f"[Monitor] ⚠️ خطأ أثناء فحص منشورات {store_name}: {e}")

        return posts[:15]

monitor_engine = MonitorEngine()
