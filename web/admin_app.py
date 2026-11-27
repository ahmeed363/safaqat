import os
import sys
import sqlite3
import asyncio
import hmac
import hashlib
import time
from typing import Optional, Dict, Any, List
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Query, Body, Request, Response, Depends
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel

# Add root directory to path
sys.path.insert(0, os.path.abspath("."))

from config.settings import settings
from database.db_manager import db
from telegram import Bot

tg_application_instance = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """إدارة دورة حياة السيرفر: مزامنة Turso Cloud وتشغيل بوت التليجرام مباشرة داخل حلقة asyncio الرئيسية"""
    global tg_application_instance

    # 1. استيراد أحدث نسخة من قاعدة بيانات Turso Cloud عند الإقلاع
    try:
        from database.turso_sync import sync_from_turso_on_boot
        sync_from_turso_on_boot()
    except Exception as e:
        print(f"[Lifespan] ⚠️ تعذر المزامنة من Turso: {e}")

    token = os.getenv("TELEGRAM_BOT_TOKEN") or settings.TELEGRAM_BOT_TOKEN
    
    if token:
        try:
            print("[Lifespan] 🤖 بدء تهيئة وتشغيل بوت التليجرام...")
            from bot.telegram_bot import create_telegram_app
            tg_application_instance = create_telegram_app()
            await tg_application_instance.initialize()
            await tg_application_instance.start()
            await tg_application_instance.updater.start_polling(drop_pending_updates=False)
            print("[Lifespan] 🚀 بوت التليجرام يعمل الآن ويستقبل الرسائل بنجاح!")
        except Exception as e:
            print(f"[Lifespan] ⚠️ تعذر تشغيل بوت التليجرام: {e}")
            import traceback
            traceback.print_exc()

    yield

    if tg_application_instance:
        try:
            print("[Lifespan] 🛑 إيقاف بوت التليجرام...")
            await tg_application_instance.updater.stop()
            await tg_application_instance.stop()
            await tg_application_instance.shutdown()
        except Exception as e:
            print(f"[Lifespan] ⚠️ خطأ أثناء إيقاف البوت: {e}")

app = FastAPI(title="رادار صفقات غزة - لوحة تحكم الإدارة", version="1.0.0", lifespan=lifespan)

TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "templates", "dashboard.html")
LOGIN_TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "templates", "login.html")
OFFERS_TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "templates", "offers.html")
SESSION_COOKIE_NAME = "safaqat_admin_session"

# --- Authentication Helpers ---

def create_session_token(username: str, duration_seconds: int = 7 * 86400) -> str:
    """توليد رمز جلسة موقع مشفر بتقنية HMAC-SHA256"""
    expires_at = int(time.time() + duration_seconds)
    payload = f"{username}:{expires_at}"
    secret = getattr(settings, "SECRET_KEY", "safaqat-secure-admin-session-key-2026")
    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}:{sig}"

def verify_session_token(token: Optional[str]) -> bool:
    """التحقق من صحة وصلاحية رمز الجلسة"""
    if not token:
        return False
    try:
        parts = token.split(":")
        if len(parts) != 3:
            return False
        username, exp_str, sig = parts
        if int(exp_str) < time.time():
            return False
        secret = getattr(settings, "SECRET_KEY", "safaqat-secure-admin-session-key-2026")
        expected_sig = hmac.new(secret.encode(), f"{username}:{exp_str}".encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected_sig, sig):
            return False
        expected_user = getattr(settings, "ADMIN_USERNAME", "admin")
        return hmac.compare_digest(username, expected_user)
    except Exception:
        return False

def is_authenticated(request: Request) -> bool:
    """فحص ما إذا كان المستخدم مسجل الدخول حالياً"""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    return verify_session_token(token)

async def require_admin(request: Request) -> bool:
    """حاجز أمني لمنع أي طلبات API غير مصرح بها"""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token and "Authorization" in request.headers:
        auth_header = request.headers["Authorization"]
        if auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()

    if not verify_session_token(token):
        raise HTTPException(
            status_code=401, 
            detail="جلسة العمل غير صالحة أو منتهية. يرجى تسجيل الدخول أولاً."
        )
    return True

# --- Schemas ---

