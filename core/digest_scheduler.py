import io
import os
import re
import time
import asyncio
from datetime import datetime
from typing import Dict, Any, List, Optional
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
import arabic_reshaper
from bidi.algorithm import get_display

from config.settings import settings
from database.db_manager import db

FONTS_DIR = Path(settings.BASE_DIR) / "assets" / "fonts"
FONT_BOLD_PATH = str(FONTS_DIR / "NotoNaskhArabic-Bold.ttf")
FONT_BLACK_PATH = str(FONTS_DIR / "Amiri-Bold.ttf")

MONTHS_AR = {
    1: "يناير", 2: "فبراير", 3: "مارس", 4: "أبريل", 5: "مايو", 6: "يونيو",
    7: "يوليو", 8: "أغسطس", 9: "سبتمبر", 10: "أكتوبر", 11: "نوفمبر", 12: "ديسمبر"
}

THEMES = [
    {
        "name": "زمردي ذهبي (صباحي - أساسيات وغذاء)",
        "headline": "نشرة الصباح: أساسيات المطبخ والغذاء",
        "sub": "قبل ما تنزل السوق.. اعرف أرخص الأسعار الحية أولاً بأول",
        "bg_top": (4, 59, 47),
        "bg_mid": (7, 23, 40),
        "bg_bot": (3, 8, 18),
        "accent": (16, 185, 129),
        "accent_light": (110, 231, 183),
        "gold": (251, 191, 36),
    },
    {
        "name": "سماوي مشرق (عصري - بقالة ومنظفات)",
        "headline": "نشرة العصر: البقالة والمنظفات والتوفير",
        "sub": "مقارنة حية لأسعار السلع اليوم في متاجر ومولات القطاع",
        "bg_top": (12, 54, 92),
        "bg_mid": (9, 24, 48),
        "bg_bot": (3, 9, 20),
        "accent": (14, 165, 233),
        "accent_light": (125, 211, 252),
        "gold": (253, 224, 71),
    },
    {
        "name": "ملكي ذهبي (مسائي - مقارنة المحافظات)",
        "headline": "ملخص المساء: أرخص سعر في كل محافظة",
        "sub": "جهّز طلبات بكرة بأرخص سعر.. تغطية حية لجميع المحافظات",
        "bg_top": (55, 36, 14),
        "bg_mid": (19, 22, 42),
        "bg_bot": (5, 8, 18),
        "accent": (245, 158, 11),
        "accent_light": (253, 230, 138),
        "gold": (52, 211, 153),
    },
]

def _load_font(path: str, size: int) -> ImageFont.FreeTypeFont:
    """إجبار محرك BASIC في Pillow لمنع عكس النص مرتين على لينكس عند توفر libraqm"""
    layout_basic = getattr(getattr(ImageFont, "Layout", None), "BASIC", None)
    kwargs = {"layout_engine": layout_basic} if layout_basic is not None else {}
    return ImageFont.truetype(path, size, **kwargs)


def _ar(text: str) -> str:
    """تشكيل وترتيب النص العربي للعرض السليم من اليمين لليسار بدون إيموجي"""
    clean = re.sub(r'[\U00010000-\U0010ffff]|[\u2600-\u27bf]', '', str(text or '')).strip()
    if not clean:
        return ""
    return get_display(arabic_reshaper.reshape(clean))

def extract_general_area(raw_loc: str, store_area: str = "") -> str:
    """تحديد المحافظة/المدينة فقط دون كشف العنوان التفصيلي أو اسم المتجر"""
    combined = f"{raw_loc or ''} {store_area or ''}".lower()
    if any(k in combined for k in ("رفح", "rafah")):
        return "رفح والمواصي"
    if any(k in combined for k in ("خانيونس", "خان يونس", "khan yunis", "khanyounis")):
        return "خانيونس"
    if any(k in combined for k in ("دير البلح", "deir")):
        return "دير البلح"
    if any(k in combined for k in ("النصيرات", "الوسطى", "البريج", "المغازي", "الزوايدة", "nuseirat")):
        return "المحافظة الوسطى"
    if any(k in combined for k in ("غزة", "gaza", "الشمال", "جباليا", "الرمال", "الشيخ رضوان", "الشجاعية", "النفق", "التفاح", "فهمي بيك", "الجلاء", "تل الهوا")):
        return "مدينة غزة والشمال"
    return "قطاع غزة"

