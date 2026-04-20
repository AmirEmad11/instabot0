"""
وحدة إدارة الجلسات (Session Manager)
- الأولوية للكوكيز المحفوظة: يتحقق من الجلسة أولاً دون فتح صفحة الدخول إطلاقاً
- كتابة بشرية حقيقية مع delay=150ms لمحاكاة الإنسان
- User-Agent ويندوز حقيقي لتقليل الشك
- wait_for_selector لا يوقف البرنامج بل يعطي تحذير واضح
"""

import json
import logging
import os; os.environ["LD_LIBRARY_PATH"] = "/run/current-system/sw/lib:/run/opengl-driver/lib"
from pathlib import Path
from playwright.async_api import (
    async_playwright,
    Browser,
    BrowserContext,
    Page,
    Playwright,
)
from config import (
    SESSION_FILE,
    HEADLESS_MODE,
    VIEWPORT_WIDTH,
    VIEWPORT_HEIGHT,
    INSTAGRAM_USERNAME,
    INSTAGRAM_PASSWORD,
    MOBILE_EMULATION,
)
from utils import random_delay, take_error_screenshot

logger = logging.getLogger(__name__)

# User-Agent ويندوز (fallback)
WINDOWS_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/123.0.0.0 Safari/537.36"
)

# User-Agent iPhone 15 Pro Max لمحاكاة الموبايل البشرية
IPHONE_USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/17.2 Mobile/15E148 Safari/604.1"
)