class LoginPayload(BaseModel):
    username: str
    password: str
    remember: Optional[bool] = True

class DealUpdatePayload(BaseModel):
    product_name: str
    price: float
    summary_ar: Optional[str] = ""
    location: Optional[str] = ""

class CustomTestDealPayload(BaseModel):
    product_name: str
    price: float
    store_name: Optional[str] = "متجر تجريبي"
    location: Optional[str] = "قطاع غزة"
    summary_ar: Optional[str] = ""
    currency: Optional[str] = "ILS"

class StoreCreatePayload(BaseModel):
    url: str
    name: str
    city_area: Optional[str] = "مدينة غزة"
    category: Optional[str] = "تموين وسوبرماركت"
    phone: Optional[str] = ""

class StoreUpdatePayload(BaseModel):
    name: str
    city_area: str
    category: Optional[str] = "تموين وسوبرماركت"
    phone: Optional[str] = ""
    url: Optional[str] = ""

class BroadcastPayload(BaseModel):
    message: str

class DigestSendPayload(BaseModel):
    image_base64: str
    caption: Optional[str] = ""

# --- Web Endpoints ---

@app.get("/login", response_class=HTMLResponse)
async def serve_login(request: Request):
    """عرض صفحة تسجيل الدخول إلى لوحة التحكم"""
    if is_authenticated(request):
        return RedirectResponse(url="/", status_code=302)
    if not os.path.exists(LOGIN_TEMPLATE_PATH):
        raise HTTPException(status_code=404, detail="Login template not found")
    with open(LOGIN_TEMPLATE_PATH, "r", encoding="utf-8") as f:
        html_content = f.read()
    return HTMLResponse(content=html_content)

@app.post("/api/login")
async def login_endpoint(payload: LoginPayload):
    """التحقق من بيانات الدخول وتعيين كوكيز الجلسة المشفر"""
    admin_user = getattr(settings, "ADMIN_USERNAME", "admin")
    admin_pass = getattr(settings, "ADMIN_PASSWORD", "safaqat2026")

    is_user_ok = hmac.compare_digest(payload.username.strip(), admin_user)
    is_pass_ok = hmac.compare_digest(payload.password, admin_pass)

    if not (is_user_ok and is_pass_ok):
        return JSONResponse(
            status_code=401,
            content={"status": "error", "message": "اسم المستخدم أو كلمة المرور غير صحيحة"}
        )

    # 30 يوماً إذا تم تفعيل 'تذكرني'، وإلا 7 أيام
    duration = (30 if payload.remember else 7) * 86400
    token = create_session_token(admin_user, duration)

    resp = JSONResponse(
        status_code=200,
        content={"status": "ok", "message": "تم تسجيل الدخول بنجاح", "redirect": "/"}
    )
    resp.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=duration,
        httponly=True,
        samesite="lax",
        path="/"
    )
    return resp

@app.get("/logout")
async def logout_get():
    """تسجيل الخروج وإعادة التوجيه لصفحة الدخول"""
    resp = RedirectResponse(url="/login", status_code=302)
    resp.delete_cookie(key=SESSION_COOKIE_NAME, path="/")
    return resp

@app.post("/api/logout")
async def logout_post():
    """تسجيل الخروج عبر طلب API"""
    resp = JSONResponse(
        status_code=200,
        content={"status": "ok", "message": "تم تسجيل الخروج بنجاح", "redirect": "/login"}
    )
    resp.delete_cookie(key=SESSION_COOKIE_NAME, path="/")
    return resp

@app.get("/", response_class=HTMLResponse)
async def serve_dashboard(request: Request):
    """عرض صفحة لوحة تحكم الإدارة الرئيسية (محمية بتسجيل الدخول)"""
    if not is_authenticated(request):
        return RedirectResponse(url="/login", status_code=302)
    if not os.path.exists(TEMPLATE_PATH):
        raise HTTPException(status_code=404, detail="Template not found")
    with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
        html_content = f.read()
    return HTMLResponse(content=html_content)

