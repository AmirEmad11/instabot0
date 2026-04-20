"""
وحدة إدارة الإعدادات الخارجية
تحفظ وتحمّل جميع إعدادات المستخدم في ملف settings.json
بدلاً من تعديل ملف config.py يدوياً
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

SETTINGS_FILE = "settings.json"

# القيم الافتراضية لجميع الإعدادات
DEFAULT_SETTINGS = {
    "username": "",
    "password": "",
    "max_dm_per_day": 20,
    "max_follows_per_day": 30,
    "max_comments_scroll": 15,
    "delay_min_action": 2,
    "delay_max_action": 5,
    "delay_min_message": 15,
    "delay_max_message": 35,
    "delay_scroll": 2,
    "headless_mode": False,
    "target_posts": [],
    "keywords": [
        "تفاصيل", "بكام", "السعر", "سعر", "مهتم", "تفاصیل", "السعر كام",
        "ديتيلز", "details", "price", "info", "how much", "dm",
        "متاح", "كم السعر",
        "للبيع", "للإيجار", "موقع", "العنوان", "أين",
        "تواصل", "ابي", "ابغى", "اريد",
        "interested", "price", "available", "info",
    ],
    "message_templates": [
        "السلام عليكم {أخي الكريم|صديقي|عزيزي}، رأيت {تعليقك|استفساركم|اهتمامك} وأنا {سعيد|يسعدني} {بمساعدتك|بالرد عليك}. هل أنت مهتم بمعرفة {تفاصيل|معلومات} أكثر عن العقار؟",
        "{أهلاً وسهلاً|مرحباً} {بك|بكم}! {لاحظت|رأيت} {استفسارك|تعليقك} عن العقار. {يسعدني|أنا متاح} لمشاركتك {كافة التفاصيل|جميع المعلومات} التي تحتاجها.",
        "وعليكم السلام! {شكراً|بارك الله فيك} على {اهتمامك|استفسارك}. {العقار متاح|هذا العقار لا يزال متاحاً} و{السعر تنافسي|السعر مناسب جداً}. {هل تود|هل يمكنني} إرسال {المزيد من التفاصيل|تفاصيل كاملة}؟",
        "{مرحباً|أهلاً}! {تواصلت معك|أرسلت لك} بخصوص {استفسارك|سؤالك} عن {العقار|الوحدة}. {نحن|فريقنا} {متاحون|جاهزون} للإجابة على {جميع|كافة} تساؤلاتك.",
    ],
    "comment_reply_text": "تم التواصل ✅",
}


class SettingsManager:
    """
    مدير الإعدادات - يقرأ ويكتب ملف settings.json
    يُستخدم من قِبَل الواجهة الرسومية لحفظ وتحميل إعدادات المستخدم
    """

    def __init__(self, settings_file: str = SETTINGS_FILE):
        self.settings_file = settings_file
        self._settings = {}
        self.load()

    def load(self) -> dict:
        """
        تحميل الإعدادات من الملف، وإنشاؤه بالقيم الافتراضية إن لم يكن موجوداً
        
        Returns:
            قاموس الإعدادات المحملة
        """
        if Path(self.settings_file).exists():
            try:
                with open(self.settings_file, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                # دمج الإعدادات المحفوظة مع الافتراضية (لإضافة أي مفاتيح جديدة)
                self._settings = {**DEFAULT_SETTINGS, **saved}
                logger.debug("تم تحميل الإعدادات من settings.json")
            except Exception as e:
                logger.error(f"خطأ في تحميل الإعدادات: {e} - استخدام القيم الافتراضية")
                self._settings = DEFAULT_SETTINGS.copy()
        else:
            self._settings = DEFAULT_SETTINGS.copy()
            self.save()
            logger.info("تم إنشاء ملف settings.json بالقيم الافتراضية")

        return self._settings

    def save(self):
        """
        حفظ الإعدادات الحالية في ملف settings.json
        """
        try:
            with open(self.settings_file, "w", encoding="utf-8") as f:
                json.dump(self._settings, f, ensure_ascii=False, indent=2)
            logger.info("تم حفظ الإعدادات في settings.json")
        except Exception as e:
            logger.error(f"خطأ في حفظ الإعدادات: {e}")

    def get(self, key: str, default=None):
        """
        الحصول على قيمة إعداد محدد
        
        Args:
            key: مفتاح الإعداد
            default: القيمة الافتراضية إذا لم يُوجد المفتاح
        """
        return self._settings.get(key, default)

    def set(self, key: str, value):
        """
        تعيين قيمة إعداد محدد وحفظه فوراً
        
        Args:
            key: مفتاح الإعداد
            value: القيمة الجديدة
        """
        self._settings[key] = value

    def update(self, updates: dict):
        """
        تحديث مجموعة من الإعدادات دفعة واحدة وحفظها
        
        Args:
            updates: قاموس التحديثات
        """
        self._settings.update(updates)
        self.save()

    def get_all(self) -> dict:
        """إرجاع نسخة من جميع الإعدادات"""
        return self._settings.copy()
