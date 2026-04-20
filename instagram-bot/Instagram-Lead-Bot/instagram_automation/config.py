"""
ملف الإعدادات المركزية للنظام
"""

from pathlib import Path as _Path
_BASE = _Path(__file__).parent

# ==================== وضع التصحيح ====================
# False = واجهة نظيفة (للإنتاج) | True = كل التفاصيل التقنية
DEBUG_MODE = False

# ==================== إعدادات الحساب ====================
INSTAGRAM_USERNAME = ""
INSTAGRAM_PASSWORD = ""

# ==================== إعدادات الملفات ====================
SESSION_FILE = str(_BASE / "session_state.json")
DATABASE_FILE = str(_BASE / "leads.db")
SCREENSHOTS_DIR = str(_BASE / "screenshots")

# ==================== إعدادات User-Agent ====================
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# ==================== إعدادات الحد الأقصى ====================
MAX_DM_PER_DAY = 20
MAX_FOLLOWS_PER_DAY = 30
MAX_COMMENTS_SCROLL = 150

# ==================== الكلمات الدلالية (احتياطية) ====================
KEYWORDS = [
    "تفاصيل", "بكام", "السعر", "سعر", "مهتم",
    "details", "price", "info", "how much", "interested",
    "متاح", "تواصل", "available",
]

# ==================== نماذج الرسائل ====================
MESSAGE_TEMPLATES = [
    "السلام عليكم {أخي الكريم|صديقي|عزيزي}، رأيت {تعليقك|اهتمامك} وأنا {سعيد|يسعدني} {بمساعدتك|بالرد عليك}. هل أنت مهتم بمعرفة التفاصيل؟",
    "{أهلاً|مرحباً}! {لاحظت|رأيت} تعليقك. {يسعدني|أنا متاح} لمشاركتك {كافة التفاصيل|المعلومات} التي تحتاجها.",
]

# ==================== نص الرد على التعليق ====================
COMMENT_REPLY_TEXT = "تم التواصل ✅"

# ==================== إعدادات الرد التلقائي ====================
PUBLIC_AUTO_REPLY = True   # الرد على تعليقات الحسابات العامة
PRIVATE_AUTO_REPLY = False  # الرد على تعليقات الحسابات الخاصة
PRIVATE_REPLY_TEXT = "تم إرسال التفاصيل، يرجى مراجعة طلبات المراسلة ✅"

# ==================== إعدادات التأخير (بالثواني) ====================
DELAY_MIN_ACTION = 30
DELAY_MAX_ACTION = 60
DELAY_MIN_MESSAGE = 60
DELAY_MAX_MESSAGE = 120
DELAY_SCROLL = 3

# ==================== إعدادات المتصفح ====================
HEADLESS_MODE = True
VIEWPORT_WIDTH = 390
VIEWPORT_HEIGHT = 844

# ==================== محاكاة الموبايل ====================
MOBILE_EMULATION = True   # iPhone 15 Pro Max user-agent + touch viewport

# ==================== فلترة المنافسين ====================
COMPETITOR_FILTER = True
COMPETITOR_KEYWORDS = [
    "broker", "real estate", "realtor", "property", "developer",
    "عقارات", "شركة", "تسويق", "وسيط", "بروكر", "عقار", "مطور",
]