@app.get("/gaza", response_class=HTMLResponse)
@app.get("/offers", response_class=HTMLResponse)
async def serve_public_offers():
    """عرض الواجهة العامة المجانية لعروض اليوم في غزة (بوابة جذب المشتركين)"""
    if not os.path.exists(OFFERS_TEMPLATE_PATH):
        raise HTTPException(status_code=404, detail="Offers page not found")
    with open(OFFERS_TEMPLATE_PATH, "r", encoding="utf-8") as f:
        html_content = f.read()
    return HTMLResponse(content=html_content)

def _extract_general_area(raw_loc: str, store_area: str = "") -> str:
    """استدعاء الدالة المشتركة لتحديد المحافظة العامة"""
    from core.digest_scheduler import extract_general_area
    return extract_general_area(raw_loc, store_area)

@app.get("/api/public/deals")
async def get_public_deals(limit: int = Query(120, ge=10, le=200)):
    """جلب أحدث الصفقات للعرض العام مع إخفاء اسم المتجر والهاتف والعنوان التفصيلي"""
    from core.ai_evaluator import is_invalid_product_name
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM stores WHERE is_verified = 1")
        stores_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM deals WHERE is_bargain = 1 AND (post_time_text LIKE 'اليوم%' OR created_at >= date('now'))")
        today_deals_count = cursor.fetchone()[0]

        cursor.execute("""
        SELECT d.id, d.product_name, d.price, d.currency, d.location, d.post_time_text, d.creation_time,
               s.city_area as store_area, s.category as store_category, COALESCE(s.is_partner, 0) as is_partner
        FROM deals d
        LEFT JOIN stores s ON d.store_id = s.id
        WHERE d.is_bargain = 1
        ORDER BY
            CASE
                WHEN d.post_time_text LIKE 'اليوم%' THEN 1
                WHEN d.post_time_text LIKE 'أمس%' THEN 2
                ELSE 3
            END ASC,
            COALESCE(s.is_partner, 0) DESC,
            COALESCE(d.creation_time, 0) DESC,
            d.id DESC
        LIMIT ?
        """, (limit,))
        rows = [dict(r) for r in cursor.fetchall()]

    public_deals = []
    for r in rows:
        p_name = str(r.get("product_name") or "").strip()
        if is_invalid_product_name(p_name):
            continue
        curr_raw = str(r.get("currency") or "ILS").upper()
        curr_label = "شيكل" if curr_raw in ("ILS", "NIS", "SHEKEL", "شيكل") else ("$" if curr_raw in ("USD", "دولار") else curr_raw)
        try:
            p_val = float(r.get("price", 0))
            p_str = str(int(p_val)) if p_val.is_integer() else f"{p_val:.1f}".rstrip("0").rstrip(".")
        except Exception:
            p_str = str(r.get("price", ""))

        public_deals.append({
            "id": r["id"],
            "product_name": p_name,
            "price": p_str,
            "currency": curr_label,
            "area": _extract_general_area(r.get("location", ""), r.get("store_area", "")),
            "post_time_text": r.get("post_time_text") or "اليوم",
            "category": r.get("store_category") or "عام",
            "is_partner": bool(r.get("is_partner", 0)),
        })

    return {
        "stores_count": stores_count,
        "today_deals_count": today_deals_count,
        "deals": public_deals,
    }

# --- API Endpoints ---

@app.get("/api/health")
def health_status():
    """فحص سلامة السيرفر ومتغيرات البيئة السحابية (مفتوح لفحص Render Health Checks)"""
    import os
    from config.settings import settings
    return {
        "status": "healthy",
        "has_telegram_bot_token": bool(os.getenv("TELEGRAM_BOT_TOKEN") or settings.TELEGRAM_BOT_TOKEN),
        "has_gemini_api_key": bool(os.getenv("GEMINI_API_KEY") or settings.GEMINI_API_KEY),
        "has_turso_db": bool(os.getenv("TURSO_DATABASE_URL") or os.getenv("TURSO_AUTH_TOKEN")),
        "verified_stores": len(db.get_all_stores(verified_only=True)),
        "night_mode": getattr(settings, "NIGHT_MODE_ENABLED", True)
    }

@app.get("/api/stats")
async def get_stats(_: bool = Depends(require_admin)):
    """إحصائيات المنظومة الحية"""
    return db.get_system_stats()

