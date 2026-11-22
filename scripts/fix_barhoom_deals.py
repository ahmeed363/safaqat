import sys, os
sys.path.insert(0, os.path.abspath("."))
import sqlite3
from database.turso_client import turso
from core.ai_evaluator import is_invalid_product_name

BARHOOM_FIXES = {
    494: ("تفاح أصفر طازج", 7.5, "عرض تفاح أصفر طازج بسعر 7.5 شيكل للكيلو في مول برهوم | Khan Yunis"),
    493: ("بصل طازج", 5.5, "عرض بصل طازج بسعر 5.5 شيكل للكيلو في مول برهوم | Khan Yunis"),
    492: ("كوسا طازجة", 6.0, "عرض كوسا طازجة بسعر 6.0 شيكل للكيلو في مول برهوم | Khan Yunis"),
    491: ("أفوكادو S طازج", 9.0, "عرض أفوكادو S طازج بسعر 9.0 شيكل للكيلو في مول برهوم | Khan Yunis"),
    490: ("باذنجان أسود طازج", 7.0, "عرض باذنجان أسود طازج بسعر 7.0 شيكل للكيلو في مول برهوم | Khan Yunis"),
    489: ("فرسمون طازج", 6.0, "عرض فرسمون طازج بسعر 6.0 شيكل للكيلو في مول برهوم | Khan Yunis"),
    488: ("قرع أصفر طازج", 6.5, "عرض قرع أصفر طازج بسعر 6.5 شيكل للكيلو في مول برهوم | Khan Yunis"),
    487: ("قرع أصفر طازج", 6.5, "عرض قرع أصفر طازج بسعر 6.5 شيكل للكيلو في مول برهوم | Khan Yunis"),
}

print("=== تحديث وتصحيح صفقات الخضار والفواكه لمول برهوم في Turso Cloud والمحلي ===")

# 1. Update Turso
for d_id, (p_name, price, summary) in BARHOOM_FIXES.items():
    print(f"• تصحيح الصفقة {d_id}: '{p_name}' ({price} شيكل)")
    turso.execute(
        "UPDATE deals SET product_name = ?, price = ?, summary_ar = ? WHERE id = ?",
        [p_name, price, summary, d_id]
    )

# Delete junk deal 495 if slogan
turso.execute("DELETE FROM deals WHERE id = 495")

# Check if any remaining invalid deals in Turso
turso_deals = turso.query("SELECT id, product_name FROM deals")
deleted_turso = 0
for d in turso_deals:
    d_id = d.get("id")
    p_name = d.get("product_name", "")
    if d_id in BARHOOM_FIXES:
        continue
    if is_invalid_product_name(p_name):
        print(f"  🗑️ مسح صفقة مبهمة من Turso رقم {d_id}: '{p_name}'")
        turso.execute("DELETE FROM deals WHERE id = ?", [d_id])
        deleted_turso += 1

print(f"✅ انتهى تحديث Turso بنجاح. تم مسح {deleted_turso} وحذف 495 وتصحيح 8 صفقات.")

# 2. Update local DB
conn = sqlite3.connect("safaqat.db")
c = conn.cursor()
for d_id, (p_name, price, summary) in BARHOOM_FIXES.items():
    c.execute(
        "UPDATE deals SET product_name = ?, price = ?, summary_ar = ? WHERE id = ?",
        (p_name, price, summary, d_id)
    )
c.execute("DELETE FROM deals WHERE id = 495")

local_deals = c.execute("SELECT id, product_name FROM deals").fetchall()
deleted_local = 0
for d_id, p_name in local_deals:
    if d_id in BARHOOM_FIXES:
        continue
    if is_invalid_product_name(p_name):
        c.execute("DELETE FROM deals WHERE id = ?", (d_id,))
        deleted_local += 1

conn.commit()
conn.close()
print(f"✅ انتهى تحديث المحلي بنجاح. تم مسح {deleted_local} وحذف 495 وتصحيح 8 صفقات.")
