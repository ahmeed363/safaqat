import re
import urllib.parse
from typing import List, Dict, Any
import requests
from bs4 import BeautifulSoup
from config.settings import settings
from database.db_manager import db
from core.ai_evaluator import ai_evaluator

class DiscoveryEngine:
    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

    def search_potential_facebook_pages(self, query_keyword: str) -> List[str]:
        """
        البحث الذكي في محركات البحث لاكتشاف صفحات فيسبوك تابعة لمحلات غزة
        باستخدام استعلامات متخصصة (Google Dorking)
        """
        discovered_urls = []
        dork_query = f'site:facebook.com "غزة" OR "دير البلح" OR "خانيونس" OR "رفح" "{query_keyword}"'
        encoded_query = urllib.parse.quote(dork_query)
        search_url = f"https://html.duckduckgo.com/html/?q={encoded_query}"

        try:
            response = requests.get(search_url, headers=self.headers, timeout=10)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, "html.parser")
                links = soup.find_all("a", class_="result__url")
                for link in links:
                    href = link.get("href", "")
                    # استخراج رابط فيسبوك المباشر
                    if "facebook.com" in href:
                        clean_url = self._clean_facebook_url(href)
                        if clean_url:
                            discovered_urls.append(clean_url)
        except Exception as e:
            print(f"[Discovery] خطأ أثناء البحث: {e}")

        return list(set(discovered_urls))

    def _clean_facebook_url(self, raw_url: str) -> str:
        """تنظيف رابط الفيسبوك لإرجاع الرابط المباشر للصفحة"""
        if "uddg=" in raw_url:
            match = re.search(r"uddg=([^&]+)", raw_url)
            if match:
                raw_url = urllib.parse.unquote(match.group(1))

        # الاحتفاظ فقط برابط الصفحة الأساسي
        match = re.match(r"(https?://(?:www\.)?facebook\.com/[^/?&#]+)", raw_url)
        if match:
            url = match.group(1)
            # استبعاد الروابط العامة غير المرغوبة
            excluded = ["facebook.com/login", "facebook.com/help", "facebook.com/policies"]
            if not any(ex in url for ex in excluded):
                return url
        return ""

    def run_discovery_cycle(self) -> int:
        """
        تنفيذ دورة استكشاف شاملة:
        1. البحث عن صفحات جديدة بناء على الكلمات المفتاحية
        2. إضافة الروابط الجديدة لجدول الروابط المعلقة
        3. تقييم الروابط المعلقة بالذكاء الاصطناعي وإضافتها للمتاجر المؤكدة
        """
        print("[Discovery] 🔍 بدء دورة استكشاف الصفحات والمتاجر الجديدة...")
        new_links_count = 0

        # 1. البحث عبر الكلمات المفتاحية
        for keyword in settings.GAZA_KEYWORDS[:5]: # تشغيل عينة من الكلمات
            found_urls = self.search_potential_facebook_pages(keyword)
            for url in found_urls:
                if db.add_discovered_link(url, source_type="web_search", discovered_from=keyword):
                    new_links_count += 1

        print(f"[Discovery] 📥 تم العثور على {new_links_count} رابط جديد قيد المراجعة.")

        # 2. تقييم الروابط المعلقة بالذكاء الاصطناعي
        added_stores = self.process_pending_links()
        return added_stores

    def process_pending_links(self) -> int:
        """
        فحص الروابط المعلقة باستخدام Gemini AI
        وتحويل الصفحات التجارية الحقيقية إلى متاجر معتمدة في الرادار
        """
        pending = db.get_pending_links(limit=10)
        approved_count = 0

        for item in pending:
            link_id = item["id"]
            url = item["url"]
            print(f"[Discovery] 🤖 فحص الصفحة: {url}")

            # محاكاة جلب النبذة والمنشورات الأخيرة من الرابط
            # (في بيئة الإنتاج يتم جلب HTML الصفحة وقراءة الميتا داتا)
            page_meta = self._fetch_page_metadata(url)
            
            evaluation = ai_evaluator.evaluate_facebook_page(
                page_name=page_meta.get("name", url.split("/")[-1]),
                page_bio=page_meta.get("bio", ""),
                recent_posts=page_meta.get("recent_posts", "")
            )

            if evaluation.get("is_valid_gaza_shop", False):
                db.add_store(
                    name=page_meta.get("name") or url.split("/")[-1],
                    url=url,
                    platform="facebook",
                    city_area=evaluation.get("city_area", "غزة"),
                    category=evaluation.get("shop_category", "عام"),
                    phone=evaluation.get("phone_number", ""),
                    discovery_source="autonomous_agent"
                )
                db.update_link_status(link_id, status="approved", ai_reason=evaluation.get("reason", ""))
                print(f"[Discovery] ✅ تم اعتماد المتجر بنجاح: {page_meta.get('name') or url}")
                approved_count += 1
            else:
                db.update_link_status(link_id, status="rejected", ai_reason=evaluation.get("reason", ""))
                print(f"[Discovery] ❌ تم استبعاد الصفحة: {evaluation.get('reason')}")

        return approved_count

    def _fetch_page_metadata(self, url: str) -> Dict[str, str]:
        """جلب العناوين والوصف الأولي للصفحة"""
        try:
            resp = requests.get(url, headers=self.headers, timeout=8)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                title = soup.title.string if soup.title else ""
                desc = ""
                meta_desc = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", attrs={"property": "og:description"})
                if meta_desc:
                    desc = meta_desc.get("content", "")
                return {"name": title.replace(" | Facebook", "").strip(), "bio": desc, "recent_posts": desc}
        except Exception:
            pass
        return {"name": url.split("/")[-1], "bio": "", "recent_posts": ""}

discovery_engine = DiscoveryEngine()