def get_gaza_now() -> datetime:
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Asia/Gaza"))
    except Exception:
        from datetime import timedelta, timezone
        return datetime.now(timezone(timedelta(hours=2)))

_MORNING_KWS = (
    "دجاج", "لحم", "كبدة", "بانية", "سمك", "بطاطا", "بندورة", "طماطم", "خيار",
    "بصل", "زيت", "سكر", "طحين", "جبنة", "لبن", "بيض", "فواكه", "رز", "أرز",
)
_AFTERNOON_KWS = (
    "منظف", "صابون", "سائل", "كلور", "شامبو", "بامبرز", "حفاض", "نسكافيه",
    "قهوة", "شاي", "شوكولاتة", "بسكويت", "تونة", "فول", "مكرونة", "عصير", "حليب",
)


def _slot_priority_score(row: Dict[str, Any], slot_hour: Optional[int]) -> int:
    """ترتيب أولوية العروض حسب تخصص الفترة (10 صباحاً، 15 عصراً، 20 مساءً)"""
    name = f"{row.get('product_name', '')} {row.get('store_category', '')}".lower()
    score = 10 if row.get("is_partner") else 0
    if slot_hour == 10 and any(k in name for k in _MORNING_KWS):
        score += 20
    elif slot_hour == 15 and any(k in name for k in _AFTERNOON_KWS):
        score += 20
    return score


def get_digest_data(limit: int = 80, slot_hour: Optional[int] = None) -> Dict[str, Any]:
    """جلب مرشحي النشرة اليومية المتنوعين مع حساب مؤشر التوفير وتخصص الفترات"""
    from core.ai_evaluator import is_invalid_product_name
    from core.price_insights import compute_price_insight

    now_gaza = get_gaza_now()
    date_ar = f"{now_gaza.day} {MONTHS_AR.get(now_gaza.month, '')} {now_gaza.year}"

    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM stores WHERE is_verified = 1")
        stores_count = cursor.fetchone()[0]
        cursor.execute("""
        SELECT d.id, d.store_id, d.product_name, d.price, d.currency, d.location, d.post_time_text, d.creation_time,
               s.name as store_name, s.city_area as store_area, s.category as store_category, COALESCE(s.is_partner, 0) as is_partner
        FROM deals d
        LEFT JOIN stores s ON d.store_id = s.id
        WHERE d.is_bargain = 1 AND d.price > 0
        ORDER BY
            CASE
                WHEN d.post_time_text LIKE 'اليوم%' THEN 1
                WHEN d.post_time_text LIKE 'أمس%' THEN 2
                ELSE 3
            END ASC,
            COALESCE(s.is_partner, 0) DESC,
            COALESCE(d.creation_time, 0) DESC,
            d.id DESC
        LIMIT 250
        """)
        rows = [dict(r) for r in cursor.fetchall()]

    if slot_hour in (10, 15):
        rows = sorted(rows, key=lambda r: _slot_priority_score(r, slot_hour), reverse=True)

    candidates = []
    seen_prefixes = set()
    seen_stores = set()
    seen_areas = set()
    used_ids = set()

    # الجولة الأولى: اختيار صفقة مميزة من كل متجر وصنف (ومحافظة مختلفة في نشرة المساء)
    for pass_num in (1, 2):
        for r in rows:
            if r["id"] in used_ids:
                continue
            p_name = str(r.get("product_name") or "").strip()
            if is_invalid_product_name(p_name) or len(p_name) < 3:
                continue
            sid = r.get("store_id")
            first_word = p_name.split()[0]
            area_val = extract_general_area(r.get("location", ""), r.get("store_area", ""))

            if pass_num == 1:
                if sid in seen_stores or first_word in seen_prefixes:
                    continue
                if slot_hour == 20 and len(seen_areas) < 5 and area_val in seen_areas:
                    continue
            else:
                if first_word in seen_prefixes and len(candidates) < 12:
                    continue

            seen_stores.add(sid)
            seen_prefixes.add(first_word)
            seen_areas.add(area_val)
            used_ids.add(r["id"])

            curr_raw = str(r.get("currency") or "ILS").upper()
            curr_label = "شيكل" if curr_raw in ("ILS", "NIS", "SHEKEL", "شيكل") else ("$" if curr_raw in ("USD", "دولار") else curr_raw)
            try:
                p_val = float(r.get("price", 0))
                p_str = str(int(p_val)) if p_val.is_integer() else f"{p_val:.1f}".rstrip("0").rstrip(".")
            except Exception:
                p_str = str(r.get("price", ""))

            insight = compute_price_insight(
                product_name=p_name,
                price=r.get("price"),
                currency=curr_raw,
                comparable_deals=rows,
                deal_id=r["id"],
            )

            candidates.append({
                "id": r["id"],
                "product_name": p_name[:34],
                "price": p_str,
                "currency": curr_label,
                "area": area_val,
                "store_name": r.get("store_name") or "",
                "is_partner": bool(r.get("is_partner", 0)),
                "drop_pct": insight["drop_pct"] if insight else None,
                "avg_price": insight["avg_price"] if insight else None,
            })
            if len(candidates) >= 18:
                break
        if len(candidates) >= 18:
            break

    return {
        "date_ar": date_ar,
        "stores_count": stores_count,
        "candidates": candidates,
    }

