"""
وحدة الأدوات المساعدة
تحتوي على دوال مشتركة تُستخدم في جميع أجزاء النظام
"""

import re
import random
import asyncio
import logging
from datetime import datetime
from pathlib import Path
from playwright.async_api import Page
from config import (
    DELAY_MIN_ACTION,
    DELAY_MAX_ACTION,
    SCREENSHOTS_DIR,
    DEBUG_MODE,
)

logger = logging.getLogger(__name__)


def setup_logging():
    """
    إعداد نظام تسجيل الأحداث (Logging) بتنسيق واضح ومنظم
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler("automation.log", encoding="utf-8"),
        ],
    )


def parse_spintax(text: str) -> str:
    """
    معالجة نص بصيغة Spintax واختيار عبارة عشوائية من كل مجموعة
    مثال: {مرحبا|أهلاً|السلام} → يختار إحدى الثلاثة عشوائياً
    
    Args:
        text: النص المحتوي على صيغة Spintax
        
    Returns:
        النص بعد معالجة جميع الاختيارات العشوائية
    """
    pattern = re.compile(r"\{([^{}]+)\}")
    
    while pattern.search(text):
        def replace_match(match):
            choices = match.group(1).split("|")
            return random.choice(choices)
        
        text = pattern.sub(replace_match, text)
    
    return text


def get_random_message(templates: list) -> str:
    """
    اختيار نموذج رسالة عشوائي ومعالجة الـ Spintax فيه
    
    Args:
        templates: قائمة نماذج الرسائل
        
    Returns:
        الرسالة النهائية بعد المعالجة
    """
    template = random.choice(templates)
    return parse_spintax(template)


def normalize_search_text(text: str) -> str:
    text = (text or "").lower()
    replacements = {
        "أ": "ا",
        "إ": "ا",
        "آ": "ا",
        "ٱ": "ا",
        "ى": "ي",
        "ی": "ي",
        "ئ": "ي",
        "ؤ": "و",
        "ة": "ه",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    text = re.sub(r"[\u064b-\u065f\u0670]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def contains_keyword(text: str, keywords: list) -> bool:
    """
    التحقق مما إذا كان النص يحتوي على أي من الكلمات الدلالية
    
    Args:
        text: النص المراد فحصه
        keywords: قائمة الكلمات الدلالية
        
    Returns:
        True إذا احتوى على كلمة دلالية، False إذا لم يحتوِ
    """
    normalized_text = normalize_search_text(text)
    compact_text = normalized_text.replace(" ", "")
    for keyword in keywords:
        normalized_keyword = normalize_search_text(str(keyword))
        if not normalized_keyword:
            continue
        compact_keyword = normalized_keyword.replace(" ", "")
        if normalized_keyword in normalized_text or compact_keyword in compact_text:
            return True
    return False


async def random_delay(min_sec: float = None, max_sec: float = None):
    """
    تأخير عشوائي لمحاكاة السلوك البشري
    
    Args:
        min_sec: الحد الأدنى بالثواني (يستخدم القيمة الافتراضية إذا لم تُحدد)
        max_sec: الحد الأقصى بالثواني (يستخدم القيمة الافتراضية إذا لم تُحدد)
    """
    _min = min_sec if min_sec is not None else DELAY_MIN_ACTION
    _max = max_sec if max_sec is not None else DELAY_MAX_ACTION
    
    delay = random.uniform(_min, _max)
    logger.debug(f"انتظار {delay:.1f} ثانية...")
    await asyncio.sleep(delay)


async def human_like_mouse_move(page: Page, target_x: int, target_y: int):
    """
    تحريك الماوس بمسار منحنٍ غير مستقيم لمحاكاة الحركة البشرية
    
    Args:
        page: صفحة Playwright الحالية
        target_x: الإحداثي الأفقي للهدف
        target_y: الإحداثي الرأسي للهدف
    """
    # إنشاء نقاط وسيطة عشوائية على طول المسار
    steps = random.randint(5, 10)
    current_x = random.randint(100, 500)
    current_y = random.randint(100, 400)
    
    for i in range(steps):
        # حساب الإزاحة العشوائية لكل خطوة
        progress = (i + 1) / steps
        intermediate_x = int(current_x + (target_x - current_x) * progress)
        intermediate_y = int(current_y + (target_y - current_y) * progress)
        
        # إضافة اهتزاز عشوائي صغير
        jitter_x = random.randint(-5, 5)
        jitter_y = random.randint(-5, 5)
        
        await page.mouse.move(
            intermediate_x + jitter_x,
            intermediate_y + jitter_y
        )
        await asyncio.sleep(random.uniform(0.02, 0.08))
    
    # التحرك للهدف النهائي
    await page.mouse.move(target_x, target_y)


async def human_like_click(page: Page, selector: str):
    """
    الضغط على عنصر بطريقة تشبه السلوك البشري
    (تحريك الماوس أولاً، ثم تأخير قصير، ثم الضغط)
    
    Args:
        page: صفحة Playwright الحالية
        selector: محدد العنصر المراد الضغط عليه
    """
    element = await page.query_selector(selector)
    if not element:
        raise ValueError(f"لم يُعثر على العنصر: {selector}")
    
    box = await element.bounding_box()
    if box:
        # الضغط في مكان عشوائي داخل العنصر
        click_x = box["x"] + random.uniform(box["width"] * 0.3, box["width"] * 0.7)
        click_y = box["y"] + random.uniform(box["height"] * 0.3, box["height"] * 0.7)
        
        await human_like_mouse_move(page, int(click_x), int(click_y))
        await asyncio.sleep(random.uniform(0.1, 0.3))
        await page.mouse.click(int(click_x), int(click_y))
    else:
        await element.click()


async def take_error_screenshot(page: Page, error_name: str = "error"):
    """
    التقاط لقطة شاشة عند الأخطاء الحرجة فقط.
    في وضع الإنتاج (DEBUG_MODE=False): يلتقط فقط عند الفشل الكامل (ليس صور debug_).
    في وضع التصحيح (DEBUG_MODE=True): يلتقط كل شيء.
    """
    is_debug_shot = error_name.startswith("debug_") or error_name.startswith("before_")
    if not DEBUG_MODE and is_debug_shot:
        return

    Path(SCREENSHOTS_DIR).mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{SCREENSHOTS_DIR}/{error_name}_{timestamp}.png"

    try:
        await page.screenshot(path=filename)
        logger.error(f"📸 لقطة خطأ: {filename}")
    except Exception as e:
        logger.error(f"فشل التقاط لقطة الشاشة: {e}")
