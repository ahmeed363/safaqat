import asyncio
from typing import Dict, Any, List
from telegram import Bot
from config.settings import settings
from database.db_manager import db
from bot.telegram_bot import format_deal_time, render_deal_card

class AlertDispatcher:
    def __init__(self, bot_token: str = ""):
        self.bot_token = bot_token or settings.TELEGRAM_BOT_TOKEN
        self.bot = Bot(token=self.bot_token) if self.bot_token else None

    async def broadcast_deal(self, deal: Dict[str, Any]) -> int:
        """
        بث الصفقة فورياً لجميع المشتركين مع تفعيل خاصية الحماية من النسخ protect_content=True
        وبتنسيق جذاب وملفت يبرز السلعة والسعر
        """
        if not self.bot:
            print("[Dispatcher] ⚠️ لم يتم ضبط TELEGRAM_BOT_TOKEN. تم تخطي البث.")
            return 0

        # جلب جميع المشتركين المؤهلين (المفعلين وأصحاب التجربة المجانية)
        subscribers = db.get_active_subscribers()
        sent_count = 0
        deal_id = deal.get("id")

        from telegram import InlineKeyboardMarkup, InlineKeyboardButton
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
                await self.bot.send_message(
                    chat_id=chat_id,
                    text=subscriber_text,
                    parse_mode="Markdown",
                    protect_content=True, # 🔒 تفعيل منع النسخ وإعادة التوجيه ولقطة الشاشة
                    disable_web_page_preview=True,
                    reply_markup=reply_markup
                )
                sent_count += 1
            except Exception as e:
                # Fallback if markdown error
                try:
                    await self.bot.send_message(
                        chat_id=chat_id,
                        text=subscriber_text.replace("*", "").replace("`", ""),
                        protect_content=True,
                        disable_web_page_preview=True,
                        reply_markup=reply_markup
                    )
                    sent_count += 1
                except Exception as ex2:
                    print(f"[Dispatcher] فشل الإرسال للمشترك {chat_id}: {ex2}")

        # إذا كانت هناك قناة عامة للتسويق (نرسل نسخة طعم تسويقية بدون رقم الهاتف)
        if settings.TELEGRAM_BROADCAST_CHAT_ID:
            prod_name = deal.get("product_name", "سلعة جديدة")
            prod_price = deal.get("price", "")
            prod_curr = deal.get("currency", "ILS")
            prod_loc = deal.get("location", "قطاع غزة")
            teaser_text = (
                f"⚡ **رصد جديد من رادار صفقات غزة** ⚡\n\n"
                f"🛒 **السلعة:** {prod_name}\n"
                f"💰 **السعر:** {prod_price} {prod_curr} *(سعر حرق)*\n"
                f"📍 **الموقع:** {prod_loc}\n\n"
                f"🔒 *تم إرسال رقم التاجر والتفاصيل كاملة وفيديو العرض للمشتركين في البوت الخاص.*\n"
                f"👉 للاشتراك وتصلك الصفقات في ثوانٍ: تواصل مع البوت فوراً."
            )
            try:
                await self.bot.send_message(
                    chat_id=settings.TELEGRAM_BROADCAST_CHAT_ID,
                    text=teaser_text,
                    parse_mode="Markdown"
                )
            except Exception as e:
                print(f"[Dispatcher] فشل الإرسال للقناة العامة: {e}")

        # تعليم الصفقة بأنها بُثت
        if "id" in deal:
            db.mark_deal_broadcasted(deal["id"])

        print(f"[Dispatcher] 📢 تم بث الصفقة بنجاح إلى {sent_count} مشترك.")
        return sent_count

    async def broadcast_all_pending_deals(self) -> int:
        """بث كل الصفقات المعلقة في قاعدة البيانات"""
        unbroadcasted = db.get_unbroadcasted_deals()
        total_sent = 0
        for deal in unbroadcasted:
            await self.broadcast_deal(deal)
            total_sent += 1
        return total_sent

alert_dispatcher = AlertDispatcher()