def build_varied_digest_caption(deals: List[Dict[str, Any]], stores_count: int, date_ar: str, format_idx: int = 0) -> str:
    """بناء 6 صيغ منشورات مختلفة وجذابة لمنع التكرار ورفع التفاعل على فيسبوك وواتساب"""
    deal_lines = "\n".join(
        f"🔹 {d['product_name']}: {d['price']} {d['currency']} ({d['area']})"
        + (f" 🔥 أرخص بـ {d['drop_pct']}%" if d.get("drop_pct") else "")
        for d in deals
    )
    footer = (
        "\n🔍 لمعرفة أسماء المحلات والمواقع وأرقام التجار والبحث عن أي سلعة أخرى مجاناً 👇\n\n"
        "🌐 دليل الأسعار الحي (افتح مباشرة):\n"
        "https://safaqat-pi7r.onrender.com/gaza?ref=tg\n\n"
        "📲 أو تابعنا على قناة تليجرام:\n"
        "@gaza_safaqat"
    )

    templates = [
        # 0: نشرة الصباح
        (
            f"☀️ يسعد صباحكم أهلنا في غزة 🌸 ({date_ar})\n"
            f"قبل ما تنزلوا تشتروا أغراض البيت.. شوفوا أرخص الأسعار الحية التي رصدها الرادار من أكثر من {stores_count} متجراً:\n\n"
            f"{deal_lines}\n{footer}"
        ),
        # 1: مقارنة وتوفير (ليش تدفع أكثر؟)
        (
            f"🛒 ليش تشتري بالغالي وفيه محل جنبك عامل سعر حرق؟ 🔥\n"
            f"بعض أرخص الأسعار الحقيقية المرصودة اليوم في أسواق القطاع ({date_ar}):\n\n"
            f"{deal_lines}\n{footer}"
        ),
        # 2: صدمة الأسعار / سعر الكسر
        (
            f"⚡ رصد عاجل لأقوى تخفيضات وسعر الحرق اليوم في غزة ({date_ar}) 💥\n"
            f"تغطية مستمرة لأكثر من {stores_count} سوبرماركت ومول بالقطاع:\n\n"
            f"{deal_lines}\n{footer}"
        ),
        # 3: موجهة لستات البيوت والأسرة
        (
            f"🏠 لكل بيت في غزة حابب يوفر في مصروفه اليوم ❤️🛒\n"
            f"جمعنالكم هذه الباقة من عروض اليوم الطازجة في محافظات القطاع ({date_ar}):\n\n"
            f"{deal_lines}\n{footer}"
        ),
        # 4: أسلوب الفضول والجولة السريعة
        (
            f"📍 جولة سريعة على أسعار السلع في أسواق غزة الآن ({date_ar}) 👀⚡\n"
            f"شوفوا الأسعار اللي لقيناها اليوم في مختلف المناطق:\n\n"
            f"{deal_lines}\n{footer}"
        ),
        # 5: ملخص المساء الذهبي
        (
            f"🌙 ملخص التوفير المسائي من رادار صفقات غزة ({date_ar}) ✨\n"
            f"جهّز قائمة طلبات بكرة بأرخص سعر متوفر في أكثر من {stores_count} متجر:\n\n"
            f"{deal_lines}\n{footer}"
        ),
    ]
    return templates[format_idx % len(templates)]