@app.get("/api/deals")
async def get_deals(limit: int = 150, _: bool = Depends(require_admin)):
    """جلب أحدث الصفقات المسجلة بالرادار"""
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        SELECT d.*, s.name as store_name, s.url as store_url 
        FROM deals d 
        LEFT JOIN stores s ON d.store_id = s.id 
        ORDER BY 
            CASE 
                WHEN d.post_time_text LIKE 'اليوم%' THEN 1 
                WHEN d.post_time_text LIKE 'أمس%' THEN 2 
                ELSE 3 
            END ASC,
            COALESCE(d.creation_time, 0) DESC,
            d.id DESC
        LIMIT ?
        """, (limit,))
        return [dict(row) for row in cursor.fetchall()]

@app.put("/api/deals/{deal_id}")
async def update_deal_endpoint(deal_id: int, payload: DealUpdatePayload, _: bool = Depends(require_admin)):
    """تعديل بيانات صفقة وسعرها"""
    success = db.update_deal(
        deal_id=deal_id,
        product_name=payload.product_name,
        price=payload.price,
        summary_ar=payload.summary_ar or "",
        location=payload.location or ""
    )
    if not success:
        raise HTTPException(status_code=404, detail="الصفقة غير موجودة")
    return {"status": "ok", "message": "تم تحديث الصفقة بنجاح"}

@app.delete("/api/deals/{deal_id}")
async def delete_deal_endpoint(deal_id: int, _: bool = Depends(require_admin)):
    """حذف صفقة من المنظومة"""
    success = db.delete_deal(deal_id)
    if not success:
        raise HTTPException(status_code=404, detail="الصفقة غير موجودة")
    return {"status": "ok", "message": "تم حذف الصفقة بنجاح"}

@app.post("/api/deals/{deal_id}/test_send")
async def test_send_deal_endpoint(deal_id: int, _: bool = Depends(require_admin)):
    """إرسال بطاقة صفقة محددة مباشرة إلى تليجرام الإدارة كتجربة عمل"""
    token = settings.TELEGRAM_BOT_TOKEN
    admin_id = settings.ADMIN_TELEGRAM_ID
    if not token or not admin_id:
        raise HTTPException(status_code=500, detail="إعدادات التليجرام غير مكتملة")

    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        SELECT d.*, s.name as store_name, s.url as store_url 
        FROM deals d 
        LEFT JOIN stores s ON d.store_id = s.id 
        WHERE d.id = ?
        """, (deal_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="الصفقة غير موجودة")
        deal = dict(row)

    from bot.telegram_bot import render_deal_card
    card_text = "🧪 **[معاينة بطاقة عرض - تجربة لوحة التحكم]**\n\n" + render_deal_card(deal, is_admin=True, is_broadcast=True, compact=False)
    
    from telegram import Bot, InlineKeyboardMarkup, InlineKeyboardButton
    async with Bot(token=token) as bot:
        reply_markup = InlineKeyboardMarkup([[
            InlineKeyboardButton("👁️ فتح تفاصيل العرض", callback_data=f"deal_expand:{deal_id}")
        ]])
        try:
            await bot.send_message(
                chat_id=str(admin_id),
                text=card_text,
                parse_mode="Markdown",
                protect_content=True,
                reply_markup=reply_markup
            )
        except Exception:
            await bot.send_message(
                chat_id=str(admin_id),
                text=card_text.replace("*", "").replace("`", ""),
                protect_content=True,
                reply_markup=reply_markup
            )

    return {"status": "ok", "message": f"تم إرسال بطاقة ({deal['product_name']}) بنجاح إلى تليجرام الإدارة! 🚀"}

