"""
الواجهة الرسومية الاحترافية لنظام الأتمتة العقارية
مبنية بمكتبة CustomTkinter مع فصل كامل بين المنطق والعرض

تشغيل:
    python gui.py
"""

import queue
import threading
import logging
import tkinter as tk
from tkinter import messagebox
from datetime import datetime

import customtkinter as ctk

from settings_manager import SettingsManager
from bot_runner import BotRunner

# ─── إعداد المظهر العام ────────────────────────────────────────────
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

logger = logging.getLogger(__name__)

# ─── ثوابت الألوان ────────────────────────────────────────────────
CLR_BG_MAIN   = "#1a1a2e"   # خلفية رئيسية
CLR_BG_PANEL  = "#16213e"   # خلفية اللوحات
CLR_BG_CARD   = "#0f3460"   # خلفية البطاقات
CLR_ACCENT    = "#e94560"   # لون التمييز (أحمر)
CLR_GREEN     = "#4ade80"   # أخضر (نجاح)
CLR_YELLOW    = "#fbbf24"   # أصفر (تحذير)
CLR_TEXT      = "#e2e8f0"   # نص رئيسي
CLR_MUTED     = "#94a3b8"   # نص خافت
CLR_INPUT_BG  = "#1e293b"   # خلفية حقول الإدخال
CLR_BTN_START = "#16a34a"   # زر البدء
CLR_BTN_STOP  = "#dc2626"   # زر الإيقاف


class LogHandler(logging.Handler):
    """معالج Logging يُرسل الرسائل إلى queue.Queue للعرض في الواجهة"""

    def __init__(self, log_queue: queue.Queue):
        super().__init__()
        self.log_queue = log_queue
        fmt = logging.Formatter("%(asctime)s  %(message)s", datefmt="%H:%M:%S")
        self.setFormatter(fmt)

    def emit(self, record: logging.LogRecord):
        try:
            self.log_queue.put_nowait(self.format(record))
        except Exception:
            pass


class SectionLabel(ctk.CTkLabel):
    """عنوان قسم بتنسيق موحّد"""

    def __init__(self, parent, text, **kwargs):
        super().__init__(
            parent,
            text=text,
            font=ctk.CTkFont(family="Arial", size=13, weight="bold"),
            text_color=CLR_ACCENT,
            **kwargs,
        )


class LabeledEntry(ctk.CTkFrame):
    """حقل إدخال مع تسمية توضيحية فوقه"""

    def __init__(self, parent, label: str, placeholder: str = "",
                 show: str = "", **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)
        ctk.CTkLabel(
            self, text=label,
            font=ctk.CTkFont(size=11),
            text_color=CLR_MUTED,
            anchor="w",
        ).pack(fill="x", padx=2, pady=(0, 2))
        self.entry = ctk.CTkEntry(
            self,
            placeholder_text=placeholder,
            show=show,
            fg_color=CLR_INPUT_BG,
            border_color=CLR_BG_CARD,
            text_color=CLR_TEXT,
            height=34,
        )
        self.entry.pack(fill="x")

    def get(self) -> str:
        return self.entry.get()

    def set(self, value: str):
        self.entry.delete(0, "end")
        self.entry.insert(0, str(value))


class SpinboxRow(ctk.CTkFrame):
    """صف يحتوي على تسمية + حقل رقمي"""

    def __init__(self, parent, label: str, default: int = 0,
                 min_val: int = 1, max_val: int = 9999, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)
        ctk.CTkLabel(
            self, text=label,
            font=ctk.CTkFont(size=11),
            text_color=CLR_TEXT,
            anchor="w",
        ).pack(side="left", fill="x", expand=True)
        self.var = tk.IntVar(value=default)
        self.spinbox = ctk.CTkEntry(
            self,
            textvariable=self.var,
            fg_color=CLR_INPUT_BG,
            border_color=CLR_BG_CARD,
            text_color=CLR_TEXT,
            width=70,
            height=30,
            justify="center",
        )
        self.spinbox.pack(side="right")

    def get(self) -> int:
        try:
            return int(self.var.get())
        except ValueError:
            return 0

    def set(self, value: int):
        self.var.set(int(value))