class SessionManager:

    def __init__(self):
        self.playwright: Playwright = None
        self.browser: Browser = None
        self.context: BrowserContext = None
        self.page: Page = None

    # ─────────────────────────────────────────────────────────────
    #  تنظيف الكوكيز (Cookie Sanitization)
    # ─────────────────────────────────────────────────────────────

    VALID_SAME_SITE = {"Strict", "Lax", "None"}

    @staticmethod
    def _sanitize_cookie(cookie: dict) -> dict:
        """
        ينظّف كوكي واحد قبل حقنه في Playwright:
        - sameSite: إذا لم تكن Strict/Lax/None يُحوَّل إلى Lax
        - expires: يُحوَّل إلى float إذا كان نصاً
        - no_restriction: يُحوَّل إلى None ليتوافق مع Playwright
        """
        cookie = dict(cookie)

        # ── sameSite ──
        same_site = cookie.get("sameSite", "Lax")
        if same_site not in SessionManager.VALID_SAME_SITE:
            logger.debug(
                f"🍪 sameSite غير صالح '{same_site}' في كوكي '{cookie.get('name', '?')}' → تحويل إلى Lax"
            )
            cookie["sameSite"] = "Lax"

        # ── expires ──
        expires = cookie.get("expires")
        if expires is not None and isinstance(expires, str):
            try:
                cookie["expires"] = float(expires)
                logger.debug(f"🍪 expires تم تحويله من نص إلى float للكوكي '{cookie.get('name', '?')}'")
            except (ValueError, TypeError):
                logger.warning(f"⚠️ تعذّر تحويل expires='{expires}' للكوكي '{cookie.get('name', '?')}' - تم حذفه")
                cookie.pop("expires", None)

        # ── no_restriction → None ──
        for key, value in list(cookie.items()):
            if value == "no_restriction":
                logger.debug(f"🍪 القيمة 'no_restriction' في حقل '{key}' للكوكي '{cookie.get('name', '?')}' → تحويل إلى None")
                cookie[key] = None

        return cookie

    @classmethod
    def _sanitize_storage_state(cls, session_path: Path) -> dict | None:
        """
        يقرأ ملف الجلسة وينظّف جميع الكوكيز قبل تمريرها لـ Playwright.
        يعيد None إذا فشلت القراءة.
        """
        try:
            with open(session_path, "r", encoding="utf-8") as f:
                state = json.load(f)
            original_cookies = state.get("cookies", [])
            state["cookies"] = [cls._sanitize_cookie(c) for c in original_cookies]
            logger.info(f"🧹 تم تنظيف {len(state['cookies'])} كوكي بنجاح")
            return state
        except Exception as e:
            logger.warning(f"⚠️ فشل قراءة/تنظيف ملف الجلسة: {e}")
            return None

    @staticmethod
    def _chromium_executable_path() -> str:
        candidates = [
            os.environ.get("CHROMIUM_PATH"),
            "/usr/bin/chromium",
            "/usr/bin/chromium-browser",
            "/run/current-system/sw/bin/chromium",
            "/run/current-system/sw/bin/chromium-browser",
        ]
        store_candidates = []
        try:
            for name in os.listdir("/nix/store"):
                if "chromium" not in name.lower() and "playwright" not in name.lower():
                    continue
                base = Path("/nix/store") / name
                for rel in ("bin/chromium", "bin/chromium-browser"):
                    store_candidates.append(str(base / rel))
                try:
                    for child in base.iterdir():
                        if child.name.startswith("chromium-"):
                            store_candidates.append(str(child / "chrome-linux" / "chrome"))
                except OSError:
                    pass
                browsers = base / "browsers"
                try:
                    for child in browsers.iterdir():
                        if child.name.startswith("chromium-"):
                            store_candidates.append(str(child / "chrome-linux" / "chrome"))
                except OSError:
                    pass
        except OSError:
            pass
        candidates.extend(sorted(store_candidates, reverse=True))
        for candidate in candidates:
            if candidate and Path(candidate).exists() and os.access(candidate, os.X_OK):
                return candidate
        raise RuntimeError("Chromium executable not found.")

    async def start(self) -> Page:
        import traceback as tb
        try:
            os.environ.setdefault("PLAYWRIGHT_SKIP_VALIDATE_HOST_REQUIREMENTS", "true")
            logger.info("🔧 جاري تهيئة Playwright...")
            self.playwright = await async_playwright().start()

            executable_path = self._chromium_executable_path()
            print(f"[BOT] Using Chromium: {executable_path}", flush=True)

            launch_args = [
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--single-process",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
                "--disable-web-security",
                "--disable-features=IsolateOrigins,site-per-process",
                "--disable-gpu",
            ]
            if MOBILE_EMULATION:
                launch_args += [
                    "--enable-touch-events",
                    "--touch-events=enabled",
                ]

            self.browser = await self.playwright.chromium.launch(
                executable_path=executable_path,
                headless=True,
                timeout=60000,
                args=launch_args,
            )
            logger.info("✅ تم تشغيل Chromium بنجاح")
        except Exception as e:
            err = f"❌ فشل تشغيل المتصفح: {e}\n{tb.format_exc()}"
            logger.error(err)
            print(err, flush=True)
            raise

        try:
            if MOBILE_EMULATION:
                selected_ua = IPHONE_USER_AGENT
                logger.info("📱 وضع الموبايل: iPhone 15 Pro Max (390×844 + touch)")
            else:
                selected_ua = WINDOWS_USER_AGENT
                logger.info("🖥️ وضع سطح المكتب: Windows Chrome")

            context_options = {
                "user_agent": selected_ua,
                "viewport": {"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT},
                "locale": "ar-SA",
                "timezone_id": "Asia/Riyadh",
                "java_script_enabled": True,
                "has_touch": MOBILE_EMULATION,
                "is_mobile": MOBILE_EMULATION,
                "extra_http_headers": {
                    "Accept-Language": "ar-SA,ar;q=0.9,en-US;q=0.8,en;q=0.7",
                },
            }

            session_path = Path(SESSION_FILE)
            if session_path.exists():
                logger.info("📂 تحميل جلسة محفوظة مع تنظيف الكوكيز...")
                sanitized_state = self._sanitize_storage_state(session_path)
                if sanitized_state is not None:
                    context_options["storage_state"] = sanitized_state
                else:
                    logger.warning("⚠️ فشل تنظيف الجلسة - سيتم تجاهل ملف الجلسة")

            self.context = await self.browser.new_context(**context_options)
            await self.context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
                window.chrome = { runtime: {} };
            """)
            self.page = await self.context.new_page()
            return self.page
        except Exception as e:
            import traceback as tb2
            err = f"❌ فشل إنشاء Context: {e}\n{tb2.format_exc()}"
            logger.error(err)
            raise

    # ─────────────────────────────────────────────────────────────
    #  الكتابة البشرية (Human Typing)
    # ─────────────────────────────────────────────────────────────

    async def _human_type(self, selector: str, text: str, delay: int = 150):
        """
        كتابة بشرية حقيقية حرفاً بحرف مع تأخير delay milliseconds
        بدلاً من fill() السريع الذي يكشفه Instagram فوراً.
        يستخدم tap() في وضع الموبايل لمحاكاة اللمس.
        """
        import config as cfg
        if cfg.MOBILE_EMULATION:
            await self.page.tap(selector)
        else:
            await self.page.click(selector)
        await random_delay(0.3, 0.7)
        await self.page.keyboard.press("Control+a")
        await self.page.keyboard.press("Delete")
        await random_delay(0.2, 0.5)
        await self.page.keyboard.type(text, delay=delay)
        await random_delay(0.3, 0.8)

    # ─────────────────────────────────────────────────────────────
    #  wait_for_selector آمن (لا يوقف البرنامج)
    # ─────────────────────────────────────────────────────────────

    async def _safe_wait_for_selector(self, selector: str, timeout: int = 15000, label: str = "") -> bool:
        """
        wait_for_selector آمن: يعطي تحذير واضح إذا لم يجد العنصر
        بدلاً من إيقاف البرنامج بالكامل.
        """
        try:
            await self.page.wait_for_selector(selector, timeout=timeout)
            return True
        except Exception:
            desc = label or selector
            logger.warning(f"⚠️ العنصر '{desc}' لم يُعثر عليه خلال {timeout//1000}ث")
            return False

    # ─────────────────────────────────────────────────────────────
    #  لقطة شاشة تشخيصية مع إرسال المسار للـ log
    # ─────────────────────────────────────────────────────────────

    async def _debug_screenshot(self, filename: str) -> str:
        """
        يأخذ لقطة شاشة ويُعيد المسار الكامل.
        يُطبع في الـ log بصيغة خاصة تلتقطها واجهة Streamlit.
        """
        try:
            path = Path(filename).resolve()
            await self.page.screenshot(path=str(path))
            logger.info(f"DEBUG_SCREENSHOT:{path}")
            return str(path)
        except Exception as e:
            logger.warning(f"⚠️ فشل أخذ لقطة الشاشة: {e}")
            return ""

    # ─────────────────────────────────────────────────────────────
    #  التحقق الصارم من تسجيل الدخول
    # ─────────────────────────────────────────────────────────────

    async def _strict_login_check(self) -> bool:
        """
        تحقق صارم: يبحث عن عناصر واجهة Instagram التي تظهر
        فقط عند تسجيل الدخول.
        """
        try:
            username = INSTAGRAM_USERNAME.strip()

            # أسلوب 1: رابط بروفايل المستخدم في شريط التنقل
            if username:
                profile_link = await self.page.query_selector(
                    f'a[href="/{username}/"], nav a[href="/{username}"]'
                )
                if profile_link:
                    logger.info(f"✅ تسجيل الدخول مؤكد: وُجد رابط بروفايل @{username}")
                    return True

            # أسلوب 2: أيقونات شريط التنقل (تظهر فقط لمن سجّل الدخول)
            nav_selectors = [
                'a[href="/direct/inbox/"]',
                'svg[aria-label="Direct"]',
                'svg[aria-label="New post"]',
                'svg[aria-label="Home"]',
                'a[aria-label="Home"]',
                '[aria-label="Create"]',
                '[aria-label="إنشاء"]',
                '[aria-label="الرئيسية"]',
            ]
            for sel in nav_selectors:
                el = await self.page.query_selector(sel)
                if el:
                    logger.info(f"✅ تسجيل الدخول مؤكد: عنصر '{sel}' موجود")
                    return True

            # أسلوب 3: فحص محتوى الصفحة - بيانات المستخدم المسجل
            content = await self.page.content()
            if ('"viewer":{' in content or
                    (username and f'"username":"{username}"' in content)):
                logger.info("✅ تسجيل الدخول مؤكد: بيانات المستخدم موجودة في الصفحة")
                return True

            # أسلوب 4: إذا وُجد زر "Log in" → غير مسجّل قطعاً
            login_btn = await self.page.query_selector(
                'button:has-text("Log in"), a:has-text("Log in"), '
                'button:has-text("Log In"), input[value="Log In"]'
            )
            if login_btn:
                logger.warning("⚠️ زر تسجيل الدخول موجود - الجلسة منتهية")
                return False

            # لقطة للتشخيص إذا لم نتأكد
            await self._debug_screenshot("debug_login_check.png")
            logger.warning("⚠️ تعذّر تأكيد حالة تسجيل الدخول - تحقق من لقطة الشاشة أعلاه")
            return False

        except Exception as e:
            logger.error(f"خطأ في _strict_login_check: {e}")
            return False

    async def ensure_logged_in(self) -> bool:
        """
        الأولوية للكوكيز المحفوظة:
        1. إذا وُجد ملف الجلسة → يفتح الصفحة الرئيسية مباشرةً (لا صفحة دخول)
        2. يتحقق صارماً من الجلسة
        3. إذا فشلت الجلسة → يسجّل الدخول بالمعتاد
        """
        try:
            session_path = Path(SESSION_FILE)

            if session_path.exists():
                logger.info("🍪 جلسة محفوظة موجودة - فتح الصفحة الرئيسية مباشرةً...")
                try:
                    await self.page.goto(
                        "https://www.instagram.com/",
                        wait_until="domcontentloaded",
                        timeout=60000,
                    )
                    await random_delay(2, 4)

                    screenshot_path = await self._debug_screenshot("debug_homepage.png")
                    logger.info(f"📸 لقطة الصفحة الرئيسية: {screenshot_path}")

                    current_url = self.page.url
                    logger.info(f"🌐 URL الحالي: {current_url}")

                    if "/accounts/login" in current_url:
                        logger.warning("⚠️ الجلسة المحفوظة انتهت - الانتقال لتسجيل الدخول...")
                        return await self.login()

                    is_logged_in = await self._strict_login_check()
                    if is_logged_in:
                        logger.info("✅ الجلسة سارية - لم يُفتح صفحة الدخول إطلاقاً")
                        return True

                    logger.warning("⚠️ الجلسة لم تنجح - محاولة تسجيل الدخول...")
                except Exception as nav_err:
                    logger.warning(f"⚠️ خطأ في فتح الصفحة الرئيسية: {nav_err}")
            else:
                logger.info("ℹ️ لا توجد جلسة محفوظة - الانتقال لتسجيل الدخول...")

            return await self.login()

        except Exception as e:
            import traceback as tb
            logger.error(f"خطأ في ensure_logged_in: {e}\n{tb.format_exc()}")
            return await self.login()

    async def login(self) -> bool:
        try:
            login_url = "https://www.instagram.com/accounts/login/"
            logger.info("📡 فتح صفحة تسجيل الدخول...")
            try:
                await self.page.goto(login_url, wait_until="domcontentloaded", timeout=60000)
            except Exception as e:
                logger.warning(f"⚠️ تأخير في تحميل صفحة الدخول: {e}")

            logger.info(f"✅ URL الحالي: {self.page.url}")
            await self._debug_screenshot("debug_login_page.png")
            await random_delay(3, 5)

            # ── التحقق من وجود حقل اسم المستخدم (آمن) ──
            username_selector = 'input[name="username"]'
            found = await self._safe_wait_for_selector(
                username_selector, timeout=15000, label="حقل اسم المستخدم"
            )

            if not found:
                logger.warning("⚠️ حقل اليوزر غير موجود - إعادة تحميل الصفحة...")
                try:
                    await self.page.reload(wait_until="domcontentloaded", timeout=60000)
                    await random_delay(3, 5)
                except Exception:
                    pass

                found = await self._safe_wait_for_selector(
                    username_selector, timeout=15000, label="حقل اسم المستخدم (محاولة 2)"
                )
                if not found:
                    logger.error("❌ فشل تحميل صفحة الدخول - تحقق من لقطات الشاشة")
                    await self._debug_screenshot("debug_login_error.png")
                    return False

            logger.info("🔍 إدخال بيانات تسجيل الدخول (كتابة بشرية 150ms/حرف)...")
            await self._human_type(username_selector, INSTAGRAM_USERNAME, delay=150)
            await random_delay(1, 2)

            password_selector = 'input[name="password"]'
            pw_found = await self._safe_wait_for_selector(
                password_selector, timeout=10000, label="حقل كلمة المرور"
            )
            if not pw_found:
                logger.error("❌ حقل كلمة المرور غير موجود")
                await self._debug_screenshot("debug_login_error.png")
                return False

            await self._human_type(password_selector, INSTAGRAM_PASSWORD, delay=150)
            await random_delay(1, 2)

            logger.info("🖱️ الضغط على زر الدخول...")
            submit_selector = 'button[type="submit"]'

            submit_found = await self._safe_wait_for_selector(
                submit_selector, timeout=10000, label="زر الإرسال"
            )
            if not submit_found:
                logger.warning("⚠️ زر الإرسال غير موجود - إعادة محاولة...")
                try:
                    await self.page.reload(wait_until="domcontentloaded", timeout=60000)
                    await random_delay(3, 5)
                except Exception:
                    pass
                await self._human_type(username_selector, INSTAGRAM_USERNAME, delay=150)
                await random_delay(0.8, 1.5)
                await self._human_type(password_selector, INSTAGRAM_PASSWORD, delay=150)
                await random_delay(0.8, 1.5)

            await self.page.click(submit_selector)

            logger.info("⏳ انتظار إعادة التوجيه...")
            try:
                await self.page.wait_for_url("https://www.instagram.com/", timeout=30000)
            except Exception:
                await self.page.wait_for_load_state("domcontentloaded")

            await random_delay(4, 6)
            await self._debug_screenshot("debug_after_login.png")

            is_ok = await self._strict_login_check()
            if is_ok:
                await self.save_session()
                logger.info("✅ تسجيل الدخول ناجح - تم حفظ الجلسة")
                return True
            else:
                logger.error("❌ تسجيل الدخول فشل - تحقق من لقطات الشاشة أعلاه")
                return False

        except Exception as e:
            import traceback as tb
            err = f"❌ فشل تسجيل الدخول: {e}\n{tb.format_exc()}"
            logger.error(err)
            await self._debug_screenshot("debug_login_error.png")
            return False

    async def save_session(self):
        try:
            await self.context.storage_state(path=SESSION_FILE)
            logger.info(f"💾 تم حفظ الجلسة: {SESSION_FILE}")
        except Exception as e:
            logger.error(f"فشل حفظ الجلسة: {e}")

    async def check_action_block(self) -> bool:
        try:
            content = await self.page.content()
            block_indicators = [
                "action_blocked",
                "We Restrict Certain Activity",
                "Try Again Later",
                "تقييد بعض الأنشطة",
                "حاول مرة أخرى لاحقاً",
            ]
            for indicator in block_indicators:
                if indicator.lower() in content.lower():
                    logger.warning("⚠️ Action Block مكتشف!")
                    return True
            return False
        except Exception as e:
            logger.error(f"خطأ في فحص Action Block: {e}")
            return False

    async def close(self):
        try:
            if self.context:
                await self.save_session()
                await self.context.close()
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()
            logger.info("تم إغلاق المتصفح بنجاح")
        except Exception as e:
            logger.error(f"خطأ عند إغلاق المتصفح: {e}")
