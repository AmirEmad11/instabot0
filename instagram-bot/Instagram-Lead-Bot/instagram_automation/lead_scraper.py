"""
وحدة استخراج العملاء المحتملين (Lead Scraper)
- تستهدف قائمة التعليقات (ul) تحديداً وتستبعد صاحب المنشور
- تستخدم Roles/Aria-labels بدلاً من الـ classes المتغيرة
- وضع Debug: لقطة شاشة + إحصاء العناصر
- يطبع نص التعليق بوضوح في الـ Logs
"""

import asyncio
import logging
import random
import re
from pathlib import Path

from playwright.async_api import Page
import config as cfg
from utils import random_delay, take_error_screenshot

logger = logging.getLogger(__name__)

_HAS_LETTER = re.compile(
    r'[a-zA-Z\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\u0621-\u064A]'
)


class LeadScraper:

    def __init__(self, page: Page):
        self.page = page
        self.keywords = cfg.KEYWORDS
        self.target_new_comments = 500
        # ── Incremental Extraction ──
        self._accumulated_leads: list[dict] = []
        self._seen_usernames: set = set()
        # ── Strict Owner Filter ──
        self._post_owner: str = ""
        # ── Caption Capture ──
        self.target_caption: str = ""

    # ─────────────────────────────────────────────────────────────
    #  الدالة الرئيسية
    # ─────────────────────────────────────────────────────────────

    async def scrape_leads_from_post(
        self, post_url: str, db_check_fn=None
    ) -> list[dict]:
        """
        db_check_fn: دالة async تأخذ username وترجع True لو موجود في قاعدة البيانات.
                     مثال: db_manager.lead_exists
        Time Management: يوقف السحب تلقائياً بعد 4 دقائق ويحفظ ما تم جمعه.
        """
        leads = []
        # ── إعادة تعيين المجمّعات لكل منشور جديد ──
        self._accumulated_leads = []
        self._seen_usernames = set()
        self._post_owner = ""
        self.target_caption = ""
        self._scrape_start_time = asyncio.get_event_loop().time()  # Time Management
        try:
            logger.info(f"🔍 انتقال إلى المنشور...")
            await self.page.goto(post_url, wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(2)

            # ① التحقق من تسجيل الدخول
            if not await self._verify_logged_in():
                logger.error("❌ صفحة تسجيل الدخول مكتشفة! التوقف فوراً.")
                await take_error_screenshot(self.page, "login_required")
                return leads

            # ① ب - إغلاق أي نوافذ منبثقة قبل البدء (ينظّف الشاشة تماماً)
            popup_count = await self._dismiss_popups()
            if popup_count > 0:
                logger.info(f"[🔔] أُغلقت {popup_count} نافذة منبثقة قبل السحب")
                await asyncio.sleep(1.0)

            # ② فتح قسم التعليقات والتمرير
            is_reel = "/reel" in post_url
            if is_reel:
                comments_ready = await self._force_open_reels_comments()
                if not comments_ready:
                    logger.error("❌ لم يتم فتح نافذة تعليقات Reels - لن يبدأ السحب بدون ظهور dialog")
                    await self._take_debug_screenshot("reels_error")
                    return leads
                # إغلاق أي بوب-أب ظهرت عند فتح نافذة التعليقات
                await self._dismiss_popups()
            else:
                await self._open_comments_section()
                await self._wait_for_comments_content()
                await self._dismiss_popups()

            # ② ب - استخراج صاحب المنشور مبكراً وإضافته للـ Blacklist الداخلية
            self._post_owner = await self._extract_post_owner()
            if self._post_owner:
                self._seen_usernames.add(self._post_owner.lower())
                logger.info(f"[🚫] صاحب المنشور محجوب: @{self._post_owner}")

            # ② ج - Capture Caption First: سحب وتخزين الكابشن قبل السحب
            self.target_caption = await self._capture_caption()

            scrolls, comment_count = await self._scroll_to_load_comments(
                post_url=post_url, db_check_fn=db_check_fn
            )
            logger.info(f"[⚡] تحميل {comment_count} تعليق في {scrolls} تمريرة")

            # ③ فتح الردود المخفية بسرعة
            await self._click_view_replies()

            # ④ استخراج نهائي + دمج مع ما تراكم خلال الـ Scroll
            def _is_valid_lead(lead: dict) -> bool:
                uname = lead["username"].lower()
                if self._post_owner and uname == self._post_owner.lower():
                    return False
                if uname in self._seen_usernames:
                    return False
                return True

            final_batch = await self._extract_leads_from_comments(post_url)
            for lead in final_batch:
                if _is_valid_lead(lead):
                    self._seen_usernames.add(lead["username"].lower())
                    self._accumulated_leads.append(lead)

            # فلتر صارم نهائي: أزل صاحب المنشور من أي مكان في القائمة
            if self._post_owner:
                self._accumulated_leads = [
                    l for l in self._accumulated_leads
                    if l["username"].lower() != self._post_owner.lower()
                ]
            leads = list(self._accumulated_leads)

            if not leads:
                logger.info("🔁 لم تظهر تعليقات بعد - محاولة Scroll إضافية للتحقق قبل الخروج")
                await self._extra_scroll_for_comments()
                await asyncio.sleep(1)
                await self._click_view_replies()
                retry_batch = await self._extract_leads_from_comments(post_url)
                for lead in retry_batch:
                    if _is_valid_lead(lead):
                        self._seen_usernames.add(lead["username"].lower())
                        self._accumulated_leads.append(lead)
                if self._post_owner:
                    self._accumulated_leads = [
                        l for l in self._accumulated_leads
                        if l["username"].lower() != self._post_owner.lower()
                    ]
                leads = list(self._accumulated_leads)
                if not leads:
                    await self._take_debug_screenshot("reels_error")
            logger.info(f"✅ استخرج {len(leads)} عميل محتمل | صاحب المنشور المحجوب: @{self._post_owner or 'غير محدد'}")

        except Exception as e:
            logger.error(f"خطأ أثناء استخراج العملاء: {e}")
            await take_error_screenshot(self.page, "scrape_error")

        return leads

    # ─────────────────────────────────────────────────────────────
    #  إغلاق النوافذ المنبثقة (داخلي - يُستخدم قبل/بعد التنقل)
    # ─────────────────────────────────────────────────────────────

    async def _extract_post_owner(self) -> str:
        """
        Bulletproof Owner Detection:
        يستخرج اسم مستخدم صاحب الريل/المنشور من Header أعلى المنشور بدقة.
        يستبعد الحساب المسجّل دخوله من النتائج.
        """
        try:
            logged_in_user = (cfg.INSTAGRAM_USERNAME or "").strip().lower()
            result = await self.page.evaluate("""
                (loggedInUser) => {
                    const cleanHref = href => {
                        if (!href) return '';
                        let path = href;
                        try { path = href.startsWith('http') ? new URL(href).pathname : href; } catch {}
                        return path.replace(/^\//, '').replace(/\/$/, '').trim();
                    };
                    const isProfileHref = href => {
                        if (!href) return false;
                        const p = href.startsWith('/') ? href : (() => {
                            try { return new URL(href).pathname; } catch { return href; }
                        })();
                        return /^\/[^\/]+\/$/.test(p) &&
                               !p.includes('/p/') && !p.includes('/explore/') &&
                               !p.includes('/reel') && !p.includes('/stories/') &&
                               !p.includes('/accounts/') && !p.includes('/tags/') &&
                               !p.includes('/direct/') && !p.includes('/about/') &&
                               !p.includes('/privacy/') && !p.includes('/legal/');
                    };
                    const isNotLoggedInUser = username =>
                        !loggedInUser || username.toLowerCase() !== loggedInUser;

                    // ── ① أدق Selector: Header أعلى الـ Reel مباشرة ──
                    const preciseSelectors = [
                        'article header a[href^="/"]',
                        'div[role="dialog"] header a[href^="/"]',
                        'div[role="presentation"] header a[href^="/"]',
                        // Reel header في وضع الموبايل (أعلى الصفحة قبل الفيديو)
                        'section > div > div > div > header a[href^="/"]',
                        'div[style*="position"] header a[href^="/"]',
                    ];
                    for (const sel of preciseSelectors) {
                        const links = Array.from(document.querySelectorAll(sel))
                            .filter(a => isProfileHref(a.getAttribute('href')));
                        for (const link of links) {
                            const username = cleanHref(link.getAttribute('href'));
                            if (username && isNotLoggedInUser(username)) return username;
                        }
                    }

                    // ── ② Fallback: أول رابط بروفايل في header عام ──
                    const headerSelectors = [
                        'article header', 'div[role="dialog"] header',
                        'div[role="presentation"] header', 'main header', 'header'
                    ];
                    for (const sel of headerSelectors) {
                        const header = document.querySelector(sel);
                        if (!header) continue;
                        const links = Array.from(header.querySelectorAll('a[href]'))
                            .filter(a => isProfileHref(a.getAttribute('href')));
                        for (const link of links) {
                            const username = cleanHref(link.getAttribute('href'));
                            if (username && isNotLoggedInUser(username)) return username;
                        }
                    }

                    // ── ③ JSON المدمج في الصفحة (أكثر دقة للـ Reel) ──
                    try {
                        const scripts = Array.from(document.querySelectorAll('script[type="application/json"]'));
                        for (const script of scripts) {
                            const match = (script.textContent || '').match(/"username"\s*:\s*"([^"]{2,40})"/);
                            if (match) {
                                const username = match[1];
                                if (isNotLoggedInUser(username) && !/\s/.test(username)) return username;
                            }
                        }
                    } catch {}

                    // ── ④ آخر خيار: أول رابط بروفايل غير المسجّل في الصفحة ──
                    const roots = [
                        document.querySelector('[role="dialog"]'),
                        document.querySelector('div[role="presentation"]'),
                        document.querySelector('article'),
                        document.querySelector('main'),
                        document.body
                    ].filter(Boolean);
                    for (const root of roots) {
                        for (const link of root.querySelectorAll('a[href]')) {
                            if (!isProfileHref(link.getAttribute('href'))) continue;
                            const username = cleanHref(link.getAttribute('href'));
                            if (username && isNotLoggedInUser(username)) return username;
                        }
                    }
                    return '';
                }
            """, logged_in_user)
            owner = (result or "").strip()
            if owner:
                logger.info(f"[🎯] Bulletproof Owner Detection: صاحب المنشور = @{owner}")
            return owner
        except Exception as e:
            logger.debug(f"_extract_post_owner error: {e}")
            return ""

    async def _capture_caption(self) -> str:
        """
        Capture Caption First: يدخل على عنصر الكابشن الرئيسي ويسحب نصه
        ويخزنه في self.target_caption قبل بدء أي سحب للتعليقات.
        يستهدف العنصر الأول (Index 0) في قائمة التعليقات أو الـ span
        المرتبط بصاحب المنشور مباشرة.
        """
        try:
            caption = await self.page.evaluate("""
                (postOwner) => {
                    const cleanHref = href => {
                        if (!href) return '';
                        let path = href;
                        try { path = href.startsWith('http') ? new URL(href).pathname : href; } catch {}
                        return path.replace(/^\//, '').replace(/\/$/, '').trim();
                    };

                    // ① العنصر الأول في قائمة التعليقات (Index 0 = الكابشن عادةً)
                    const commentContainers = [
                        document.querySelector('[role="dialog"] ul'),
                        document.querySelector('[role="sheet"] ul'),
                        document.querySelector('[role="main"] ul'),
                        document.querySelector('article ul'),
                        document.querySelector('main ul'),
                    ];
                    for (const ul of commentContainers.filter(Boolean)) {
                        const firstItem = ul.querySelector('li, [role="listitem"]');
                        if (!firstItem) continue;
                        const link = firstItem.querySelector('a[href]');
                        if (link) {
                            const username = cleanHref(link.getAttribute('href'));
                            if (postOwner && username &&
                                username.toLowerCase() === postOwner.toLowerCase()) {
                                const text = (firstItem.innerText || firstItem.textContent || '')
                                    .replace(/\s+/g, ' ').trim();
                                if (text.length > 20) return text;
                            }
                        }
                        // حتى لو مش محدد المالك، اسحب النص من أول عنصر كـ fallback
                        const rawText = (firstItem.innerText || firstItem.textContent || '')
                            .replace(/\s+/g, ' ').trim();
                        if (rawText.length > 50) return rawText;
                    }

                    // ② Fallback: أي span طويل مرتبط بصاحب المنشور
                    if (postOwner) {
                        const ownerLinks = Array.from(document.querySelectorAll('a[href]'))
                            .filter(a => cleanHref(a.getAttribute('href') || '').toLowerCase()
                                         === postOwner.toLowerCase());
                        for (const ownerLink of ownerLinks) {
                            let node = ownerLink.parentElement;
                            for (let i = 0; node && i < 8; i++) {
                                const spans = Array.from(node.querySelectorAll('span'))
                                    .filter(s => !s.closest('a[href]') &&
                                                 (s.innerText || '').trim().length > 30);
                                if (spans.length > 0)
                                    return spans.map(s => s.innerText).join(' ').trim();
                                node = node.parentElement;
                            }
                        }
                    }
                    return '';
                }
            """, self._post_owner)
            caption = (caption or "").strip()
            if caption:
                logger.info(f"[📝] target_caption ملتقط ({len(caption)} حرف): {caption[:80]}...")
            else:
                logger.info("[📝] لم يُعثر على كابشن مميز — المتابعة بدون فلتر كابشن")
            return caption
        except Exception as e:
            logger.debug(f"_capture_caption error: {e}")
            return ""

    async def _dismiss_popups(self) -> int:
        """
        يغلق أي نافذة منبثقة (Save Login / Notifications) قبل السحب.
        نسخة مدمجة مخصصة لـ LeadScraper - لا تحتاج AutomationEngine.
        """
        dismiss_texts = [
            "Not Now", "Not now", "ليس الآن", "Skip", "تخطي",
            "Cancel", "إلغاء", "Dismiss", "Close", "إغلاق",
            "Don't Allow", "Later", "لاحقاً",
        ]
        selectors = (
            [f'button:has-text("{t}")' for t in dismiss_texts] +
            [f'[role="button"]:has-text("{t}")' for t in dismiss_texts] +
            ['button[aria-label*="Close"]', '[role="button"][aria-label*="Close"]',
             'button[aria-label*="إغلاق"]']
        )
        closed = 0
        for sel in selectors:
            try:
                btn = await self.page.query_selector(sel)
                if btn and await btn.is_visible():
                    logger.info(f"[🔔] إغلاق نافذة منبثقة: «{sel}»")
                    await btn.tap() if cfg.MOBILE_EMULATION else await btn.click()
                    await asyncio.sleep(1.0)
                    closed += 1
                    break
            except Exception:
                continue
        return closed

    # ─────────────────────────────────────────────────────────────
    #  التحقق من تسجيل الدخول
    # ─────────────────────────────────────────────────────────────

    async def _verify_logged_in(self) -> bool:
        try:
            current_url = self.page.url
            if "/accounts/login" in current_url or "/login" in current_url:
                logger.error(f"🚫 URL يشير لصفحة الدخول: {current_url}")
                return False

            page_text = await self.page.inner_text("body")
            login_indicators = [
                "Log in to Instagram",
                "تسجيل الدخول إلى إنستجرام",
                "Log In",
                "Log into Facebook",
            ]
            for indicator in login_indicators:
                if indicator.lower() in page_text.lower():
                    logger.error(f"🚫 مؤشر تسجيل دخول مكتشف: '{indicator}'")
                    return False

            logger.info("✅ الصفحة محملة - المستخدم مسجّل الدخول")
            return True
        except Exception as e:
            logger.warning(f"تعذّر فحص تسجيل الدخول: {e}")
            return True

    # ─────────────────────────────────────────────────────────────
    #  أدوات التشخيص
    # ─────────────────────────────────────────────────────────────

    async def _take_debug_screenshot(self, name: str):
        try:
            screenshots_dir = Path(cfg.SCREENSHOTS_DIR)
            screenshots_dir.mkdir(exist_ok=True)
            path = str(screenshots_dir / f"{name}.png")
            await self.page.screenshot(path=path, full_page=False)
            logger.info(f"📸 لقطة شاشة: {path}")
        except Exception as e:
            logger.warning(f"فشل التقاط لقطة: {e}")

    async def _log_element_counts(self):
        try:
            counts = await self.page.evaluate("""
                () => {
                    const area = document.querySelector('[role="dialog"]') ||
                                 document.querySelector('section') ||
                                 document.querySelector('article') ||
                                 document.querySelector('main') ||
                                 document.body;

                    const spansWithText = Array.from(area.querySelectorAll('span'))
                        .filter(el => el.innerText && el.innerText.trim().length > 1).length;

                    const liCount = area.querySelectorAll('li').length;
                    const ulCount = area.querySelectorAll('ul').length;
                    const roleListItems = area.querySelectorAll('[role="listitem"]').length;

                    const profileLinks = Array.from(area.querySelectorAll('a[href^="/"]'))
                        .filter(a => {
                            const p = a.getAttribute('href') || '';
                            return p.match(/^\/[^\/]+\/$/) &&
                                   !p.includes('/p/') && !p.includes('/explore/') &&
                                   !p.includes('/reels/') && !p.includes('/stories/') &&
                                   !p.includes('/accounts/');
                        }).length;

                    const header = document.querySelector('article header, header[role]');
                    let postAuthor = 'غير محدد';
                    if (header) {
                        const link = header.querySelector('a[href^="/"]');
                        if (link) postAuthor = (link.getAttribute('href') || '').replace(/\//g, '');
                    }

                    return { spansWithText, liCount, ulCount, roleListItems, profileLinks, postAuthor };
                }
            """)
            logger.info(
                f"📊 إحصاء | ul: {counts['ulCount']} | li: {counts['liCount']} | "
                f"listitem: {counts['roleListItems']} | روابط مستخدمين: {counts['profileLinks']} | "
                f"span نصي: {counts['spansWithText']} | صاحب المنشور: {counts['postAuthor']}"
            )
        except Exception as e:
            logger.warning(f"فشل إحصاء العناصر: {e}")

    # ─────────────────────────────────────────────────────────────
    #  Navigation Guard — العودة للمنشور إذا تغير الرابط
    # ─────────────────────────────────────────────────────────────

    async def _check_and_restore_url(self, expected_url: str) -> bool:
        """
        يفحص إذا انجرف المتصفح عن رابط المنشور (مثل فتح بروفايل بالخطأ).
        إذا تغير الرابط → يضغط Back فوراً ويعود للمنشور ويعيد True.
        """
        try:
            current = self.page.url
            # تجاهل fragment / query params - قارن المسار فقط
            if expected_url.split("?")[0].rstrip("/") in current.split("?")[0].rstrip("/"):
                return False  # الرابط لم يتغير
            logger.warning(
                f"[🔙] انجراف URL مكتشف!\n"
                f"   المتوقع: {expected_url[:70]}\n"
                f"   الحالي : {current[:70]}\n"
                f"   → ضغط Back والعودة للمنشور..."
            )
            await self.page.go_back(wait_until="domcontentloaded", timeout=10000)
            await asyncio.sleep(2)
            # إذا لم يعد للرابط الصحيح، انتقل مباشرةً
            if expected_url.split("?")[0].rstrip("/") not in self.page.url.split("?")[0].rstrip("/"):
                await self.page.goto(expected_url, wait_until="domcontentloaded", timeout=15000)
                await asyncio.sleep(2)
            logger.info(f"[✅] تمت العودة للمنشور: {self.page.url[:60]}")
            return True
        except Exception as e:
            logger.warning(f"[⚠] Navigation Guard خطأ: {e}")
            return False

    # ─────────────────────────────────────────────────────────────
    #  التمرير وتحميل التعليقات
    # ─────────────────────────────────────────────────────────────

    async def _open_comments_section(self):
        try:
            selectors = [
                'button[aria-label*="omment"]',
                'button[aria-label*="Comment"]',
                'button[aria-label*="عليق"]',
                '[role="button"][aria-label*="omment"]',
                '[role="button"][aria-label*="Comment"]',
                'svg[aria-label*="Comment"]',
                'svg[aria-label*="omment"]',
                'a[href*="/comments/"]',
            ]
            for selector in selectors:
                el = await self.page.query_selector(selector)
                if el and await el.is_visible():
                    await el.click()
                    await asyncio.sleep(3)
                    break
        except Exception:
            pass

    async def _detect_comments_visible(self) -> bool:
        """
        يكتشف ظهور قسم التعليقات بطريقة مرنة:
        - في الموبايل: Bottom Sheet يغطي الشاشة (لا dialog رسمي)
        - في الديسك توب: [role="dialog"]
        يقبل أي حاوية تحتوي على تعليقات أو روابط مستخدمين.
        """
        # Selectors مرنة بالترتيب من الأكثر تخصصاً للأعم
        flexible_selectors = [
            '[role="dialog"]',
            '[role="sheet"]',
            '[role="main"] ul',
            '[role="main"] li',
            'div[style*="bottom"] ul',
            'div[style*="bottom"] li',
            'ul li a[href^="/"]',
            'div[role="presentation"] ul',
            'div[role="presentation"] li',
            'section ul li',
            'main ul li',
        ]
        combined = ", ".join(flexible_selectors)
        try:
            await self.page.wait_for_selector(combined, timeout=5000)
            logger.info("✅ تم رصد محتوى التعليقات في الشاشة (Bottom Sheet أو Dialog)")
            return True
        except Exception:
            pass

        # فحص بديل: هل تغيّر DOM بشكل ملحوظ بعد الضغط؟
        try:
            link_count = await self.page.evaluate("""
                () => document.querySelectorAll('a[href^="/"]').length
            """)
            if link_count > 5:
                logger.info(f"✅ رُصد {link_count} رابط في الصفحة — يُفترض أن التعليقات ظهرت (Bottom Sheet)")
                return True
        except Exception:
            pass

        return False

    async def _force_open_reels_comments(self) -> bool:
        for attempt in range(3):
            try:
                clicked = await self._click_reels_comment_icon(use_offset=attempt >= 1)
                if not clicked:
                    logger.warning(f"⚠️ المحاولة {attempt+1}: لم يتم العثور على أيقونة تعليقات Reels")
                    await asyncio.sleep(2)
                    continue

                # انتظار أطول في الموبايل (Bottom Sheet يحتاج وقتاً للحركة)
                wait_time = 4 if cfg.MOBILE_EMULATION else 3
                await asyncio.sleep(wait_time)

                # ── وضع الموبايل: اقبل Bottom Sheet بدون dialog رسمي ──
                if cfg.MOBILE_EMULATION:
                    visible = await self._detect_comments_visible()
                    if visible:
                        logger.info("✅ [موبايل] التعليقات ظهرت كـ Bottom Sheet — متابعة السحب")
                        return True
                    else:
                        logger.warning(f"⚠️ [موبايل] المحاولة {attempt+1}: لم تظهر التعليقات بعد")
                else:
                    # ── ديسك توب: انتظر dialog الرسمي ──
                    try:
                        await self.page.wait_for_selector('[role="dialog"]', timeout=7000)
                        logger.info("✅ تم فتح نافذة تعليقات Reels وظهر عنصر dialog")
                        return True
                    except Exception:
                        logger.warning(f"⚠️ المحاولة {attempt+1}: لم يظهر dialog")

            except Exception as e:
                logger.warning(f"تعذّرت محاولة {attempt+1} لفتح تعليقات Reels: {e}")

            if attempt < 2:
                logger.info(f"🔁 إعادة المحاولة {attempt+2}/3...")
                await asyncio.sleep(2)

        # ── Force Scrape: إذا فشل الكشف الرسمي في الموبايل، ابدأ السحب مهما كان ──
        if cfg.MOBILE_EMULATION:
            logger.warning("⚠️ [Force Scrape] تجاوز شرط dialog في وضع الموبايل — بدء السحب على أي حال")
            return True

        return False

    async def _click_reels_comment_icon(self, use_offset: bool = False) -> bool:
        selectors = [
            'button[aria-label*="Comment"]',
            'button[aria-label*="comment"]',
            'button[aria-label*="تعليق"]',
            '[role="button"][aria-label*="Comment"]',
            '[role="button"][aria-label*="comment"]',
            '[role="button"][aria-label*="تعليق"]',
            'svg[aria-label*="Comment"]',
            'svg[aria-label*="comment"]',
            'svg[aria-label*="تعليق"]',
        ]

        for selector in selectors:
            try:
                el = await self.page.query_selector(selector)
                if not el:
                    continue
                target = await el.evaluate_handle("""
                    el => el.closest('button, [role="button"], a') || el
                """)
                try:
                    if use_offset:
                        box = await target.as_element().bounding_box()
                        if box:
                            await self.page.mouse.click(
                                box["x"] + (box["width"] * 0.60),
                                box["y"] + (box["height"] * 0.55)
                            )
                        else:
                            await target.as_element().click(force=True)
                    else:
                        await target.as_element().click(force=True)
                    logger.info(f"💬 تم الضغط على أيقونة التعليقات: {selector}")
                    return True
                except Exception:
                    clicked = await self.page.evaluate("""
                        selector => {
                            const el = document.querySelector(selector);
                            if (!el) return false;
                            const target = el.closest('button, [role="button"], a') || el;
                            target.click();
                            return true;
                        }
                    """, selector)
                    if clicked:
                        logger.info(f"💬 تم تنفيذ JavaScript click على أيقونة التعليقات: {selector}")
                        return True
            except Exception:
                continue

        try:
            clicked = await self.page.evaluate("""
                useOffset => {
                    const visible = el => {
                        const rect = el.getBoundingClientRect();
                        return rect.width > 0 && rect.height > 0 &&
                               rect.bottom > 0 && rect.right > 0 &&
                               rect.top < window.innerHeight && rect.left < window.innerWidth;
                    };
                    const textOf = el => (el?.innerText || el?.textContent || '').trim().toLowerCase();
                    const reelsRoots = [
                        document.querySelector('div[role="presentation"]'),
                        document.querySelector('div.x168nmei'),
                        document.querySelector('div[class*="x168nmei"]'),
                        document.querySelector('main'),
                        document.body
                    ].filter(Boolean);
                    const isCommentTarget = el => {
                        const aria = (el.getAttribute?.('aria-label') || '').toLowerCase();
                        const title = (el.getAttribute?.('title') || '').toLowerCase();
                        const text = textOf(el);
                        return aria.includes('comment') || aria.includes('تعليق') ||
                               title.includes('comment') || title.includes('تعليق') ||
                               text === 'comment' || text === 'تعليق' || text.includes('comments');
                    };
                    for (const root of reelsRoots) {
                        const candidates = Array.from(root.querySelectorAll('button, [role="button"], a, svg'))
                            .filter(el => visible(el) && isCommentTarget(el));
                        for (const el of candidates) {
                            const target = el.closest('button, [role="button"], a') || el;
                            if (useOffset) {
                                const rect = target.getBoundingClientRect();
                                const x = rect.left + rect.width * 0.60;
                                const y = rect.top + rect.height * 0.55;
                                const offsetTarget = document.elementFromPoint(x, y) || target;
                                offsetTarget.dispatchEvent(new MouseEvent('pointerdown', { bubbles: true, clientX: x, clientY: y }));
                                offsetTarget.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, clientX: x, clientY: y }));
                                offsetTarget.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, clientX: x, clientY: y }));
                                offsetTarget.dispatchEvent(new MouseEvent('click', { bubbles: true, clientX: x, clientY: y }));
                            } else {
                                target.click();
                            }
                            return true;
                        }
                    }
                    const svgs = Array.from(document.querySelectorAll('svg')).filter(svg => {
                        const label = (svg.getAttribute('aria-label') || '').toLowerCase();
                        const pathCount = svg.querySelectorAll('path, polygon, circle').length;
                        return visible(svg) && (label.includes('comment') || label.includes('تعليق') || pathCount >= 1);
                    });
                    for (const svg of svgs) {
                        const target = svg.closest('button, [role="button"], a') || svg.parentElement;
                        if (!target || !visible(target)) continue;
                        target.click();
                        return true;
                    }
                    return false;
                }
            """, use_offset)
            if clicked:
                logger.info("💬 تم الضغط على SVG/عنصر تعليق Reels عبر JavaScript")
                return True
        except Exception as e:
            logger.warning(f"فشل JavaScript click لأيقونة تعليقات Reels: {e}")

        return False

    async def _wait_for_comments_content(self) -> bool:
        selectors = [
            # Dialog (ديسك توب)
            '[role="dialog"] ul li',
            '[role="dialog"] [role="listitem"]',
            '[role="dialog"] a[href^="/"]',
            # Bottom Sheet (موبايل) - يملأ الشاشة
            '[role="sheet"] ul li',
            '[role="sheet"] a[href^="/"]',
            '[role="main"] ul li',
            '[role="main"] a[href^="/"]',
            # عام
            'div[role="presentation"] span',
            'div.x168nmei span',
            'div[class*="x168nmei"] span',
            'article ul li',
            'article [role="listitem"]',
            'main ul li',
            'main [role="listitem"]',
            'section ul li',
            'section [role="listitem"]',
            'ul[role="list"] li',
            'article a[href^="/"]',
        ]
        try:
            await self.page.wait_for_selector(", ".join(selectors), timeout=5000)
            logger.info("✅ ظهرت عناصر التعليقات")
            return True
        except Exception:
            pass
        logger.warning("⚠️ لم تظهر عناصر التعليقات خلال 5 ثوانٍ - سيتم المتابعة بمحاولة التمرير")
        return False

    async def _get_loaded_comment_count(self) -> int:
        """
        يعد التعليقات المحملة عبر عدّ روابط الملفات الشخصية في الصفحة كلها.
        يستخدم document.body (لا dialog فقط) لدعم Reels Mobile Bottom Sheet.
        """
        try:
            return await self.page.evaluate("""
                () => {
                    const seen = new Set();
                    // ابحث في الصفحة كلها — Reels Bottom Sheet مش دايماً داخل [role="dialog"]
                    document.querySelectorAll('a[href^="/"]').forEach(a => {
                        const p = a.getAttribute('href') || '';
                        if (p.match(/^\\/[^\\/]+\\/$/) &&
                            !p.includes('/p/') && !p.includes('/explore/') &&
                            !p.includes('/reels/') && !p.includes('/stories/') &&
                            !p.includes('/accounts/') && !p.includes('/direct/') &&
                            !p.includes('/tags/') && !p.includes('/locations/')) {
                            seen.add(p);
                        }
                    });
                    return seen.size;
                }
            """)
        except Exception:
            return 0

    async def _focus_dialog_for_scroll(self):
        """
        يضمن التركيز داخل حاوية التعليقات قبل بدء التمرير.
        - في وضع الموبايل: لا tap على الإطلاق (يفتح بروفايل عن طريق الخطأ).
          بدلاً منه: JavaScript يُعطي focus للحاوية القابلة للتمرير.
        - في الديسك توب: click في مركز الحاوية.
        """
        try:
            if cfg.MOBILE_EMULATION:
                # ← لا تعمل tap أبداً في وضع الموبايل داخل قائمة التعليقات
                # استخدم JavaScript فقط لإعطاء focus بأمان
                await self.page.evaluate("""
                    () => {
                        const findScrollable = root => {
                            const walk = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT);
                            let node = walk.nextNode();
                            while (node) {
                                const st = window.getComputedStyle(node);
                                if ((st.overflowY === 'auto' || st.overflowY === 'scroll') &&
                                     node.scrollHeight > node.clientHeight + 10) return node;
                                node = walk.nextNode();
                            }
                            return root;
                        };
                        const root =
                            document.querySelector('[role="dialog"]') ||
                            document.querySelector('[role="sheet"]') ||
                            document.querySelector('[role="main"]') ||
                            document.querySelector('main') || document.body;
                        const target = findScrollable(root);
                        try { target.focus(); } catch {}
                    }
                """)
                logger.info("[🎯] JavaScript focus على حاوية التعليقات (بدون tap — موبايل)")
            else:
                box = await self.page.evaluate("""
                    () => {
                        const root =
                            document.querySelector('[role="dialog"]') ||
                            document.querySelector('[role="main"]') ||
                            document.querySelector('main') ||
                            document.body;
                        const walk = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT);
                        let scrollable = null;
                        let node = walk.nextNode();
                        while (node) {
                            const st = window.getComputedStyle(node);
                            if ((st.overflowY === 'auto' || st.overflowY === 'scroll') &&
                                 node.scrollHeight > node.clientHeight + 10) {
                                scrollable = node; break;
                            }
                            node = walk.nextNode();
                        }
                        const target = scrollable || root;
                        const rect = target.getBoundingClientRect();
                        if (rect.width === 0 || rect.height === 0) return null;
                        return { x: rect.left + rect.width / 2, y: rect.top + rect.height * 0.4,
                                 w: rect.width, h: rect.height };
                    }
                """)
                if box and box.get('w', 0) > 0:
                    await self.page.mouse.click(box['x'], box['y'])
                    await asyncio.sleep(0.8)
                    logger.info("[🎯] تم التركيز داخل حاوية التعليقات")
        except Exception as e:
            logger.warning(f"تعذّر التركيز على حاوية التعليقات: {e}")

    async def _do_smart_scroll(self) -> bool:
        """
        تمرير ذكي بأربع استراتيجيات مع التحقق من النجاح:
        1- JavaScript يبحث عن العنصر القابل للتمرير (dialog أو Bottom Sheet)
        2- Mouse wheel فوق مركز الشاشة (موبايل) أو مركز النافذة (ديسك توب)
        3- Touch Swipe للموبايل
        4- Fallback عام
        """
        # ─── الاستراتيجية 1: JavaScript مع قياس scrollTop قبل/بعد ───
        result = await self.page.evaluate("""
            () => {
                const findScrollable = (root) => {
                    const walk = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT);
                    let node = walk.nextNode();
                    while (node) {
                        const st = window.getComputedStyle(node);
                        if ((st.overflowY === 'auto' || st.overflowY === 'scroll') &&
                             node.scrollHeight > node.clientHeight + 10) return node;
                        node = walk.nextNode();
                    }
                    return root;
                };
                // البحث بترتيب الأولوية: dialog → Bottom Sheet → main → body
                const root =
                    document.querySelector('[role="dialog"]') ||
                    document.querySelector('[role="sheet"]') ||
                    document.querySelector('div[style*="bottom"]') ||
                    document.querySelector('[role="main"]') ||
                    document.querySelector('main') ||
                    document.querySelector('section') ||
                    document.body;
                const target = findScrollable(root);
                const before = target.scrollTop;
                target.scrollTop = target.scrollHeight;
                // محاولة جماعية على كل عنصر قابل للتمرير في الصفحة
                [root,
                 root.firstElementChild,
                 root.querySelector('ul'),
                 root.querySelector('div > div'),
                 root.querySelector('div > div > div')]
                .filter(Boolean)
                .forEach(el => { try { el.scrollTop = el.scrollHeight; } catch {} });
                const after = target.scrollTop;
                return { success: after > before, before, after, tag: target.tagName };
            }
        """)

        if result.get('success'):
            logger.debug(f"[✔] JS scroll نجح: {result.get('before')}→{result.get('after')} على <{result.get('tag')}>")
            return True

        logger.debug(f"[⚠] scrollTop لم يتغير ({result.get('before')}→{result.get('after')}) - محاولة Mouse Wheel")

        # ─── الاستراتيجية 2: Mouse Wheel (مركز الشاشة للموبايل / مركز النافذة للديسك توب) ───
        try:
            if cfg.MOBILE_EMULATION:
                # في الموبايل Bottom Sheet يملأ الشاشة كلها → تمرير من مركز الشاشة
                vp = await self.page.evaluate("""
                    () => ({ x: window.innerWidth / 2, y: window.innerHeight * 0.55 })
                """)
                scroll_x, scroll_y = vp['x'], vp['y']
                logger.debug(f"[📱] Mouse wheel من مركز الشاشة ({scroll_x:.0f}, {scroll_y:.0f})")
            else:
                coords = await self.page.evaluate("""
                    () => {
                        const root =
                            document.querySelector('[role="dialog"]') ||
                            document.querySelector('[role="main"]') ||
                            document.querySelector('main') ||
                            document.body;
                        const r = root.getBoundingClientRect();
                        return { x: r.left + r.width / 2, y: r.top + r.height * 0.6 };
                    }
                """)
                scroll_x, scroll_y = coords['x'], coords['y']

            wheel_dist = random.randint(400, 700)
            await self.page.mouse.move(scroll_x, scroll_y)
            await self.page.mouse.wheel(0, wheel_dist)
            await asyncio.sleep(0.2)
            await self.page.mouse.wheel(0, wheel_dist + random.randint(-80, 80))
            logger.debug(f"[🖱️] Mouse wheel بمسافة {wheel_dist}")
            return True
        except Exception as e:
            logger.debug(f"Mouse wheel فشل: {e}")

        # ─── الاستراتيجية 3: Touch Swipe للموبايل ───
        if cfg.MOBILE_EMULATION:
            try:
                # Bottom Sheet يملأ الشاشة → نستخدم مركز الشاشة مباشرةً بدون البحث عن dialog
                box = await self.page.evaluate("""
                    () => {
                        const w = window.innerWidth;
                        const h = window.innerHeight;
                        return {
                            x: w / 2,
                            startY: h * 0.72,
                            endY:   h * 0.22
                        };
                    }
                """)
                if box:
                    # ← لا tap قبل الـ swipe — مباشرة Touch Events فقط
                    # محاكاة swipe للأعلى (تمرير لأسفل)
                    await self.page.evaluate(f"""
                        () => {{
                            const x = {box['x']};
                            const startY = {box['startY']};
                            const endY = {box['endY']};
                            const el = document.elementFromPoint(x, startY) || document.body;
                            const touchStart = new TouchEvent('touchstart', {{
                                bubbles: true, cancelable: true,
                                touches: [new Touch({{ identifier: 1, target: el, clientX: x, clientY: startY }})],
                                changedTouches: [new Touch({{ identifier: 1, target: el, clientX: x, clientY: startY }})]
                            }});
                            const touchMove = new TouchEvent('touchmove', {{
                                bubbles: true, cancelable: true,
                                touches: [new Touch({{ identifier: 1, target: el, clientX: x, clientY: endY }})],
                                changedTouches: [new Touch({{ identifier: 1, target: el, clientX: x, clientY: endY }})]
                            }});
                            const touchEnd = new TouchEvent('touchend', {{
                                bubbles: true, cancelable: true,
                                touches: [],
                                changedTouches: [new Touch({{ identifier: 1, target: el, clientX: x, clientY: endY }})]
                            }});
                            el.dispatchEvent(touchStart);
                            el.dispatchEvent(touchMove);
                            el.dispatchEvent(touchEnd);
                        }}
                    """)
                    await asyncio.sleep(1.2)
                    logger.debug("[📱] Touch Swipe للموبايل تم تنفيذه")
                    return True
            except Exception as e:
                logger.debug(f"Touch Swipe فشل: {e}")

        # ─── الاستراتيجية 4: Fallback عام ───
        try:
            await self.page.evaluate("""
                () => {
                    const sels = [
                        '[role="dialog"] ul',
                        '[role="dialog"] > div',
                        '[role="dialog"] > div > div',
                        'section ul', 'main ul', 'article ul',
                        'main', 'article'
                    ];
                    for (const s of sels) {
                        const el = document.querySelector(s);
                        if (el && el.scrollHeight > el.clientHeight)
                            el.scrollTop = el.scrollHeight;
                    }
                    window.scrollBy(0, 800);
                }
            """)
        except Exception:
            pass
        return False

    async def _wait_for_spinner(self):
        """ينتظر اختفاء أيقونة التحميل (Loading Spinner) إذا وُجدت"""
        try:
            spinner_sels = [
                '[aria-label*="Loading"]', '[aria-label*="تحميل"]',
                'svg[aria-label*="Loading"]', '[role="progressbar"]',
                'circle[class*="loading"]', '[data-testid*="spinner"]',
            ]
            for sel in spinner_sels:
                spinner = await self.page.query_selector(sel)
                if spinner and await spinner.is_visible():
                    try:
                        await self.page.wait_for_selector(
                            sel, state="hidden", timeout=4000
                        )
                    except Exception:
                        pass
                    break
        except Exception:
            pass

    async def _final_load_more_check(self):
        """فحص نهائي: ضغط على أي زر 'تحميل المزيد' ظاهر قبل الخروج"""
        btns_texts = [
            "Load more comments", "تحميل المزيد من التعليقات",
            "View more replies", "مشاهدة المزيد من الردود",
            "Load more", "تحميل المزيد",
            "View replies", "عرض الردود",
        ]
        selectors = (
            [f'span[role="button"]:has-text("{t}")' for t in btns_texts] +
            [f'button:has-text("{t}")' for t in btns_texts] +
            ['[role="button"][aria-label*="Load more"]',
             '[role="button"][aria-label*="تحميل المزيد"]']
        )
        clicked = 0
        for sel in selectors:
            try:
                buttons = await self.page.query_selector_all(sel)
                for btn in buttons:
                    if await btn.is_visible():
                        await btn.click()
                        clicked += 1
                        await asyncio.sleep(1.5)
            except Exception:
                continue
        if clicked:
            logger.info(f"[🔁] الفحص النهائي: ضُغط على {clicked} زر تحميل مزيد")
            await asyncio.sleep(2)

    async def _scroll_to_load_comments(self, post_url: str = None, db_check_fn=None) -> tuple[int, int]:
        scroll_count, empty_scrolls, total_new = 0, 0, 0
        previous_count = await self._get_loaded_comment_count()

        # ← تركيز داخل النافذة قبل بدء السكرول (بدون tap في الموبايل)
        await self._focus_dialog_for_scroll()

        try:
            for i in range(cfg.MAX_COMMENTS_SCROLL):
                # ── Navigation Guard: تحقق من URL قبل كل scroll ──
                if post_url and cfg.MOBILE_EMULATION:
                    restored = await self._check_and_restore_url(post_url)
                    if restored:
                        # أعد فتح التعليقات بعد العودة
                        logger.info("[🔄] إعادة فتح التعليقات بعد العودة للمنشور...")
                        await self._force_open_reels_comments()
                        await asyncio.sleep(2)

                # ── Time Management: إيقاف تلقائي بعد 4 دقائق ──
                elapsed = asyncio.get_event_loop().time() - self._scrape_start_time
                if elapsed > 240:
                    logger.warning(f"[⏰] Time Management: تجاوز 4 دقائق ({elapsed:.0f}ث) — حفظ ما تم جمعه والخروج")
                    break

                # ── Jiggle: كل 10 فاشلات متتالية (بدون حد أعلى) ──
                if empty_scrolls > 0 and empty_scrolls % 10 == 0:
                    logger.info(f"[🔀] {empty_scrolls} تمريرة فاشلة — تنفيذ Jiggle Scroll...")
                    await self._do_jiggle_scroll()
                    await asyncio.sleep(1.5)
                else:
                    await self._do_smart_scroll()

                # ── تأخير ديناميكي ──
                # بعد التمريرة 50: نوم أعمق (3-5ث) لأن الصفحات الطويلة تتقل
                if cfg.MOBILE_EMULATION:
                    if scroll_count >= 50:
                        await random_delay(3.0, 5.0)
                        logger.debug(f"[💤] Stay-Alive sleep (تمريرة {scroll_count}+50)")
                    else:
                        await random_delay(1.5, 3.0)
                else:
                    await random_delay(0.5, 1.0)

                await self._click_load_more_comments()
                scroll_count += 1

                # ── Lazy Loading Buffer: توقف كل 5 تمريرات ──
                if scroll_count % 5 == 0:
                    extra_wait = 3.0 if cfg.MOBILE_EMULATION else 2.0
                    logger.info(f"[⏳] توقف مؤقت للـ Lazy Loading بعد {scroll_count} تمريرة...")
                    await self._wait_for_spinner()
                    await asyncio.sleep(extra_wait)

                current_count = await self._get_loaded_comment_count()
                new_comments = max(current_count - previous_count, 0)
                total_new += new_comments
                previous_count = current_count

                logger.info(f"[📊] جاري سحب المزيد.. الإجمالي الحالي: {current_count} تعليق | فاشلة متتالية: {empty_scrolls}")

                empty_scrolls = 0 if new_comments > 0 else empty_scrolls + 1

                # ── Bottom Reach Check: هل وصلنا فعلاً للنهاية؟ ──
                # رفعنا الحد: 15 فاشلة متتالية + 25 scroll كلي قبل الفحص
                if empty_scrolls >= 15 and scroll_count > 25:
                    reached_end = await self._check_comments_end()
                    if reached_end:
                        break

                # ── Incremental Extraction: استخرج كل 10 تمريرات ──
                if post_url and scroll_count % 10 == 0:
                    logger.info(f"[💾] Incremental save بعد {scroll_count} تمريرة...")
                    try:
                        batch = await self._extract_leads_from_comments(post_url)
                        added = 0
                        for lead in batch:
                            uname = lead["username"].lower()
                            # ① صاحب المنشور → تجاهل
                            if self._post_owner and uname == self._post_owner.lower():
                                continue
                            # ② مكرر داخل الجلسة → تجاهل
                            if uname in self._seen_usernames:
                                continue
                            # ③ موجود في قاعدة البيانات → تجاهل
                            if db_check_fn:
                                try:
                                    if await db_check_fn(lead["username"]):
                                        logger.debug(f"[🔁] @{lead['username']} موجود في DB - تخطي")
                                        continue
                                except Exception:
                                    pass
                            self._seen_usernames.add(uname)
                            self._accumulated_leads.append(lead)
                            added += 1
                        if added:
                            logger.info(f"[💾] أُضيف {added} عميل جديد | الإجمالي المحفوظ: {len(self._accumulated_leads)}")
                    except Exception as inc_e:
                        logger.warning(f"[⚠️] خطأ في Incremental extraction: {inc_e}")

                if total_new >= self.target_new_comments:
                    logger.info(f"[✅] تم الوصول للعدد المطلوب: {total_new} تعليق جديد")
                    break
                if empty_scrolls >= 35:
                    logger.info(f"[⛔] لا تعليقات جديدة بعد 35 تمريرة متتالية - إيقاف السحب")
                    break
        except Exception as e:
            logger.error(f"خطأ أثناء التمرير: {e}")

        # ── الفحص النهائي: ضغط على أي زر تحميل مزيد ظاهر ──
        if previous_count < self.target_new_comments:
            await self._final_load_more_check()
            final_count = await self._get_loaded_comment_count()
            if final_count > previous_count:
                logger.info(f"[📈] الفحص النهائي أضاف {final_count - previous_count} تعليق إضافي")
                previous_count = final_count

        return scroll_count, previous_count

    async def _do_jiggle_scroll(self):
        """
        Jiggle: سحبة صغيرة لأعلى ثم سحبة كبيرة لأسفل لإجبار إنستغرام على Refresh.
        تُستخدم عندما تتوالى التمريرات بدون تعليقات جديدة.
        """
        try:
            # ① خطوة صغيرة لأعلى (100-200px)
            await self.page.evaluate("""
                () => {
                    const root =
                        document.querySelector('[role="dialog"]') ||
                        document.querySelector('[role="sheet"]') ||
                        document.querySelector('[role="main"]') ||
                        document.querySelector('main') ||
                        document.body;
                    const findScrollable = (r) => {
                        const walk = document.createTreeWalker(r, NodeFilter.SHOW_ELEMENT);
                        let node = walk.nextNode();
                        while (node) {
                            const st = window.getComputedStyle(node);
                            if ((st.overflowY === 'auto' || st.overflowY === 'scroll') &&
                                 node.scrollHeight > node.clientHeight + 10) return node;
                            node = walk.nextNode();
                        }
                        return r;
                    };
                    const target = findScrollable(root);
                    target.scrollTop = Math.max(0, target.scrollTop - 150);
                    window.scrollBy(0, -150);
                }
            """)
            await asyncio.sleep(0.6)

            # ② سحبة كبيرة لأسفل (scrollHeight كامل)
            await self.page.evaluate("""
                () => {
                    const root =
                        document.querySelector('[role="dialog"]') ||
                        document.querySelector('[role="sheet"]') ||
                        document.querySelector('[role="main"]') ||
                        document.querySelector('main') ||
                        document.body;
                    const findScrollable = (r) => {
                        const walk = document.createTreeWalker(r, NodeFilter.SHOW_ELEMENT);
                        let node = walk.nextNode();
                        while (node) {
                            const st = window.getComputedStyle(node);
                            if ((st.overflowY === 'auto' || st.overflowY === 'scroll') &&
                                 node.scrollHeight > node.clientHeight + 10) return node;
                            node = walk.nextNode();
                        }
                        return r;
                    };
                    const target = findScrollable(root);
                    target.scrollTop = target.scrollHeight;
                    [root,
                     root.firstElementChild,
                     root.querySelector('ul'),
                     root.querySelector('div > div'),
                    ].filter(Boolean).forEach(el => {
                        try { el.scrollTop = el.scrollHeight; } catch {}
                    });
                    window.scrollBy(0, 1200);
                }
            """)

            # ③ Touch Swipe كبير في الموبايل
            if cfg.MOBILE_EMULATION:
                box = await self.page.evaluate("""
                    () => ({ x: window.innerWidth / 2, startY: window.innerHeight * 0.80, endY: window.innerHeight * 0.10 })
                """)
                await self.page.evaluate(f"""
                    () => {{
                        const x = {box['x']}; const startY = {box['startY']}; const endY = {box['endY']};
                        const el = document.elementFromPoint(x, startY) || document.body;
                        el.dispatchEvent(new TouchEvent('touchstart', {{ bubbles:true, cancelable:true,
                            touches:[new Touch({{identifier:2,target:el,clientX:x,clientY:startY}})],
                            changedTouches:[new Touch({{identifier:2,target:el,clientX:x,clientY:startY}})] }}));
                        el.dispatchEvent(new TouchEvent('touchmove', {{ bubbles:true, cancelable:true,
                            touches:[new Touch({{identifier:2,target:el,clientX:x,clientY:endY}})],
                            changedTouches:[new Touch({{identifier:2,target:el,clientX:x,clientY:endY}})] }}));
                        el.dispatchEvent(new TouchEvent('touchend', {{ bubbles:true, cancelable:true,
                            touches:[],
                            changedTouches:[new Touch({{identifier:2,target:el,clientX:x,clientY:endY}})] }}));
                    }}
                """)
            logger.info("[🔀] Jiggle Scroll: أعلى → أسفل (تحديث إجباري للـ Lazy Loading)")
        except Exception as e:
            logger.debug(f"Jiggle scroll error: {e}")

    async def _check_comments_end(self) -> bool:
        """
        Bottom Reach Check: هل وصلنا لنهاية التعليقات فعلاً؟
        يبحث عن نصوص 'End of comments' أو اختفاء الـ Spinner + عدم وجود زر تحميل مزيد.
        """
        try:
            result = await self.page.evaluate("""
                () => {
                    const bodyText = (document.body?.innerText || '').toLowerCase();
                    const endPhrases = [
                        'no more comments', 'end of comments', 'no comments yet',
                        'لا مزيد من التعليقات', 'نهاية التعليقات', 'لا توجد تعليقات',
                        'لا تعليقات حتى الآن'
                    ];
                    const hasEndText = endPhrases.some(p => bodyText.includes(p));

                    const spinnerSels = [
                        '[aria-label*="Loading"]', '[aria-label*="تحميل"]',
                        'svg[aria-label*="Loading"]', '[role="progressbar"]',
                        '[data-testid*="spinner"]'
                    ];
                    const hasSpinner = spinnerSels.some(sel => {
                        const el = document.querySelector(sel);
                        return el && el.offsetParent !== null;
                    });

                    const moreButtonSels = [
                        'button[aria-label*="Load more"]',
                        'span[role="button"]',
                        'button'
                    ];
                    const moreTexts = ['load more', 'تحميل المزيد', 'view more', 'عرض المزيد'];
                    const hasMoreBtn = moreButtonSels.some(sel => {
                        const els = Array.from(document.querySelectorAll(sel));
                        return els.some(el => moreTexts.some(t => (el.innerText||'').toLowerCase().includes(t)));
                    });

                    return { hasEndText, hasSpinner, hasMoreBtn };
                }
            """)
            if result.get('hasEndText'):
                logger.info("[🏁] Bottom Reach: نص نهاية التعليقات مكتشف — توقف السحب")
                return True
            if not result.get('hasSpinner') and not result.get('hasMoreBtn'):
                # لا spinner ولا زر تحميل → قد نكون وصلنا للنهاية (نحتاج تأكيد بعدة تمريرات فاشلة)
                logger.debug("[🔍] Bottom Reach: لا Spinner ولا زر تحميل مزيد")
            return False
        except Exception as e:
            logger.debug(f"Bottom check error: {e}")
            return False

    async def _extra_scroll_for_comments(self):
        try:
            await self.page.evaluate("""
                () => {
                    const containers = [
                        document.querySelector('[role="dialog"] ul'),
                        document.querySelector('[role="dialog"]'),
                        document.querySelector('section ul'),
                        document.querySelector('main ul'),
                        document.querySelector('article ul'),
                        document.querySelector('main'),
                        document.scrollingElement,
                        document.documentElement,
                        document.body
                    ].filter(Boolean);
                    for (const container of containers) {
                        try {
                            container.scrollTop = container.scrollHeight;
                        } catch {}
                    }
                    window.scrollBy(0, 1200);
                }
            """)
        except Exception as e:
            logger.warning(f"تعذّر تنفيذ Scroll التحقق الإضافي: {e}")

    async def _click_load_more_comments(self):
        selectors = [
            'button[aria-label*="Load more"]',
            'button[aria-label*="تحميل المزيد"]',
            'span[role="button"]:has-text("Load more")',
            'span[role="button"]:has-text("تحميل المزيد")',
        ]
        for selector in selectors:
            try:
                btn = await self.page.query_selector(selector)
                if btn and await btn.is_visible():
                    await btn.click()
                    await random_delay(1, 2)
                    break
            except Exception:
                continue

    async def _click_view_replies(self):
        """
        يضغط على كل أزرار 'View replies' / 'مشاهدة الردود' لكشف الردود المخفية.
        يستمر حتى لا يجد أزراراً جديدة.
        """
        reply_texts = [
            "View replies", "View reply",
            "مشاهدة الردود", "مشاهدة الرد",
            "عرض الردود", "عرض الرد",
        ]
        selectors = [
            f'span[role="button"]:has-text("{t}")' for t in reply_texts
        ] + [
            f'button:has-text("{t}")' for t in reply_texts
        ] + [
            'span[role="button"][aria-label*="repl"]',
            'button[aria-label*="repl"]',
        ]

        clicked_total = 0
        for _round in range(5):
            clicked_this_round = 0
            for selector in selectors:
                try:
                    buttons = await self.page.query_selector_all(selector)
                    for btn in buttons:
                        try:
                            if await btn.is_visible():
                                await btn.click()
                                await random_delay(0.8, 1.5)
                                clicked_this_round += 1
                        except Exception:
                            continue
                except Exception:
                    continue
            clicked_total += clicked_this_round
            if clicked_this_round == 0:
                break
            await random_delay(1, 2)

        if clicked_total:
            logger.info(f"🔽 تم فتح {clicked_total} ردود مخفية (View replies)")

    # ─────────────────────────────────────────────────────────────
    #  استخراج العملاء - الاستراتيجية المحسّنة
    # ─────────────────────────────────────────────────────────────

    @staticmethod
    def _has_real_text(text: str) -> bool:
        """يقبل أي نص يحتوي على حرف واحد على الأقل (عربي أو إنجليزي)"""
        return bool(_HAS_LETTER.search(text))

    async def _extract_leads_from_comments(self, post_url: str) -> list[dict]:
        """
        استخراج التعليقات الفعلية باستخدام Parent-Scan و JavaScript ذكي.
        يتحقق أولاً من أن المتصفح لا يزال على صفحة المنشور (Navigation Guard).
        """
        leads = []
        seen_usernames = set()
        logged_in_user = (cfg.INSTAGRAM_USERNAME or "").strip().lower()

        # ── Navigation Guard قبل الاستخراج ──
        if cfg.MOBILE_EMULATION:
            restored = await self._check_and_restore_url(post_url)
            if restored:
                logger.info("[🔄] استُعيد الرابط قبل الاستخراج — إعادة فتح التعليقات...")
                await self._force_open_reels_comments()
                await asyncio.sleep(2)

        try:
            raw = await self.page.evaluate("""
                ([loggedInUser, postOwner, targetCaption]) => {
                    const textOf = el => (el?.innerText || el?.textContent || '').replace(/\s+/g, ' ').trim();

                    // ══════════════════════════════════════════════════════
                    // [5] Clean the DOM: احذف العنصر الأول (Index 0) من
                    //     قائمة التعليقات برمجياً قبل بدء الـ Loop —
                    //     لأنه غالباً الكابشن المزور.
                    // ══════════════════════════════════════════════════════
                    (() => {
                        const commentLists = [
                            document.querySelector('[role="dialog"] ul'),
                            document.querySelector('[role="sheet"] ul'),
                            document.querySelector('[role="main"] ul'),
                            document.querySelector('article ul'),
                            document.querySelector('main ul'),
                        ].filter(Boolean);
                        for (const ul of commentLists) {
                            const firstItem = ul.querySelector('li, [role="listitem"]');
                            if (firstItem) { firstItem.remove(); break; }
                        }
                    })();

                    // ══════════════════════════════════════════════════════
                    // [2] Full Blacklist Matching:
                    //   أ) مطابقة مباشرة: النص = الكابشن تماماً
                    //   ب) 3+ كلمات متتالية من الكابشن موجودة في النص
                    // ══════════════════════════════════════════════════════
                    const normalizeText = t => (t || '').replace(/\s+/g, ' ').replace(/[!?.،]/g, '').trim().toLowerCase();

                    const hasCaptionSequence = (text, caption) => {
                        if (!caption || !text) return false;
                        const normText    = normalizeText(text);
                        const normCaption = normalizeText(caption);
                        // أ) مطابقة مباشرة (كاملة أو شبه كاملة)
                        if (normText === normCaption) return true;
                        if (normCaption.length > 5 && normText.includes(normCaption)) return true;
                        if (normCaption.length > 5 && normCaption.includes(normText)) return true;
                        // ب) 3+ كلمات متتالية (بدون فلتر على طول الكلمة)
                        const captionWords = normCaption.split(/\s+/).filter(w => w.length >= 1);
                        if (captionWords.length < 3) return false;
                        const seqLen = Math.min(3, captionWords.length);
                        for (let i = 0; i <= captionWords.length - seqLen; i++) {
                            const seq = captionWords.slice(i, i + seqLen).join(' ');
                            if (normText.includes(seq)) return true;
                        }
                        return false;
                    };

                    // ══════════════════════════════════════════════════════
                    // [3] Length-Based Exclusion: نسبة تشابه Jaccard
                    //     على مستوى الكلمات (كل الكلمات بدون حد أدنى)
                    // ══════════════════════════════════════════════════════
                    const similarityRatio = (text, caption) => {
                        if (!caption || !text) return 0;
                        const words1 = new Set(normalizeText(text).split(/\s+/).filter(Boolean));
                        const words2 = new Set(normalizeText(caption).split(/\s+/).filter(Boolean));
                        if (words2.size === 0) return 0;
                        let intersection = 0;
                        for (const w of words1) if (words2.has(w)) intersection++;
                        return intersection / Math.max(words1.size, words2.size);
                    };

                    const cleanHref = href => {
                        if (!href) return '';
                        let path = href;
                        try { path = href.startsWith('http') ? new URL(href).pathname : href; } catch {}
                        return path.replace(/^\//, '').replace(/\/$/, '').trim();
                    };

                    const isProfileHref = href => {
                        if (!href) return false;
                        const p = href.startsWith('/') ? href : (() => {
                            try { return new URL(href).pathname; } catch { return href; }
                        })();
                        return /^\/[^\/]+\/$/.test(p) &&
                               !p.includes('/p/') && !p.includes('/explore/') &&
                               !p.includes('/reels/') && !p.includes('/stories/') &&
                               !p.includes('/accounts/') && !p.includes('/tags/') &&
                               !p.includes('/direct/') && !p.includes('/about/') &&
                               !p.includes('/privacy/') && !p.includes('/legal/');
                    };

                    const getPostAuthor = () => {
                        const headerSelectors = [
                            'article header',
                            'div[role="dialog"] header',
                            'div[role="presentation"] header',
                            'main header',
                            'header'
                        ];
                        for (const selector of headerSelectors) {
                            const header = document.querySelector(selector);
                            if (!header) continue;
                            const links = Array.from(header.querySelectorAll('a[href]'))
                                .filter(a => isProfileHref(a.getAttribute('href')));
                            if (links.length) return cleanHref(links[0].getAttribute('href'));
                        }
                        const roots = [
                            document.querySelector('[role="dialog"]'),
                            document.querySelector('div[role="presentation"]'),
                            document.querySelector('div.x168nmei'),
                            document.querySelector('div[class*="x168nmei"]'),
                            document.querySelector('article'),
                            document.querySelector('main'),
                            document.body
                        ].filter(Boolean);
                        for (const root of roots) {
                            for (const link of root.querySelectorAll('a[href]')) {
                                if (isProfileHref(link.getAttribute('href'))) {
                                    return cleanHref(link.getAttribute('href'));
                                }
                            }
                        }
                        return null;
                    };

                    const getSearchRoots = () => {
                        const roots = [
                            // Dialog (ديسك توب)
                            document.querySelector('[role="dialog"]'),
                            // Bottom Sheet (موبايل)
                            document.querySelector('[role="sheet"]'),
                            document.querySelector('[role="main"]'),
                            // عناصر أخرى
                            document.querySelector('div[role="presentation"]'),
                            document.querySelector('div.x168nmei'),
                            document.querySelector('div[class*="x168nmei"]'),
                            document.querySelector('section'),
                            document.querySelector('article'),
                            document.querySelector('main'),
                            document.body
                        ].filter(Boolean);
                        return roots.filter((root, index) => roots.indexOf(root) === index);
                    };

                    const getRootProfileLinks = roots => {
                        const seenHrefs = new Set();
                        const links = [];
                        for (const root of roots) {
                            for (const link of root.querySelectorAll('a[href]')) {
                                const href = link.getAttribute('href') || '';
                                if (!isProfileHref(href)) continue;
                                const key = cleanHref(href).toLowerCase();
                                if (!key || seenHrefs.has(key + '::' + textOf(link))) continue;
                                seenHrefs.add(key + '::' + textOf(link));
                                links.push(link);
                            }
                        }
                        return links;
                    };

                    const extractLooseReelsRows = roots => {
                        const rows = [];
                        for (const root of roots) {
                            const containers = Array.from(root.querySelectorAll(
                                'div.x168nmei, div[class*="x168nmei"], div[role="presentation"], ul li, [role="listitem"]'
                            ));
                            for (const container of containers) {
                                const links = Array.from(container.querySelectorAll('a[href]')).filter(a => isProfileHref(a.getAttribute('href')));
                                // ── تأكد من تعليق مفرد: بروفايل واحد بالضبط ──
                                if (links.length !== 1) continue;
                                const spans = Array.from(container.querySelectorAll('span'))
                                    // ── استبعاد spans تحتوي [role="button"] (نص الكابشن / المزيد) ──
                                    .filter(s => !s.querySelector('[role="button"]'))
                                    .filter(s => !s.closest('a[href], time, button, [role="button"]'))
                                    .map(textOf)
                                    .filter(Boolean)
                                    .filter(text => !badText(text));
                                for (const link of links) {
                                    const username = cleanHref(link.getAttribute('href'));
                                    const text = spans.find(spanText => spanText.toLowerCase() !== username.toLowerCase());
                                    if (username && text) rows.push({ username, text, method: 'reels-container-scan' });
                                }
                            }
                        }
                        return rows;
                    };

                    // ── Owner Filter: استخدم postOwner المستخرج مسبقاً من Python ──
                    const postAuthor = (postOwner && postOwner.trim()) ? postOwner.trim() : getPostAuthor();
                    const blacklist = new Set();
                    blacklist.add('applewinning10');
                    if (postAuthor) blacklist.add(postAuthor.toLowerCase());
                    if (loggedInUser) blacklist.add(loggedInUser.toLowerCase());

                    // ── Facebook Comments Bypass ──
                    const isFacebookSection = el => {
                        let node = el;
                        for (let i = 0; node && i < 8; i++) {
                            const text = (node.innerText || node.textContent || '').slice(0, 200).toLowerCase();
                            if (text.includes('this reel has comments from facebook') ||
                                text.includes('has comments from facebook') ||
                                text.includes('comments from facebook')) return true;
                            node = node.parentElement;
                        }
                        return false;
                    };

                    const badText = text => {
                        const t = (text || '').replace(/\s+/g, ' ').trim();
                        const low = t.toLowerCase();
                        if (t.length < 2) return true;
                        if (/^\d+(w|h|m|d|s|ث|د|س|ي)?$/i.test(t)) return true;
                        if (/^[•·.]+$/.test(t)) return true;
                        // ── "X comments / replies / likes" (e.g. "8 comments", "5 likes") ──
                        if (/^\d+\s*(comments?|replies?|likes?|تعليقات?|ردود?|إعجاب)$/i.test(t)) return true;
                        // ── نص بلا حروف حقيقية (إيموجي + رقم مثل "❤️ 5") ──
                        if (!/[a-zA-Z\u0600-\u06FF]/.test(t)) return true;
                        // ── Deep Content Cleaning: Facebook / فيسبوك ──
                        if (low.includes('facebook') || low.includes('فيسبوك')) return true;
                        // ── Caption Guard: نصوص تنتهي بـ "المزيد" أو "see more" هي Caption لا تعليق ──
                        if (low.endsWith('المزيد') || low.endsWith('...المزيد') ||
                            low.endsWith('see more') || low.endsWith('...see more')) return true;
                        return [
                            'follow', 'following', 'reply', 'replies', 'view replies',
                            'see translation', 'translation', 'like', 'liked',
                            'متابعة', 'يتابع', 'رد', 'الرد', 'ردود', 'عرض الردود',
                            'مشاهدة الردود', 'أعجبني', 'ترجمة', 'عرض الترجمة'
                        ].some(word => low.includes(word));
                    };

                    const isCleanSpan = (span, username) => {
                        if (!span || span.closest('a[href]')) return false;
                        if (span.querySelector('a[href]')) return false;
                        // ── منع spans تحتوي زر "المزيد" / "See more" (نص الكابشن) ──
                        if (span.querySelector('[role="button"]')) return false;
                        if (span.closest('time, button, [role="button"]')) return false;
                        const text = textOf(span);
                        if (!text || text.toLowerCase() === (username || '').toLowerCase()) return false;
                        return !badText(text);
                    };

                    const nearestCommentRoot = link => {
                        // ① أولوية قصوى: li أو listitem (تعليق واحد مضمون)
                        const preferred = link.closest('li, [role="listitem"]');
                        if (preferred) return preferred;
                        // ② div مع class خاص بإنستجرام
                        const igDiv = link.closest('div.x168nmei, div[class*="x168nmei"]');
                        if (igDiv) return igDiv;
                        // ③ تصاعد تدريجي - توقف عند أصغر حاوية تحتوي بروفايل واحد بالضبط
                        let node = link.parentElement;
                        for (let depth = 0; node && depth < 6; depth += 1) {
                            const pLinks = Array.from(node.querySelectorAll('a[href]'))
                                .filter(a => isProfileHref(a.getAttribute('href')));
                            if (pLinks.length === 1) return node;
                            // إذا تجاوز 1 → الحاوية واسعة جداً → ارجع للأب المباشر للرابط (أحفظ)
                            if (pLinks.length > 1) return link.parentElement;
                            node = node.parentElement;
                        }
                        return link.parentElement;
                    };

                    const textFromParentScan = (link, username) => {
                        // ── حد أعلى: لا نتجاوز nearestCommentRoot حتى لا نسحب Caption المنشور ──
                        const boundary = nearestCommentRoot(link);
                        let node = link.parentElement;
                        for (let depth = 0; node && depth < 9; depth += 1) {
                            const spans = Array.from(node.querySelectorAll('span'))
                                .filter(span => isCleanSpan(span, username))
                                .map(textOf)
                                .filter((text, index, arr) => arr.indexOf(text) === index)
                                // ── Caption Guard: لا نقبل أي span نصه هو الكابشن ──
                                .filter(text => !hasCaptionSequence(text, targetCaption));
                            const direct = spans.find(text => text.length > 1);
                            if (direct) return direct;
                            if (node === boundary) break;
                            node = node.parentElement;
                        }
                        return '';
                    };

                    const textAfterUsername = (link, username) => {
                        const root = nearestCommentRoot(link);
                        if (!root) return '';
                        const profileLinks = new Set(
                            Array.from(root.querySelectorAll('a[href]'))
                                .filter(a => isProfileHref(a.getAttribute('href')))
                        );
                        const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
                        const pieces = [];
                        let collecting = false;
                        while (walker.nextNode()) {
                            const node = walker.currentNode;
                            const parent = node.parentElement;
                            if (!parent) continue;
                            const value = (node.nodeValue || '').replace(/\s+/g, ' ').trim();
                            if (!value) continue;
                            const ownerLink = parent.closest('a[href]');
                            if (ownerLink === link || value.toLowerCase() === username.toLowerCase()) {
                                collecting = true;
                                continue;
                            }
                            if (!collecting) continue;
                            if (ownerLink && profileLinks.has(ownerLink)) break;
                            if (parent.closest('time, button, [role="button"]')) continue;
                            if (badText(value)) continue;
                            if (value.toLowerCase() === username.toLowerCase()) continue;
                            // ── Caption Guard: لا نضم قطع نص مشابهة للكابشن ──
                            if (hasCaptionSequence(value, targetCaption)) continue;
                            pieces.push(value);
                            if (pieces.join(' ').length >= 180) break;
                        }
                        const result = pieces.join(' ').replace(/\s+/g, ' ').trim();
                        // رفض النتيجة الكاملة لو هي الكابشن
                        return hasCaptionSequence(result, targetCaption) ? '' : result;
                    };

                    const escapeRegex = value => value.replace(/[-/\\^$*+?.()|[\]{}]/g, '\\$&');

                    const textByCloneCleanup = (link, username) => {
                        const root = nearestCommentRoot(link);
                        if (!root) return '';
                        const clone = root.cloneNode(true);
                        clone.querySelectorAll('a[href], time, button, [role="button"]').forEach(el => el.remove());
                        const text = textOf(clone)
                            .replace(new RegExp('^' + escapeRegex(username) + '\\b', 'i'), '')
                            .trim();
                        if (badText(text)) return '';
                        // ── Caption Guard: لا نقبل النص إذا كان هو الكابشن ──
                        if (hasCaptionSequence(text, targetCaption)) return '';
                        return text;
                    };

                    const searchRoots = getSearchRoots();
                    const profileLinks = getRootProfileLinks(searchRoots);
                    const results = [];
                    const debugSamples = [];
                    const seen = new Set();

                    const addResult = (username, rawText, method) => {
                        if (!username || username.includes('/') || username.length < 2) return;
                        if (blacklist.has(username.toLowerCase())) return;
                        const text = (rawText || '').replace(/\s+/g, ' ').trim();
                        debugSamples.push({ username, text: text || '(فارغ)', method });
                        if (!text || text.toLowerCase() === username.toLowerCase()) return;
                        if (badText(text)) return;
                        // ── [2] Full Blacklist Matching: 5+ كلمات متتالية من الكابشن ──
                        if (hasCaptionSequence(text, targetCaption)) return;
                        // ── [3] Length-Based Exclusion: طويل + تشابه 30%+ مع الكابشن ──
                        if (text.length > 200 && similarityRatio(text, targetCaption) >= 0.30) return;
                        const key = username.toLowerCase() + '::' + text.substring(0, 120).toLowerCase();
                        if (seen.has(key)) return;
                        seen.add(key);
                        results.push({ username, text, method });
                    };

                    for (const link of profileLinks) {
                        // ── Facebook Comments Bypass: تجاهل روابط داخل قسم Facebook ──
                        if (isFacebookSection(link)) continue;
                        const username = cleanHref(link.getAttribute('href'));
                        if (!username || blacklist.has(username.toLowerCase())) continue;
                        // ── [4] Identifier Check: listitem يبدأ بـ loggedInUser →
                        //     منطقة محظورة — تجاهل نص التعليق كلياً ──
                        if (loggedInUser && username.toLowerCase() === loggedInUser.toLowerCase()) continue;
                        const parentText = textFromParentScan(link, username);
                        const followingText = textAfterUsername(link, username);
                        const fallbackText = textByCloneCleanup(link, username);
                        const method = parentText ? 'parent-scan' : followingText ? 'evaluate-next-text' : 'clone-cleanup';
                        addResult(username, parentText || followingText || fallbackText, method);
                    }

                    for (const item of extractLooseReelsRows(searchRoots)) {
                        addResult(item.username, item.text, item.method);
                    }

                    return {
                        postAuthor,
                        blacklist: [...blacklist],
                        profileLinksSeen: profileLinks.length,
                        debugSamples: debugSamples.slice(0, 15),
                        results
                    };
                }
            """, [logged_in_user, self._post_owner, self.target_caption])

            post_author = raw.get("postAuthor") or "غير محدد"
            profile_links_seen = raw.get("profileLinksSeen", 0)
            comments_data = raw.get("results", [])
            total_comments = len(comments_data)

            logger.info(
                f"[🔎] روابط مستخدمين مكتشفة: {profile_links_seen} | "
                f"تعليقات صالحة: {total_comments} | صاحب المنشور: {post_author}"
            )

            # ── Debug Screenshot: لقطة شاشة فورية إذا كان الإجمالي 0 ──
            if total_comments == 0:
                logger.warning(
                    f"[⚠️] الإجمالي 0 تعليق! (روابط مكتشفة: {profile_links_seen}) - التقاط لقطة شاشة تشخيصية"
                )
                await self._take_debug_screenshot("zero_comments_inside_dialog")
                await self._log_element_counts()

            # سطر واحد مختصر فقط
            logger.info(
                f"PROGRESS_COMMENTS total={total_comments} checked=0 leads=0"
            )

            batch_logged = False
            for checked, item in enumerate(comments_data, 1):
                # طباعة مرة كل 20 عميل فقط
                if checked % 20 == 1 and not batch_logged:
                    logger.info(f"[⚡] جاري معالجة مجموعة تعليقات...")
                    batch_logged = False
                if checked % 20 == 0:
                    logger.info(
                        f"PROGRESS_COMMENTS total={total_comments} "
                        f"checked={checked} leads={len(leads)}"
                    )
                    batch_logged = True
                else:
                    batch_logged = False

                username = item.get("username", "").strip()
                comment_text = item.get("text", "").strip()

                if not username or username in seen_usernames:
                    continue
                if "/" in username or len(username) < 2:
                    continue
                if username.lower() == logged_in_user:
                    continue
                if post_author and username.lower() == post_author.lower():
                    continue
                # ── Strict Owner Filter: مقارنة مع self._post_owner المستخرج مبكراً ──
                if self._post_owner and username.lower() == self._post_owner.lower():
                    logger.debug(f"[🚫] تم حذف صاحب المنشور @{username} من النتائج")
                    continue
                # ── Deep Content Cleaning: استبعاد نصوص تحتوي Facebook/فيسبوك ──
                comment_lower = comment_text.lower()
                if 'facebook' in comment_lower or 'فيسبوك' in comment_lower:
                    logger.debug(f"[🚫] تخطي @{username} - نص يحتوي Facebook/فيسبوك")
                    continue
                # ── Incremental UX: تنظيف نصوص "Reply" و "X comments" ──
                import re as _re
                comment_text = _re.sub(r'\b\d+\s*(comments?|replies?|تعليقات?|ردود?)\b', '', comment_text, flags=_re.IGNORECASE).strip()
                comment_text = _re.sub(r'\b(Reply|Replies|View replies|مشاهدة الردود|عرض الردود)\b', '', comment_text, flags=_re.IGNORECASE).strip()
                comment_text = _re.sub(r'\s{2,}', ' ', comment_text).strip()
                if not comment_text or comment_text.lower() == username.lower():
                    logger.debug(f"تخطي @{username} - النص فارغ أو هو الاسم نفسه بعد التنظيف")
                    continue

                if self._has_real_text(comment_text):
                    seen_usernames.add(username)
                    leads.append({
                        "username": username,
                        "comment_text": comment_text,
                        "post_url": post_url,
                    })

                    pass  # تمت إضافة العميل للقائمة

                if checked == total_comments:
                    logger.info(
                        f"PROGRESS_COMMENTS total={total_comments} "
                        f"checked={checked} leads={len(leads)}"
                    )

        except Exception as e:
            logger.error(f"خطأ في استخراج التعليقات: {e}")
            await take_error_screenshot(self.page, "extract_comments_error")

        return leads

    def set_keywords(self, keywords: list):
        self.keywords = keywords
