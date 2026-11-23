import asyncio
from typing import Dict, Any, List, Optional
from telegram import Bot, InlineKeyboardMarkup, InlineKeyboardButton
from config.settings import settings
from database.db_manager import db
from bot.telegram_bot import render_deal_card

class AlertDispatcher:
    def __init__(self, bot_token: str = ""):
        self.bot_token = bot_token or settings.TELEGRAM_BOT_TOKEN

    async def broadcast_deal(self, deal: Dict[str, Any], bot: Optional[Bot] = None) -> int:
        """
        بث الصفقة فورياً لجميع المشتركين مع تفعيل خاصية الحماية من النسخ protect_content=True
        وبتنسيق جذاب وملفت يبرز السلعة والسعر
        """
        if not self.bot_token:
            print("[Dispatcher] ⚠️ لم يتم ضبط TELEGRAM_BOT_TOKEN. تم تخطي البث.")
            return 0

        # حارس بوابة الجودة: منع بث أي صفقة تحمل اسماً غير صالح أو عبارة ترويجية مبهمة
        prod_name = str(deal.get("product_name") or "").strip()
        from core.ai_evaluator import is_invalid_product_name
        if is_invalid_product_name(prod_name):
            print(f"[Dispatcher] 🛑 تم حجب وإلغاء بث صفقة مبهمة: '{prod_name}'")
            if deal.get("id"):
                db.mark_deal_broadcasted(deal["id"])
            return 0

        async def _send_with_bot(active_bot: Bot) -> int:
            subscribers = db.get_active_subscribers()
            sent_count = 0
            deal_id = deal.get("id")

            reply_markup = None
            if deal_id:
                reply_markup = InlineKeyboardMarkup([[
                    InlineKeyboardButton("👁️ عرض تفاصيل المتجر والموقع", callback_data=f"deal_expand:{deal_id}")
                ]])

            for sub in subscribers:
                chat_id = str(sub["telegram_chat_id"])
                is_admin = (chat_id == str(settings.ADMIN_TELEGRAM_ID))
                subscriber_text = render_deal_card(deal, is_admin=is_admin, is_broadcast=True, compact=True)

                try:
                    await active_bot.send_message(
                        chat_id=chat_id,
                        text=subscriber_text,
                        parse_mode="Markdown",
                        protect_content=True,
                        disable_web_page_preview=True,
                        reply_markup=reply_markup
                    )
                    sent_count += 1
                except Exception as e:
                    try:
                        await active_bot.send_message(
                            chat_id=chat_id,
                            text=subscriber_text.replace("*", "").replace("`", ""),
                            protect_content=True,
                            disable_web_page_preview=True,
                            reply_markup=reply_markup
                        )
                        sent_count += 1
                    except Exception as ex2:
                        print(f"[Dispatcher] فشل الإرسال للمشترك {chat_id}: {ex2}")

            # إذا كانت هناك قناة عامة للتسويق (نرسل نسخة طعم تسويقية بدون اسم المتجر ورقم الهاتف)
            if settings.TELEGRAM_BROADCAST_CHAT_ID:
                prod_name = deal.get("product_name", "سلعة جديدة")
                prod_price = deal.get("price", "")
                prod_curr = deal.get("currency", "ILS")
                prod_loc = deal.get("location", "قطاع غزة")
                post_time = deal.get("post_time_text", "اليوم")
                teaser_text = (
                    f"⚡ **صيد جديد رصده الرادار في أسواق غزة** ⚡\n\n"
                    f"🛍️ **السلعة:** {prod_name}\n"
                    f"🔥 **السعر:** {prod_price} {prod_curr} *(سعر حرق)*\n"
                    f"📍 **المنطقة:** {prod_loc}\n"
                    f"⏰ **التوقيت:** {post_time}\n\n"
                    f"🔒 **تنبيه:** اسم المتجر ورقم هاتف التاجر ورابط العرض الأصلي محجوبة ومخصصة للمشتركين في البوت الخاص.\n\n"
                    f"👇 اضغط على الزر أدناه لمعرفة تفاصيل المتجر ورقم التاجر فوراً:"
                )
                channel_btn = InlineKeyboardMarkup([[
                    InlineKeyboardButton("⚡ كشف تفاصيل المتجر والتاجر في البوت", url="https://t.me/gaza_safaqat_bot?start=channel_teaser")
                ]])
                try:
                    await active_bot.send_message(
                        chat_id=settings.TELEGRAM_BROADCAST_CHAT_ID,
                        text=teaser_text,
                        parse_mode="Markdown",
                        reply_markup=channel_btn
                    )
                except Exception as e:
                    try:
                        await active_bot.send_message(
                            chat_id=settings.TELEGRAM_BROADCAST_CHAT_ID,
                            text=teaser_text.replace("*", "").replace("`", ""),
                            reply_markup=channel_btn
                        )
                    except Exception as ex2:
                        print(f"[Dispatcher] فشل الإرسال للقناة العامة: {ex2}")

            # تعليم الصفقة بأنها بُثت في القاعدة المحلية والسحابية
            if deal_id:
                db.mark_deal_broadcasted(deal_id)

            if sent_count > 0:
                print(f"[Dispatcher] 📢 تم بث الصفقة [{deal.get('product_name')}] بنجاح إلى {sent_count} مشترك.")
            return sent_count

        if bot:
            return await _send_with_bot(bot)
        else:
            async with Bot(token=self.bot_token) as fresh_bot:
                return await _send_with_bot(fresh_bot)

    async def broadcast_all_pending_deals(self) -> int:
        """بث كل الصفقات المعلقة في قاعدة البيانات"""
        unbroadcasted = db.get_unbroadcasted_deals()
        if not unbroadcasted:
            return 0
        total_sent = 0
        async with Bot(token=self.bot_token) as fresh_bot:
            for deal in unbroadcasted:
                sent = await self.broadcast_deal(deal, bot=fresh_bot)
                if sent > 0:
                    total_sent += 1
                await asyncio.sleep(0.6) # مهلة لمنع الـ Flood limit في تليجرام
        return total_sent

alert_dispatcher = AlertDispatcher()