@app.post("/api/deals/test_custom")
async def test_custom_deal_endpoint(payload: CustomTestDealPayload, _: bool = Depends(require_admin)):
    """إرسال بطاقة تجريبية مخصصة بالسلعة والسعر المحددين إلى تليجرام الإدارة"""
    token = settings.TELEGRAM_BOT_TOKEN
    admin_id = settings.ADMIN_TELEGRAM_ID
    if not token or not admin_id:
        raise HTTPException(status_code=500, detail="إعدادات التليجرام غير مكتملة")

    fake_deal = {
        "id": 999999,
        "product_name": payload.product_name,
        "price": payload.price,
        "currency": payload.currency or "ILS",
        "store_name": payload.store_name or "متجر تجريبي",
        "location": payload.location or "قطاع غزة",
        "summary_ar": payload.summary_ar or f"عرض تجريبي لـ {payload.product_name} بسعر {payload.price} {payload.currency or 'ILS'}",
        "post_time_text": "الآن مباشرة ⚡",
        "raw_post_url": "https://facebook.com",
        "phone_contact": "0590000000"
    }

    from bot.telegram_bot import render_deal_card
    card_text = "🧪 **[إرسال تجريبي مخصص من لوحة التحكم]**\n\n" + render_deal_card(fake_deal, is_admin=True, is_broadcast=True, compact=False)
    
    from telegram import Bot
    async with Bot(token=token) as bot:
        try:
            await bot.send_message(
                chat_id=str(admin_id),
                text=card_text,
                parse_mode="Markdown",
                protect_content=True
            )
        except Exception:
            await bot.send_message(
                chat_id=str(admin_id),
                text=card_text.replace("*", "").replace("`", ""),
                protect_content=True
            )

    return {"status": "ok", "message": f"تم إرسال التجربة لـ ({payload.product_name}) بنجاح إلى تليجرام الإدارة! 🚀"}

@app.get("/api/digest")
async def get_daily_digest(_: bool = Depends(require_admin)):
    """توليد قائمة متنوعة من أقوى وأرخص عروض اليوم مع 6 صيغ منشورات مختلفة"""
    from core.digest_scheduler import get_digest_data
    return get_digest_data(limit=80)

@app.post("/api/digest/trigger_auto")
async def trigger_auto_digest_now(slot_hour: int = Query(10), _: bool = Depends(require_admin)):
    """تشغيل وإرسال نشرة مجدولة فورية إلى تليجرام الإدارة للاختبار أو النشر السريع"""
    from core.digest_scheduler import digest_scheduler
    ok = await digest_scheduler.dispatch_scheduled_post(slot_hour=slot_hour)
    if not ok:
        raise HTTPException(status_code=500, detail="تعذر توليد أو إرسال النشرة حالياً")
    return {"status": "ok", "message": "تم توليد وإرسال النشرة التلقائية إلى تليجرام بنجاح! 🚀"}

@app.post("/api/digest/send_telegram")
async def send_digest_to_telegram(payload: DigestSendPayload, _: bool = Depends(require_admin)):
    """إرسال صورة النشرة اليومية المصممة + النص الجاهز إلى تليجرام الإدارة"""
    import base64
    import io
    from telegram.request import HTTPXRequest

    token = settings.TELEGRAM_BOT_TOKEN
    admin_id = settings.ADMIN_TELEGRAM_ID
    if not token or not admin_id:
        raise HTTPException(status_code=500, detail="إعدادات التليجرام غير مكتملة")

    raw_b64 = payload.image_base64.split(",", 1)[-1].strip()
    try:
        img_bytes = base64.b64decode(raw_b64)
    except Exception:
        raise HTTPException(status_code=400, detail="صيغة الصورة غير صالحة")

    req = HTTPXRequest(read_timeout=30.0, connect_timeout=15.0)
    async with Bot(token=token, request=req) as bot:
        await bot.send_photo(
            chat_id=str(admin_id),
            photo=io.BytesIO(img_bytes),
            caption=(payload.caption or "📰 نشرة عروض أسواق غزة اليومية ⚡")[:1024]
        )

    return {"status": "ok", "message": "تم إرسال صورة النشرة والنص إلى تليجرام الإدارة بنجاح! 🚀"}

@app.get("/api/stores")
async def get_stores(_: bool = Depends(require_admin)):
    """جلب كافة المتاجر المعتمدة"""
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM stores ORDER BY id ASC")
        return [dict(row) for row in cursor.fetchall()]

@app.post("/api/stores")
async def create_store(payload: StoreCreatePayload, _: bool = Depends(require_admin)):
    """إضافة متجر جديد لقائمة المراقبة"""
    store_id = db.add_store(
        name=payload.name,
        url=payload.url,
        city_area=payload.city_area or "مدينة غزة",
        category=payload.category or "تموين وسوبرماركت",
        phone=payload.phone or "",
        discovery_source="web_dashboard"
    )
    return {"status": "ok", "store_id": store_id}