def _wrap_arabic_lines(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int, max_lines: int = 2) -> List[str]:
    words = [w for w in str(text or "").split() if w]
    lines: List[str] = []
    cur = ""
    for w in words:
        test = f"{cur} {w}".strip()
        shaped = _ar(test)
        bbox = draw.textbbox((0, 0), shaped, font=font)
        if (bbox[2] - bbox[0]) <= max_width:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = w
            if len(lines) >= max_lines:
                break
    if cur and len(lines) < max_lines:
        lines.append(cur)
    return lines or [text]

def render_digest_image_bytes(deals: List[Dict[str, Any]], date_ar: str, stores_count: int, theme_idx: int = 0) -> bytes:
    """توليد صورة إنفوجرافيك فائقة الدقة 1080×1080 بالخط العربي المدمج للعمل على السحابة 24/7"""
    theme = THEMES[theme_idx % len(THEMES)]
    W, H = 1080, 1080
    img = Image.new("RGBA", (W, H), (*theme["bg_bot"], 255))
    draw = ImageDraw.Draw(img)

    # 1. خلفية متدرجة ناعمة
    for y in range(H):
        if y < 420:
            t = y / 420.0
            c1, c2 = theme["bg_top"], theme["bg_mid"]
        else:
            t = (y - 420) / float(H - 420)
            c1, c2 = theme["bg_mid"], theme["bg_bot"]
        r = int(c1[0] * (1 - t) + c2[0] * t)
        g = int(c1[1] * (1 - t) + c2[1] * t)
        b = int(c1[2] * (1 - t) + c2[2] * t)
        draw.line([(0, y), (W, y)], fill=(r, g, b, 255))

    # 2. دوائر رادار خفيفة في الخلفية
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    ac = theme["accent"]
    for i, rad in enumerate([160, 280, 400, 520]):
        alpha = max(12, 42 - i * 8)
        od.ellipse([(W // 2 - rad, 210 - rad), (W // 2 + rad, 210 + rad)], outline=(*ac, alpha), width=2)
    img = Image.alpha_composite(img, overlay)
    draw = ImageDraw.Draw(img)

    # تحميل الخطوط المدمجة بمحرك BASIC موحد بين ويندوز ولينكس
    if os.path.exists(FONT_BLACK_PATH):
        f_headline = _load_font(FONT_BLACK_PATH, 48)
        f_prod = _load_font(FONT_BLACK_PATH, 26)
        f_price = _load_font(FONT_BLACK_PATH, 32)
        f_pill = _load_font(FONT_BLACK_PATH, 22)
    else:
        f_headline = ImageFont.load_default()
        f_prod = f_price = f_pill = f_headline

    if os.path.exists(FONT_BOLD_PATH):
        f_sub = _load_font(FONT_BOLD_PATH, 21)
        f_area = _load_font(FONT_BOLD_PATH, 19)
        f_curr = _load_font(FONT_BOLD_PATH, 18)
        f_cta = _load_font(FONT_BOLD_PATH, 23)
    else:
        f_sub = f_area = f_curr = f_cta = f_headline

    # 3. الشريط العلوي (الشعار يميناً والتاريخ يساراً)
    draw.rounded_rectangle([(W - 360, 42), (W - 56, 96)], radius=27, fill=(6, 40, 45, 220), outline=(*theme["accent"], 200), width=2)
    brand_txt = _ar("رادار صفقات غزة")
    bb = draw.textbbox((0, 0), brand_txt, font=f_pill)
    draw.text((W - 208 - (bb[2] - bb[0]) // 2, 48), brand_txt, fill=theme["accent_light"], font=f_pill)

    draw.rounded_rectangle([(56, 42), (346, 96)], radius=27, fill=theme["gold"])
    dt_txt = _ar(date_ar)
    db_box = draw.textbbox((0, 0), dt_txt, font=f_pill)
    draw.text((201 - (db_box[2] - db_box[0]) // 2, 48), dt_txt, fill=(15, 23, 42), font=f_pill)

    # 4. العنوان الرئيسي والفرعي
    hl_txt = _ar(theme["headline"])
    hl_box = draw.textbbox((0, 0), hl_txt, font=f_headline)
    hx = (W - (hl_box[2] - hl_box[0])) // 2
    draw.text((hx + 2, 108), hl_txt, fill=(0, 0, 0, 180), font=f_headline)
    draw.text((hx, 106), hl_txt, fill=(255, 255, 255), font=f_headline)

    sub_txt = _ar(f"رصد حي من أكثر من {stores_count} متجر وسوبرماركت - {theme['sub']}")
    sb_box = draw.textbbox((0, 0), sub_txt, font=f_sub)
    draw.text(((W - (sb_box[2] - sb_box[0])) // 2, 198), sub_txt, fill=theme["gold"], font=f_sub)

    # 5. بطاقات الصفقات الست (عمودين × 3 صفوف)
    card_w, card_h, gap_y = 470, 182, 22
    start_x, start_y = 56, 258
    for idx, deal in enumerate(deals[:6]):
        col = idx % 2
        row = idx // 2
        x = (W - start_x - card_w) if col == 0 else start_x
        y = start_y + row * (card_h + gap_y)
        is_p = deal.get("is_partner", False)

        border_col = theme["gold"] if is_p else (*theme["accent"], 120)
        draw.rounded_rectangle([(x, y), (x + card_w, y + card_h)], radius=22, fill=(15, 23, 42, 235), outline=border_col, width=2)
        draw.rounded_rectangle([(x + card_w - 11, y + 24), (x + card_w - 4, y + card_h - 24)], radius=3, fill=theme["gold"] if is_p else theme["accent"])

        # المنطقة (أعلى يمين البطاقة)
        area_label = f"{deal['area']}  (شريك معتمد)" if is_p else deal["area"]
        area_sh = _ar(area_label)
        ab = draw.textbbox((0, 0), area_sh, font=f_area)
        draw.text((x + card_w - 26 - (ab[2] - ab[0]), y + 20), area_sh, fill=theme["accent_light"], font=f_area)

        # اسم المنتج (سطر أو سطرين)
        lines = _wrap_arabic_lines(draw, deal["product_name"], f_prod, card_w - 210, 2)
        for li, ln in enumerate(lines):
            sh = _ar(ln)
            lb = draw.textbbox((0, 0), sh, font=f_prod)
            draw.text((x + card_w - 26 - (lb[2] - lb[0]), y + 58 + li * 38), sh, fill=(255, 255, 255), font=f_prod)

        # كبسولة السعر (يسار البطاقة)
        pill_w, pill_h = 148, 76
        px, py = x + 20, y + (card_h - pill_h) // 2 + 8
        draw.rounded_rectangle([(px, py), (px + pill_w, py + pill_h)], radius=18, fill=(10, 62, 52, 230), outline=theme["accent"], width=2)

        pr_txt = str(deal["price"])
        pb = draw.textbbox((0, 0), pr_txt, font=f_price)
        draw.text((px + (pill_w - (pb[2] - pb[0])) // 2, py + 8), pr_txt, fill=theme["gold"], font=f_price)

        cu_txt = _ar(deal["currency"])
        cb = draw.textbbox((0, 0), cu_txt, font=f_curr)
        draw.text((px + (pill_w - (cb[2] - cb[0])) // 2, py + 44), cu_txt, fill=(226, 232, 240), font=f_curr)

        # شارة نسبة التوفير الحقيقية (لقطة اليوم) أسفل كبسولة السعر إن توفرت
        drop_pct = deal.get("drop_pct")
        if drop_pct:
            sv_txt = _ar(f"أرخص {drop_pct}%")
            svb = draw.textbbox((0, 0), sv_txt, font=f_curr)
            draw.rounded_rectangle([(px + 12, py + pill_h + 6), (px + pill_w - 12, py + pill_h + 31)], radius=8, fill=(5, 150, 105, 220))
            draw.text((px + (pill_w - (svb[2] - svb[0])) // 2, py + pill_h + 8), sv_txt, fill=(255, 255, 255), font=f_curr)

    # 6. الشريط السفلي (روابط الدخول)
    cta_y, cta_h = 880, 152
    draw.rounded_rectangle([(56, cta_y), (W - 56, cta_y + cta_h)], radius=26, fill=(6, 48, 42, 240), outline=theme["accent"], width=3)

    cta_title = _ar("أسماء المحلات والمواقع وأرقام التجار متوفرة مجاناً الآن:")
    ctb = draw.textbbox((0, 0), cta_title, font=f_cta)
    draw.text(((W - (ctb[2] - ctb[0])) // 2, cta_y + 20), cta_title, fill=(255, 255, 255), font=f_cta)

    # رابط الويب يميناً
    draw.rounded_rectangle([(520, cta_y + 70), (990, cta_y + 128)], radius=16, fill=(5, 150, 105))
    web_txt = "safaqat-pi7r.onrender.com/gaza"
    wb = draw.textbbox((0, 0), web_txt, font=f_pill)
    draw.text((755 - (wb[2] - wb[0]) // 2, cta_y + 84), web_txt, fill=(255, 255, 255), font=f_pill)

    # رابط تليجرام يساراً
    draw.rounded_rectangle([(90, cta_y + 70), (495, cta_y + 128)], radius=16, fill=(2, 132, 199))
    tg_txt = "Telegram: @gaza_safaqat"
    tb = draw.textbbox((0, 0), tg_txt, font=f_pill)
    draw.text((292 - (tb[2] - tb[0]) // 2, cta_y + 84), tg_txt, fill=(255, 255, 255), font=f_pill)

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=92, optimize=True)
    return buf.getvalue()

class DailyDigestScheduler:
    """مجدول النشرات اليومية التلقائي: يولد ويرسل منشورات بصيغ وتصاميم متجددة على مدار اليوم"""

    def __init__(self):
        self.sent_slots = set()  # {(YYYY-MM-DD, hour)}

    def _get_schedule_hours(self) -> List[int]:
        raw = getattr(settings, "DIGEST_SCHEDULE_HOURS", "10,15,20")
        hours = []
        for part in str(raw).split(","):
            part = part.strip()
            if part.isdigit() and 0 <= int(part) <= 23:
                hours.append(int(part))
        return hours or [10, 15, 20]

    async def dispatch_scheduled_post(self, slot_hour: int, force_theme: Optional[int] = None) -> bool:
        """توليد وإرسال نشرة مخصصة بصيغة مختلفة حسب التوقيت إلى تليجرام الإدارة"""
        from telegram import Bot
        from telegram.request import HTTPXRequest

        token = settings.TELEGRAM_BOT_TOKEN
        admin_id = settings.ADMIN_TELEGRAM_ID
        if not token or not admin_id:
            return False

        data = get_digest_data(limit=80, slot_hour=slot_hour)
        candidates = data.get("candidates", [])
        if not candidates:
            return False

        now_gaza = get_gaza_now()
        hours = self._get_schedule_hours()
        slot_idx = hours.index(slot_hour) if slot_hour in hours else 0

        # تدوير السلع بين الفترة الصباحية والعصرية والمسائية حتى لا تتكرر نفس الـ 6 سلع طوال اليوم
        offset = (slot_idx * 4) % max(1, len(candidates) - 5) if len(candidates) > 6 else 0
        chosen_deals = candidates[offset:offset + 6]
        if len(chosen_deals) < 6:
            chosen_deals = candidates[:6]

        # تدوير الصيغ والألوان حسب اليوم والفترة (6 صيغ مختلفة)
        day_seed = now_gaza.timetuple().tm_yday
        format_idx = (day_seed + slot_idx * 2) % 6
        theme_idx = force_theme if force_theme is not None else (slot_idx % len(THEMES))

        img_bytes = render_digest_image_bytes(
            deals=chosen_deals,
            date_ar=data["date_ar"],
            stores_count=data["stores_count"],
            theme_idx=theme_idx
        )
        caption = build_varied_digest_caption(
            deals=chosen_deals,
            stores_count=data["stores_count"],
            date_ar=data["date_ar"],
            format_idx=format_idx
        )

        slot_names = {10: "الصباحية ☀️", 15: "العصرية 🔥", 20: "المسائية 🌙"}
        slot_label = slot_names.get(slot_hour, f"الساعة {slot_hour}:00")

        # إذا تم ضبط صفحة فيسبوك (FB_PAGE_ID & FB_PAGE_ACCESS_TOKEN) ننشر تلقائياً على صفحة فيسبوك!
        fb_note = ""
        try:
            from core.facebook_publisher import facebook_publisher
            if facebook_publisher.is_configured:
                fb_res = facebook_publisher.publish_photo_post(img_bytes, caption)
                if fb_res.get("ok"):
                    fb_note = f"\n📘 **فيسبوك:** تم النشر التلقائي على صفحتك بنجاح ✅ (ID: `{fb_res.get('post_id')}`)"
                else:
                    fb_note = f"\n⚠️ **فيسبوك:** تعذر النشر الآلي ({fb_res.get('error')})"
        except Exception as fb_ex:
            fb_note = f"\n⚠️ **فيسبوك:** خطأ أثناء النشر ({fb_ex})"

        req = HTTPXRequest(read_timeout=30.0, connect_timeout=15.0)
        async with Bot(token=token, request=req) as bot:
            await bot.send_photo(
                chat_id=str(admin_id),
                photo=io.BytesIO(img_bytes),
                caption=caption[:1024]
            )
            await bot.send_message(
                chat_id=str(admin_id),
                text=f"🤖 **تم تجهيز النشرة {slot_label} تلقائياً!**{fb_note}\nالصورة والنص أعلاه جاهزان للنسخ والمشاركة مباشرة في المجموعات وواتساب ⚡",
                parse_mode="Markdown"
            )
        print(f"[DigestScheduler] ✅ تم إرسال النشرة المجدولة للساعة {slot_hour}:00 بصيغة #{format_idx}")
        return True

    def run_forever(self):
        """حلقة المراقبة المستمرة في الخلفية لتوقيت غزة"""
        print(f"[DigestScheduler] 🕒 بدء مجدول النشرات اليومية التلقائي في الساعات: {self._get_schedule_hours()} بتوقيت غزة")
        while True:
            try:
                if getattr(settings, "DIGEST_AUTO_ENABLED", True):
                    now_gaza = get_gaza_now()
                    today_key = now_gaza.strftime("%Y-%m-%d")
                    cur_hour = now_gaza.hour
                    schedule_hours = self._get_schedule_hours()

                    if cur_hour in schedule_hours and (today_key, cur_hour) not in self.sent_slots:
                        # ننتظر حتى لا تتزامن مع ثانية إقلاع السيرفر إن أمكن
                        self.sent_slots.add((today_key, cur_hour))
                        asyncio.run(self.dispatch_scheduled_post(cur_hour))
            except Exception as e:
                print(f"[DigestScheduler] ⚠️ خطأ في المجدول اليومي: {e}")
            time.sleep(60)

digest_scheduler = DailyDigestScheduler()
