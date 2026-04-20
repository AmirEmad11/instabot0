"""
الملف الرئيسي لنظام الأتمتة العقارية على إنستجرام
نقطة الدخول الوحيدة للنظام - يجمع جميع الوحدات معاً

كيفية الاستخدام:
    python main.py

تأكد من تعديل ملف config.py أولاً وإدخال بيانات حسابك.
"""

import asyncio
import logging
from config import (
    INSTAGRAM_USERNAME,
    MAX_DM_PER_DAY,
    MAX_FOLLOWS_PER_DAY,
    DELAY_MIN_MESSAGE,
    DELAY_MAX_MESSAGE,
)
from session_manager import SessionManager
from lead_scraper import LeadScraper
from automation_engine import AutomationEngine
from database import DatabaseManager
from utils import setup_logging, random_delay, take_error_screenshot

logger = logging.getLogger(__name__)


# ==================== قائمة المنشورات المستهدفة ====================
# أضف هنا روابط المنشورات أو الريلز التي تريد استخراج العملاء منها
TARGET_POSTS = [
    "https://www.instagram.com/p/XXXXXXXXXX/",   # مثال: رابط منشور عقاري
    "https://www.instagram.com/reel/YYYYYYYYYY/", # مثال: رابط ريل عقاري
]


class InstagramRealEstateBot:
    """
    الكلاس الرئيسي للبوت - يجمع جميع وحدات النظام في مكان واحد
    ويُنسّق العمليات المختلفة بطريقة آمنة ومنظمة
    """

    def __init__(self):
        self.session_manager = SessionManager()
        self.db_manager = DatabaseManager()
        self.lead_scraper: LeadScraper = None
        self.automation_engine: AutomationEngine = None
        
        # عدادات العمليات اليومية
        self.daily_dm_count = 0
        self.daily_follow_count = 0

    async def initialize(self):
        """
        تهيئة جميع مكونات النظام (قاعدة البيانات + المتصفح + تسجيل الدخول)
        """
        logger.info("=" * 60)
        logger.info("🚀 بدء تشغيل نظام الأتمتة العقارية على إنستجرام")
        logger.info("=" * 60)
        
        # تهيئة قاعدة البيانات
        await self.db_manager.initialize()
        
        # بدء تشغيل المتصفح وتحميل الجلسة
        page = await self.session_manager.start()
        
        # تسجيل الدخول إذا لزم الأمر
        logged_in = await self.session_manager.ensure_logged_in()
        if not logged_in:
            raise RuntimeError("❌ فشل تسجيل الدخول - تحقق من بيانات الحساب في config.py")
        
        # تهيئة وحدات العمل
        self.lead_scraper = LeadScraper(page)
        self.automation_engine = AutomationEngine(page)
        
        # تحميل عدد الرسائل المرسلة اليوم من قاعدة البيانات
        self.daily_dm_count = await self.db_manager.get_daily_dm_count()
        logger.info(f"الرسائل المرسلة اليوم: {self.daily_dm_count}/{MAX_DM_PER_DAY}")

    async def process_post(self, post_url: str):
        """
        معالجة منشور واحد: استخراج العملاء، متابعتهم، ومراسلتهم
        
        Args:
            post_url: رابط المنشور أو الريل
        """
        logger.info(f"\n{'='*50}")
        logger.info(f"🔍 جارٍ معالجة المنشور: {post_url}")
        logger.info(f"{'='*50}")
        
        # 1. استخراج العملاء المحتملين من التعليقات
        leads = await self.lead_scraper.scrape_leads_from_post(post_url)
        
        if not leads:
            logger.info("لم يُعثر على عملاء محتملين في هذا المنشور")
            return
        
        logger.info(f"📋 تم استخراج {len(leads)} عميل محتمل")
        
        # 2. معالجة كل عميل محتمل
        for lead in leads:
            await self._process_single_lead(lead)
            
            # التحقق من الحد اليومي للرسائل
            if self.daily_dm_count >= MAX_DM_PER_DAY:
                logger.warning(f"⛔ تم الوصول للحد اليومي ({MAX_DM_PER_DAY} رسالة) - إيقاف المراسلة")
                break

    async def _process_single_lead(self, lead: dict):
        """
        معالجة عميل محتمل واحد: التحقق من قاعدة البيانات، المتابعة، الرسالة، والرد
        
        Args:
            lead: قاموس يحتوي على بيانات العميل (username, comment_text, post_url)
        """
        username = lead["username"]
        comment_text = lead["comment_text"]
        post_url = lead["post_url"]
        
        logger.info(f"\n👤 معالجة العميل: @{username}")
        
        # التحقق مما إذا كان مسجلاً مسبقاً في قاعدة البيانات
        if await self.db_manager.lead_exists(username):
            logger.info(f"⏭️ تم تخطي @{username} - موجود مسبقاً في قاعدة البيانات")
            return
        
        # التحقق من وجود Action Block قبل كل عملية
        is_blocked = await self.session_manager.check_action_block()
        if is_blocked:
            logger.error("🚫 تم اكتشاف Action Block! إيقاف العمليات...")
            raise RuntimeError("Action Block detected - توقف النظام للحماية")
        
        # إضافة العميل لقاعدة البيانات
        await self.db_manager.add_lead(username, post_url, comment_text)
        
        # --- الخطوة 1: زيارة البروفايل والمتابعة ---
        followed = False
        if self.daily_follow_count < MAX_FOLLOWS_PER_DAY:
            try:
                followed = await self.automation_engine.visit_and_follow_profile(username)
                if followed:
                    self.daily_follow_count += 1
                    await self.db_manager.update_lead_status(username, followed=True)
            except Exception as e:
                logger.error(f"خطأ أثناء المتابعة: {e}")
                await self.db_manager.update_lead_status(username, status="error")
        
        await random_delay(3, 6)
        
        # --- الخطوة 2: إرسال رسالة DM ---
        if self.daily_dm_count < MAX_DM_PER_DAY:
            try:
                dm_sent = await self.automation_engine.send_direct_message(
                    username,
                    user_id=lead.get("user_id") or lead.get("id") or lead.get("pk"),
                )
                if dm_sent:
                    self.daily_dm_count += 1
                    await self.db_manager.update_lead_status(
                        username, dm_sent=True, status="messaged"
                    )
                    logger.info(
                        f"📨 الرسائل المرسلة اليوم: {self.daily_dm_count}/{MAX_DM_PER_DAY}"
                    )
            except Exception as e:
                logger.error(f"خطأ أثناء إرسال DM: {e}")
                await self.db_manager.update_lead_status(username, status="error")
        
        await random_delay(5, 10)
        
        # --- الخطوة 3: الرد على التعليق ---
        try:
            replied = await self.automation_engine.reply_to_comment(post_url, username)
            if replied:
                await self.db_manager.update_lead_status(username, comment_replied=True)
        except Exception as e:
            logger.error(f"خطأ أثناء الرد على التعليق: {e}")
        
        # تأخير ختامي بين كل عميل وآخر
        await random_delay(15, 25)

    async def run(self):
        """
        الدالة الرئيسية لتشغيل البوت - تمر على جميع المنشورات المستهدفة
        """
        try:
            await self.initialize()
            
            logger.info(f"\n📌 قائمة المنشورات المستهدفة: {len(TARGET_POSTS)} منشور")
            
            for i, post_url in enumerate(TARGET_POSTS, 1):
                logger.info(f"\n📍 المنشور {i}/{len(TARGET_POSTS)}")
                await self.process_post(post_url)
                
                # تأخير بين المنشورات لتجنب الحظر
                if i < len(TARGET_POSTS):
                    logger.info("⏳ انتظار قبل الانتقال للمنشور التالي...")
                    await random_delay(30, 60)
            
            logger.info("\n" + "=" * 60)
            logger.info("✅ اكتملت جميع العمليات بنجاح!")
            logger.info(f"📊 إجمالي الرسائل المرسلة: {self.daily_dm_count}")
            logger.info(f"📊 إجمالي المتابعات: {self.daily_follow_count}")
            logger.info("=" * 60)
            
        except RuntimeError as e:
            logger.critical(f"❌ خطأ حرج: {e}")
        except Exception as e:
            logger.error(f"❌ خطأ غير متوقع: {e}")
            if self.session_manager.page:
                await take_error_screenshot(self.session_manager.page, "critical_error")
        finally:
            await self.session_manager.close()


async def main():
    """نقطة الدخول الرئيسية للبرنامج"""
    setup_logging()
    bot = InstagramRealEstateBot()
    await bot.run()


if __name__ == "__main__":
    asyncio.run(main())