@app.put("/api/stores/{store_id}")
async def update_store_endpoint(store_id: int, payload: StoreUpdatePayload, _: bool = Depends(require_admin)):
    """تعديل بيانات متجر (الاسم، العنوان، الجوال، والتصنيف)"""
    success = db.update_store(
        store_id=store_id,
        name=payload.name,
        city_area=payload.city_area,
        category=payload.category or "تموين وسوبرماركت",
        phone=payload.phone or "",
        url=payload.url or ""
    )
    if not success:
        raise HTTPException(status_code=404, detail="المتجر غير موجود")
    return {"status": "ok", "message": "تم تحديث بيانات المتجر بنجاح"}

@app.post("/api/stores/{store_id}/toggle")
async def toggle_store(store_id: int, _: bool = Depends(require_admin)):
    """تفعيل أو تعطيل مراقبة متجر"""
    new_status = db.toggle_store_status(store_id)
    if new_status is None:
        raise HTTPException(status_code=404, detail="المتجر غير موجود")
    return {"status": "ok", "is_verified": new_status}

@app.post("/api/stores/{store_id}/partner")
async def toggle_store_partner_endpoint(store_id: int, _: bool = Depends(require_admin)):
    """ترقية أو إلغاء تمييز متجر كشريك رسمي (أولوية في الويب والبوت)"""
    new_partner = db.toggle_store_partner(store_id)
    if new_partner is None:
        raise HTTPException(status_code=404, detail="المتجر غير موجود")
    return {"status": "ok", "is_partner": new_partner}

@app.delete("/api/stores/{store_id}")
async def delete_store_endpoint(store_id: int, _: bool = Depends(require_admin)):
    """حذف متجر وكافة صفقاته من المنظومة"""
    success = db.delete_store(store_id)
    if not success:
        raise HTTPException(status_code=404, detail="المتجر غير موجود")
    return {"status": "ok", "message": "تم حذف المتجر بنجاح"}

@app.get("/api/subscribers")
async def get_subscribers(_: bool = Depends(require_admin)):
    """جلب قائمة كافة المشتركين"""
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM subscribers ORDER BY id DESC")
        return [dict(row) for row in cursor.fetchall()]

@app.post("/api/subscribers/{chat_id}/extend")
async def extend_sub_endpoint(chat_id: str, days: int = Query(7, ge=1, le=365), _: bool = Depends(require_admin)):
    """تمديد اشتراك تجريبي"""
    success = db.extend_subscriber_trial(chat_id=chat_id, days=days)
    if not success:
        raise HTTPException(status_code=404, detail="المشترك غير موجود")
    return {"status": "ok", "message": f"تم تمديد التجربة لمدة {days} أيام"}

@app.post("/api/subscribers/{chat_id}/status")
async def update_sub_status_endpoint(chat_id: str, status: str = Query("active"), _: bool = Depends(require_admin)):
    """ترقية أو تغيير حالة اشتراك"""
    success = db.update_subscriber_status(chat_id=chat_id, status=status)
    if not success:
        raise HTTPException(status_code=404, detail="المشترك غير موجود")
    return {"status": "ok", "message": f"تم تغيير حالة المشترك إلى {status}"}

@app.post("/api/broadcast")
async def broadcast_endpoint(payload: BroadcastPayload, _: bool = Depends(require_admin)):
    """بث إشعار عام من لوحة الويب إلى كافة مشتركي التليجرام"""
    token = settings.TELEGRAM_BOT_TOKEN
    if not token:
        raise HTTPException(status_code=500, detail="TELEGRAM_BOT_TOKEN غير مضبوط")
    
    bot = Bot(token=token)
    subs = db.get_active_subscribers()
    sent_count = 0
    
    for sub in subs:
        cid = str(sub["telegram_chat_id"])
        try:
            await bot.send_message(
                chat_id=cid,
                text=payload.message,
                parse_mode="Markdown",
                protect_content=True
            )
            sent_count += 1
        except Exception as e:
            print(f"[WebBroadcast] Error sending to {cid}: {e}")

    return {"status": "ok", "sent_count": sent_count}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("web.admin_app:app", host="127.0.0.1", port=8000, reload=True)
