import os
import sys
import sqlite3
import asyncio
from typing import Optional, Dict, Any, List
from fastapi import FastAPI, HTTPException, Query, Body
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

# Add root directory to path
sys.path.insert(0, os.path.abspath("."))

from config.settings import settings
from database.db_manager import db
from telegram import Bot

app = FastAPI(title="رادار صفقات غزة - لوحة تحكم الإدارة", version="1.0.0")

TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "templates", "dashboard.html")

# --- Schemas ---

class DealUpdatePayload(BaseModel):
    product_name: str
    price: float
    summary_ar: Optional[str] = ""
    location: Optional[str] = ""

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

# --- Web Endpoints ---

@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    """عرض صفحة لوحة تحكم الإدارة الرئيسية"""
    if not os.path.exists(TEMPLATE_PATH):
        raise HTTPException(status_code=404, detail="Template not found")
    with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
        html_content = f.read()
    return HTMLResponse(content=html_content)

# --- API Endpoints ---

@app.get("/api/stats")
async def get_stats():
    """إحصائيات المنظومة الحية"""
    return db.get_system_stats()

@app.get("/api/deals")
async def get_deals(limit: int = 150):
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
async def update_deal_endpoint(deal_id: int, payload: DealUpdatePayload):
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
async def delete_deal_endpoint(deal_id: int):
    """حذف صفقة من المنظومة"""
    success = db.delete_deal(deal_id)
    if not success:
        raise HTTPException(status_code=404, detail="الصفقة غير موجودة")
    return {"status": "ok", "message": "تم حذف الصفقة بنجاح"}

@app.get("/api/stores")
async def get_stores():
    """جلب كافة المتاجر المعتمدة"""
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM stores ORDER BY id ASC")
        return [dict(row) for row in cursor.fetchall()]

@app.post("/api/stores")
async def create_store(payload: StoreCreatePayload):
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
async def update_store_endpoint(store_id: int, payload: StoreUpdatePayload):
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
async def toggle_store(store_id: int):
    """تفعيل أو تعطيل مراقبة متجر"""
    new_status = db.toggle_store_status(store_id)
    if new_status is None:
        raise HTTPException(status_code=404, detail="المتجر غير موجود")
    return {"status": "ok", "is_verified": new_status}

@app.delete("/api/stores/{store_id}")
async def delete_store_endpoint(store_id: int):
    """حذف متجر وكافة صفقاته من المنظومة"""
    success = db.delete_store(store_id)
    if not success:
        raise HTTPException(status_code=404, detail="المتجر غير موجود")
    return {"status": "ok", "message": "تم حذف المتجر بنجاح"}

@app.get("/api/subscribers")
async def get_subscribers():
    """جلب قائمة كافة المشتركين"""
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM subscribers ORDER BY id DESC")
        return [dict(row) for row in cursor.fetchall()]

@app.post("/api/subscribers/{chat_id}/extend")
async def extend_sub_endpoint(chat_id: str, days: int = Query(7, ge=1, le=365)):
    """تمديد اشتراك تجريبي"""
    success = db.extend_subscriber_trial(chat_id=chat_id, days=days)
    if not success:
        raise HTTPException(status_code=404, detail="المشترك غير موجود")
    return {"status": "ok", "message": f"تم تمديد التجربة لمدة {days} أيام"}

@app.post("/api/subscribers/{chat_id}/status")
async def update_sub_status_endpoint(chat_id: str, status: str = Query("active")):
    """ترقية أو تغيير حالة اشتراك"""
    success = db.update_subscriber_status(chat_id=chat_id, status=status)
    if not success:
        raise HTTPException(status_code=404, detail="المشترك غير موجود")
    return {"status": "ok", "message": f"تم تغيير حالة المشترك إلى {status}"}

@app.post("/api/broadcast")
async def broadcast_endpoint(payload: BroadcastPayload):
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
