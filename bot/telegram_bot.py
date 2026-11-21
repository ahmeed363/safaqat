import logging
import re
from datetime import datetime, timezone, timedelta
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from config.settings import settings
from database.db_manager import db

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

def format_deal_time(created_at_val) -> str:
    """تنسيق وقت رصد الصفقة بالدقيقة والساعة مع بيان حداثتها بدقة ومطابقة اليوم الفعلي"""
    if not created_at_val:
        return "اليوم"
    try:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
            try:
                dt_utc = datetime.strptime(str(created_at_val), fmt).replace(tzinfo=timezone.utc)
                break
            except ValueError:
                continue
        else:
            return "اليوم"

        now_utc = datetime.now(timezone.utc)
        diff = now_utc - dt_utc
        total_seconds = max(0, diff.total_seconds())

        # التوقيت المحلي لغزة (UTC+2)
        local_dt = dt_utc + timedelta(hours=2)
        local_now = now_utc + timedelta(hours=2)

        hour_str = local_dt.strftime("%I:%M").lstrip("0")
        am_pm = "م" if local_dt.hour >= 12 else "ص"
        exact_time = f"الساعة {hour_str} {am_pm}"

        # التحقق من اليوم نفسه
        if local_dt.date() == local_now.date():
            if total_seconds < 60:
                relative = "الآن مباشرة 🔥"
            elif total_seconds < 3600:
                mins = int(total_seconds // 60)
                relative = f"قبل {mins} دقيقة ⚡"
            elif total_seconds < 7200:
                relative = "قبل ساعة واحدة"
            elif total_seconds < 36000:
                hrs = int(total_seconds // 3600)
                relative = f"قبل {hrs} ساعات"
            else:
                hrs = int(total_seconds // 3600)
                relative = f"قبل {hrs} ساعة"
            return f"اليوم {exact_time} ({relative})"

        # التحقق من أمس
        yesterday = local_now.date() - timedelta(days=1)
        if local_dt.date() == yesterday:
            return f"أمس {exact_time}"

        # تاريخ أقدم
        days = (local_now.date() - local_dt.date()).days
        if days == 2:
            return f"بتاريخ {local_dt.strftime('%d/%m/%Y')} {exact_time} (قبل يومين)"
        return f"بتاريخ {local_dt.strftime('%d/%m/%Y')} {exact_time} (قبل {days} أيام)"
    except Exception:
        return "اليوم"

def format_price(price_val, currency_val: str = "ILS") -> str:
    """تنسيق السعر بشكل أنيق ومقروء للمستهلك في غزة بدون أصفار عشرية زائدة"""
    try:
        p = float(price_val)
        p_str = str(int(p)) if p.is_integer() else f"{p:.1f}".rstrip('0').rstrip('.')
    except Exception:
        p_str = str(price_val)

    curr = "شيكل" if str(currency_val).upper() in ["ILS", "NIS", "SHEKEL", "شيكل"] else ("$" if str(currency_val).upper() in ["USD", "دولار"] else str(currency_val))
    return f"{p_str} {curr}"

def render_deal_card(deal: dict, is_admin: bool = False, is_broadcast: bool = False, compact: bool = False) -> str:
    """توليد بطاقة العرض بتصميم جذاب، واضح، ومنظم يدعم النمط المختصر (سلعة + سعر) والنمط الكامل"""
    product = deal.get("product_name", "صفقة تجارية").strip()
    price_formatted = format_price(deal.get("price", 0), deal.get("currency", "ILS"))
    store = deal.get("store_name") or "أحد المتاجر في غزة"
    location = deal.get("location") or "قطاع غزة"
    time_str = deal.get("post_time_text") or format_deal_time(deal.get("created_at"))
    summary = deal.get("summary_ar", "").strip()
    phone = str(deal.get("phone_contact") or "").strip()
    if phone in ["None", "غير متوفر", "لا يوجد"]:
        phone = ""

    target_link = deal.get("raw_post_url") or deal.get("store_url") or ""
    if target_link and "#" in target_link:
        target_link = target_link.split("#")[0]

    lines = []
    if is_broadcast:
        lines.append("⚡ **صيد جديد - صفقة لقطة رصدها الرادار** ⚡\n")

    # إبراز اسم السلعة والسعر بشكل ملفت وواضح
    lines.append(f"🛍️ **{product}**")
    lines.append(f"🔥 **السعر:** **{price_formatted} فقط** 🏷️")

    # في حال النمط المختصر: نكتفي بالصنف والسعر فقط
    if compact:
        if is_broadcast:
            lines.append("\n🔒 *هذه الرسالة محمية ومخصصة للمشتركين فقط - اضغط أدناه لعرض المتجر*")
        return "\n".join(lines)

    # في حال النمط الكامل: تظهر باقي التفاصيل والموقع
    lines.append("──────────────────────")
    lines.append(f"🏪 **المتجر:** {store}")
    lines.append(f"📍 **الموقع:** {location}")
    lines.append(f"⏰ **توقيت العرض:** {time_str}")

    # رقم الهاتف يظهر فقط في حال توفره بدلاً من إظهار سطر فارغ
    if phone:
        lines.append(f"📞 **للتواصل والحجز:** `{phone}`")

    # تفاصيل العرض الإضافية
    if summary and summary != product:
        lines.append(f"📝 **التفاصيل:** {summary}")

    # رابط التحقق المباشر يظهر حصرياً للأدمن
    if is_admin and target_link:
        lines.append("──────────────────────")
        lines.append(f"🔗 **رابط التحقق (خاص بك):** [فتح المنشور على فيسبوك ↗️]({target_link})")

    if is_broadcast:
        lines.append("\n🔒 *هذه الرسالة محمية ومخصصة للمشتركين فقط - ممنوع إعادة التوجيه*")

    return "\n".join(lines)

# --- لوحات المفاتيح التفاعلية ---

def get_persistent_bottom_keyboard() -> ReplyKeyboardMarkup:
    """كيبورد سفلي دائم يسهل على أي مستخدم في غزة التنقل بلمسة واحدة دون كتابة أي أوامر"""
    keyboard = [
        [KeyboardButton("⚡ القائمة الرئيسية"), KeyboardButton("🔍 بحث فوري عن سلعة")],
        [KeyboardButton("🌾 تموين وأساسيات"), KeyboardButton("🥩 لحوم ودواجن")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_admin_panel_keyboard() -> InlineKeyboardMarkup:
    """لوحة مفاتيح لوحة تحكم الإدارة الشاملة"""
    keyboard = [
        [
            InlineKeyboardButton("📊 إحصائيات تفصيلية", callback_data="admin_stats"),
            InlineKeyboardButton("👥 قائمة المشتركين", callback_data="admin_users")
        ],
        [
            InlineKeyboardButton("🏪 دليل وإدارة المتاجر", callback_data="nav_stores"),
            InlineKeyboardButton("🗑️ إدارة وحذف الصفقات", callback_data="admin_deals")
        ],
        [
            InlineKeyboardButton("➕ إضافة متجر جديد", callback_data="admin_add_store"),
            InlineKeyboardButton("📢 بث إشعار عام", callback_data="admin_broadcast")
        ],
        [
            InlineKeyboardButton("🏠 العودة للقائمة الرئيسية", callback_data="nav_main")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_main_menu_keyboard(is_admin: bool = False) -> InlineKeyboardMarkup:
    """القائمة الرئيسية: تصنيف بالسلعة أو بالمنطقة (مع زر خاص بالإدارة فقط للوحة التحكم وزر بحث فوري)"""
    keyboard = [
        [
            InlineKeyboardButton("🗂️ تصفح حسب نوع السلعة", callback_data="nav_cats"),
            InlineKeyboardButton("📍 تصفح حسب المنطقة والمدينة", callback_data="nav_areas")
        ],
        [
            InlineKeyboardButton("🔍 بحث فوري عن سلعة", callback_data="nav_search"),
            InlineKeyboardButton("🔥 أحدث عروض اليوم (الكل)", callback_data="filter_all")
        ]
    ]
    if is_admin:
        keyboard.append([
            InlineKeyboardButton("👑 لوحة تحكم الإدارة (خاص بك)", callback_data="admin_menu")
        ])
    return InlineKeyboardMarkup(keyboard)

def get_categories_keyboard() -> InlineKeyboardMarkup:
    """قائمة تصنيفات السلع والمنتجات"""
    keyboard = [
        [
            InlineKeyboardButton("🌾 مواد تموينية وسلع أساسية", callback_data="cat_food"),
            InlineKeyboardButton("🥩 لحوم ودواجن وأسماك طازجة", callback_data="cat_meat")
        ],
        [
            InlineKeyboardButton("🧼 منظفات ومستلزمات منزلية", callback_data="cat_cleaning"),
            InlineKeyboardButton("🍫 حلويات ومسليات وشيبس", callback_data="cat_sweets")
        ],
        [
            InlineKeyboardButton("☕ بن ومكسرات ومشروبات", callback_data="cat_coffee"),
            InlineKeyboardButton("⚡ طاقة شمسية وبطاريات", callback_data="cat_solar")
        ],
        [
            InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية", callback_data="nav_main")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_areas_keyboard() -> InlineKeyboardMarkup:
    """قائمة محافظات ومناطق قطاع غزة"""
    keyboard = [
        [
            InlineKeyboardButton("🏙️ مدينة غزة والشمال", callback_data="area_gaza"),
            InlineKeyboardButton("🌴 دير البلح", callback_data="area_deir")
        ],
        [
            InlineKeyboardButton("🏘️ المحافظة الوسطى (النصيرات)", callback_data="area_central"),
            InlineKeyboardButton("🌾 خانيونس", callback_data="area_khan")
        ],
        [
            InlineKeyboardButton("⛺ رفح والمواصي", callback_data="area_rafah")
        ],
        [
            InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية", callback_data="nav_main")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

# استعلامات تصنيفات السلع
CATEGORY_QUERIES = {
    "cat_food": {
        "title": "🌾 **أحدث عروض المواد التموينية والسلع الأساسية (مفرق):**",
        "where": "(s.category LIKE '%تموين%' OR s.category LIKE '%غذائ%' OR s.category LIKE '%طحين%' OR d.product_name LIKE '%سكر%' OR d.product_name LIKE '%زيت%' OR d.product_name LIKE '%طحين%' OR d.product_name LIKE '%أرز%' OR d.product_name LIKE '%جبنة%') AND d.product_name NOT LIKE '%لحم%' AND d.product_name NOT LIKE '%دجاج%' AND d.product_name NOT LIKE '%منظف%' AND d.product_name NOT LIKE '%شوكولاتة%'"
    },
    "cat_meat": {
        "title": "🥩 **أحدث عروض اللحوم والدواجن والأسماك الطازجة (مفرق):**",
        "where": "s.category LIKE '%لحوم%' OR s.category LIKE '%دواجن%' OR d.product_name LIKE '%سمك%' OR d.product_name LIKE '%لحم%' OR d.product_name LIKE '%دجاج%' OR d.product_name LIKE '%صدر%'"
    },
    "cat_cleaning": {
        "title": "🧼 **أحدث عروض المنظفات والمستلزمات المنزلية (مفرق):**",
        "where": "d.product_name LIKE '%منظف%' OR d.product_name LIKE '%جلي%' OR d.product_name LIKE '%كلور%' OR s.category LIKE '%منزلية%'"
    },
    "cat_sweets": {
        "title": "🍫 **أحدث عروض الحلويات والمسليات والشوكولاتة والشيبس:**",
        "where": "d.product_name LIKE '%شوكولاتة%' OR d.product_name LIKE '%ويفر%' OR d.product_name LIKE '%شيبس%' OR d.product_name LIKE '%بسكويت%'"
    },
    "cat_coffee": {
        "title": "☕ **أحدث عروض البن والمكسرات والبهارات:**",
        "where": "s.category LIKE '%مكسرات%' OR s.category LIKE '%بن%' OR d.product_name LIKE '%قهوة%' OR d.product_name LIKE '%مكسرات%'"
    },
    "cat_solar": {
        "title": "⚡ **أحدث عروض الطاقة البديلة والألواح والبطاريات:**",
        "where": "s.category LIKE '%طاقة%' OR s.category LIKE '%بطاريات%' OR s.category LIKE '%مولد%'"
    },
    "filter_all": {
        "title": "🔥 **أقوى عروض المفرق والتجزئة لليوم (شامل كافة المحلات):**",
        "where": "d.is_bargain = 1"
    }
}

# استعلامات المناطق الجغرافية
AREA_QUERIES = {
    "area_gaza": {
        "title": "🏙️ **أحدث عروض ومحلات مدينة غزة والشمال:**",
        "where": "d.location LIKE '%غزة%' OR s.city_area LIKE '%غزة%' OR d.location LIKE '%السرايا%' OR d.location LIKE '%الشجاعية%'"
    },
    "area_deir": {
        "title": "🌴 **أحدث عروض ومحلات دير البلح:**",
        "where": "d.location LIKE '%دير البلح%' OR s.city_area LIKE '%دير البلح%'"
    },
    "area_central": {
        "title": "🏘️ **أحدث عروض ومحلات المحافظة الوسطى (النصيرات والزوايدة):**",
        "where": "d.location LIKE '%الوسطى%' OR d.location LIKE '%النصيرات%' OR s.city_area LIKE '%الوسطى%' OR s.city_area LIKE '%النصيرات%'"
    },
    "area_khan": {
        "title": "🌾 **أحدث عروض ومحلات خانيونس:**",
        "where": "d.location LIKE '%خانيونس%' OR s.city_area LIKE '%خانيونس%'"
    },
    "area_rafah": {
        "title": "⛺ **أحدث عروض ومحلات رفح والمواصي:**",
        "where": "d.location LIKE '%رفح%' OR s.city_area LIKE '%رفح%'"
    }
}

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """الترحيب بالمستخدم وعرض لوحة التحكم الرئيسية المنظمة"""
    user = update.effective_user
    chat_id = str(update.effective_chat.id)

    sub_data = db.register_subscriber(
        chat_id=chat_id,
        username=user.username or "",
        full_name=user.full_name or "صديق صفقات"
    )

    welcome_msg = (
        f"أهلاً بك يا {user.first_name} في **رادار صفقات غزة الذكي** ⚡\n\n"
        f"🎁 اشتراكك التجريبي مفعل مجاناً حتى: `{sub_data.get('trial_ends_at', 'أسبوع من الآن')}`\n"
        f"🔒 عروض مفرق وتجزئة حية من صفحات ومتاجر القطاع مباشرة لهاتفك.\n\n"
        f"👇 **اختر طريقة استعراض الصفقات والعروض:**"
    )

    is_admin = (chat_id == str(settings.ADMIN_TELEGRAM_ID))

    await update.message.reply_text(
        welcome_msg, 
        parse_mode="Markdown",
        reply_markup=get_main_menu_keyboard(is_admin=is_admin)
    )

async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض القائمة الرئيسية"""
    chat_id = str(update.effective_chat.id)
    is_admin = (chat_id == str(settings.ADMIN_TELEGRAM_ID))
    await update.message.reply_text(
        "⚡ **لوحة التحكم الرئيسية لرادار صفقات غزة:**\nاختر طريقة التصفح المناسبة لك:",
        parse_mode="Markdown",
        reply_markup=get_main_menu_keyboard(is_admin=is_admin)
    )

async def category_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """الاستجابة لضغط أزرار التنقل والتصنيفات والمناطق"""
    query = update.callback_query
    await query.answer()

    data = query.data
    chat_id = str(query.message.chat_id)
    is_admin = (chat_id == str(settings.ADMIN_TELEGRAM_ID))

    # التنقل بين الشاشات
    if data == "nav_main":
        await query.message.edit_text(
            "⚡ **القائمة الرئيسية:**\nاختر طريقة استعراض الصفقات:",
            parse_mode="Markdown",
            reply_markup=get_main_menu_keyboard(is_admin=is_admin)
        )
        return

    if data == "nav_cats":
        await query.message.edit_text(
            "🗂️ **تصنيف السلع والمنتجات:**\nاختر نوع البضاعة التي تبحث عن عروضها:",
            parse_mode="Markdown",
            reply_markup=get_categories_keyboard()
        )
        return

    if data == "nav_search":
        await query.message.reply_text(
            "🔍 **اكتب اسم السلعة أو المحل مباشرة في المحادثة:**\n(مثال: `جبنة`، `سكر`، `زيت`، `حليب`، `طلال عواد`، `دجاج`)\nوسأجلب لك أحدث العروض وأسعارها فوراً!",
            parse_mode="Markdown"
        )
        return

    if data == "nav_areas":
        await query.message.edit_text(
            "📍 **تصنيف المناطق والمحافظات في قطاع غزة:**\nاختر منطقتك لعرض عروض المحلات القريبة منك:",
            parse_mode="Markdown",
            reply_markup=get_areas_keyboard()
        )
        return

    # لوحة تحكم إدارة المنظومة
    if data == "admin_menu":
        if not is_admin:
            await query.answer("🔒 هذه اللوحة مخصصة لإدارة المنظومة فقط.", show_alert=True)
            return
        stats = db.get_system_stats()
        msg = (
            "👑 **لوحة تحكم إدارة رادار صفقات غزة** ⚡\n\n"
            f"👥 **المشتركون:** `{stats['total_subs']}` (تجريبي: `{stats['trial_subs']}` | مفعل: `{stats['paid_subs']}`)\n"
            f"🏪 **المتاجر المعتمدة:** `{stats['verified_stores']}` متجراً\n"
            f"🛍️ **إجمالي الصفقات:** `{stats['total_deals']}` صفقة\n"
            f"🔥 **عروض اليوم الحية:** `{stats['today_deals']}` صفقة\n"
            f"📸 **عروض مصورة بالبوستر:** `{stats['deals_with_images']}` صفقة\n\n"
            "👇 **اختر من الأزرار أدناه ما تريد مراجعته أو إدارته:**"
        )
        await query.message.edit_text(msg, parse_mode="Markdown", reply_markup=get_admin_panel_keyboard())
        return

    if data == "admin_stats":
        if not is_admin: return
        stats = db.get_system_stats()
        with db.get_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT city_area, COUNT(*) FROM stores WHERE is_verified = 1 GROUP BY city_area ORDER BY COUNT(*) DESC")
            area_rows = c.fetchall()
            
        area_lines = []
        for area, cnt in area_rows:
            area_lines.append(f"• {area}: `{cnt}` متجر")
            
        msg = (
            "📊 **إحصائيات تفصيلية لرادار صفقات غزة:**\n\n"
            f"👥 **المشتركون:** {stats['total_subs']} مشترك\n"
            f"🛍️ **إجمالي الصفقات:** {stats['total_deals']} ({stats['today_deals']} صفقة لليوم)\n"
            f"📸 **عروض مع بوستر إعلاني:** {stats['deals_with_images']}\n\n"
            f"📍 **توزيع المتاجر المعتمدة ({stats['verified_stores']} متجر):**\n" + "\n".join(area_lines)
        )
        back_btn = InlineKeyboardButton("🔙 لوحة الإدارة", callback_data="admin_menu")
        await query.message.edit_text(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[back_btn]]))
        return

    if data == "admin_users":
        if not is_admin: return
        subs = db.get_recent_subscribers(15)
        lines = [f"👥 **قائمة المشتركين المسجلين في البوت ({len(subs)} مشترك):**\n"]
        for idx, s in enumerate(subs, 1):
            u_name = f"@{s['username']}" if s['username'] else "بدون معرف"
            f_name = s['full_name'] or "مشترك"
            t_end = s['trial_ends_at'][:10] if s['trial_ends_at'] else "غير محدد"
            st_badge = "🎁 تجريبي" if s['subscription_status'] == 'trial' else "✅ مفعل"
            lines.append(f"{idx}. **{f_name}** ({u_name})\n    🆔 `{s['telegram_chat_id']}` | {st_badge} حتى: `{t_end}`\n")
            
        back_btn = InlineKeyboardButton("🔙 لوحة الإدارة", callback_data="admin_menu")
        await query.message.edit_text("\n".join(lines), parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[back_btn]]))
        return

    if data == "admin_deals":
        if not is_admin: return
        with db.get_connection() as conn:
            c = conn.cursor()
            c.execute("""
            SELECT d.id, d.product_name, d.price, d.currency, s.name as store_name, d.post_time_text 
            FROM deals d 
            LEFT JOIN stores s ON d.store_id = s.id 
            ORDER BY d.id DESC LIMIT 6
            """)
            rows = c.fetchall()
            
        await query.message.reply_text("🗑️ **أحدث 6 صفقات مرصودة (اضغط حذف لإزالة أي صفقة فوراً):**", parse_mode="Markdown")
        for r in rows:
            del_text = (
                f"🛍️ **{r['product_name']}**\n"
                f"💰 السعر: **{r['price']} {r['currency']}**\n"
                f"🏪 المتجر: {r['store_name']}\n"
                f"⏰ الوقت: {r['post_time_text'] or 'اليوم'}"
            )
            del_btn = InlineKeyboardButton("🗑️ حذف هذه الصفقة", callback_data=f"del_deal:{r['id']}")
            await query.message.reply_text(del_text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[del_btn]]))
        return

    if data.startswith("del_deal:"):
        if not is_admin: return
        deal_id = int(data.split(":")[1])
        success = db.delete_deal(deal_id)
        if success:
            await query.message.edit_text(f"❌ **تم حذف الصفقة #{deal_id} من المنظومة بنجاح.**", parse_mode="Markdown")
        else:
            await query.answer("الصفقة غير موجودة أو تم حذفها مسبقاً.")
        return

    if data == "admin_add_store":
        if not is_admin: return
        msg = (
            "➕ **كيفية إضافة متجر جديد للرادار:**\n\n"
            "يمكنك إضافة أي صفحة فيسبوك لمحل أو سوبرماركت في غزة فوراً بإرسال رسالة بالصيغة:\n"
            "`/addstore <رابط الصفحة> | <اسم المحل> | <المنطقة> | <التصنيف> | <رقم الهاتف>`\n\n"
            "📝 **مثال قابل للنسخ:**\n"
            "`/addstore https://www.facebook.com/mysupermarket | سوبرماركت الأمانة | دير البلح | تموين وسوبرماركت | 0599000000`\n\n"
            "📡 سيبدأ الرادار فوراً بفحص الصفحة ورصد عروضها آلياً."
        )
        back_btn = InlineKeyboardButton("🔙 لوحة الإدارة", callback_data="admin_menu")
        await query.message.edit_text(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[back_btn]]))
        return

    if data == "admin_broadcast":
        if not is_admin: return
        msg = (
            "📢 **بث إشعار عام لجميع المشتركين:**\n\n"
            "لبث رسالة أو إشعار لجميع مستخدمي البوت في ثانية واحدة، أرسل الأمر:\n"
            "`/broadcast <نص الرسالة>`\n\n"
            "📝 **مثال:**\n"
            "`/broadcast عروض جديدة قوية على اللحوم والدواجن في دير البلح وخانيونس لليوم، تصفحوها الآن عبر /menu`"
        )
        back_btn = InlineKeyboardButton("🔙 لوحة الإدارة", callback_data="admin_menu")
        await query.message.edit_text(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[back_btn]]))
        return

    if data == "nav_stores":
        if not is_admin:
            await query.answer("🔒 هذه الخاصية مخصصة لإدارة المنظومة فقط.", show_alert=True)
            return
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM stores WHERE is_verified = 1")
            total = cursor.fetchone()[0]
        msg = (
            f"🏪 **دليل المتاجر المعتمدة في رادار صفقات ({total} متجراً):**\n\n"
            f"يغطي الرادار شبكة واسعة من كبرى محلات السوبرماركت، مراكز التموين، محلات اللحوم والأسماك، والمولات في قطاع غزة.\n\n"
            f"اختر المحافظة لاستعراض قائمة متاجرها المعتمدة:"
        )
        keyboard = [
            [
                InlineKeyboardButton("🏙️ متاجر مدينة غزة (50+)", callback_data="stores_gaza"),
                InlineKeyboardButton("🌾 متاجر خانيونس (15+)", callback_data="stores_khan")
            ],
            [
                InlineKeyboardButton("🌴 متاجر دير البلح والوسطى", callback_data="stores_central"),
                InlineKeyboardButton("⛺ متاجر رفح والمواصي", callback_data="stores_rafah")
            ],
            [
                InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="nav_main")
            ]
        ]
        await query.message.edit_text(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if data.startswith("stores_"):
        region_map = {
            "stores_gaza": ("مدينة غزة", "%غزة%"),
            "stores_khan": ("خانيونس", "%خانيونس%"),
            "stores_central": ("دير البلح والوسطى", "%الوسطى% OR city_area LIKE '%دير البلح%' OR city_area LIKE '%النصيرات%'"),
            "stores_rafah": ("رفح والمواصي", "%رفح%")
        }
        reg_title, reg_cond = region_map.get(data, ("غزة", "%غزة%"))
        with db.get_connection() as conn:
            cursor = conn.cursor()
            if "OR" in reg_cond:
                cursor.execute(f"SELECT name, category, city_area, url FROM stores WHERE is_verified = 1 AND ({reg_cond}) LIMIT 20")
            else:
                cursor.execute("SELECT name, category, city_area, url FROM stores WHERE is_verified = 1 AND city_area LIKE ? LIMIT 20", (reg_cond,))
            st_list = cursor.fetchall()

        lines = [f"🏪 **أهم المتاجر المعتمدة في {reg_title} ({len(st_list)} متجراً):**\n"]
        for idx, st in enumerate(st_list, 1):
            s_name = st[0].replace("\n", " ").strip()
            s_cat = st[1].replace("\n", " ").strip()
            s_url = st[3]
            lines.append(f"{idx}. [{s_name}]({s_url})\n    🏷️ _{s_cat}_\n")

        lines.append("_📡 يرصد الوكيل هذه المتاجر دورياً لاقتناص أي عروض جديدة._")
        back_btn = InlineKeyboardButton("🔙 اختيار محافظة أخرى", callback_data="nav_stores")
        home_btn = InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="nav_main")
        await query.message.edit_text("\n".join(lines), parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[back_btn, home_btn]]), disable_web_page_preview=True)
        return

    # توسيع بطاقة العرض وإظهار كامل التفاصيل
    if data.startswith("deal_expand:"):
        deal_id = int(data.split(":")[1])
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
            await query.answer("عذراً، هذا العرض لم يعد متوفراً.", show_alert=True)
            return

        deal = dict(row)
        is_broadcast_msg = "صيد جديد" in (query.message.text or "")
        full_text = render_deal_card(deal, is_admin=is_admin, compact=False, is_broadcast=is_broadcast_msg)

        detail_buttons = []
        # إذا توفرت صورة العرض الأصلية، يظهر زر للمعاينة عند الطلب (توفيراً للبيانات)
        if deal.get("image_url"):
            detail_buttons.append([InlineKeyboardButton("🖼️ معاينة صورة الإعلان الأصلية", callback_data=f"deal_photo:{deal_id}")])

        collapse_btn = InlineKeyboardButton("🔼 إخفاء التفاصيل", callback_data=f"deal_collapse:{deal_id}")
        detail_buttons.append([collapse_btn])

        detail_markup = InlineKeyboardMarkup(detail_buttons)
        try:
            await query.message.edit_text(
                full_text, 
                parse_mode="Markdown", 
                reply_markup=detail_markup,
                disable_web_page_preview=True
            )
        except Exception:
            await query.message.edit_text(
                full_text.replace("*", "").replace("`", ""), 
                reply_markup=detail_markup,
                disable_web_page_preview=True
            )
        return

    # إرسال صورة العرض الأصلية بناءً على طلب الزبون (النمط الموفر للبيانات)
    if data.startswith("deal_photo:"):
        deal_id = int(data.split(":")[1])
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT product_name, price, currency, image_url FROM deals WHERE id = ?", (deal_id,))
            row = cursor.fetchone()

        if not row or not row["image_url"]:
            await query.answer("عذراً، صورة هذا العرض غير متوفرة في منشور المتجر.", show_alert=True)
            return

        p_name = row["product_name"]
        p_price = row["price"]
        p_curr = row["currency"]
        img_url = row["image_url"]

        await query.answer("جاري عرض صورة الإعلان... 📸")
        try:
            await query.message.reply_photo(
                photo=img_url,
                caption=f"📸 **بوستر العرض الأصلي:**\n🛍️ {p_name} ({p_price} {p_curr})",
                parse_mode="Markdown",
                protect_content=True
            )
        except Exception as e:
            try:
                import requests
                import io
                r = requests.get(img_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
                if r.status_code == 200:
                    await query.message.reply_photo(
                        photo=io.BytesIO(r.content),
                        caption=f"📸 **بوستر العرض الأصلي:**\n🛍️ {p_name} ({p_price} {p_curr})",
                        parse_mode="Markdown",
                        protect_content=True
                    )
                else:
                    await query.message.reply_text("عذراً، تعذر تحميل الصورة من صفحة المتجر حالياً.")
            except Exception as ex2:
                print(f"[Bot] خطأ إرسال الصورة: {ex2}")
                await query.message.reply_text("عذراً، تعذر إرسال الصورة.")
        return

    # طي بطاقة العرض للنمط المختصر (الصنف والسعر فقط)
    if data.startswith("deal_collapse:"):
        deal_id = int(data.split(":")[1])
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
            await query.answer("عذراً، هذا العرض لم يعد متوفراً.", show_alert=True)
            return

        deal = dict(row)
        is_broadcast_msg = "صيد جديد" in (query.message.text or "")
        compact_text = render_deal_card(deal, is_admin=is_admin, compact=True, is_broadcast=is_broadcast_msg)
        expand_btn = InlineKeyboardButton("👁️ عرض تفاصيل المتجر والموقع", callback_data=f"deal_expand:{deal_id}")
        try:
            await query.message.edit_text(
                compact_text, 
                parse_mode="Markdown", 
                reply_markup=InlineKeyboardMarkup([[expand_btn]]),
                disable_web_page_preview=True
            )
        except Exception:
            await query.message.edit_text(
                compact_text.replace("*", "").replace("`", ""), 
                reply_markup=InlineKeyboardMarkup([[expand_btn]]),
                disable_web_page_preview=True
            )
        return

    if data == "noop":
        return

    # دعم الانتقال بين الصفحات: مثال cat_food:2 أو area_deir:1
    page = 1
    base_key = data
    if ":" in data:
        parts = data.split(":")
        base_key = parts[0]
        try:
            page = int(parts[1])
        except ValueError:
            page = 1

    # استعراض صفقات متجر محدد: store_deals:47
    if base_key == "store_deals":
        store_id = int(parts[1]) if len(parts) > 1 else None
        page = int(parts[2]) if len(parts) > 2 else 1
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM stores WHERE id = ?", (store_id,))
            st_row = cursor.fetchone()
            s_name = st_row[0] if st_row else "المتجر"

            cursor.execute("SELECT COUNT(*) FROM deals WHERE store_id = ? AND is_bargain = 1", (store_id,))
            total_count = cursor.fetchone()[0]

            page_size = 8
            total_pages = max(1, (total_count + page_size - 1) // page_size)
            offset = (page - 1) * page_size

            cursor.execute("""
            SELECT d.*, s.name as store_name, s.url as store_url 
            FROM deals d 
            LEFT JOIN stores s ON d.store_id = s.id 
            WHERE d.store_id = ? AND d.is_bargain = 1
            ORDER BY 
                CASE 
                    WHEN d.post_time_text LIKE 'اليوم%' THEN 1 
                    WHEN d.post_time_text LIKE 'أمس%' THEN 2 
                    ELSE 3 
                END ASC,
                COALESCE(d.creation_time, 0) DESC,
                d.id DESC
            LIMIT ? OFFSET ?
            """, (store_id, page_size, offset))
            deals = [dict(row) for row in cursor.fetchall()]

        title = f"🏪 **أحدث عروض وتخفيضات {s_name}:**"
        info_dict = {"title": title, "where": f"d.store_id = {store_id}"}
        is_area = False
    else:
        # فحص هل الضغطة لـ (تصنيف سلعة) أم لـ (منطقة جغرافية)
        is_area = base_key in AREA_QUERIES
        info_dict = AREA_QUERIES.get(base_key) if is_area else CATEGORY_QUERIES.get(base_key)

        if not info_dict:
            await query.message.reply_text("عفواً، الخيار غير متوفر حالياً.")
            return

        page_size = 8
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"""
            SELECT COUNT(*) 
            FROM deals d 
            LEFT JOIN stores s ON d.store_id = s.id 
            WHERE {info_dict['where']}
            """)
            total_count = cursor.fetchone()[0]

            total_pages = max(1, (total_count + page_size - 1) // page_size)
            if page > total_pages:
                page = total_pages
            offset = (page - 1) * page_size

            query_sql = f"""
            SELECT d.*, s.name as store_name, s.url as store_url 
            FROM deals d 
            LEFT JOIN stores s ON d.store_id = s.id 
            WHERE {info_dict['where']}
            ORDER BY 
                CASE 
                    WHEN d.post_time_text LIKE 'اليوم%' THEN 1 
                    WHEN d.post_time_text LIKE 'أمس%' THEN 2 
                    ELSE 3 
                END ASC,
                COALESCE(d.creation_time, 0) DESC,
                d.id DESC
            LIMIT ? OFFSET ?
            """
            cursor.execute(query_sql, (page_size, offset))
            deals = [dict(row) for row in cursor.fetchall()]

    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton("⬅️ السابق", callback_data=f"{base_key}:{page - 1}"))
    if total_pages > 1:
        nav_row.append(InlineKeyboardButton(f"📄 {page} / {total_pages}", callback_data="noop"))
    if page < total_pages:
        nav_row.append(InlineKeyboardButton("التالي ➡️", callback_data=f"{base_key}:{page + 1}"))

    back_button = InlineKeyboardButton(
        "🔙 اختيار منطقة أخرى" if is_area else "🔙 اختيار سلعة أخرى", 
        callback_data="nav_areas" if is_area else "nav_cats"
    )
    home_button = InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="nav_main")

    keyboard = []
    if nav_row:
        keyboard.append(nav_row)
    keyboard.append([back_button, home_button])
    back_markup = InlineKeyboardMarkup(keyboard)

    if not deals:
        await query.message.reply_text(
            f"{info_dict['title']}\n\n🔍 لم يتم رصد عروض جديدة في هذا القسم حالياً، الرادار يواصل المسح!",
            parse_mode="Markdown",
            reply_markup=back_markup
        )
        return

    start_num = offset + 1
    end_num = min(offset + len(deals), total_count)
    header_text = f"{info_dict['title']}\n📊 _الصفحة {page} من {total_pages} (عرض الصفقات {start_num}-{end_num} من أصل {total_count})_"
    await query.message.reply_text(header_text, parse_mode="Markdown")

    for d in deals:
        deal_card = render_deal_card(d, is_admin=is_admin, compact=True)
        expand_btn = InlineKeyboardButton("👁️ عرض تفاصيل المتجر والموقع", callback_data=f"deal_expand:{d['id']}")
        try:
            await query.message.reply_text(
                deal_card, 
                parse_mode="Markdown", 
                protect_content=True, 
                disable_web_page_preview=True,
                reply_markup=InlineKeyboardMarkup([[expand_btn]])
            )
        except Exception:
            await query.message.reply_text(
                deal_card.replace("*", "").replace("`", ""), 
                protect_content=True, 
                disable_web_page_preview=True,
                reply_markup=InlineKeyboardMarkup([[expand_btn]])
            )

    await query.message.reply_text("👇 للتنقل واستعراض باقي الصفقات:", reply_markup=back_markup)

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """التحقق من حالة الاشتراك"""
    chat_id = str(update.effective_chat.id)
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM subscribers WHERE telegram_chat_id = ?", (chat_id,))
        sub = cursor.fetchone()

    if not sub:
        await update.message.reply_text("عفواً، اضغط /start للتسجيل المجاني.")
        return

    sub = dict(sub)
    status = sub["subscription_status"]
    trial_ends = sub["trial_ends_at"]

    msg = (
        f"📊 **حالة اشتراكك:**\n\n"
        f"👤 الاسم: {sub['full_name']}\n"
        f"📌 نوع الاشتراك: {'فترة تجريبية مجانية 🎁' if status == 'trial' else 'اشتراك مدفوع مفعل ✅'}\n"
        f"⏳ ينتهي في: `{trial_ends}`"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def latest_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """توجيه المستخدم للقائمة الرئيسية المنظمة"""
    await menu_command(update, context)

async def stores_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض دليل المتاجر المعتمدة (خاص بإدارة المنظومة فقط)"""
    chat_id = str(update.effective_chat.id)
    if chat_id != str(settings.ADMIN_TELEGRAM_ID):
        await update.message.reply_text(
            "🔒 **عذراً، هذا الأمر مخصص لإدارة المنظومة فقط.**\n\n"
            "يمكنك استعراض أحدث الصفقات والعروض عبر القائمة الرئيسية: /menu",
            parse_mode="Markdown"
        )
        return

    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM stores WHERE is_verified = 1")
        total = cursor.fetchone()[0]
    msg = (
        f"🏪 **دليل المتاجر المعتمدة في رادار صفقات ({total} متجراً):**\n\n"
        f"يغطي الرادار شبكة واسعة من كبرى محلات السوبرماركت، مراكز التموين، محلات اللحوم والأسماك، والمولات في قطاع غزة.\n\n"
        f"اختر المحافظة لاستعراض قائمة متاجرها المعتمدة:"
    )
    keyboard = [
        [
            InlineKeyboardButton("🏙️ متاجر مدينة غزة (50+)", callback_data="stores_gaza"),
            InlineKeyboardButton("🌾 متاجر خانيونس (15+)", callback_data="stores_khan")
        ],
        [
            InlineKeyboardButton("🌴 متاجر دير البلح والوسطى", callback_data="stores_central"),
            InlineKeyboardButton("⛺ متاجر رفح والمواصي", callback_data="stores_rafah")
        ],
        [
            InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="nav_main")
        ]
    ]
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def deals_search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """البحث السريع عن سلعة أو متجر محدد: /deals جبنة أو /deals طلال عواد"""
    query_str = " ".join(context.args).strip() if context.args else ""
    if not query_str:
        await update.message.reply_text(
            "🔍 **البحث السريع في صفقات غزة:**\nاكتب اسم السلعة أو المتجر بعد الأمر، مثال:\n`/deals جبنة` أو `/deals سكر` أو `/deals طلال عواد` أو `/deals دجاج`",
            parse_mode="Markdown"
        )
        return

    chat_id = str(update.effective_chat.id)
    is_admin = (chat_id == str(settings.ADMIN_TELEGRAM_ID))

    with db.get_connection() as conn:
        cursor = conn.cursor()
        words = [w for w in query_str.split() if len(w) > 1]
        if len(words) > 1:
            clauses = []
            params = []
            for w in words:
                p = f"%{w}%"
                clauses.append("(d.product_name LIKE ? OR s.name LIKE ? OR d.summary_ar LIKE ? OR d.location LIKE ?)")
                params.extend([p, p, p, p])
            where_sql = " AND ".join(clauses)
        else:
            where_sql = "(d.product_name LIKE ? OR s.name LIKE ? OR d.summary_ar LIKE ? OR d.location LIKE ?)"
            params = [f"%{query_str}%"] * 4

        cursor.execute(f"""
        SELECT d.*, s.name as store_name, s.url as store_url 
        FROM deals d 
        LEFT JOIN stores s ON d.store_id = s.id 
        WHERE ({where_sql})
          AND d.is_bargain = 1
        ORDER BY 
            CASE 
                WHEN d.post_time_text LIKE 'اليوم%' THEN 1 
                WHEN d.post_time_text LIKE 'أمس%' THEN 2 
                ELSE 3 
            END ASC,
            COALESCE(d.creation_time, 0) DESC,
            d.id DESC
        LIMIT 10
        """, params)
        deals = [dict(row) for row in cursor.fetchall()]

    if not deals:
        await update.message.reply_text(
            f"🔍 لم يتم العثور على صفقات تطابق: **{query_str}**.\nجرب كلمة أخرى مثل: `جبنة`، `زيت`، `حليب`، `سكر`.",
            parse_mode="Markdown"
        )
        return

    await update.message.reply_text(
        f"🔍 **نتائج البحث عن:** `{query_str}` (أحدث {len(deals)} صفقات):", 
        parse_mode="Markdown"
    )

    for d in deals:
        deal_card = render_deal_card(d, is_admin=is_admin, compact=True)
        expand_btn = InlineKeyboardButton("👁️ عرض تفاصيل المتجر والموقع", callback_data=f"deal_expand:{d['id']}")
        try:
            await update.message.reply_text(
                deal_card, 
                parse_mode="Markdown", 
                protect_content=True, 
                disable_web_page_preview=True,
                reply_markup=InlineKeyboardMarkup([[expand_btn]])
            )
        except Exception:
            await update.message.reply_text(
                deal_card.replace("*", "").replace("`", ""), 
                protect_content=True, 
                disable_web_page_preview=True,
                reply_markup=InlineKeyboardMarkup([[expand_btn]])
            )

async def text_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    الاستجابة لأي رسالة نصية يكتبها المستخدم واعتبارها بحثاً تلقائياً عن السلعة مباشرة
    دون الحاجة لكتابة أوامر بالإنجليزية إطلاقاً لتسهيل الاستخدام على أي مواطن
    """
    text = (update.message.text or "").strip()
    if not text:
        return

    # التفاعل مع أزرار التحكم أو التحيات
    if text in ["⚡ القائمة الرئيسية", "القائمة الرئيسية", "الرئيسية", "menu"]:
        await menu_command(update, context)
        return
    elif text in ["🔍 بحث فوري عن سلعة", "بحث", "ابحث"]:
        await update.message.reply_text(
            "🔍 **اكتب اسم السلعة أو المحل مباشرة في المحادثة:**\n(مثال: `جبنة`، `سكر`، `زيت`، `حليب`، `طلال عواد`، `دجاج`)\nوسأبحث لك عنها فوراً في جميع المحلات!",
            parse_mode="Markdown"
        )
        return
    elif text in ["🌾 تموين وأساسيات", "تموين", "مواد تموينية"]:
        context.args = ["تموين"]
        await deals_search_command(update, context)
        return
    elif text in ["🥩 لحوم ودواجن", "لحوم", "دواجن"]:
        context.args = ["دجاج"]
        await deals_search_command(update, context)
        return
    elif text in ["سلام", "السلام عليكم", "مرحبا", "أهلا", "هلا", "مرحبا بك", "الو", "صباح الخير", "مساء الخير"]:
        await start_command(update, context)
        return

    # تنظيف الكلمات الزائدة من العبارات الطبيعية اليومية
    # مثال: "بدي جبنة فيتا" -> "جبنة فيتا"
    # "وين في عروض زيت" -> "زيت"
    # "اريد طحين" -> "طحين"
    clean_query = re.sub(r'^(بدي|ابحث عن|ابحثلي عن|اريد|في عروض|عروض|سعر|وين في|مين عنده|محتاج|اسعار|سعر)\s+', '', text).strip()
    if not clean_query:
        clean_query = text

    context.args = clean_query.split()
    await deals_search_command(update, context)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """المساعدة والدعم الفني"""
    help_text = (
        "💡 **كيف يعمل رادار صفقات غزة؟**\n\n"
        "1. يراقب الذكاء الاصطناعي صفحات ومتاجر التجزئة والمفرق في قطاع غزة.\n"
        "2. يصنف الصفقات حسب نوع السلعة وحسب منطقتك الجغرافية بدقة.\n"
        "3. يمكنك البحث الفوري عن أي سلعة عبر الأمر: `/deals جبنة` أو `/deals زيت`\n"
        "4. يرسل لك إشعاراً في نفس الثانية مع رقم التاجر ومكانه.\n\n"
        "أرسل /menu في أي وقت للتصفح."
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")

def create_telegram_app() -> Application:
    """تهيئة تطبيق التليجرام"""
    token = settings.TELEGRAM_BOT_TOKEN
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN غير مضبوط في .env")

    application = Application.builder().token(token).build()
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("menu", menu_command))
    application.add_handler(CommandHandler("stores", stores_command))
    application.add_handler(CommandHandler("categories", menu_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("latest", latest_command))
    application.add_handler(CommandHandler("deals", deals_search_command))
    application.add_handler(CommandHandler("search", deals_search_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CallbackQueryHandler(category_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message_handler))

    return application

if __name__ == "__main__":
    try:
        app = create_telegram_app()
        print("🤖 بدء تشغيل بوت التليجرام لرادار الصفقات...")
        app.run_polling()
    except Exception as e:
        print(f"خطأ في تشغيل البوت: {e}")
