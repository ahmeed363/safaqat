import re
from typing import Dict, Any, List, Optional

_STOP_WORDS = {
    "كيلو", "كغم", "غرام", "جم", "لتر", "مل", "حبة", "باكيت", "كرتونة",
    "علبة", "صندوق", "ربطة", "عرض", "طازج", "طازجة", "عادي", "فاخر",
    "ممتاز", "كبير", "صغير", "وسط", "من", "في", "على", "مع", "أو", "و",
}


def _normalize_currency(raw: str) -> str:
    c = str(raw or "ILS").upper().strip()
    if c in ("ILS", "NIS", "SHEKEL", "شيكل", "ش"):
        return "ILS"
    if c in ("USD", "دولار", "$"):
        return "USD"
    return c


def _product_tokens(name: str) -> set[str]:
    clean = re.sub(r"[^\w\s\u0600-\u06FF]", " ", str(name or "").lower())
    clean = re.sub(r"\d+(?:\.\d+)?", " ", clean)
    tokens = {
        t.strip() for t in clean.split()
        if len(t.strip()) >= 2 and t.strip() not in _STOP_WORDS
    }
    return tokens


def compute_price_insight(
    product_name: str,
    price: Any,
    currency: str,
    comparable_deals: List[Dict[str, Any]],
    deal_id: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """مقارنة سعر العرض الحالي بمتوسط أسعار السلع المشابهة المسجلة في القاعدة"""
    try:
        cur_price = float(price)
        if cur_price <= 0:
            return None
    except Exception:
        return None

    cur_curr = _normalize_currency(currency)
    target_tokens = _product_tokens(product_name)
    if not target_tokens:
        return None

    peer_prices: List[float] = []
    for d in comparable_deals:
        if deal_id is not None and d.get("id") == deal_id:
            continue
        if _normalize_currency(d.get("currency", "ILS")) != cur_curr:
            continue
        try:
            other_price = float(d.get("price") or 0)
        except Exception:
            continue
        if other_price <= 0:
            continue

        other_tokens = _product_tokens(d.get("product_name", ""))
        if not other_tokens:
            continue

        overlap = len(target_tokens & other_tokens)
        # تطابق معقول بين الكلمات الجوهرية مع استبعاد فروقات الأسعار المتطرفة (> 3x)
        needed = 1 if len(target_tokens) == 1 else min(2, len(target_tokens))
        if overlap >= needed and (0.35 * cur_price <= other_price <= 3.0 * cur_price):
            peer_prices.append(other_price)

    if len(peer_prices) < 2:
        return None

    avg_price = sum(peer_prices) / len(peer_prices)
    if avg_price <= cur_price:
        return None

    drop_pct = int(round(((avg_price - cur_price) / avg_price) * 100))
    if drop_pct < 8 or drop_pct > 65:
        return None

    return {
        "avg_price": round(avg_price, 1),
        "drop_pct": drop_pct,
        "sample_count": len(peer_prices),
        "badge": f"أرخص بـ {drop_pct}%",
    }