# ══════════════════════════════════════════════════════════════════
#  النافذة الرئيسية
# ══════════════════════════════════════════════════════════════════

class InstagramBotGUI(ctk.CTk):
    """
    النافذة الرئيسية للتطبيق
    تتضمن جميع أقسام الواجهة وتُنسّق العمل بين الواجهة والبوت
    """

    def __init__(self):
        super().__init__()

        self.settings_mgr = SettingsManager()
        self.log_queue: queue.Queue = queue.Queue()
        self.stop_event: threading.Event = threading.Event()
        self.bot_thread: threading.Thread | None = None
        self.is_running = False

        self._setup_logging()
        self._build_window()
        self._build_ui()
        self._load_settings_to_ui()
        self._poll_log_queue()

    # ─── إعداد النافذة ────────────────────────────────────────────

    def _setup_logging(self):
        root_log = logging.getLogger()
        root_log.setLevel(logging.INFO)
        handler = LogHandler(self.log_queue)
        root_log.addHandler(handler)

    def _build_window(self):
        self.title("🏠 نظام الأتمتة العقارية - إنستجرام")
        self.geometry("1280x760")
        self.minsize(1100, 680)
        self.configure(fg_color=CLR_BG_MAIN)
        # منع الإغلاق العشوائي أثناء تشغيل البوت
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ─── بناء الواجهة ─────────────────────────────────────────────

    def _build_ui(self):
        # ─── شريط العنوان ─────────────────────────────
        header = ctk.CTkFrame(self, fg_color=CLR_BG_PANEL, height=56, corner_radius=0)
        header.pack(fill="x", side="top")
        header.pack_propagate(False)

        ctk.CTkLabel(
            header,
            text="  🏠  نظام الأتمتة العقارية على إنستجرام",
            font=ctk.CTkFont(family="Arial", size=18, weight="bold"),
            text_color=CLR_TEXT,
            anchor="w",
        ).pack(side="left", padx=20, pady=10)

        # مؤشر الحالة في الشريط
        self.status_badge = ctk.CTkLabel(
            header,
            text="  ⏹  متوقف  ",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#111",
            fg_color=CLR_MUTED,
            corner_radius=12,
        )
        self.status_badge.pack(side="right", padx=20, pady=14)

        # ─── منطقة المحتوى الرئيسية ───────────────────
        content = ctk.CTkFrame(self, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=12, pady=12)
        content.columnconfigure(0, weight=0, minsize=310)
        content.columnconfigure(1, weight=1)
        content.rowconfigure(0, weight=1)

        # اللوحة اليسرى (الإعدادات)
        left = ctk.CTkScrollableFrame(
            content,
            fg_color=CLR_BG_PANEL,
            corner_radius=12,
            scrollbar_button_color=CLR_BG_CARD,
        )
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self._build_left_panel(left)

        # اللوحة اليمنى (التحكم + السجل)
        right = ctk.CTkFrame(content, fg_color="transparent")
        right.grid(row=0, column=1, sticky="nsew")
        right.rowconfigure(0, weight=0)
        right.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)

        self._build_links_panel(right)
        self._build_log_panel(right)

    # ─── اللوحة اليسرى: الإعدادات ────────────────────────────────

    def _build_left_panel(self, parent):
        pad = {"padx": 14, "pady": 6}

        # ─ تسجيل الدخول ─
        ctk.CTkFrame(parent, fg_color=CLR_ACCENT, height=2).pack(fill="x", **{"padx": 14, "pady": (14, 0)})
        SectionLabel(parent, "🔐  تسجيل الدخول").pack(anchor="w", **{"padx": 14, "pady": (6, 4)})

        self.e_user = LabeledEntry(parent, "اسم المستخدم", placeholder="instagram_username")
        self.e_user.pack(fill="x", **pad)

        self.e_pass = LabeledEntry(parent, "كلمة المرور", placeholder="••••••••", show="•")
        self.e_pass.pack(fill="x", **pad)

        ctk.CTkButton(
            parent,
            text="💾  حفظ بيانات الدخول",
            command=self._save_credentials,
            fg_color=CLR_BG_CARD,
            hover_color="#1a4a80",
            text_color=CLR_TEXT,
            height=36,
            corner_radius=8,
        ).pack(fill="x", **{"padx": 14, "pady": (2, 10)})

        # ─ الحدود اليومية ─
        ctk.CTkFrame(parent, fg_color=CLR_ACCENT, height=2).pack(fill="x", **{"padx": 14, "pady": (6, 0)})
        SectionLabel(parent, "📊  الحدود اليومية").pack(anchor="w", **{"padx": 14, "pady": (6, 4)})

        self.spin_max_dm = SpinboxRow(parent, "الحد الأقصى للرسائل (DM)", default=20)
        self.spin_max_dm.pack(fill="x", **pad)

        self.spin_max_follow = SpinboxRow(parent, "الحد الأقصى للمتابعات", default=30)
        self.spin_max_follow.pack(fill="x", **pad)

        self.spin_max_scroll = SpinboxRow(parent, "تمريرات التعليقات", default=15)
        self.spin_max_scroll.pack(fill="x", **pad)

        # ─ الفواصل الزمنية ─
        ctk.CTkFrame(parent, fg_color=CLR_ACCENT, height=2).pack(fill="x", **{"padx": 14, "pady": (10, 0)})
        SectionLabel(parent, "⏱  الفواصل الزمنية (ثانية)").pack(anchor="w", **{"padx": 14, "pady": (6, 4)})

        self.spin_d_min_act = SpinboxRow(parent, "تأخير إجراء - أدنى", default=2)
        self.spin_d_min_act.pack(fill="x", **pad)

        self.spin_d_max_act = SpinboxRow(parent, "تأخير إجراء - أقصى", default=5)
        self.spin_d_max_act.pack(fill="x", **pad)

        self.spin_d_min_msg = SpinboxRow(parent, "تأخير رسالة - أدنى", default=15)
        self.spin_d_min_msg.pack(fill="x", **pad)

        self.spin_d_max_msg = SpinboxRow(parent, "تأخير رسالة - أقصى", default=35)
        self.spin_d_max_msg.pack(fill="x", **pad)

        # ─ وضع المتصفح ─
        ctk.CTkFrame(parent, fg_color=CLR_ACCENT, height=2).pack(fill="x", **{"padx": 14, "pady": (10, 0)})
        SectionLabel(parent, "🌐  إعدادات المتصفح").pack(anchor="w", **{"padx": 14, "pady": (6, 4)})

        self.var_headless = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            parent,
            text="Headless Mode (بدون نافذة)",
            variable=self.var_headless,
            text_color=CLR_TEXT,
            checkmark_color=CLR_TEXT,
            fg_color=CLR_ACCENT,
        ).pack(anchor="w", **{"padx": 14, "pady": 6})

        # ─ زر حفظ الإعدادات ─
        ctk.CTkFrame(parent, fg_color=CLR_ACCENT, height=2).pack(fill="x", **{"padx": 14, "pady": (10, 0)})
        ctk.CTkButton(
            parent,
            text="💾  حفظ جميع الإعدادات",
            command=self._save_all_settings,
            fg_color=CLR_BG_CARD,
            hover_color="#1a4a80",
            text_color=CLR_TEXT,
            height=38,
            corner_radius=8,
        ).pack(fill="x", **{"padx": 14, "pady": 12})

    # ─── لوحة الروابط ─────────────────────────────────────────────

    def _build_links_panel(self, parent):
        frame = ctk.CTkFrame(parent, fg_color=CLR_BG_PANEL, corner_radius=12)
        frame.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        frame.columnconfigure(0, weight=1)

        SectionLabel(frame, "🔗  روابط المنشورات المستهدفة").pack(
            anchor="w", padx=14, pady=(10, 4)
        )

        # صف الإدخال + الإضافة
        row = ctk.CTkFrame(frame, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=(0, 6))
        row.columnconfigure(0, weight=1)

        self.e_url = ctk.CTkEntry(
            row,
            placeholder_text="https://www.instagram.com/p/XXXXXXXX/  أو  /reel/XXXXXXXX/",
            fg_color=CLR_INPUT_BG,
            border_color=CLR_BG_CARD,
            text_color=CLR_TEXT,
            height=36,
        )
        self.e_url.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.e_url.bind("<Return>", lambda _: self._add_url())

        ctk.CTkButton(
            row,
            text="➕ إضافة",
            command=self._add_url,
            width=90,
            height=36,
            fg_color=CLR_BG_CARD,
            hover_color=CLR_ACCENT,
            text_color=CLR_TEXT,
            corner_radius=8,
        ).grid(row=0, column=1)

        # قائمة الروابط + أزرار التحكم
        list_frame = ctk.CTkFrame(frame, fg_color="transparent")
        list_frame.pack(fill="x", padx=14, pady=(0, 10))
        list_frame.columnconfigure(0, weight=1)

        self.links_listbox = tk.Listbox(
            list_frame,
            bg=CLR_INPUT_BG,
            fg=CLR_TEXT,
            selectbackground=CLR_BG_CARD,
            selectforeground=CLR_TEXT,
            activestyle="none",
            borderwidth=0,
            highlightthickness=0,
            font=("Consolas", 10),
            height=5,
        )
        self.links_listbox.grid(row=0, column=0, sticky="ew")

        btn_col = ctk.CTkFrame(list_frame, fg_color="transparent")
        btn_col.grid(row=0, column=1, padx=(8, 0), sticky="n")

        ctk.CTkButton(
            btn_col,
            text="🗑 حذف",
            command=self._remove_url,
            width=80,
            height=30,
            fg_color=CLR_BTN_STOP,
            hover_color="#b91c1c",
            text_color=CLR_TEXT,
            corner_radius=8,
        ).pack(pady=(0, 4))

        ctk.CTkButton(
            btn_col,
            text="🗑 كل",
            command=self._clear_urls,
            width=80,
            height=30,
            fg_color=CLR_BG_CARD,
            hover_color="#1a4a80",
            text_color=CLR_TEXT,
            corner_radius=8,
        ).pack()

        # ─ أزرار البدء والإيقاف ─
        ctrl = ctk.CTkFrame(frame, fg_color="transparent")
        ctrl.pack(fill="x", padx=14, pady=(0, 12))
        ctrl.columnconfigure((0, 1), weight=1)

        self.btn_start = ctk.CTkButton(
            ctrl,
            text="▶  بدء تشغيل البوت",
            command=self._start_bot,
            fg_color=CLR_BTN_START,
            hover_color="#15803d",
            text_color="white",
            height=42,
            font=ctk.CTkFont(size=14, weight="bold"),
            corner_radius=10,
        )
        self.btn_start.grid(row=0, column=0, sticky="ew", padx=(0, 6))

        self.btn_stop = ctk.CTkButton(
            ctrl,
            text="⏹  إيقاف",
            command=self._stop_bot,
            fg_color=CLR_BTN_STOP,
            hover_color="#b91c1c",
            text_color="white",
            height=42,
            font=ctk.CTkFont(size=14, weight="bold"),
            corner_radius=10,
            state="disabled",
        )
        self.btn_stop.grid(row=0, column=1, sticky="ew", padx=(6, 0))

        # ─ شريط العدادات ─
        counters = ctk.CTkFrame(frame, fg_color=CLR_BG_CARD, corner_radius=8)
        counters.pack(fill="x", padx=14, pady=(0, 12))
        for i in range(3):
            counters.columnconfigure(i, weight=1)

        self.lbl_dm_count = self._counter_cell(counters, "رسائل DM", "0", col=0)
        self.lbl_follow_count = self._counter_cell(counters, "متابعات", "0", col=1)
        self.lbl_leads_count = self._counter_cell(counters, "عملاء", "0", col=2)

    def _counter_cell(self, parent, title: str, value: str, col: int) -> ctk.CTkLabel:
        cell = ctk.CTkFrame(parent, fg_color="transparent")
        cell.grid(row=0, column=col, padx=10, pady=8, sticky="ew")
        ctk.CTkLabel(
            cell, text=value,
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color=CLR_ACCENT,
        ).pack()
        ctk.CTkLabel(
            cell, text=title,
            font=ctk.CTkFont(size=10),
            text_color=CLR_MUTED,
        ).pack()
        # نُعيد مؤشر للـ label الرقمي لتحديثه لاحقاً
        return cell.winfo_children()[0]

    # ─── لوحة سجل الحالة ─────────────────────────────────────────

    def _build_log_panel(self, parent):
        frame = ctk.CTkFrame(parent, fg_color=CLR_BG_PANEL, corner_radius=12)
        frame.grid(row=1, column=0, sticky="nsew")
        frame.rowconfigure(1, weight=1)
        frame.columnconfigure(0, weight=1)

        # ─ رأس السجل ─
        header = ctk.CTkFrame(frame, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=14, pady=(10, 4))

        SectionLabel(header, "📋  سجل الأحداث المباشر").pack(side="left")

        ctk.CTkButton(
            header,
            text="🗑  مسح",
            command=self._clear_log,
            width=70,
            height=26,
            fg_color=CLR_BG_CARD,
            hover_color=CLR_ACCENT,
            text_color=CLR_TEXT,
            corner_radius=6,
        ).pack(side="right")

        # ─ مربع النص ─
        self.log_text = tk.Text(
            frame,
            bg=CLR_INPUT_BG,
            fg=CLR_TEXT,
            font=("Consolas", 11),
            wrap="word",
            borderwidth=0,
            highlightthickness=0,
            state="disabled",
            padx=10,
            pady=6,
        )
        self.log_text.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0, 14))

        # ألوان الرسائل المختلفة
        self.log_text.tag_config("success", foreground=CLR_GREEN)
        self.log_text.tag_config("error",   foreground="#f87171")
        self.log_text.tag_config("warn",    foreground=CLR_YELLOW)
        self.log_text.tag_config("info",    foreground="#93c5fd")
        self.log_text.tag_config("dim",     foreground=CLR_MUTED)

        # شريط تمرير رأسي
        scrollbar = ctk.CTkScrollbar(frame, command=self.log_text.yview)
        scrollbar.grid(row=1, column=1, sticky="ns", pady=(0, 14), padx=(0, 8))
        self.log_text.configure(yscrollcommand=scrollbar.set)

    # ══════════════════════════════════════════════════════════════
    #  منطق الإعدادات
    # ══════════════════════════════════════════════════════════════

    def _load_settings_to_ui(self):
        """تحميل الإعدادات المحفوظة وملء حقول الواجهة"""
        s = self.settings_mgr.get_all()

        self.e_user.set(s.get("username", ""))
        self.e_pass.set(s.get("password", ""))

        self.spin_max_dm.set(s.get("max_dm_per_day", 20))
        self.spin_max_follow.set(s.get("max_follows_per_day", 30))
        self.spin_max_scroll.set(s.get("max_comments_scroll", 15))
        self.spin_d_min_act.set(s.get("delay_min_action", 2))
        self.spin_d_max_act.set(s.get("delay_max_action", 5))
        self.spin_d_min_msg.set(s.get("delay_min_message", 15))
        self.spin_d_max_msg.set(s.get("delay_max_message", 35))
        self.var_headless.set(s.get("headless_mode", False))

        for url in s.get("target_posts", []):
            self.links_listbox.insert("end", url)

        self._log("ℹ️  تم تحميل الإعدادات المحفوظة", "info")

    def _collect_settings_from_ui(self) -> dict:
        """جمع جميع قيم الواجهة في قاموس واحد"""
        urls = list(self.links_listbox.get(0, "end"))
        return {
            "username":            self.e_user.get().strip(),
            "password":            self.e_pass.get().strip(),
            "max_dm_per_day":      self.spin_max_dm.get(),
            "max_follows_per_day": self.spin_max_follow.get(),
            "max_comments_scroll": self.spin_max_scroll.get(),
            "delay_min_action":    self.spin_d_min_act.get(),
            "delay_max_action":    self.spin_d_max_act.get(),
            "delay_min_message":   self.spin_d_min_msg.get(),
            "delay_max_message":   self.spin_d_max_msg.get(),
            "headless_mode":       self.var_headless.get(),
            "target_posts":        urls,
        }

    def _save_credentials(self):
        """حفظ بيانات الدخول فقط"""
        self.settings_mgr.update({
            "username": self.e_user.get().strip(),
            "password": self.e_pass.get().strip(),
        })
        self._log("✅ تم حفظ بيانات الدخول", "success")

    def _save_all_settings(self):
        """حفظ جميع الإعدادات"""
        data = self._collect_settings_from_ui()
        self.settings_mgr.update(data)
        self._log("✅ تم حفظ جميع الإعدادات في settings.json", "success")

    # ══════════════════════════════════════════════════════════════
    #  إدارة الروابط
    # ══════════════════════════════════════════════════════════════

    def _add_url(self):
        url = self.e_url.get().strip()
        if not url:
            return
        if not ("instagram.com/p/" in url or "instagram.com/reel/" in url):
            messagebox.showwarning(
                "رابط غير صحيح",
                "يجب أن يكون الرابط منشوراً أو ريلز من إنستجرام\n"
                "مثال: https://www.instagram.com/p/XXXXXXXXXX/"
            )
            return
        # تجنب التكرار
        existing = list(self.links_listbox.get(0, "end"))
        if url not in existing:
            self.links_listbox.insert("end", url)
            self._log(f"➕ تمت إضافة الرابط: {url[:60]}...", "dim")
        self.e_url.delete(0, "end")

    def _remove_url(self):
        selected = self.links_listbox.curselection()
        if selected:
            url = self.links_listbox.get(selected[0])
            self.links_listbox.delete(selected[0])
            self._log(f"🗑  تم حذف: {url[:60]}...", "dim")

    def _clear_urls(self):
        self.links_listbox.delete(0, "end")
        self._log("🗑  تم مسح جميع الروابط", "warn")

    # ══════════════════════════════════════════════════════════════
    #  تشغيل / إيقاف البوت
    # ══════════════════════════════════════════════════════════════

    def _start_bot(self):
        if self.is_running:
            return

        # التحقق من المتطلبات الأساسية
        username = self.e_user.get().strip()
        password = self.e_pass.get().strip()
        urls = list(self.links_listbox.get(0, "end"))

        if not username or not password:
            messagebox.showerror("بيانات ناقصة", "يرجى إدخال اسم المستخدم وكلمة المرور أولاً")
            return
        if not urls:
            messagebox.showerror("لا توجد روابط", "يرجى إضافة رابط منشور واحد على الأقل")
            return

        # حفظ الإعدادات قبل البدء
        self._save_all_settings()

        # إعداد حالة التشغيل
        self.stop_event.clear()
        self.is_running = True
        self._set_running_state(True)

        # إنشاء البوت وتشغيله في Thread منفصل
        settings = self._collect_settings_from_ui()
        runner = BotRunner(
            settings=settings,
            target_posts=urls,
            log_queue=self.log_queue,
            stop_event=self.stop_event,
            on_finish=self._on_bot_finished,
        )

        self.bot_thread = threading.Thread(
            target=runner.run_in_thread,
            daemon=True,
            name="BotWorkerThread",
        )
        self.bot_thread.start()
        self._log("🚀 تم بدء تشغيل البوت في خلفية البرنامج", "success")

    def _stop_bot(self):
        if not self.is_running:
            return
        self.stop_event.set()
        self._log("🛑 جارٍ إيقاف البوت... انتظر اكتمال العملية الحالية", "warn")
        self.btn_stop.configure(state="disabled", text="⏳ جارٍ الإيقاف...")

    def _on_bot_finished(self):
        """تُستدعى من Thread البوت عند انتهائه - تُجدّد الواجهة عبر after()"""
        self.after(0, self._reset_after_finish)

    def _reset_after_finish(self):
        self.is_running = False
        self._set_running_state(False)
        self._log("✅ انتهى البوت - الواجهة جاهزة من جديد", "success")

    def _set_running_state(self, running: bool):
        """تحديث حالة عناصر الواجهة بناءً على حالة التشغيل"""
        if running:
            self.btn_start.configure(state="disabled", text="⏳ جارٍ التشغيل...")
            self.btn_stop.configure(state="normal", text="⏹  إيقاف")
            self.status_badge.configure(
                text="  ▶  يعمل  ",
                fg_color=CLR_BTN_START,
                text_color="white",
            )
        else:
            self.btn_start.configure(state="normal", text="▶  بدء تشغيل البوت")
            self.btn_stop.configure(state="disabled", text="⏹  إيقاف")
            self.status_badge.configure(
                text="  ⏹  متوقف  ",
                fg_color=CLR_MUTED,
                text_color="#111",
            )

    # ══════════════════════════════════════════════════════════════
    #  سجل الأحداث
    # ══════════════════════════════════════════════════════════════

    def _log(self, message: str, tag: str = "info"):
        """كتابة رسالة مباشرة في سجل الأحداث"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        line = f"{timestamp}  {message}\n"
        self.log_text.configure(state="normal")
        self.log_text.insert("end", line, tag)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _poll_log_queue(self):
        """
        فحص queue الرسائل كل 120ms وإظهارها في السجل
        يعمل بشكل مستمر عبر after() بدون block للواجهة
        """
        try:
            while True:
                msg = self.log_queue.get_nowait()
                # تحديد لون الرسالة بناءً على محتواها
                tag = "info"
                low = msg.lower()
                if any(k in low for k in ("✅", "نجاح", "تم", "success")):
                    tag = "success"
                elif any(k in low for k in ("❌", "خطأ", "error", "critical")):
                    tag = "error"
                elif any(k in low for k in ("⚠️", "تحذير", "warning", "warn", "⛔", "🚫")):
                    tag = "warn"
                elif any(k in low for k in ("ℹ️", "info", "─", "═")):
                    tag = "dim"

                self.log_text.configure(state="normal")
                self.log_text.insert("end", msg + "\n", tag)
                self.log_text.see("end")
                self.log_text.configure(state="disabled")

        except queue.Empty:
            pass

        self.after(120, self._poll_log_queue)

    def _clear_log(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    # ══════════════════════════════════════════════════════════════
    #  إغلاق النافذة
    # ══════════════════════════════════════════════════════════════

    def _on_close(self):
        if self.is_running:
            if not messagebox.askyesno(
                "تأكيد الإغلاق",
                "البوت لا يزال يعمل!\nهل تريد إيقافه وإغلاق البرنامج؟",
            ):
                return
            self.stop_event.set()

        self.destroy()


# ──────────────────────────────────────────────────────────────────
#  نقطة الدخول
# ──────────────────────────────────────────────────────────────────

def main():
    logging.basicConfig(level=logging.INFO)
    app = InstagramBotGUI()
    app.mainloop()


if __name__ == "__main__":
    main()
