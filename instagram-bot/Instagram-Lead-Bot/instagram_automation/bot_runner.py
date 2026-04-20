"""
وحدة تشغيل البوت (Bot Runner)
- يدعم وضع السحب فقط (scrape_only) بدون تنفيذ
- يدعم Turbo Mode بتأخيرات 1-3 ثوانٍ فقط
- يدعم pre_selected_leads لتنفيذ قائمة محددة مسبقاً
- إيقاف طارئ فوري مع إغلاق المتصفح
"""

import asyncio
import json
import logging
import queue
import random
import threading
import traceback
from pathlib import Path
from typing import Callable

from session_manager import SessionManager
from lead_scraper import LeadScraper
from automation_engine import AutomationEngine
from database import DatabaseManager
from utils import random_delay, take_error_screenshot

logger = logging.getLogger(__name__)

# ── تسجيل الأخطاء في ملف خارجي (server_errors.log) ──
_log_file = Path(__file__).parent / "server_errors.log"
if not any(isinstance(h, logging.FileHandler) and h.baseFilename == str(_log_file)
           for h in logging.getLogger().handlers):
    _fh = logging.FileHandler(str(_log_file), encoding="utf-8")
    _fh.setLevel(logging.ERROR)
    _fh.setFormatter(logging.Formatter(
        "%(asctime)s  [%(levelname)s]  %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logging.getLogger().addHandler(_fh)


class QueueLogHandler(logging.Handler):
    _HIGH_LEVEL_KEYWORDS = (
        "🚀 بدء", "🌐 جاري", "✅ تم تشغيل", "🔐 جاري", "✅ تم تسجيل",
        "📨 الرسائل", "☕ راحة", "✅ Turbo اكتمل", "🛑", "⛔",
        "🔔 فح", "🔍 المنشور", "📋 عملاء", "⚠️  لم يُعثر",
        "EXEC_", "BATCH_", "REST_", "SCRAPED_", "SCRAPE_DONE", "LEAD_",
    )

    def __init__(self, log_queue: queue.Queue):
        super().__init__()
        self.log_queue = log_queue
        fmt = logging.Formatter("%(asctime)s  %(message)s", datefmt="%H:%M:%S")
        self.setFormatter(fmt)

    def emit(self, record: logging.LogRecord):
        import config as cfg
        try:
            if not cfg.DEBUG_MODE and record.levelno == logging.INFO:
                msg = record.getMessage()
                if not any(kw in msg for kw in self._HIGH_LEVEL_KEYWORDS):
                    return
            self.log_queue.put_nowait(self.format(record))
        except Exception:
            pass


class BotRunner:

    def __init__(
        self,
        settings: dict,
        target_posts: list[str],
        log_queue: queue.Queue,
        stop_event: threading.Event,
        on_finish: Callable = None,
        scrape_only: bool = False,
        turbo_mode: bool = False,
        pre_selected_leads: list[dict] = None,
    ):
        self.settings = settings
        self.target_posts = target_posts
        self.log_queue = log_queue
        self.stop_event = stop_event
        self.on_finish = on_finish
        self.scrape_only = scrape_only
        self.turbo_mode = turbo_mode
        self.pre_selected_leads = pre_selected_leads or []

        self.session_manager = SessionManager()
        self.db_manager = DatabaseManager()
        self.lead_scraper: LeadScraper = None
        self.automation_engine: AutomationEngine = None

        self.daily_dm_count = 0
        self.daily_follow_count = 0
        self.successful_dm_batch_count = 0

        self._apply_settings()

    # ─────────────────────────────────────────────────────────────
    #  تطبيق الإعدادات
    # ─────────────────────────────────────────────────────────────

    def _apply_settings(self):
        import config as cfg

        cfg.INSTAGRAM_USERNAME = self.settings.get("username", "")
        cfg.INSTAGRAM_PASSWORD = self.settings.get("password", "")
        cfg.MAX_DM_PER_DAY = int(self.settings.get("max_dm_per_day", 20))
        cfg.MAX_FOLLOWS_PER_DAY = int(self.settings.get("max_follows_per_day", 30))
        cfg.MAX_COMMENTS_SCROLL = int(self.settings.get("max_comments_scroll", 50))
        cfg.DELAY_MIN_ACTION = float(self.settings.get("delay_min_action", 30))
        cfg.DELAY_MAX_ACTION = float(self.settings.get("delay_max_action", 60))
        cfg.DELAY_MIN_MESSAGE = float(self.settings.get("delay_min_message", 60))
        cfg.DELAY_MAX_MESSAGE = float(self.settings.get("delay_max_message", 120))
        cfg.DELAY_SCROLL = float(self.settings.get("delay_scroll", 3))
        cfg.HEADLESS_MODE = True  # دائماً headless على السيرفر (VPS لا يوجد شاشة)
        cfg.KEYWORDS = self.settings.get("keywords", cfg.KEYWORDS)
        cfg.MOBILE_EMULATION = bool(self.settings.get("mobile_emulation", True))
        cfg.COMPETITOR_FILTER = bool(self.settings.get("competitor_filter", True))
        kw_from_settings = self.settings.get("competitor_keywords", None)
        if kw_from_settings:
            cfg.COMPETITOR_KEYWORDS = kw_from_settings
        cfg.PUBLIC_AUTO_REPLY = bool(self.settings.get("public_auto_reply", True))
        cfg.PRIVATE_AUTO_REPLY = bool(self.settings.get("private_auto_reply", False))
        cfg.PRIVATE_REPLY_TEXT = self.settings.get("private_reply_text", cfg.PRIVATE_REPLY_TEXT)

        # ── مسار الجلسة الديناميكي (لكل مستخدم SaaS) ──
        session_file = self.settings.get("session_file", None)
        if session_file:
            cfg.SESSION_FILE = session_file

        raw_templates = self.settings.get("message_templates", cfg.MESSAGE_TEMPLATES)
        cfg.MESSAGE_TEMPLATES = self._parse_templates(raw_templates)
        cfg.COMMENT_REPLY_TEXT = self.settings.get("comment_reply_text", cfg.COMMENT_REPLY_TEXT)

    @staticmethod
    def _parse_templates(raw) -> list[str]:
        if isinstance(raw, list):
            result = []
            for item in raw:
                result.extend(BotRunner._split_on_pipe(str(item)))
            return [t for t in result if t.strip()] or list(raw)
        if isinstance(raw, str):
            return BotRunner._split_on_pipe(raw) or [raw]
        return list(raw) if raw else []

    @staticmethod
    def _split_on_pipe(text: str) -> list[str]:
        parts, depth, current = [], 0, []
        for ch in text:
            if ch == '{':
                depth += 1; current.append(ch)
            elif ch == '}':
                depth -= 1; current.append(ch)
            elif ch == '|' and depth == 0:
                p = ''.join(current).strip()
                if p: parts.append(p)
                current = []
            else:
                current.append(ch)
        last = ''.join(current).strip()
        if last: parts.append(last)
        return parts

    # ─────────────────────────────────────────────────────────────
    #  إعداد Logging
    # ─────────────────────────────────────────────────────────────

    def _setup_queue_logging(self):
        root = logging.getLogger()
        handler = QueueLogHandler(self.log_queue)
        handler.setLevel(logging.INFO)
        root.addHandler(handler)
        root.setLevel(logging.INFO)

    def _is_stopped(self) -> bool:
        return self.stop_event.is_set()

    # ─────────────────────────────────────────────────────────────
    #  التهيئة
    # ─────────────────────────────────────────────────────────────

    async def initialize(self):
        import config as cfg

        mode_label = "سحب فقط 🔍" if self.scrape_only else ("Turbo ⚡" if self.turbo_mode else "عادي")
        logger.info(f"🚀 بدء تشغيل نظام الأتمتة | الوضع: {mode_label}")
        logger.info(f"👤 الحساب: @{cfg.INSTAGRAM_USERNAME}")
        logger.info(f"📌 المنشورات المستهدفة: {len(self.target_posts)}")
        if self.turbo_mode and self.pre_selected_leads:
            logger.info(f"⚡ Turbo: تنفيذ {len(self.pre_selected_leads)} عميل محدد مسبقاً")

        await self.db_manager.initialize()

        logger.info("🌐 جاري تشغيل المتصفح...")
        page = await self.session_manager.start()
        logger.info("✅ تم تشغيل المتصفح بنجاح")

        logger.info("🔐 جاري التحقق من تسجيل الدخول...")
        logged_in = await self.session_manager.ensure_logged_in()
        if not logged_in:
            raise RuntimeError("❌ فشل تسجيل الدخول - تحقق من البيانات")

        self.lead_scraper = LeadScraper(page)
        self.automation_engine = AutomationEngine(page)

        # ── إغلاق النوافذ المنبثقة بعد تسجيل الدخول (Save Login / Notifications) ──
        logger.info("🔔 فحص النوافذ المنبثقة بعد تسجيل الدخول...")
        await self.automation_engine.handle_popups(max_rounds=5)
        self.lead_scraper.set_keywords(cfg.KEYWORDS)
        self.automation_engine.set_message_templates(cfg.MESSAGE_TEMPLATES)
        self.automation_engine.set_comment_reply_text(cfg.COMMENT_REPLY_TEXT)
        self.automation_engine.set_private_auto_reply(
            cfg.PRIVATE_AUTO_REPLY,
            cfg.PRIVATE_REPLY_TEXT,
        )

        self.daily_dm_count = await self.db_manager.get_daily_dm_count()
        logger.info(f"📨 الرسائل المرسلة اليوم: {self.daily_dm_count}/{cfg.MAX_DM_PER_DAY}")

    # ─────────────────────────────────────────────────────────────
    #  معالجة المنشورات (وضع عادي أو سحب فقط)
    # ─────────────────────────────────────────────────────────────

    async def process_post(self, post_url: str, index: int, total: int):
        import config as cfg

        if self._is_stopped():
            return

        logger.info(f"{'─' * 45}")
        logger.info(f"🔍 المنشور {index}/{total}: {post_url[:60]}...")
        logger.info(f"{'─' * 45}")

        # ── إغلاق أي نوافذ منبثقة قد تغطي الشاشة قبل بدء السحب ──
        await self.automation_engine.handle_popups(max_rounds=3)

        leads = await self.lead_scraper.scrape_leads_from_post(
            post_url, db_check_fn=self.db_manager.lead_exists
        )

        if not leads:
            logger.info("⚠️  لم يُعثر على عملاء محتملين في هذا المنشور")
            return

        logger.info(f"📋 عملاء محتملون: {len(leads)}")

        # ── وضع السحب فقط: إرسال النتائج للواجهة عبر الـ Queue ──
        if self.scrape_only:
            payload = json.dumps(leads, ensure_ascii=False)
            self.log_queue.put_nowait(f"SCRAPED_LEADS:{payload}")
            logger.info(f"📤 تم إرسال {len(leads)} تعليق للعرض في الواجهة")
            return

        # ── الوضع العادي: تنفيذ الإجراءات ──
        total_leads = len(leads)
        for lead_idx, lead in enumerate(leads, 1):
            if self._is_stopped():
                logger.info("🛑 تم إيقاف العملية")
                break
            if self.daily_dm_count >= cfg.MAX_DM_PER_DAY:
                logger.warning(f"⛔ الحد اليومي للرسائل ({cfg.MAX_DM_PER_DAY}) - توقف")
                break
            self.log_queue.put_nowait(f"LEAD_PROCESSING:{lead_idx}/{total_leads} @{lead['username']}")
            await self._process_single_lead(lead, lead_idx, total_leads)

    # ─────────────────────────────────────────────────────────────
    #  Turbo Mode: تنفيذ قائمة محددة مسبقاً بتأخيرات 1-3 ثوانٍ
    # ─────────────────────────────────────────────────────────────

    async def run_selected_leads_turbo(self):
        import config as cfg

        if not self.pre_selected_leads:
            logger.warning("⚠️ لا توجد عملاء محددون للإرسال")
            return

        logger.info(f"⚡ Turbo Mode: بدء إرسال {len(self.pre_selected_leads)} عميل")
        logger.info(f"⏱️ التأخير بين كل عميل: 15-25 ثانية، وراحة 60-120 ثانية بعد كل 10 رسائل")
        self.log_queue.put_nowait(f"EXEC_TOTAL total={len(self.pre_selected_leads)}")
        self.log_queue.put_nowait("BATCH_STATUS sent=0 total=10")
        processed_count = 0

        for i, lead in enumerate(self.pre_selected_leads, 1):
            if self._is_stopped():
                logger.info("🛑 تم إيقاف العملية")
                break
            if self.daily_dm_count >= cfg.MAX_DM_PER_DAY:
                logger.warning(f"⛔ الحد اليومي للرسائل ({cfg.MAX_DM_PER_DAY}) - توقف")
                break

            username = lead['username']
            total = len(self.pre_selected_leads)
            logger.info(f"⚡ [{i}/{total}] معالجة: @{username}")
            self.log_queue.put_nowait(f"LEAD_PROCESSING:{i}/{total} @{username}")
            self.log_queue.put_nowait(
                f"EXEC_PROGRESS current={max(i - 1, 0)} total={total} username={username}"
            )
            dm_sent = await self._process_single_lead_turbo(lead)
            self.log_queue.put_nowait(
                f"EXEC_PROGRESS current={i} total={total} username={username}"
            )
            if dm_sent:
                self.log_queue.put_nowait(f"LEAD_DONE_OK:{i}/{total} @{username}")
            else:
                self.log_queue.put_nowait(f"LEAD_DONE_SKIP:{i}/{total} @{username}")
            processed_count = i

            # ── حفظ Checkpoint ──
            _site_user = self.settings.get("site_username", "")
            if _site_user:
                try:
                    import site_database as _sdb
                    _remaining = self.pre_selected_leads[i:]
                    if _remaining:
                        _sdb.save_checkpoint(_site_user, i, _remaining)
                    else:
                        _sdb.clear_checkpoint(_site_user)
                except Exception:
                    pass

            if dm_sent:
                await self._apply_batch_rest_if_needed()

        logger.info("=" * 45)
        logger.info(f"✅ Turbo اكتمل! رسائل: {self.daily_dm_count} | متابعات: {self.daily_follow_count}")
        logger.info("=" * 45)
        self.log_queue.put_nowait(f"EXEC_PROGRESS current={processed_count} total={len(self.pre_selected_leads)} username=")
        # ── مسح Checkpoint عند الاكتمال ──
        _site_user = self.settings.get("site_username", "")
        if _site_user:
            try:
                import site_database as _sdb
                _sdb.clear_checkpoint(_site_user)
            except Exception:
                pass

    async def _process_single_lead_turbo(self, lead: dict) -> bool:
        """معالجة عميل واحد بتأخيرات Turbo (1-3 ثوانٍ)"""
        import config as cfg

        username = lead.get("username", "")
        comment_text = lead.get("comment_text", "")
        post_url = lead.get("post_url", "")

        if not username:
            return False

        if await self.db_manager.dm_already_sent(username):
            logger.info(f"⏭️ تخطي @{username} - تم إرسال رسالة له مسبقاً")
            return False

        is_blocked = await self.session_manager.check_action_block()
        if is_blocked:
            logger.error("🚫 Action Block مكتشف! إيقاف العمليات")
            self.stop_event.set()
            return False

        await self.db_manager.add_lead(username, post_url, comment_text)

        account_type = "unknown"
        is_private = False

        # ── متابعة (Turbo) ──
        if not self._is_stopped() and self.daily_follow_count < cfg.MAX_FOLLOWS_PER_DAY:
            try:
                follow_result = await self.automation_engine.visit_and_follow_profile(username)
                if follow_result.get("is_competitor"):
                    logger.info(f"[🚫] تخطي @{username} - منافس")
                    return False
                followed = follow_result["followed"]
                account_type = follow_result["account_type"]
                is_private = account_type == "private"
                if followed:
                    self.daily_follow_count += 1
                await self.db_manager.update_lead_status(
                    username, followed=followed, account_type=account_type
                )
            except Exception as e:
                logger.error(f"❌ متابعة @{username}: {str(e)[:60]}")

        # ── DM (Turbo) – يحاول الإرسال للعام والخاص عبر 3-Dots ──
        if not self._is_stopped() and self.daily_dm_count < cfg.MAX_DM_PER_DAY:
            if is_private:
                # انتظار أطول للحسابات الخاصة قبل محاولة الإرسال
                await asyncio.sleep(random.uniform(2.0, 3.5))
            try:
                dm_sent = await self.automation_engine.send_direct_message(
                    username,
                    user_id=lead.get("user_id") or lead.get("id") or lead.get("pk"),
                    is_private=is_private,
                )
                if dm_sent:
                    self.daily_dm_count += 1
                    self.successful_dm_batch_count += 1
                    self.log_queue.put_nowait(
                        f"BATCH_STATUS sent={self.successful_dm_batch_count % 10 or 10} total=10"
                    )
                    status = "messaged"
                    await self.db_manager.update_lead_status(
                        username, dm_sent=True, status=status
                    )
                    if is_private:
                        logger.info(f"[🔒💬] DM ناجح لحساب خاص: @{username}")
                else:
                    if is_private:
                        await self.db_manager.update_lead_status(username, status="private_pending")
            except Exception as e:
                logger.error(f"❌ DM @{username}: {str(e)[:60]}")
                if is_private:
                    await self.db_manager.update_lead_status(username, status="private_pending")

        # ── رد على التعليق (Turbo) ──
        if not self._is_stopped():
            try:
                if is_private and cfg.PRIVATE_AUTO_REPLY:
                    replied = await self.automation_engine.reply_to_comment(
                        post_url, username, custom_text=cfg.PRIVATE_REPLY_TEXT
                    )
                    if replied:
                        await self.db_manager.update_lead_status(username, comment_replied=True)
                elif not is_private and cfg.PUBLIC_AUTO_REPLY:
                    replied = await self.automation_engine.reply_to_comment(post_url, username)
                    if replied:
                        await self.db_manager.update_lead_status(username, comment_replied=True)
            except Exception as e:
                logger.error(f"❌ رد @{username}: {str(e)[:60]}")

        await asyncio.sleep(random.uniform(15, 25))
        return dm_sent if "dm_sent" in locals() else False

    async def _apply_batch_rest_if_needed(self):
        if self.successful_dm_batch_count > 0 and self.successful_dm_batch_count % 10 == 0:
            rest_seconds = random.randint(60, 120)
            self.log_queue.put_nowait(f"REST_START seconds={rest_seconds}")
            logger.info(f"☕ راحة إجبارية بعد 10 رسائل ناجحة: {rest_seconds} ثانية")
            await asyncio.sleep(rest_seconds)
            self.log_queue.put_nowait("REST_END")
            self.log_queue.put_nowait("BATCH_STATUS sent=0 total=10")

    # ─────────────────────────────────────────────────────────────
    #  الوضع العادي: معالجة عميل واحد
    # ─────────────────────────────────────────────────────────────

    async def _process_single_lead(self, lead: dict, lead_idx: int = 0, total_leads: int = 0):
        import config as cfg

        username = lead["username"]
        comment_text = lead["comment_text"]
        post_url = lead["post_url"]
        idx_label = f"{lead_idx}/{total_leads}" if total_leads else "?"

        logger.info(f"👤 معالجة: @{username}")

        if await self.db_manager.dm_already_sent(username):
            logger.info(f"⏭️  تخطي @{username} - تم إرسال رسالة له مسبقاً")
            self.log_queue.put_nowait(f"LEAD_DONE_SKIP:{idx_label} @{username}")
            return

        is_blocked = await self.session_manager.check_action_block()
        if is_blocked:
            logger.error("🚫 Action Block مكتشف! إيقاف العمليات")
            self.stop_event.set()
            raise RuntimeError("Action Block detected")

        await self.db_manager.add_lead(username, post_url, comment_text)

        account_type = "unknown"
        is_private = False

        if not self._is_stopped() and self.daily_follow_count < cfg.MAX_FOLLOWS_PER_DAY:
            try:
                follow_result = await self.automation_engine.visit_and_follow_profile(username)
                if follow_result.get("is_competitor"):
                    logger.info(f"[🚫] تخطي @{username} - منافس (كلمة محظورة في البيو)")
                    return
                followed = follow_result["followed"]
                account_type = follow_result["account_type"]
                is_private = account_type == "private"
                if followed:
                    self.daily_follow_count += 1
                await self.db_manager.update_lead_status(
                    username, followed=followed, account_type=account_type
                )
                status_label = "🔒 خاص" if is_private else "🌐 عام"
                logger.info(
                    f"   {'✅' if followed else '⚠️'} متابعة @{username} "
                    f"{status_label} - المجموع: {self.daily_follow_count}/{cfg.MAX_FOLLOWS_PER_DAY}"
                )
                if is_private and followed:
                    logger.info(f"[🔒] حساب خاص - تم طلب المتابعة: @{username}")
            except Exception as e:
                logger.error(f"   ❌ خطأ في المتابعة: {e}")
                await self.db_manager.update_lead_status(username, status="error")

        await random_delay(3, 6)

        if not self._is_stopped() and self.daily_dm_count < cfg.MAX_DM_PER_DAY:
            already_sent = await self.db_manager.dm_already_sent(username)
            if already_sent:
                logger.info(f"⏭️  DM مُرسل مسبقاً لـ @{username}")
            else:
                if is_private:
                    # انتظار أطول للحسابات الخاصة قبل محاولة DM عبر 3-Dots
                    logger.info(f"   🔒 @{username} حساب خاص - محاولة DM عبر 3-Dots...")
                    await random_delay(2.5, 4.0)
                try:
                    dm_sent = await self.automation_engine.send_direct_message(
                        username,
                        user_id=lead.get("user_id") or lead.get("id") or lead.get("pk"),
                        is_private=is_private,
                    )
                    if dm_sent:
                        self.daily_dm_count += 1
                        self.successful_dm_batch_count += 1
                        self.log_queue.put_nowait(
                            f"BATCH_STATUS sent={self.successful_dm_batch_count % 10 or 10} total=10"
                        )
                        await self.db_manager.update_lead_status(
                            username, dm_sent=True, status="messaged"
                        )
                        acc_label = "🔒 خاص" if is_private else "🌐 عام"
                        logger.info(
                            f"   📨 رسالة لـ @{username} ({acc_label}) - "
                            f"المجموع: {self.daily_dm_count}/{cfg.MAX_DM_PER_DAY}"
                        )
                    else:
                        if is_private:
                            logger.info(f"   🔒 @{username} خاص - DM فشل → private_pending")
                            await self.db_manager.update_lead_status(username, status="private_pending")
                except Exception as e:
                    logger.error(f"   ❌ خطأ في إرسال DM: {e}")
                    if is_private:
                        await self.db_manager.update_lead_status(username, status="private_pending")
                    else:
                        await self.db_manager.update_lead_status(username, status="error")

        await random_delay(5, 10)

        if not self._is_stopped():
            try:
                if is_private and cfg.PRIVATE_AUTO_REPLY:
                    replied = await self.automation_engine.reply_to_comment(
                        post_url, username, custom_text=cfg.PRIVATE_REPLY_TEXT
                    )
                    if replied:
                        await self.db_manager.update_lead_status(username, comment_replied=True)
                        logger.info(f"   💬 رد على @{username} (خاص)")
                elif not is_private and cfg.PUBLIC_AUTO_REPLY:
                    replied = await self.automation_engine.reply_to_comment(post_url, username)
                    if replied:
                        await self.db_manager.update_lead_status(username, comment_replied=True)
                        logger.info(f"   💬 رد على @{username} (عام)")
                else:
                    logger.info(f"   🔕 الرد التلقائي معطّل لـ @{username}")
            except Exception as e:
                logger.error(f"   ❌ خطأ في الرد على التعليق: {e}")

        # ── نهاية المعالجة: إرسال حالة DONE ──
        _dm_done = locals().get("dm_sent", False)
        if _dm_done:
            self.log_queue.put_nowait(f"LEAD_DONE_OK:{idx_label} @{username}")
        else:
            self.log_queue.put_nowait(f"LEAD_DONE_SKIP:{idx_label} @{username}")

        await random_delay(15, 25)
        await self._apply_batch_rest_if_needed()

    # ─────────────────────────────────────────────────────────────
    #  متابعة الحسابات التي قبلت طلب المتابعة (Follow-up)
    # ─────────────────────────────────────────────────────────────

    async def check_accepted_requests(self):
        """
        يمر على جميع الحسابات الخاصة (private_pending) في قاعدة البيانات.
        إذا قبلوا طلب المتابعة (Following) → يرسل لهم DM فوراً.
        """
        import config as cfg

        pending = await self.db_manager.get_private_pending_leads()
        if not pending:
            logger.info("ℹ️ لا توجد حسابات خاصة معلّقة بانتظار القبول")
            return

        logger.info(f"🔔 فحص {len(pending)} حساب خاص معلّق...")
        accepted_count = 0
        dm_sent_count = 0

        for lead in pending:
            if self._is_stopped():
                break
            if self.daily_dm_count >= cfg.MAX_DM_PER_DAY:
                logger.warning(f"⛔ الحد اليومي للرسائل ({cfg.MAX_DM_PER_DAY}) - توقف")
                break

            username = lead.get("username", "")
            if not username:
                continue

            try:
                profile_url = f"https://www.instagram.com/{username}/"
                await self.automation_engine.page.goto(
                    profile_url, wait_until="domcontentloaded", timeout=15000
                )
                await random_delay(1.5, 3.0)

                is_following = await self.automation_engine.check_if_following(username)
                if not is_following:
                    logger.info(f"⏳ @{username} لم يقبل بعد - متخطَّى")
                    continue

                accepted_count += 1
                logger.info(f"✅ @{username} قبِل المتابعة! جاري إرسال رسالة...")

                dm_sent = await self.automation_engine.send_direct_message(username)
                if dm_sent:
                    dm_sent_count += 1
                    self.daily_dm_count += 1
                    await self.db_manager.update_lead_status(
                        username, dm_sent=True, status="messaged"
                    )
                    logger.info(f"📨 تم إرسال رسالة لـ @{username}")
                else:
                    logger.warning(f"⚠️ تعذّر إرسال رسالة لـ @{username}")

                await random_delay(20, 40)

            except Exception as e:
                logger.error(f"❌ فحص @{username}: {str(e)[:80]}")
                await random_delay(5, 10)

        logger.info("=" * 45)
        logger.info(f"✅ Follow-up اكتمل! قبلوا: {accepted_count} | رسائل أُرسلت: {dm_sent_count}")
        logger.info("=" * 45)

    async def run_followup_async(self):
        """الحلقة الكاملة لعملية Follow-up"""
        try:
            await self.initialize()
            await self.check_accepted_requests()
        except Exception as e:
            logger.error(f"❌ Follow-up خطأ: {e}\n{traceback.format_exc()}")
        finally:
            await self._close_browser_with_timeout()
            if self.on_finish:
                self.on_finish()

    def run_followup_in_thread(self):
        """تشغيل Follow-up في Thread مستقل"""
        self._setup_queue_logging()
        try:
            print("[BOT] Follow-up thread started", flush=True)
            self.log_queue.put_nowait("🔔 بدء نظام متابعة الحسابات المقبولة...")
            asyncio.run(self.run_followup_async())
            print("[BOT] Follow-up thread finished.", flush=True)
        except Exception as e:
            err = f"❌ خطأ في Follow-up: {e}\n{traceback.format_exc()}"
            self.log_queue.put_nowait(err)
            print(err, flush=True)

    # ─────────────────────────────────────────────────────────────
    #  الحلقة الرئيسية
    # ─────────────────────────────────────────────────────────────

    async def _close_browser_with_timeout(self):
        try:
            await asyncio.wait_for(self.session_manager.close(), timeout=8.0)
            logger.info("✅ تم إغلاق المتصفح")
        except asyncio.TimeoutError:
            print("[BOT] Browser close timed out - forcing shutdown", flush=True)
        except Exception as e:
            print(f"[BOT] Error closing browser: {e}", flush=True)

    async def run_async(self):
        try:
            await self.initialize()

            # ── Turbo Mode مع عملاء محددين مسبقاً ──
            if self.turbo_mode and self.pre_selected_leads:
                await self.run_selected_leads_turbo()

            # ── وضع السحب فقط أو الوضع العادي ──
            elif self.target_posts:
                for i, post_url in enumerate(self.target_posts, 1):
                    if self._is_stopped():
                        break
                    await self.process_post(post_url, i, len(self.target_posts))
                    if i < len(self.target_posts) and not self._is_stopped():
                        if self.scrape_only:
                            await asyncio.sleep(2)
                        else:
                            logger.info("⏳ انتظار قبل المنشور التالي (30-60 ث)...")
                            await random_delay(30, 60)

                if self.scrape_only:
                    logger.info("🔍 اكتمل السحب! راجع التعليقات في واجهة الاختيار.")
                    self.log_queue.put_nowait("SCRAPE_DONE")
                elif not self._is_stopped():
                    logger.info("=" * 45)
                    logger.info("✅ اكتملت جميع العمليات!")
                    logger.info(f"📊 رسائل: {self.daily_dm_count} | متابعات: {self.daily_follow_count}")
                    logger.info("=" * 45)

            if self._is_stopped():
                logger.info("🛑 تم إيقاف البوت")

        except RuntimeError as e:
            logger.critical(f"❌ خطأ حرج: {e}\n{traceback.format_exc()}")
        except Exception as e:
            logger.error(f"❌ خطأ غير متوقع: {e}\n{traceback.format_exc()}")
            if self.session_manager.page:
                try:
                    await take_error_screenshot(self.session_manager.page, "critical_error")
                except Exception:
                    pass
        finally:
            await self._close_browser_with_timeout()
            if self.on_finish:
                self.on_finish()

    def run_in_thread(self):
        self._setup_queue_logging()
        try:
            print("[BOT] Thread started", flush=True)
            self.log_queue.put_nowait("⚙️ Thread البوت بدأ...")
            asyncio.run(self.run_async())
            print("[BOT] Thread finished.", flush=True)
        except Exception as e:
            err = f"❌ خطأ في run_in_thread: {e}\n{traceback.format_exc()}"
            self.log_queue.put_nowait(err)
            print(err, flush=True)
