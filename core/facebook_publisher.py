import os
import re
import httpx
from typing import Dict, Any, Optional
from config.settings import settings

class FacebookPublisher:
    """ناشر آلي رسمي لصفحة فيسبوك عبر Graph API مع دعم وضع الروابط في أول تعليق لرفع الوصول"""

    GRAPH_API_BASE = "https://graph.facebook.com/v21.0"

    @property
    def is_configured(self) -> bool:
        page_id = os.getenv("FB_PAGE_ID") or getattr(settings, "FB_PAGE_ID", "")
        token = os.getenv("FB_PAGE_ACCESS_TOKEN") or getattr(settings, "FB_PAGE_ACCESS_TOKEN", "")
        return bool(page_id and token)

    def _split_caption_and_links(self, caption: str) -> tuple[str, str]:
        """فصل الروابط عن نص المنشور لوضعها في أول تعليق (يرفع وصول فيسبوك بنسبة كبيرة)"""
        urls = re.findall(r'https?://\S+', caption or "")
        if not urls:
            return caption, ""

        clean_lines = []
        for line in (caption or "").splitlines():
            if any(u in line for u in urls):
                continue
            clean_lines.append(line)

        clean_body = "\n".join(clean_lines).strip()
        if "أول تعليق" not in clean_body:
            clean_body += "\n\n👇 رابط دليل الأسعار الحي والقناة متوفران في أول تعليق!"

        comment_text = (
            "🌐 دليل الأسعار الحي (ابحث واعرف أسماء المحلات مجاناً):\n"
            "https://safaqat-pi7r.onrender.com/gaza\n\n"
            "📲 قناة العروض اليومية على تليجرام:\n"
            "https://t.me/gaza_safaqat"
        )
        return clean_body, comment_text

    def publish_photo_post(self, image_bytes: bytes, caption: str) -> Dict[str, Any]:
        """نشر صورة النشرة على صفحة فيسبوك الرسمية مع إضافة أول تعليق تلقائياً"""
        page_id = os.getenv("FB_PAGE_ID") or getattr(settings, "FB_PAGE_ID", "")
        token = os.getenv("FB_PAGE_ACCESS_TOKEN") or getattr(settings, "FB_PAGE_ACCESS_TOKEN", "")

        if not page_id or not token:
            return {
                "ok": False,
                "error": "لم يتم ضبط إعدادات صفحة فيسبوك (FB_PAGE_ID و FB_PAGE_ACCESS_TOKEN) في Render بعد."
            }

        link_in_comment = getattr(settings, "FB_LINK_IN_FIRST_COMMENT", True)
        post_caption = caption
        first_comment = ""
        if link_in_comment:
            post_caption, first_comment = self._split_caption_and_links(caption)

        try:
            with httpx.Client(timeout=30.0) as client:
                r = client.post(
                    f"{self.GRAPH_API_BASE}/{page_id}/photos",
                    data={
                        "caption": post_caption,
                        "access_token": token,
                        "published": "true",
                    },
                    files={"source": ("safaqat_offers.jpg", image_bytes, "image/jpeg")},
                )
                data = r.json()
                if r.status_code != 200 or "error" in data:
                    err_msg = data.get("error", {}).get("message", str(data))
                    return {"ok": False, "error": f"خطأ فيسبوك API: {err_msg}"}

                post_id = data.get("post_id") or data.get("id")
                comment_id = None

                # وضع الروابط في أول تعليق تلقائياً إذا وُجدت
                if first_comment and post_id:
                    try:
                        rc = client.post(
                            f"{self.GRAPH_API_BASE}/{post_id}/comments",
                            data={"message": first_comment, "access_token": token},
                        )
                        if rc.status_code == 200:
                            comment_id = rc.json().get("id")
                    except Exception as ce:
                        print(f"[FacebookPublisher] ⚠️ تعذر إضافة أول تعليق: {ce}")

                return {
                    "ok": True,
                    "post_id": post_id,
                    "comment_id": comment_id,
                    "message": "تم النشر على صفحة فيسبوك بنجاح مع إضافة الرابط في أول تعليق! 🚀",
                }
        except Exception as e:
            return {"ok": False, "error": f"تعذر الاتصال بفيسبوك: {e}"}

facebook_publisher = FacebookPublisher()
