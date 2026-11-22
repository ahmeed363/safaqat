import sys, os
sys.path.insert(0, os.path.abspath("."))
import sqlite3
from database.turso_client import turso
from core.ai_evaluator import is_invalid_product_name

# Specific manual fixes for known deals
FIXES = {
    462: ("مفتول البدرساوي المصنوع يدويًا", 20.0, "عرض مفتول البدرساوي المصنوع يدويًا بسعر 20 شيكل للكيس في مركز طلال عواد"),
    463: ("أرز يونجا بسمتي 1121 طويل الحبّة", 8.0, "عرض أرز يونجا بسمتي 1121 طويل الحبّة بسعر 8 شيكل للكيلو (و4 كيلو بـ 29 شيكل) في مركز طلال عواد"),
    465: ("عسل أسود الرشيدي الميزان (5 عبوات)", 10.0, "عرض 5 عبوات عسل أسود الرشيدي الميزان بسعر 10 شيكل في مركز طلال عواد"),
}

print("=== جاري تصحيح وتنظيف الصفقات في Turso Cloud والمحلي ===")

# 1. Update known deals
for deal_id, (p_name, price, summary) in FIXES.items():
    print(f"• تصحيح الصفقة {deal_id}: {p_name}")
    turso.execute(
        "UPDATE deals SET product_name = ?, price = ?, summary_ar = ? WHERE id = ?",
        [p_name, price, summary, deal_id]
    )

# 2. Find and delete unfixable junk deals in Turso
turso_deals = turso.query("SELECT id, product_name FROM deals")
deleted_count = 0
for d in turso_deals:
    d_id = d.get("id")
    p_name = d.get("product_name", "")
    if d_id in FIXES:
        continue
    if is_invalid_product_name(p_name):
        print(f"  🗑️ حذف الصفقة التالفة رقم {d_id}: '{p_name}'")
        turso.execute("DELETE FROM deals WHERE id = ?", [d_id])
        deleted_count += 1

print(f"✅ تم حذف {deleted_count} صفقة مبهمة وتصحيح الصفقات الرئيسية في Turso Cloud.")

# 3. Apply the same to local DB
conn = sqlite3.connect("safaqat.db")
c = conn.cursor()
for deal_id, (p_name, price, summary) in FIXES.items():
    c.execute(
        "UPDATE deals SET product_name = ?, price = ?, summary_ar = ? WHERE id = ?",
        (p_name, price, summary, deal_id)
    )

local_deals = c.execute("SELECT id, product_name FROM deals").fetchall()
local_deleted = 0
for d_id, p_name in local_deals:
    if d_id in FIXES:
        continue
    if is_invalid_product_name(p_name):
        c.execute("DELETE FROM deals WHERE id = ?", (d_id,))
        local_deleted += 1

conn.commit()
conn.close()
print(f"✅ تم تنظيف وحذف {local_deleted} صفقة تالفة من قاعدة البيانات المحلية.")
