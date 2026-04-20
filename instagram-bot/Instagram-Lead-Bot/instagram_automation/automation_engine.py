"""
وحدة محرك الأتمتة (Automation Engine)
تحتوي على منطق المتابعة وإرسال الرسائل والرد على التعليقات
تدعم الحسابات العامة والخاصة
"""

import asyncio
import logging
import random

from playwright.async_api import Page
from config import (
    MESSAGE_TEMPLATES,
    COMMENT_REPLY_TEXT,
    DELAY_MIN_MESSAGE,
    DELAY_MAX_MESSAGE,
    COMPETITOR_KEYWORDS,
    MOBILE_EMULATION,
)
from utils import (
    random_delay,
    get_random_message,
    human_like_click,
    human_like_mouse_move,
    take_error_screenshot,
)

logger = logging.getLogger(__name__)

BUTTON_TIMEOUT_MS = 1000  # ثانية واحدة فقط - Turbo Mode


class AutomationEngine:
    """
    محرك الأتمتة - يتولى المتابعة والرسائل والردود
    يدعم الحسابات العامة والخاصة مع إمكانية الرد التلقائي على الخاصة
    """

    def __init__(self, page: Page):
        self.page = page
        self.message_templates = MESSAGE_TEMPLATES
        self.comment_reply_text = COMMENT_REPLY_TEXT
        self.private_auto_reply = False
        self.private_reply_text = "تم إرسال التفاصيل، يرجى مراجعة طلبات المراسلة ✅"

    # ─────────────────────────────────────────────────────────────
    #  معالج النوافذ المنبثقة (Pop-up Handler)
    # ─────────────────────────────────────────────────────────────

    async def handle_popups(self, max_rounds: int = 5) -> int:
        """
        يبحث عن أي نوافذ منبثقة (Save Login Info / Turn on Notifications / ...)
        ويغلقها تلقائياً بالضغط على 'Not Now' / 'ليس الآن' / 'Skip' أو أي زر إغلاق.
        يعيد عدد النوافذ المغلقة.
        يُستدعى بعد تسجيل الدخول مباشرةً وقبل الانتقال لأي رابط.
        """
        popup_button_texts = [
            "Not Now", "Not now", "not now",
            "ليس الآن", "ليس الآن",
            "Skip", "تخطي", "تجاوز",
            "Cancel", "إلغاء",
            "Dismiss", "رفض",
            "Close", "إغلاق",
            "Allow", "Don't Allow",
            "Later", "لاحقاً",
        ]

        # Selectors بالنص مباشرةً
        text_selectors = (
            [f'button:has-text("{t}")' for t in popup_button_texts] +
            [f'[role="button"]:has-text("{t}")' for t in popup_button_texts] +
            [f'span[role="button"]:has-text("{t}")' for t in popup_button_texts]
        )

        # Selectors بالـ aria-label
        aria_selectors = [
            'button[aria-label*="Close"]',
            'button[aria-label*="إغلاق"]',
            'button[aria-label*="Dismiss"]',
            '[role="button"][aria-label*="Close"]',
            '[role="button"][aria-label*="إغلاق"]',
        ]

        all_selectors = text_selectors + aria_selectors
        total_closed = 0

        for _round in range(max_rounds):
            closed_this_round = 0
            for selector in all_selectors:
                try:
                    btn = await self.page.query_selector(selector)
                    if btn and await btn.is_visible():
                        logger.info(f"[🔔] نافذة منبثقة مكتشفة → إغلاق: «{selector}»")
                        if MOBILE_EMULATION:
                            await btn.tap()
                        else:
                            await btn.click()
                        await asyncio.sleep(1.2)
                        closed_this_round += 1
                        total_closed += 1
                        break
                except Exception:
                    continue

            if closed_this_round == 0:
                break  # لا توجد نوافذ جديدة

        if total_closed > 0:
            logger.info(f"[✅] تم إغلاق {total_closed} نافذة منبثقة بنجاح")
        else:
            logger.info("[✅] لا توجد نوافذ منبثقة")

        return total_closed

    # ─────────────────────────────────────────────────────────────
    #  فحص نوع الحساب
    # ─────────────────────────────────────────────────────────────

    async def _check_if_private(self) -> bool:
        """
        كشف الحساب الخاص - سريع ودقيق:
        ① نص مرئي صريح في الـ body فقط (لا HTML كاملة — تحتوي JSON لمستخدمين آخرين)
        ② انتظار حتى 5 ث لظهور أزرار البروفايل، ثم:
           - إذا ظهر 'مراسلة/Message' → عام
           - إذا ظهر 'متابعة/Follow' بدون 'مراسلة' → خاص
        في حالة الشك → عام (الأكثر أماناً)
        ⚠️ تجنب html.includes('"is_private":true') — JSON الصفحة يحتوي بيانات مستخدمين آخرين!
        """
        try:
            # ① نص مرئي صريح في الـ body فقط (آمن)
            is_priv_text = await self.page.evaluate("""
                () => {
                    const body = document.body?.innerText || '';
                    return body.includes('هذا الحساب خاص') ||
                           body.includes('This Account is Private');
                }
            """)
            if is_priv_text:
                return True

            # ② انتظار أزرار البروفايل — حتى 5 ثوانٍ
            # نحاول كل 0.5 ث حتى يظهر 'مراسلة' أو 'Follow'
            for _ in range(10):
                await asyncio.sleep(0.5)
                result = await self.page.evaluate("""
                    () => {
                        // البحث فقط في منطقة البروفايل (header/section) لتجنب أزرار القائمة العلوية
                        const searchRoot =
                            document.querySelector('header') ||
                            document.querySelector('main') ||
                            document.body;
                        const allEls = Array.from(searchRoot.querySelectorAll(
                            'button, [role="button"], a[role="button"]'
                        ));
                        const texts = allEls.map(el => (el.innerText || '').trim());

                        // هل زرار مراسلة/Message موجود؟
                        const hasMessage = texts.some(t =>
                            t === 'مراسلة' || t === 'Message' ||
                            t === 'رسالة'  || t === 'Send message' ||
                            t === 'إرسال رسالة' || t === 'Chat'
                        );
                        // هل زرار متابعة/Follow موجود؟
                        const hasFollow = texts.some(t =>
                            t === 'متابعة' || t === 'Follow'
                        );

                        if (hasMessage) return 'public';
                        if (hasFollow)  return 'has_follow_no_message';
                        return 'loading';
                    }
                """)

                if result == 'public':
                    return False
                if result == 'has_follow_no_message':
                    # تحقق إضافي من نص الـ body قبل الحكم بأنه خاص
                    body_text = await self.page.evaluate("() => document.body?.innerText || ''")
                    if 'هذا الحساب خاص' in body_text or 'This Account is Private' in body_text:
                        return True
                    # Follow بدون Message → على الأرجح خاص، انتظر مرة أخرى قبل الحكم
                    # سنكمل الـ loop للتأكد
                    continue

            # بعد 5 ثوانٍ: فحص أخير نهائي
            final = await self.page.evaluate("""
                () => {
                    const body = document.body?.innerText || '';
                    if (body.includes('هذا الحساب خاص') ||
                        body.includes('This Account is Private')) return 'private';
                    const allEls = Array.from(document.querySelectorAll(
                        'button, [role="button"]'
                    ));
                    const texts = allEls.map(el => (el.innerText || '').trim());
                    const hasMessage = texts.some(t =>
                        t === 'مراسلة' || t === 'Message' || t === 'رسالة' ||
                        t === 'Send message' || t === 'إرسال رسالة' || t === 'Chat'
                    );
                    const hasFollow = texts.some(t => t === 'متابعة' || t === 'Follow');
                    if (hasMessage) return 'public';
                    if (hasFollow)  return 'private';
                    return 'unknown';
                }
            """)
            if final == 'private':
                return True
            # unknown أو public → افترض عام
            return False
        except Exception:
            return False

    async def check_bio_for_competitor(self) -> bool:
        """
        يفحص البيو في الصفحة الحالية للكشف عن منافسين.
        يُستدعى بعد فتح البروفايل مباشرةً - لا يضيف وقتاً إضافياً.
        """
        import config as cfg
        if not cfg.COMPETITOR_FILTER:
            return False
        try:
            bio_text = await self.page.evaluate("""
                () => {
                    const selectors = [
                        'span[class*="biography"]',
                        'div[class*="-vDIg"] span',
                        'section main header section div span',
                        'header section div:last-child span',
                        'div.-vDIg span',
                    ];
                    for (const sel of selectors) {
                        const el = document.querySelector(sel);
                        if (el && el.innerText.trim()) return el.innerText.trim();
                    }
                    const bodyText = document.body?.innerText || '';
                    const match = bodyText.match(/"biography":"([^"]{0,300})"/);
                    return match ? match[1] : '';
                }
            """)
            if not bio_text:
                return False
            bio_lower = bio_text.lower()
            for kw in cfg.COMPETITOR_KEYWORDS:
                if kw.lower() in bio_lower:
                    logger.info(f"[🚫] بيو يحتوي كلمة منافس: '{kw}' → تخطي")
                    return True
            return False
        except Exception as e:
            logger.debug(f"فحص البيو: {e}")
            return False

    async def check_if_following(self, username: str) -> bool:
        """
        يفحص إذا كان الحساب قبل طلب المتابعة (Following).
        يُستدعى بعد زيارة البروفايل.
        """
        try:
            result = await self.page.evaluate("""
                () => {
                    const body = document.body?.innerText || document.documentElement?.innerHTML || '';
                    const indicators = [
                        '"friendship_status":{"following":true',
                        '"followed_by_viewer":true',
                    ];
                    if (indicators.some(k => body.includes(k))) return true;

                    const btns = Array.from(document.querySelectorAll('button, [role="button"]'));
                    return btns.some(b => {
                        const t = (b.innerText || '').trim().toLowerCase();
                        return t === 'following' || t === 'يتابع' || t === 'متابَع';
                    });
                }
            """)
            return bool(result)
        except Exception:
            return False

    async def _find_visible_locator(self, selectors: list[str], timeout: int = BUTTON_TIMEOUT_MS):
        for selector in selectors:
            try:
                locator = self.page.locator(selector).first
                await locator.wait_for(state="visible", timeout=timeout)
                return locator
            except Exception:
                continue
        return None

    async def _click_follow_button(self, username: str) -> bool:
        """الضغط على زر المتابعة بطريقة بشرية"""
        follow_selectors = [
            "xpath=//button[contains(normalize-space(.), 'Follow') and not(contains(normalize-space(.), 'Following')) and not(contains(normalize-space(.), 'Unfollow'))]",
            "xpath=//button[contains(normalize-space(.), 'متابعة')]",
            "xpath=//*[@role='button' and contains(normalize-space(.), 'Follow') and not(contains(normalize-space(.), 'Following')) and not(contains(normalize-space(.), 'Unfollow'))]",
            "xpath=//*[@role='button' and contains(normalize-space(.), 'متابعة')]",
            'button[aria-label*="Follow"]',
            'button[aria-label*="متابعة"]',
            '[role="button"][aria-label*="Follow"]',
            '[role="button"][aria-label*="متابعة"]',
        ]
        button = await self._find_visible_locator(follow_selectors)
        if not button:
            return False

        try:
            text = (await button.inner_text(timeout=BUTTON_TIMEOUT_MS)).strip().lower()
        except Exception:
            text = ""

        if "following" in text or "unfollow" in text or "يتابع" in text:
            logger.info(f"@{username} متابَع بالفعل")
            return False

        await human_like_mouse_move(
            self.page,
            400 + (hash(username) % 100),
            300 + (hash(username) % 50),
        )
        await random_delay(0.3, 0.8)
        if MOBILE_EMULATION:
            await button.tap(timeout=BUTTON_TIMEOUT_MS)
        else:
            await button.click(timeout=BUTTON_TIMEOUT_MS)
        await random_delay(0.8, 1.5)
        return True

    # ─────────────────────────────────────────────────────────────
    #  زيارة البروفايل والمتابعة
    # ─────────────────────────────────────────────────────────────

    async def visit_and_follow_profile(self, username: str) -> dict:
        """زيارة بروفايل المستخدم والمتابعة - Turbo Mode
        يشمل فحص البيو للمنافسين بدون وقت إضافي.
        """
        result = {"followed": False, "account_type": "unknown", "is_competitor": False}
        try:
            profile_url = f"https://www.instagram.com/{username}/"
            await self.page.goto(profile_url, wait_until="domcontentloaded", timeout=15000)
            await random_delay(1.0, 1.8)

            is_competitor = await self.check_bio_for_competitor()
            if is_competitor:
                logger.info(f"[🚫] تخطي @{username} - منافس (كلمة محظورة في البيو)")
                result["is_competitor"] = True
                return result

            is_private = await self._check_if_private()
            result["account_type"] = "private" if is_private else "public"

            followed = await self._click_follow_button(username)
            result["followed"] = followed

            if followed:
                if is_private:
                    logger.info(f"[🔒] متابعة (خاص): @{username}")
                else:
                    logger.info(f"[👤] متابعة: @{username}")

        except Exception as e:
            logger.error(f"❌ زيارة @{username}: {e}")

        return result

    # ─────────────────────────────────────────────────────────────
    #  إرسال رسالة DM
    # ─────────────────────────────────────────────────────────────

    async def send_direct_message(self, username: str, user_id: str = None, is_private: bool = False) -> bool:
        """إرسال DM - Turbo Mode مع Turbo Recovery تلقائي عند Timeout"""

        async def _send_impl():
            opened = False

            # ── ① محاولة زر Message على صفحة البروفايل الحالية (Mobile + Desktop) ──
            current_url = self.page.url
            on_profile_page = f"instagram.com/{username}" in current_url

            if on_profile_page or MOBILE_EMULATION:
                opened = await self._try_profile_message_button(username, is_private=is_private)

            # ── ② Fallback ①: Direct Link بالـ username (Magic Solution للحسابات العامة) ──
            if not opened:
                logger.info(f"[🚀] Direct Link Fallback (username): instagram.com/direct/t/{username}/")
                try:
                    await self.page.goto(
                        f"https://www.instagram.com/direct/t/{username}/",
                        wait_until="domcontentloaded",
                        timeout=15000,
                    )
                    await random_delay(2, 4)
                    opened = True
                except Exception as e:
                    logger.debug(f"Direct Link Fallback فشل: {e}")

            # ── ③ Fallback ②: user_id أو Direct New ──
            if not opened:
                if user_id:
                    direct_url = f"https://www.instagram.com/direct/t/{user_id}/"
                    await self.page.goto(direct_url, wait_until="domcontentloaded", timeout=15000)
                    await random_delay(2, 4)
                    opened = True
                else:
                    opened = await self._open_direct_by_username(username)

            if not opened:
                logger.info(f"[⏭] تخطي @{username} - تعذر فتح المحادثة")
                return False

            # ── ③ Message Request Screen: زرار "إرسال رسالة" الأزرق أحياناً يظهر قبل الصندوق ──
            msg_request_selectors = [
                'button:has-text("إرسال رسالة")',
                'button:has-text("Send Message")',
                'button:has-text("Message")',
                '[role="button"]:has-text("إرسال رسالة")',
                '[role="button"]:has-text("Send Message")',
                # زرار أزرق في أسفل الشاشة (Message Request)
                'div[style*="background"] button',
                'button[style*="background-color"]',
            ]
            for mr_sel in msg_request_selectors:
                try:
                    mr_btn = self.page.locator(mr_sel).first
                    await mr_btn.wait_for(state="visible", timeout=2000)
                    logger.info(f"[📩] Message Request زرار موجود → ضغط لفتح الصندوق لـ @{username}")
                    if MOBILE_EMULATION:
                        await mr_btn.tap(timeout=BUTTON_TIMEOUT_MS)
                    else:
                        await mr_btn.click(force=True, timeout=BUTTON_TIMEOUT_MS)
                    await asyncio.sleep(1.5)
                    break
                except Exception:
                    continue

            # ── ④ انتظار صندوق الرسائل — Arabic + English selectors ──
            textbox_selector = (
                'div[role="textbox"], '
                'textarea[placeholder*="رسالة"], '
                'textarea[placeholder*="Message"], '
                'div[aria-label*="رسالة"], '
                'div[aria-label*="Message"], '
                'div[contenteditable="true"], '
                'p[aria-placeholder]'
            )
            try:
                await self.page.wait_for_selector(textbox_selector, timeout=6000)
            except Exception:
                # لو ملاقيش صندوق، صور وارجع False
                logger.warning(f"[⚠️] صندوق الرسائل لم يظهر في الـ Direct لـ @{username}")
                await take_error_screenshot(self.page, f"debug_direct_stuck_{username[:12]}")
                return False

            # ── ⑤ إرسال الرسالة ──
            message_text = get_random_message(self.message_templates)
            sent = await self._fast_fill_and_send(message_text, username)
            if not sent:
                logger.warning(f"[⚠️] فشل إرسال الرسالة لـ @{username}")
                await take_error_screenshot(self.page, f"debug_direct_stuck_{username[:12]}")
                return False

            await random_delay(2, 5)
            logger.info(f"📨 رسالة لـ @{username} | الحالة: ناجح")
            return True

        try:
            # ── Turbo Recovery: تخطي تلقائي إذا تجاوز 65 ثانية ──
            # الحسابات الخاصة تحتاج: 3-Dots (~5s) + Menu (~3s) + Direct (~8s) + Fill+Send (~12s) = ~45s
            return await asyncio.wait_for(_send_impl(), timeout=65.0)
        except asyncio.TimeoutError:
            logger.warning(f"[⏭] Turbo Recovery: تجاوز وقت @{username} → التالي فوراً")
            return False
        except Exception as e:
            logger.error(f"❌ DM @{username}: {str(e)[:60]}")
            return False

    # ─────────────────────────────────────────────────────────────
    #  إغلاق Follow Suggestions / أي Overlay يحجب زر المراسلة
    # ─────────────────────────────────────────────────────────────

    async def _dismiss_suggestions_overlay(self, username: str) -> bool:
        """
        يكتشف ويغلق أي نافذة "اقتراحات للمتابعة" أو overlay يحجب زر المراسلة.
        يُستدعى قبل محاولة أي ضغط على Message / 3-Dots.
        يعود True لو أغلق شيئاً.
        """
        dismissed = False
        try:
            # ── ① الطريقة السريعة: هل في overlay واضح يحتوي نص "اقتراحات"/"Suggestions" ──
            has_suggestions = await self.page.evaluate("""
                () => {
                    const texts = ['اقتراحات', 'Suggestions', 'Suggested', 'مقترح',
                                   'Follow suggestions', 'اقتراحات للمتابعة'];
                    const els = Array.from(document.querySelectorAll(
                        '[role="dialog"], [role="sheet"], [role="presentation"], ' +
                        'div[class*="bottom"], div[class*="modal"], div[class*="overlay"]'
                    ));
                    for (const el of els) {
                        const txt = (el.innerText || '').substring(0, 200);
                        if (texts.some(t => txt.includes(t))) return true;
                    }
                    // تحقق أيضاً من وجود أكثر من 3 أزرار متابعة متجاورة (علامة suggestions)
                    const followBtns = Array.from(document.querySelectorAll(
                        'button, [role="button"]'
                    )).filter(b => {
                        const t = (b.innerText || '').trim();
                        return t === 'متابعة' || t === 'Follow';
                    });
                    return followBtns.length >= 3;
                }
            """)

            if not has_suggestions:
                return False

            logger.info(f"[🚫] اكتشف overlay اقتراحات متابعة لـ @{username} — جاري الإغلاق...")

            # ── ② جرب زر الإغلاق الصريح ──
            close_texts  = ["إغلاق", "Close", "Not Now", "ليس الآن", "تخطي", "Skip", "×", "✕"]
            close_labels = ["إغلاق", "Close", "Dismiss"]
            close_sels = (
                [f'button:has-text("{t}")' for t in close_texts] +
                [f'[role="button"]:has-text("{t}")' for t in close_texts] +
                [f'button[aria-label="{l}"]' for l in close_labels] +
                [f'[role="button"][aria-label="{l}"]' for l in close_labels] +
                ['button[aria-label*="Close"]', 'button[aria-label*="إغلاق"]',
                 '[data-testid="close-button"]']
            )
            for sel in close_sels:
                try:
                    btn = await self.page.query_selector(sel)
                    if btn and await btn.is_visible():
                        if MOBILE_EMULATION:
                            await btn.tap()
                        else:
                            await btn.click()
                        await asyncio.sleep(1.0)
                        dismissed = True
                        logger.info(f"[✅] أُغلق overlay الاقتراحات بزر: «{sel}»")
                        break
                except Exception:
                    continue

            # ── ③ لو الزر مش موجود: Escape ──
            if not dismissed:
                await self.page.keyboard.press("Escape")
                await asyncio.sleep(0.8)
                dismissed = True
                logger.info(f"[✅] أُغلق overlay الاقتراحات بـ Escape لـ @{username}")

            # ── ④ لو لسه موجود: JavaScript إغلاق قسري ──
            still_there = await self.page.evaluate("""
                () => {
                    const texts = ['اقتراحات', 'Suggestions', 'Suggested'];
                    const els = Array.from(document.querySelectorAll(
                        '[role="dialog"], [role="sheet"], [role="presentation"]'
                    ));
                    return els.some(el => texts.some(t => (el.innerText||'').includes(t)));
                }
            """)
            if still_there:
                # scroll الصفحة لأعلى لإخفاء الـ sheet
                await self.page.evaluate("window.scrollTo(0, 0)")
                await asyncio.sleep(0.5)
                logger.info(f"[🔄] Scroll لأعلى لإخفاء overlay الاقتراحات لـ @{username}")

        except Exception as e:
            logger.debug(f"_dismiss_suggestions_overlay @{username}: {e}")

        return dismissed

    # ─────────────────────────────────────────────────────────────
    #  زر Message على البروفايل + 3-Dots للحسابات الخاصة
    # ─────────────────────────────────────────────────────────────

    async def _try_profile_message_button(self, username: str, is_private: bool = False) -> bool:
        """
        يحاول فتح DM عبر زر Message على صفحة البروفايل.
        ① Wait for Spinner to disappear (لا تبدأ وإنت في loading)
        ② Smart Wait: انتظر ظهور 'مراسلة' بدل وقت ثابت (تُتخطى للحسابات الخاصة)
        ③ get_by_text + CSS selectors بالأولوية العربية
        ④ Fallback: 3-Dots الدقيق بـ aria-label="خيارات"
        """
        try:
            # ── Immediate 3-Dots for Private: للحساب الخاص اذهب مباشرة للـ 3 نقط ──
            if is_private:
                logger.info(f"[🔒] حساب خاص → 3-Dots مباشرة بدون انتظار 'مراسلة' لـ @{username}")
                return await self._try_three_dots_message(username)

            # ── ① Wait for Loading Spinner to Disappear ──
            # بعد Follow، Instagram بيحط spinner جوه الزرار — انتظر يختفي
            try:
                # انتظر أي spinner نشط يختفي (حد أقصى 8 ث)
                await self.page.wait_for_function(
                    """() => {
                        const btns = document.querySelectorAll('button, [role="button"]');
                        for (const b of btns) {
                            const style = window.getComputedStyle(b);
                            // زرار بيحتوي على spinner (aria-busy أو دوران CSS)
                            if (b.getAttribute('aria-busy') === 'true') return false;
                        }
                        // تأكد إن مفيش عنصر بيدور حالياً
                        const spinners = document.querySelectorAll(
                            '[class*="spin"], [class*="loading"], [class*="progress"]'
                        );
                        return spinners.length === 0;
                    }""",
                    timeout=8000,
                )
                logger.info(f"[⏳] Spinner اختفى — الصفحة جاهزة لـ @{username}")
            except Exception:
                # لو فشل الـ wait، اصبر 2 ث على الأقل
                await asyncio.sleep(2.0)

            # ── ② إغلاق أي overlay اقتراحات متابعة قبل البحث عن المراسلة ──
            await self._dismiss_suggestions_overlay(username)

            # ── ③ Smart Wait: انتظر ظهور 'مراسلة' بعد انتهاء الـ Follow transition ──
            msg_appeared = False
            try:
                await self.page.wait_for_selector(
                    'text="مراسلة"',
                    timeout=10000,
                    state="visible",
                )
                logger.info(f"[✅] 'مراسلة' ظهر على البروفايل → @{username}")
                msg_appeared = True
            except Exception:
                # جرب مرة ثانية لإغلاق الـ overlay لو ظهر بعد الانتظار
                dismissed_retry = await self._dismiss_suggestions_overlay(username)
                if dismissed_retry:
                    logger.info(f"[🔄] أُغلق overlay ثانية — إعادة بحث 'مراسلة' لـ @{username}")
                    try:
                        await self.page.wait_for_selector(
                            'text="مراسلة"',
                            timeout=5000,
                            state="visible",
                        )
                        msg_appeared = True
                    except Exception:
                        pass
                if not msg_appeared:
                    logger.info(f"[🔵] 'مراسلة' لم يظهر في 10 ث → جرب selectors عامة لـ @{username}")

            # صورة بعد الانتظار لو مظهرتش
            if not msg_appeared:
                await take_error_screenshot(self.page, f"debug_after_wait_{username[:12]}")

            # ── helpers ──
            async def _tap_or_click_btn(loc):
                try:
                    await loc.scroll_into_view_if_needed(timeout=2000)
                except Exception:
                    pass
                if MOBILE_EMULATION:
                    await loc.tap(timeout=BUTTON_TIMEOUT_MS)
                else:
                    await loc.click(timeout=BUTTON_TIMEOUT_MS)

            async def _check_redirect_after_msg(label: str) -> bool:
                logger.info(f"[💬] زر '{label}' ضُغط → @{username}")
                await asyncio.sleep(2.0)
                cur = self.page.url
                if "direct/t/" in cur or "direct/inbox" in cur:
                    logger.info(f"[✅] Direct Redirect مؤكد → @{username}")
                return True

            # ── ③ Message Button Selectors — 'مراسلة' أولوية قصوى ──
            text_locators = [
                ("مراسلة",      self.page.get_by_text("مراسلة",      exact=True)),
                ("Message",     self.page.get_by_text("Message",     exact=True)),
                ("إرسال رسالة", self.page.get_by_text("إرسال رسالة", exact=True)),
                ("رسالة",       self.page.get_by_text("رسالة",       exact=True)),
                ("Message~",    self.page.get_by_text("Message",     exact=False)),
            ]
            for label, loc in text_locators:
                try:
                    await loc.first.wait_for(state="visible", timeout=2000)
                    await _tap_or_click_btn(loc.first)
                    return await _check_redirect_after_msg(label)
                except Exception:
                    continue

            # CSS selectors — 'مراسلة' أولاً
            message_selectors = [
                'button:has-text("مراسلة")',
                'a[role="button"]:has-text("مراسلة")',
                '[role="button"]:has-text("مراسلة")',
                'button[aria-label="مراسلة"]',
                'button[aria-label="Message"]',
                'button[aria-label="رسالة"]',
                '[role="button"][aria-label="Message"]',
                'button:has-text("Message")',
                'button:has-text("إرسال رسالة")',
                '[role="button"]:has-text("Message")',
                '[role="button"]:has-text("إرسال رسالة")',
                'a[href*="/direct/t/"]',
            ]
            for selector in message_selectors:
                try:
                    btn = self.page.locator(selector).first
                    await btn.wait_for(state="visible", timeout=2000)
                    await _tap_or_click_btn(btn)
                    return await _check_redirect_after_msg(selector)
                except Exception:
                    continue

            # ── ④ Fallback: 3-Dots الدقيق ──
            logger.info(f"[🔵] 'مراسلة' مش موجود → 3-Dots لـ @{username}")
            return await self._try_three_dots_message(username)

        except Exception as e:
            logger.debug(f"_try_profile_message_button @{username}: {e}")
            return False

    async def _try_three_dots_message(self, username: str) -> bool:
        """
        3-Dots Fallback — Precise Mobile Fix:
        ① Precise selector: button._a6hd + header SVG right-side + aria-label variants
        ② Wait for Menu Sheet: 1.5 ث بعد الضغط
        ③ text= locators للبحث عن 'Send message' / 'إرسال رسالة'
        ④ Wait for Direct: يتحقق من URL direct/t/ قبل الإعلان عن النجاح
        ⑤ Debug Capture: لقطة شاشة لو القائمة ظهرت بدون خيار الرسالة
        """
        async def _direct_link_fallback() -> bool:
            """الحل الأخير المضمون: فتح Direct Link مباشرة"""
            logger.info(f"[🚀] Direct Link Mandatory Fallback → /direct/t/{username}/")
            await take_error_screenshot(self.page, f"debug_direct_fallback_{username[:12]}")
            try:
                await self.page.goto(
                    f"https://www.instagram.com/direct/t/{username}/",
                    wait_until="domcontentloaded",
                    timeout=15000,
                )
                await asyncio.sleep(2.0)
                return True
            except Exception:
                return False

        async def _menu_has_message() -> bool:
            """تحقق أن القائمة المفتوحة فيها 'رسالة/مراسلة' وليس فقط حظر/إبلاغ"""
            try:
                result = await self.page.evaluate("""
                    () => {
                        const containers = document.querySelectorAll(
                            '[role="dialog"], [role="sheet"], [role="menu"], [role="listbox"]'
                        );
                        for (const c of containers) {
                            const txt = c.innerText || '';
                            if (txt.includes('مراسلة') || txt.includes('إرسال رسالة') ||
                                txt.includes('Message') || txt.includes('Send message')) {
                                return true;
                            }
                        }
                        return false;
                    }
                """)
                return bool(result)
            except Exception:
                return False

        async def _close_open_menu():
            """إغلاق القائمة المفتوحة بالضغط على Escape"""
            try:
                await self.page.keyboard.press("Escape")
                await asyncio.sleep(0.5)
            except Exception:
                pass

        try:
            # ── ⓪ إغلاق أي overlay اقتراحات قبل البحث على الـ 3-Dots ──
            await self._dismiss_suggestions_overlay(username)

            # ── ① JS SCAN: بدون اعتماد على <header> — Instagram بيستخدم div مخصصة ──
            dots_btn = None
            try:
                scan_result = await self.page.evaluate("""
                    () => {
                        // ── أ) SVG بـ aria-label ──
                        const svgLabels = ['خيارات', 'More options', 'More Options', 'Options'];
                        for (const label of svgLabels) {
                            const svg = document.querySelector(`svg[aria-label="${label}"]`);
                            if (svg) {
                                const r = svg.getBoundingClientRect();
                                if (r.top >= 0 && r.top < 250) {
                                    return {found: true, method: 'svg-aria-' + label,
                                            cx: Math.round(r.left + r.width/2),
                                            cy: Math.round(r.top + r.height/2)};
                                }
                            }
                        }

                        // ── ب) DIV صغير + SVG + بدون innerText (بس! مش textContent) ──
                        // البيانات الحقيقية: DIV pos~(57-98, 78) size=34x32 svg=True text=''
                        const allDivs = Array.from(document.querySelectorAll('div'));
                        const matches = allDivs.filter(d => {
                            const r = d.getBoundingClientRect();
                            if (r.width < 5 || r.width > 55 || r.height < 5 || r.height > 55)
                                return false;
                            const cx = r.left + r.width / 2;
                            const cy = r.top + r.height / 2;
                            if (cx < 20 || cx > 250 || cy < 40 || cy > 125) return false;
                            // innerText فقط (مش textContent) — textContent بياخد نص SVG الداخلي
                            const txt = (d.innerText || '').trim();
                            if (txt.length > 5) return false;
                            return !!d.querySelector('svg');
                        });

                        if (matches.length > 0) {
                            // الأصغر x = الأقرب لليسار = الـ 3-Dots في RTL
                            matches.sort((a, b) =>
                                a.getBoundingClientRect().left - b.getBoundingClientRect().left
                            );
                            const btn = matches[0];
                            const r = btn.getBoundingClientRect();
                            return {found: true, method: 'small-div-svg',
                                    cx: Math.round(r.left + r.width/2),
                                    cy: Math.round(r.top + r.height/2)};
                        }

                        // ── ج) Debug dump ──
                        const allElems = Array.from(
                            document.querySelectorAll('button, [role="button"], a, div, span')
                        );
                        const debug = allElems.map(b => {
                            const r = b.getBoundingClientRect();
                            return {
                                tag: b.tagName,
                                aria: b.getAttribute('aria-label'),
                                text: (b.innerText || '').trim().substring(0, 15),
                                x: Math.round(r.left), y: Math.round(r.top),
                                w: Math.round(r.width), h: Math.round(r.height),
                                svg: !!b.querySelector('svg')
                            };
                        }).filter(d => d.y >= 0 && d.y < 300 && d.w > 0 && d.w <= 55 && d.h <= 55);
                        return {found: false, debug};
                    }
                """)

                if isinstance(scan_result, dict):
                    if scan_result.get("found"):
                        js_cx = scan_result.get("cx", 0)
                        js_cy = scan_result.get("cy", 0)
                        logger.info(
                            f"[✅] JS وجد الـ 3-Dots: {scan_result.get('method')} "
                            f"| إحداثيات=({js_cx},{js_cy}) لـ @{username}"
                        )
                        # ── ضغط مباشر بالإحداثيات — بدون Playwright locator ──
                        await self.page.mouse.click(js_cx, js_cy, delay=100)
                        await asyncio.sleep(1.5)
                        try:
                            await self.page.wait_for_selector(
                                '[role="dialog"], [role="sheet"], [role="menu"], [role="listbox"]',
                                timeout=2000
                            )
                            if await _menu_has_message():
                                logger.info(f"[✅] JS click → قائمة + رسالة لـ @{username}")
                                # استخدم JS لاختيار عنصر الرسالة مباشرةً من القائمة
                                clicked = await self.page.evaluate("""
                                    () => {
                                        const labels = [
                                            'مراسلة', 'إرسال رسالة', 'Message',
                                            'Send message', 'Send Message'
                                        ];
                                        const containers = document.querySelectorAll(
                                            '[role="dialog"], [role="sheet"], [role="menu"], [role="listbox"]'
                                        );
                                        for (const c of containers) {
                                            const items = Array.from(c.querySelectorAll(
                                                'button, [role="menuitem"], [role="button"], div, span, li'
                                            ));
                                            for (const item of items) {
                                                const txt = (item.innerText || '').trim();
                                                if (labels.includes(txt)) {
                                                    item.click();
                                                    return txt;
                                                }
                                            }
                                        }
                                        return null;
                                    }
                                """)
                                if clicked:
                                    logger.info(f"[💬] JS قائمة: ضُغط على '{clicked}' لـ @{username}")
                                    await asyncio.sleep(1.5)
                                    # تحقق من نجاح الانتقال
                                    for _ in range(6):
                                        await asyncio.sleep(0.8)
                                        cur = self.page.url
                                        if "direct/t/" in cur or "direct/inbox" in cur:
                                            logger.info(f"[✅] JS → Direct لـ @{username}")
                                            return True
                                        try:
                                            tb = await self.page.query_selector(
                                                'div[role="textbox"], p[aria-placeholder], textarea'
                                            )
                                            if tb and await tb.is_visible():
                                                logger.info(f"[✅] JS → Chat Ready لـ @{username}")
                                                return True
                                        except Exception:
                                            pass
                                    logger.warning(f"[⚠️] JS click: لا redirect بعد '{clicked}' لـ @{username}")
                                    return False
                                else:
                                    logger.warning(f"[⚠️] JS: القائمة مفتوحة لكن 'إرسال رسالة' مش موجود لـ @{username}")
                                    await _close_open_menu()
                            else:
                                logger.warning(f"[⚠️] JS click: قائمة بدون رسالة لـ @{username}")
                                await _close_open_menu()
                        except Exception:
                            logger.warning(f"[⚠️] JS click: القائمة ما انفتحتش لـ @{username}")
                        # لو JS click فشل → استمر للـ CSS selectors والإحداثيات
                    else:
                        # سجّل كل الأزرار للـ debugging
                        debug_btns = scan_result.get("debug", [])
                        logger.warning(
                            f"[🔍] JS DEBUG — كل الأزرار في أول 300px لـ @{username}:"
                        )
                        for d in debug_btns:
                            logger.warning(
                                f"    [{d['tag']}] aria='{d.get('aria','')}' "
                                f"text='{d['text']}' pos=({d['x']},{d['y']}) "
                                f"size={d['w']}x{d['h']} svg={d['svg']}"
                            )
            except Exception as e:
                logger.warning(f"[⚠️] JS scan خطأ: {e}")

            # ── ② CSS يشمل div (Instagram 3-Dots = DIV بدون role) ──
            if not dots_btn:
                broad_selectors = [
                    # بـ aria-label
                    'button:has(svg[aria-label="خيارات"])',
                    'button:has(svg[aria-label="More options"])',
                    'button:has(svg[aria-label="More Options"])',
                    '[role="button"]:has(svg[aria-label="خيارات"])',
                    '[role="button"]:has(svg[aria-label="More options"])',
                    'svg[aria-label="خيارات"]',
                    'svg[aria-label="More options"]',
                    'svg[aria-label="More Options"]',
                    # DIV صغير بـ SVG (الشكل الحقيقي في Instagram)
                    'div:has(svg[aria-label="خيارات"])',
                    'div:has(svg[aria-label="More options"])',
                    'div:has(svg[aria-label="More Options"])',
                ]
                for sel in broad_selectors:
                    try:
                        locs = self.page.locator(sel)
                        count = await locs.count()
                        for i in range(count):
                            loc = locs.nth(i)
                            try:
                                bb_c = await loc.bounding_box()
                                if not bb_c or bb_c["y"] > 400:
                                    continue
                                _y_str = f"{bb_c['y']:.0f}"
                                logger.info(f"[🔵] 3-Dots via CSS: {sel} | y={_y_str}")
                                dots_btn = loc
                                break
                            except Exception:
                                continue
                        if dots_btn:
                            break
                    except Exception:
                        continue

            # ── ③ Visual Confirmation + bounding_box Debug ──
            if dots_btn:
                try:
                    bb = await dots_btn.bounding_box()
                    if bb:
                        cx = bb["x"] + bb["width"] / 2
                        cy = bb["y"] + bb["height"] / 2
                        logger.info(
                            f"[DEBUG_COORDS] الزرار مكانه: x={bb['x']:.0f}, y={bb['y']:.0f}, "
                            f"w={bb['width']:.0f}, h={bb['height']:.0f} | مركز=({cx:.0f},{cy:.0f})"
                        )
                    await dots_btn.evaluate("""
                        el => {
                            el.style.outline = '4px solid red';
                            el.style.backgroundColor = 'rgba(255,0,0,0.3)';
                        }
                    """)
                    logger.info(f"[🔴] Visual Confirmation: الزرار لُوِّن أحمر لـ @{username}")
                    await take_error_screenshot(self.page, f"debug_dots_confirm_{username[:12]}")
                except Exception:
                    pass

                # ── ④ ضغطة واحدة قوية + انتظر القائمة + تحقق المحتوى ──
                logger.info(f"[🔵] 3-Dots: ضغط (force=True) لـ @{username}")
                if MOBILE_EMULATION:
                    try:
                        await dots_btn.tap(timeout=BUTTON_TIMEOUT_MS)
                    except Exception:
                        await dots_btn.evaluate("el => el.click()")
                else:
                    await dots_btn.click(force=True, timeout=BUTTON_TIMEOUT_MS)
                await asyncio.sleep(1.5)

                # تحقق فوري: هل القائمة فيها "رسالة"؟
                if not await _menu_has_message():
                    logger.warning(f"[⚠️] القائمة مفتوحة لكن مفيش 'رسالة' → إغلاق والانتقال للإحداثيات")
                    await _close_open_menu()
                    dots_btn = None  # نزيل الزرار ونجرب الإحداثيات

            # ── ⑤ Fallback: إحداثيات موسّعة للـ header مع timeout 15 ثانية ──
            if not dots_btn:
                logger.info(f"[🎯] 3-Dots: Selectors فشلت → إحداثيات موسّعة لـ @{username}")
                await take_error_screenshot(self.page, f"debug_before_coords_{username[:12]}")

                # إحداثيات من debug حقيقي (JS LOG):
                # @mohamed.farrag: DIV pos=(57,78) size=34x32 → center=(74,94)
                # @soheerelghitany: DIV pos=(98,78) size=34x32 → center=(115,94) ← (115,80) نجح!
                # الـ y ثابت ~78-94، الـ x يختلف حسب طول اليوزرنيم (57 لـ 140)
                all_coords = [
                    # 🎯 نطاق الـ y الصحيح: 78-94 | نطاق x: 57-160
                    (74,  94), (115, 94), (115, 80), (74,  80),
                    (90,  87), (105, 87), (60,  87), (130, 87),
                    (74,  78), (115, 78), (57,  94), (140, 94),
                    (80,  94), (100, 94), (120, 94), (65,  94),
                    (150, 87), (50,  87), (160, 87), (45,  87),
                    # توسيع y قليلاً
                    (90,  70), (90,  100),(115, 70), (74,  100),
                ]
                menu_with_msg = False
                import time as _time
                deadline = _time.time() + 15.0  # 15 ثانية كحد أقصى

                for coords in all_coords:
                    if _time.time() > deadline:
                        logger.warning(f"[⏱️] 15 ثانية انتهت لـ 3-Dots @{username}")
                        break
                    logger.debug(f"[🎯] جرب إحداثيات {coords} لـ @{username}")
                    await self.page.mouse.click(coords[0], coords[1], delay=100)
                    await asyncio.sleep(1.2)
                    try:
                        await self.page.wait_for_selector(
                            '[role="dialog"], [role="sheet"], [role="menu"], [role="listbox"]',
                            timeout=800
                        )
                        if await _menu_has_message():
                            logger.info(f"[✅] قائمة + رسالة بإحداثيات {coords} لـ @{username}")
                            menu_with_msg = True
                            break
                        else:
                            logger.debug(f"[⚠️] قائمة بدون رسالة عند {coords} → إغلاق وتالي")
                            await _close_open_menu()
                    except Exception:
                        continue

                if not menu_with_msg:
                    # ── محاولة أخيرة: أغلق overlay الاقتراحات وجرب زر مراسلة مباشر ──
                    dismissed = await self._dismiss_suggestions_overlay(username)
                    if dismissed:
                        logger.info(f"[🔄] أُغلق overlay الاقتراحات — محاولة أخيرة لإيجاد 'مراسلة' لـ @{username}")
                        await asyncio.sleep(1.0)
                        # جرب زر مراسلة مباشرة بعد إغلاق الـ overlay
                        direct_msg_sels = [
                            'button:has-text("مراسلة")',
                            '[role="button"]:has-text("مراسلة")',
                            'button:has-text("Message")',
                            'button[aria-label="مراسلة"]',
                            'button[aria-label="Message"]',
                        ]
                        for _sel in direct_msg_sels:
                            try:
                                _btn = self.page.locator(_sel).first
                                await _btn.wait_for(state="visible", timeout=3000)
                                if MOBILE_EMULATION:
                                    await _btn.tap()
                                else:
                                    await _btn.click(force=True)
                                logger.info(f"[✅] زر مراسلة بعد إغلاق الاقتراحات لـ @{username}")
                                await asyncio.sleep(2.0)
                                return True
                            except Exception:
                                continue
                    logger.warning(f"[⚠️] 3-Dots: فشل تام لـ @{username} → Direct Fallback")
                    return await _direct_link_fallback()

            # ── ③ Text-Based Menu Search: أولوية للعربية (مراسلة / إرسال رسالة) ──
            msg_item = None

            # get_by_text أولاً — 'مراسلة' و'إرسال رسالة' أولوية قصوى
            text_menu_locators = [
                ("مراسلة",      self.page.get_by_text("مراسلة",      exact=True)),
                ("إرسال رسالة", self.page.get_by_text("إرسال رسالة", exact=True)),
                ("إرسال رسالة~",self.page.get_by_text("إرسال رسالة", exact=False)),
                ("Send message",self.page.get_by_text("Send message", exact=False)),
                ("Message",     self.page.get_by_text("Message",      exact=True)),
                ("رسالة",       self.page.get_by_text("رسالة",        exact=True)),
            ]
            for label, loc in text_menu_locators:
                try:
                    await loc.first.wait_for(state="visible", timeout=2000)
                    msg_item = loc.first
                    logger.info(f"[💬] وُجد '{label}' في القائمة لـ @{username}")
                    break
                except Exception:
                    continue

            # CSS selectors كـ fallback — مراسلة أولاً
            if not msg_item:
                send_msg_css = [
                    '[role="menuitem"]:has-text("مراسلة")',
                    '[role="button"]:has-text("مراسلة")',
                    'button:has-text("مراسلة")',
                    '[role="menuitem"]:has-text("إرسال رسالة")',
                    '[role="button"]:has-text("إرسال رسالة")',
                    'button:has-text("إرسال رسالة")',
                    '[role="menuitem"]:has-text("Send message")',
                    '[role="button"]:has-text("Send message")',
                    'button:has-text("Send message")',
                    'div[role="dialog"] span:has-text("مراسلة")',
                    'div[role="dialog"] span:has-text("إرسال رسالة")',
                    '[role="sheet"] span:has-text("مراسلة")',
                    '[role="sheet"] span:has-text("إرسال رسالة")',
                ]
                for sel in send_msg_css:
                    try:
                        loc = self.page.locator(sel).first
                        await loc.wait_for(state="visible", timeout=1500)
                        msg_item = loc
                        break
                    except Exception:
                        continue

            # ── Skip if Block only: لو القائمة فيها حظر/إبلاغ بس ومفيش مراسلة → تخطي ──
            if not msg_item:
                block_only = await self.page.evaluate("""
                    () => {
                        const menuTexts = Array.from(document.querySelectorAll(
                            '[role="dialog"] *, [role="sheet"] *, [role="menu"] *, [role="listbox"] *'
                        )).map(el => (el.innerText || '').trim()).filter(Boolean);
                        const hasBlock = menuTexts.some(t =>
                            t.includes('حظر') || t.includes('Block') ||
                            t.includes('إبلاغ') || t.includes('Report')
                        );
                        const hasMsg = menuTexts.some(t =>
                            t.includes('مراسلة') || t.includes('إرسال رسالة') ||
                            t.includes('Message') || t.includes('Send message')
                        );
                        return hasBlock && !hasMsg;
                    }
                """)
                if block_only:
                    logger.warning(f"[🚫] الرسايل مقفولة عند العميل @{username} (حظر/إبلاغ فقط بدون مراسلة)")
                    await take_error_screenshot(self.page, f"debug_block_only_{username[:12]}")
                    return False

                logger.warning(f"[⚠️] 3-Dots: القائمة ظهرت لكن 'Send message' مش موجود لـ @{username}")
                await take_error_screenshot(self.page, f"debug_private_menu_{username[:12]}")
                # ── Final Fallback for Private: جرب Direct Link حتى للحسابات الخاصة ──
                logger.info(f"[🚀] Final Private Fallback → direct/t/{username}/")
                try:
                    await self.page.goto(
                        f"https://www.instagram.com/direct/t/{username}/",
                        wait_until="domcontentloaded",
                        timeout=15000,
                    )
                    await asyncio.sleep(2.0)
                    return True
                except Exception:
                    return False

            # ── الضغط على Send Message مع scroll_into_view + force=True ──
            try:
                await msg_item.scroll_into_view_if_needed(timeout=2000)
            except Exception:
                pass
            if MOBILE_EMULATION:
                try:
                    await msg_item.tap(timeout=BUTTON_TIMEOUT_MS)
                except Exception:
                    await msg_item.evaluate("el => el.click()")
            else:
                await msg_item.click(force=True, timeout=BUTTON_TIMEOUT_MS)
            logger.info(f"[💬] 3-Dots → Send Message ضُغط (force=True) لـ @{username}")

            # ── ④ Wait for Direct: انتظر تغيير الـ URL لـ direct/t/ ──
            for _ in range(6):
                await asyncio.sleep(0.8)
                current_url = self.page.url
                if "direct/t/" in current_url or "direct/inbox" in current_url:
                    logger.info(f"[✅] 3-Dots Direct Redirect مؤكد → @{username} | {current_url[:60]}")
                    return True
                # تحقق بديل: هل ظهر صندوق الكتابة؟
                try:
                    tb = await self.page.query_selector(
                        'div[role="textbox"], p[aria-placeholder], textarea[placeholder]'
                    )
                    if tb and await tb.is_visible():
                        logger.info(f"[✅] 3-Dots Chat Ready (textbox) → @{username}")
                        return True
                except Exception:
                    pass

            # لو لم يتغير الـ URL بعد 4.8 ث → لقطة تشخيصية وفشل
            logger.warning(f"[⚠️] 3-Dots: Send message ضُغط لكن لا redirect لـ @{username}")
            await take_error_screenshot(self.page, f"debug_private_no_redirect_{username[:12]}")
            return False

        except Exception as e:
            logger.debug(f"_try_three_dots_message @{username}: {e}")
            return False

    # ─────────────────────────────────────────────────────────────
    #  الكتابة البشرية
    # ─────────────────────────────────────────────────────────────

    async def _open_direct_by_username(self, username: str) -> bool:
        try:
            await self.page.goto("https://www.instagram.com/direct/new/", wait_until="domcontentloaded", timeout=15000)
            await random_delay(3, 8)

            search_selectors = [
                'input[name="queryBox"]',
                'input[placeholder*="Search"]',
                'input[placeholder*="بحث"]',
                'input[aria-label*="Search"]',
                'input[aria-label*="بحث"]',
                'div[role="textbox"]',
            ]
            search_box = await self._find_visible_locator(search_selectors, timeout=3000)
            if not search_box:
                return False

            await search_box.fill(username)
            await random_delay(3, 8)

            user_option = await self._find_visible_locator(
                [
                    f'xpath=//span[contains(normalize-space(.), "{username}")]',
                    f'xpath=//*[contains(normalize-space(.), "{username}") and (@role="button" or ancestor::*[@role="button"])]',
                ],
                timeout=5000,
            )
            if not user_option:
                return False

            await user_option.click(timeout=BUTTON_TIMEOUT_MS)
            await random_delay(3, 8)

            chat_button = await self._find_visible_locator(
                [
                    'xpath=//div[@role="button" and contains(normalize-space(.), "Chat")]',
                    'xpath=//div[@role="button" and contains(normalize-space(.), "دردشة")]',
                    'xpath=//button[contains(normalize-space(.), "Chat")]',
                    'xpath=//button[contains(normalize-space(.), "دردشة")]',
                ],
                timeout=5000,
            )
            if chat_button:
                await chat_button.click(timeout=BUTTON_TIMEOUT_MS)
                await random_delay(3, 8)
            return True
        except Exception as e:
            logger.error(f"❌ فتح Direct @{username}: {str(e)[:60]}")
            return False

    async def _fast_fill_message(self, text: str):
        """لصق الرسالة فوراً داخل صندوق الكتابة — Arabic + English selectors"""
        textbox_selectors = [
            'div[role="textbox"]',
            'textarea[placeholder*="رسالة"]',
            'textarea[placeholder*="Message"]',
            'div[aria-label*="رسالة"]',
            'div[aria-label*="Message"]',
            'div[contenteditable="true"]',
            'p[aria-placeholder]',
        ]
        for selector in textbox_selectors:
            textbox = await self.page.query_selector(selector)
            if textbox and await textbox.is_visible():
                await textbox.click()
                await asyncio.sleep(0.3)
                try:
                    await textbox.fill(text)
                    return
                except Exception:
                    try:
                        await textbox.evaluate(
                            """(element, value) => {
                                element.focus();
                                document.execCommand('selectAll', false, null);
                                document.execCommand('insertText', false, value);
                                element.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: value }));
                            }""",
                            text,
                        )
                        return
                    except Exception:
                        pass

        # آخر محاولة: keyboard.type مباشرة
        await self.page.keyboard.type(text, delay=20)

    async def _fast_fill_and_send(self, text: str, username: str) -> bool:
        """
        يكتب الرسالة في صندوق الكتابة ثم يضغط زرار الإرسال.
        ① يبحث عن صندوق الكتابة بـ selectors عربية وإنجليزية
        ② يكتب النص
        ③ يحاول الضغط على زرار 'إرسال' الصريح، أو Enter كـ fallback
        """
        textbox_selectors = [
            'div[role="textbox"]',
            'textarea[placeholder*="رسالة"]',
            'textarea[placeholder*="Message"]',
            'div[aria-label*="رسالة"]',
            'div[aria-label*="Message"]',
            'div[contenteditable="true"]',
            'p[aria-placeholder]',
        ]

        textbox = None
        for selector in textbox_selectors:
            el = await self.page.query_selector(selector)
            if el and await el.is_visible():
                textbox = el
                break

        if not textbox:
            # آخر محاولة: keyboard.type مباشرة
            logger.info(f"[⌨️] صندوق الكتابة مش موجود → keyboard.type مباشرة لـ @{username}")
            await self.page.keyboard.type(text, delay=20)
            await asyncio.sleep(0.5)
            await self.page.keyboard.press("Enter")
            return True

        # اضغط على الصندوق واكتب
        try:
            await textbox.click()
        except Exception:
            await textbox.evaluate("el => el.focus()")
        await asyncio.sleep(0.3)

        # حاول fill أو execCommand أو type
        typed = False
        try:
            await textbox.fill(text)
            typed = True
        except Exception:
            pass

        if not typed:
            try:
                await textbox.evaluate(
                    """(el, val) => {
                        el.focus();
                        document.execCommand('selectAll', false, null);
                        document.execCommand('insertText', false, val);
                        el.dispatchEvent(new InputEvent('input', { bubbles: true, data: val }));
                    }""",
                    text,
                )
                typed = True
            except Exception:
                pass

        if not typed:
            await self.page.keyboard.type(text, delay=20)

        await asyncio.sleep(0.5)

        # ── ابحث عن زرار "إرسال" الصريح ──
        send_btn_selectors = [
            'button:has-text("إرسال")',
            'button[aria-label="إرسال"]',
            'button:has-text("Send")',
            'button[aria-label="Send"]',
            'button[type="submit"]',
            '[role="button"]:has-text("إرسال")',
            '[role="button"]:has-text("Send")',
            # أيقونة إرسال (SVG)
            'button:has(svg[aria-label="إرسال"])',
            'button:has(svg[aria-label="Send"])',
        ]
        send_clicked = False
        for sel in send_btn_selectors:
            try:
                btn = self.page.locator(sel).first
                await btn.wait_for(state="visible", timeout=1500)
                if MOBILE_EMULATION:
                    await btn.tap(timeout=BUTTON_TIMEOUT_MS)
                else:
                    await btn.click(force=True, timeout=BUTTON_TIMEOUT_MS)
                logger.info(f"[✅] زرار إرسال ضُغط: {sel} لـ @{username}")
                send_clicked = True
                break
            except Exception:
                continue

        if not send_clicked:
            # Fallback: Enter
            logger.info(f"[⌨️] زرار إرسال مش موجود → Enter لـ @{username}")
            await self.page.keyboard.press("Enter")

        return True

    # ─────────────────────────────────────────────────────────────
    #  الرد على التعليقات
    # ─────────────────────────────────────────────────────────────

    async def reply_to_comment(self, post_url: str, username: str,
                               custom_text: str = None) -> bool:
        """
        الرد على تعليق المستخدم في المنشور.
        custom_text: نص مخصص للرد (يُستخدم للحسابات الخاصة)
        """
        reply_text = custom_text or self.comment_reply_text
        try:
            logger.info(f"جارٍ الرد على تعليق @{username} في المنشور")

            await self.page.goto(post_url, wait_until="domcontentloaded")
            await random_delay(3, 8)

            comment_found = await self._find_and_click_reply_on_comment(username)

            if not comment_found:
                logger.warning(f"لم يُعثر على تعليق @{username} للرد عليه")
                return False

            await self._fast_fill_message(reply_text)
            await asyncio.sleep(0.5)
            await self.page.keyboard.press("Enter")
            await random_delay(3, 8)

            logger.info(f"✅ تم الرد على تعليق @{username} بنجاح")
            return True

        except Exception as e:
            logger.error(f"خطأ أثناء الرد على تعليق @{username}: {e}")
            await take_error_screenshot(self.page, f"reply_error_{username}")
            return False

    async def _find_and_click_reply_on_comment(self, username: str) -> bool:
        """البحث عن تعليق المستخدم بالـ aria-labels والـ roles"""
        try:
            result = await self.page.evaluate(f"""
                () => {{
                    const username = "{username}";
                    // البحث بالرابط المرتبط باسم المستخدم
                    const links = document.querySelectorAll('a[href="/' + username + '/"]');
                    for (const link of links) {{
                        // الحاوية: li أو أقرب div
                        const container = link.closest('li') ||
                                          link.closest('[role="row"]') ||
                                          link.closest('div');
                        if (!container) continue;

                        // البحث عن زر الرد بـ aria-label أو نص
                        const replySelectors = [
                            'button[aria-label*="Reply"]',
                            'button[aria-label*="رد"]',
                            'button:has-text("Reply")',
                            'span[role="button"]:has-text("Reply")',
                            'span[role="button"]:has-text("رد")',
                        ];
                        for (const sel of replySelectors) {{
                            const btn = container.querySelector(sel);
                            if (btn) {{
                                btn.click();
                                return true;
                            }}
                        }}
                    }}
                    return false;
                }}
            """)
            if result:
                await random_delay(1, 2)
                return True
            return False
        except Exception as e:
            logger.error(f"خطأ في البحث عن تعليق @{username}: {e}")
            return False

    # ─────────────────────────────────────────────────────────────
    #  ضبط الإعدادات
    # ─────────────────────────────────────────────────────────────

    def set_message_templates(self, templates: list):
        self.message_templates = templates
        logger.info(f"تم تحديث قوالب الرسائل ({len(templates)} قالب)")

    def set_comment_reply_text(self, text: str):
        self.comment_reply_text = text

    def set_private_auto_reply(self, enabled: bool, text: str = None):
        """تفعيل/إلغاء الرد التلقائي على الحسابات الخاصة"""
        self.private_auto_reply = enabled
        if text:
            self.private_reply_text = text
        logger.info(f"الرد التلقائي على الخاصة: {'مفعّل' if enabled else 'معطّل'}")
