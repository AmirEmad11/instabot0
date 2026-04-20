"""
Instagram Predator Ultra v7.0 – Stepped Workflow & Stealth Edition
واجهة الخطوات الثلاث: سحب → فلترة → تنفيذ
"""

import sys
import os
import io
import csv
import json
import queue
import threading
import time
import logging
import re
import sqlite3
from datetime import datetime
from pathlib import Path

_dir = Path(__file__).parent
if str(_dir) not in sys.path:
    sys.path.insert(0, str(_dir))

os.chdir(_dir)

import streamlit as st
from settings_manager import SettingsManager
import site_database as sdb

# ── File logging: تسجيل الأخطاء في ملف خارجي ──
_log_file = _dir / "server_errors.log"
_file_handler = logging.FileHandler(str(_log_file), encoding="utf-8")
_file_handler.setLevel(logging.ERROR)
_file_handler.setFormatter(logging.Formatter(
    "%(asctime)s  [%(levelname)s]  %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
))
logging.getLogger().addHandler(_file_handler)
logging.getLogger().setLevel(logging.WARNING)

st.set_page_config(
    page_title="⚡ Instagram Predator Ultra v7.0",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700;900&display=swap');

    html, body, [class*="css"] { font-family: 'Cairo', sans-serif !important; }
    .stApp { background-color: #060b14; }
    .stApp > header { background-color: #060b14; }
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #0d1117 0%, #111827 100%);
        border-right: 1px solid #1f2d3d;
    }
    [data-testid="stSidebar"] * { color: #e2e8f0 !important; }

    /* ── Step Header ── */
    .step-header {
        display: flex; align-items: center; gap: 16px;
        padding: 20px 24px;
        background: linear-gradient(135deg, #0d1117 0%, #111827 100%);
        border: 1px solid #1f2d3d;
        border-radius: 16px;
        margin-bottom: 24px;
    }
    .step-badge {
        width: 48px; height: 48px; border-radius: 12px;
        display: flex; align-items: center; justify-content: center;
        font-size: 1.4rem; font-weight: 900;
        flex-shrink: 0;
    }
    .step-badge.active  { background: linear-gradient(135deg, #6366f1, #8b5cf6); color: #fff; }
    .step-badge.done    { background: linear-gradient(135deg, #059669, #10b981); color: #fff; }
    .step-badge.waiting { background: #1f2d3d; color: #475569; }
    .step-title { font-size: 1.2rem; font-weight: 700; color: #f1f5f9; }
    .step-sub   { font-size: 0.82rem; color: #64748b; margin-top: 2px; }

    /* ── Stepper Bar ── */
    .stepper-bar {
        display: flex; align-items: center; gap: 0;
        margin-bottom: 28px;
    }
    .stepper-step {
        flex: 1; display: flex; flex-direction: column;
        align-items: center; gap: 6px;
    }
    .stepper-dot {
        width: 36px; height: 36px; border-radius: 50%;
        display: flex; align-items: center; justify-content: center;
        font-size: 0.9rem; font-weight: 700; transition: all 0.3s;
    }
    .stepper-dot.active  { background: #6366f1; color: #fff; box-shadow: 0 0 16px rgba(99,102,241,0.5); }
    .stepper-dot.done    { background: #10b981; color: #fff; }
    .stepper-dot.waiting { background: #1f2d3d; color: #475569; }
    .stepper-label { font-size: 0.72rem; color: #64748b; text-align: center; }
    .stepper-label.active  { color: #a5b4fc; font-weight: 700; }
    .stepper-label.done    { color: #6ee7b7; }
    .stepper-line { flex: 1; height: 2px; background: #1f2d3d; margin-bottom: 22px; }
    .stepper-line.done { background: linear-gradient(90deg, #10b981, #6366f1); }

    /* ── Metric Cards ── */
    .metric-row { display: flex; gap: 12px; margin-bottom: 20px; }
    .metric-card {
        flex: 1; background: #0d1117;
        border: 1px solid #1f2d3d; border-radius: 14px;
        padding: 18px 16px; text-align: center;
    }
    .metric-val { font-size: 2.2rem; font-weight: 900; line-height: 1; }
    .metric-val.blue   { color: #60a5fa; }
    .metric-val.green  { color: #34d399; }
    .metric-val.purple { color: #a78bfa; }
    .metric-val.orange { color: #fb923c; }
    .metric-lbl { font-size: 0.75rem; color: #64748b; margin-top: 6px; }

    /* ── Log Box ── */
    .log-box {
        background: #060b14;
        border: 1px solid #1f2d3d; border-radius: 12px;
        padding: 16px; font-family: 'Consolas','Courier New',monospace;
        font-size: 0.82rem; height: 360px; overflow-y: auto;
        line-height: 1.8; direction: ltr;
    }
    .log-success { color: #4ade80; }
    .log-error   { color: #f87171; }
    .log-warn    { color: #fbbf24; }
    .log-info    { color: #93c5fd; }
    .log-dim     { color: #334155; }

    /* ── Lead Table Row ── */
    .lead-row {
        display: flex; align-items: center; gap: 12px;
        background: #0d1117; border: 1px solid #1f2d3d;
        border-radius: 10px; padding: 10px 14px; margin: 5px 0;
        transition: border-color 0.2s;
    }
    .lead-row:hover { border-color: #6366f1; }
    .lead-avatar {
        width: 36px; height: 36px; border-radius: 50%;
        background: linear-gradient(135deg, #6366f1, #8b5cf6);
        display: flex; align-items: center; justify-content: center;
        font-size: 0.9rem; font-weight: 700; color: #fff; flex-shrink: 0;
    }
    .lead-user { color: #93c5fd; font-weight: 700; font-size: 0.9rem; }
    .lead-comment { color: #94a3b8; font-size: 0.82rem; flex: 1; }

    /* ── Status Badge ── */
    .status-badge {
        padding: 5px 14px; border-radius: 20px;
        font-size: 0.8rem; font-weight: 700; display: inline-block;
    }
    .badge-running  { background: #14532d; color: #86efac; }
    .badge-scraping { background: #1e1b4b; color: #a5b4fc; }
    .badge-stopped  { background: #1f2d3d; color: #64748b; }

    /* ── Primary Button override ── */
    .stButton > button[kind="primary"] {
        background: linear-gradient(135deg, #6366f1, #8b5cf6) !important;
        border: none !important; border-radius: 10px !important;
        font-weight: 700 !important; font-size: 1rem !important;
        padding: 12px 24px !important;
        transition: opacity 0.2s !important;
    }
    .stButton > button[kind="primary"]:hover { opacity: 0.88 !important; }
    .stButton > button {
        border-radius: 8px !important; font-weight: 600 !important;
    }

    /* ── Inputs ── */
    .stTextInput input, .stNumberInput input, .stTextArea textarea,
    .stSelectbox select {
        background-color: #0d1117 !important;
        color: #e2e8f0 !important;
        border-color: #1f2d3d !important;
        border-radius: 8px !important;
    }

    /* ── Section title ── */
    .stitle {
        color: #6366f1; font-size: 0.8rem; font-weight: 700;
        text-transform: uppercase; letter-spacing: 0.1em;
        border-bottom: 1px solid #1f2d3d; padding-bottom: 6px;
        margin: 20px 0 14px;
    }

    /* ── Info box ── */
    .info-box {
        background: #0d1d30; border: 1px solid #1e3a5f;
        border-radius: 10px; padding: 12px 16px;
        color: #93c5fd; font-size: 0.85rem; margin: 10px 0;
    }

    #MainMenu { visibility: hidden; }
    footer { visibility: hidden; }
    .stDeployButton { display: none; }

    @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.4} }
    .pulse { animation: pulse 1.5s ease-in-out infinite; }
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════
#  تهيئة الحالة
# ══════════════════════════════════════════════════════════════════

def _init_state():
    defaults = {
        "log_lines":         [],
        "log_queue":         queue.Queue(),
        "is_running":        False,
        "stop_event":        threading.Event(),
        "bot_thread":        None,
        "dm_count":          0,
        "follow_count":      0,
        "lead_count":        0,
        "skip_count":        0,
        "comments_checked":  0,
        "comments_total":    0,
        "settings_mgr":      SettingsManager(),
        "debug_screenshots": [],
        "scraped_leads":     [],
        "scrape_done":       False,
        "execute_total":     0,
        "execute_current":   0,
        "execute_username":  "",
        "batch_sent":        0,
        "batch_total":       10,
        "rest_until":        0.0,
        "rest_seconds":      0,
        "bot_start_time":    0.0,
        "bot_finished":      False,
        "current_action":    "",
        # ── نظام الخطوات ──
        "current_step":      1,   # 1=Scrape  2=Filter  3=Execute
        # ── SaaS Portal ──
        "site_user":         None,
        "site_user_data":    None,
        "login_error":       "",
        "admin_tab":         "users",
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init_state()

# ── تحديث settings_mgr بملف الإعدادات الخاص بالمستخدم عند تسجيل الدخول ──
if st.session_state.site_user and st.session_state.settings_mgr.settings_file == "settings.json":
    _user_settings_file = sdb.get_settings_file(st.session_state.site_user)
    st.session_state.settings_mgr = SettingsManager(_user_settings_file)

mgr: SettingsManager = st.session_state.settings_mgr


# ══════════════════════════════════════════════════════════════════
#  بوابة تسجيل الدخول
# ══════════════════════════════════════════════════════════════════

def _show_login_portal():
    st.markdown("""
    <style>
    .stApp { background: #060b14; }
    .login-wrap {
        min-height: 100vh; display: flex; align-items: center;
        justify-content: center; padding: 40px 16px;
    }
    .login-card {
        background: linear-gradient(135deg, #0d1117 0%, #111827 100%);
        border: 1px solid #1e3a5f;
        border-radius: 24px;
        padding: 48px 44px 40px;
        max-width: 440px; width: 100%;
        box-shadow: 0 32px 80px rgba(0,0,0,0.6);
    }
    </style>
    """, unsafe_allow_html=True)

    st.markdown("""
    <div style="text-align:center; margin-bottom:32px;">
      <pre style="
        font-family:'Courier New',monospace; font-size:0.6rem; line-height:1.2;
        background: linear-gradient(90deg,#38bdf8,#818cf8,#34d399);
        -webkit-background-clip:text; -webkit-text-fill-color:transparent;
        background-clip:text; margin:0 0 6px;
      ">
 ██╗███╗   ██╗███████╗████████╗ █████╗       ██╗     ███████╗ █████╗ ██████╗
 ██║████╗  ██║██╔════╝╚══██╔══╝██╔══██╗      ██║     ██╔════╝██╔══██╗██╔══██╗
 ██║██╔██╗ ██║███████╗   ██║   ███████║█████╗██║     █████╗  ███████║██║  ██║
 ██║██║╚██╗██║╚════██║   ██║   ██╔══██║╚════╝██║     ██╔══╝  ██╔══██║██║  ██║
 ██║██║ ╚████║███████║   ██║   ██║  ██║      ███████╗███████╗██║  ██║██████╔╝
 ╚═╝╚═╝  ╚═══╝╚══════╝   ╚═╝   ╚═╝  ╚═╝      ╚══════╝╚══════╝╚═╝  ╚═╝╚═════╝</pre>
      <p style="color:#475569; font-size:0.78rem; font-family:'Courier New',monospace; margin:0;">
        Developed by <span style="color:#38bdf8; font-weight:700;">Amir Emad</span>
        &nbsp;|&nbsp; v7.0 Stealth Edition
      </p>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("""
    <div style="
      background: linear-gradient(135deg, #0d1117 0%, #111827 100%);
      border: 1px solid #1e3a5f;
      border-radius: 20px;
      padding: 40px 36px 32px;
      max-width: 420px;
      margin: 0 auto;
      box-shadow: 0 24px 64px rgba(0,0,0,0.5);
    ">
      <div style="text-align:center; margin-bottom:28px;">
        <div style="font-size:2.4rem; margin-bottom:8px;">🔐</div>
        <div style="color:#f1f5f9; font-size:1.3rem; font-weight:700;">تسجيل الدخول</div>
        <div style="color:#64748b; font-size:0.8rem; margin-top:4px;">أدخل بيانات حسابك للمتابعة</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # تبديل بين الدخول والتسجيل
    _portal_mode = st.session_state.get("portal_mode", "login")
    _toggle_label = "📝 إنشاء حساب جديد" if _portal_mode == "login" else "🔐 لديّ حساب — تسجيل الدخول"
    if st.button(_toggle_label, use_container_width=True, key="btn_portal_toggle"):
        st.session_state.portal_mode = "register" if _portal_mode == "login" else "login"
        st.rerun()

    st.markdown("<br>", unsafe_allow_html=True)

    if _portal_mode == "login":
        with st.form("login_form", clear_on_submit=False):
            st.markdown('<div style="max-width:420px; margin:0 auto;">', unsafe_allow_html=True)
            username_in = st.text_input(
                "👤 اسم المستخدم",
                placeholder="أدخل اسم المستخدم",
                key="login_username_inp",
            )
            password_in = st.text_input(
                "🔑 كلمة المرور",
                type="password",
                placeholder="أدخل كلمة المرور",
                key="login_password_inp",
            )
            submitted = st.form_submit_button(
                "🚀 دخول",
                type="primary",
                use_container_width=True,
            )
            st.markdown('</div>', unsafe_allow_html=True)

            if submitted:
                u = (username_in or "").strip()
                p = (password_in or "").strip()
                if not u or not p:
                    st.error("⚠️ أدخل اسم المستخدم وكلمة المرور")
                else:
                    _chk = sdb.get_user(u)
                    if not _chk:
                        st.error("❌ اسم المستخدم أو كلمة المرور غير صحيحة")
                    elif not _chk.get("is_active"):
                        st.error("⛔ حسابك غير نشط. تواصل مع الدعم لتفعيل حسابك.")
                    else:
                        user_data = sdb.verify_password(u, p)
                        if user_data:
                            if not sdb.is_subscription_active(u):
                                st.error("⛔ انتهى اشتراكك. تواصل مع الدعم لتجديده.")
                            else:
                                st.session_state.site_user      = u
                                st.session_state.site_user_data = user_data
                                st.session_state.login_error    = ""
                                _user_settings_file = sdb.get_settings_file(u)
                                st.session_state.settings_mgr   = SettingsManager(_user_settings_file)
                                st.rerun()
                        else:
                            st.error("❌ اسم المستخدم أو كلمة المرور غير صحيحة")

    else:
        # ── نموذج إنشاء حساب جديد ──
        st.markdown("""
        <div style="
          background:#0d1117; border:1px solid #1e3a5f; border-radius:16px;
          padding:28px 28px 20px; max-width:420px; margin:0 auto;
        ">
          <div style="text-align:center; margin-bottom:20px;">
            <div style="font-size:2rem;">📝</div>
            <div style="color:#f1f5f9; font-size:1.1rem; font-weight:700; margin-top:6px;">إنشاء حساب جديد</div>
            <div style="color:#64748b; font-size:0.75rem; margin-top:4px;">
              سيتم مراجعة حسابك وتفعيله من قِبَل المدير
            </div>
          </div>
        </div>
        """, unsafe_allow_html=True)
        with st.form("register_form", clear_on_submit=True):
            _ru = st.text_input("👤 اسم المستخدم", placeholder="اختر اسم مستخدم", key="reg_u")
            _rp = st.text_input("🔑 كلمة المرور", type="password", placeholder="أدخل كلمة مرور قوية", key="reg_p")
            _rp2 = st.text_input("🔑 تأكيد كلمة المرور", type="password", placeholder="أعد إدخال كلمة المرور", key="reg_p2")
            _re = st.text_input("📧 الإيميل (اختياري)", placeholder="email@example.com", key="reg_e")
            _reg_sub = st.form_submit_button("📨 إرسال طلب التسجيل", type="primary", use_container_width=True)
            if _reg_sub:
                _ru = (_ru or "").strip().lower()
                _rp = (_rp or "").strip()
                _rp2 = (_rp2 or "").strip()
                if not _ru or not _rp:
                    st.error("⚠️ أدخل اسم المستخدم وكلمة المرور")
                elif len(_ru) < 3:
                    st.error("⚠️ اسم المستخدم يجب أن يكون 3 أحرف على الأقل")
                elif _rp != _rp2:
                    st.error("❌ كلمتا المرور غير متطابقتين")
                elif len(_rp) < 6:
                    st.error("⚠️ كلمة المرور يجب أن تكون 6 أحرف على الأقل")
                else:
                    _ok = sdb.add_user(
                        username=_ru,
                        password=_rp,
                        email=_re.strip(),
                        plan="trial",
                        subscription_end=None,
                        is_active=0,  # معلق حتى يفعّله المدير
                    )
                    if _ok:
                        st.success("✅ تم إرسال طلبك! سيتم مراجعته وتفعيله من قِبَل المدير.")
                        st.session_state.portal_mode = "login"
                    else:
                        st.error("❌ اسم المستخدم هذا مأخوذ، اختر اسماً آخر")


# ══════════════════════════════════════════════════════════════════
#  دوال مساعدة
# ══════════════════════════════════════════════════════════════════

def _drain_queue():
    while True:
        try:
            msg = st.session_state.log_queue.get_nowait()

            if msg.startswith("DEBUG_SCREENSHOT:"):
                path = msg.split("DEBUG_SCREENSHOT:", 1)[1].strip()
                if path and Path(path).exists():
                    shots = st.session_state.debug_screenshots
                    if path not in shots:
                        shots.append(path)
                        st.session_state.debug_screenshots = shots[-5:]
                continue

            if msg.startswith("SCRAPED_LEADS:"):
                try:
                    new = json.loads(msg.split("SCRAPED_LEADS:", 1)[1].strip())
                    st.session_state.scraped_leads.extend(new)
                except Exception:
                    pass
                continue

            if msg.strip() == "SCRAPE_DONE":
                st.session_state.scrape_done = True
                st.session_state.is_running = False
                # الانتقال تلقائياً للخطوة الثانية
                if st.session_state.scraped_leads:
                    st.session_state.current_step = 2
                continue

            exec_total = re.search(r"EXEC_TOTAL\s+total=(\d+)", msg)
            if exec_total:
                st.session_state.execute_total = int(exec_total.group(1))
                st.session_state.execute_current = 0
                st.session_state.bot_start_time = time.time()
                st.session_state.bot_finished = False
                continue

            exec_prog = re.search(r"EXEC_PROGRESS\s+current=(\d+)\s+total=(\d+)\s+username=(.*)", msg)
            if exec_prog:
                st.session_state.execute_current = int(exec_prog.group(1))
                st.session_state.execute_total = int(exec_prog.group(2))
                st.session_state.execute_username = exec_prog.group(3).strip()
                continue

            batch = re.search(r"BATCH_STATUS\s+sent=(\d+)\s+total=(\d+)", msg)
            if batch:
                st.session_state.batch_sent = int(batch.group(1))
                st.session_state.batch_total = int(batch.group(2))
                continue

            rest_start = re.search(r"REST_START\s+seconds=(\d+)", msg)
            if rest_start:
                seconds = int(rest_start.group(1))
                st.session_state.rest_seconds = seconds
                st.session_state.rest_until = time.time() + seconds
                continue

            if msg.strip() == "REST_END":
                st.session_state.rest_until = 0.0
                st.session_state.rest_seconds = 0
                continue

            # ── LEAD_PROCESSING: عرض سطر "جاري المعالجة" مع الكتابة فوق السابق ──
            lead_proc = re.match(r"LEAD_PROCESSING:(\S+)\s+(@\S+)", msg)
            if lead_proc:
                idx, uname = lead_proc.group(1), lead_proc.group(2)
                new_line = f"⏳ [{idx}] {uname} | جاري المعالجة..."
                st.session_state.current_action = f"🔍 جاري فحص بروفايل {uname}..."
                lines = st.session_state.log_lines
                if lines and lines[-1].startswith("⏳"):
                    lines[-1] = new_line
                else:
                    lines.append(new_line)
                continue

            # ── LEAD_ACTION: سطر التفاصيل اللحظية ──
            lead_action = re.match(r"LEAD_ACTION:(\S+)\s+(@\S+)\s+(.*)", msg)
            if lead_action:
                idx, uname, action = lead_action.group(1), lead_action.group(2), lead_action.group(3)
                st.session_state.current_action = f"{action} {uname}"
                continue

            # ── LEAD_DONE_OK: استبدال سطر ⏳ بـ ✅ ──
            lead_ok = re.match(r"LEAD_DONE_OK:(\S+)\s+(@\S+)", msg)
            if lead_ok:
                idx, uname = lead_ok.group(1), lead_ok.group(2)
                final_line = f"✅ [{idx}] {uname} | تم الإرسال بنجاح"
                st.session_state.current_action = f"✅ تم إرسال الرسالة لـ {uname}"
                lines = st.session_state.log_lines
                if lines and lines[-1].startswith("⏳"):
                    lines[-1] = final_line
                else:
                    lines.append(final_line)
                st.session_state.dm_count += 1
                continue

            # ── LEAD_DONE_SKIP: استبدال سطر ⏳ بـ ⏭ ──
            lead_skip = re.match(r"LEAD_DONE_SKIP:(\S+)\s+(@\S+)", msg)
            if lead_skip:
                idx, uname = lead_skip.group(1), lead_skip.group(2)
                final_line = f"⏭ [{idx}] {uname} | تم التخطي"
                st.session_state.current_action = f"⏭ تخطي {uname}"
                lines = st.session_state.log_lines
                if lines and lines[-1].startswith("⏳"):
                    lines[-1] = final_line
                else:
                    lines.append(final_line)
                st.session_state.skip_count += 1
                continue

            ts = datetime.now().strftime("%H:%M:%S")
            # ── تنظيف السجل: صيغة مختصرة ──
            clean = _clean_log_line(msg)
            if clean is not None:
                st.session_state.log_lines.append(f"[{ts}]  {clean}")

            if "📨" in msg or "رسالة لـ @" in msg or "dm_sent" in msg.lower():
                st.session_state.dm_count += 1
            if "متابعة @" in msg and "✅" in msg:
                st.session_state.follow_count += 1
            prog = re.search(r"PROGRESS_COMMENTS\s+total=(\d+)\s+checked=(\d+)\s+leads=(\d+)", msg)
            if prog:
                st.session_state.comments_total   = int(prog.group(1))
                st.session_state.comments_checked = int(prog.group(2))
                st.session_state.lead_count = max(st.session_state.lead_count, int(prog.group(3)))
            elif "عميل محتمل:" in msg or "✅ عميل" in msg or "العميل [" in msg:
                st.session_state.lead_count += 1

        except queue.Empty:
            break


def _clean_log_line(msg: str) -> str:
    """تحويل رسائل السجل المطوّلة إلى سطر مختصر واحد"""

    # ── رسائل الإرسال الناجح ──
    m = re.search(r"📨.*رسالة لـ @(\S+)", msg)
    if m:
        acc = "🔒 خاص" if "خاص" in msg else "🌐 عام"
        return f"[✅] تم إرسال: @{m.group(1)} | {acc}"

    # ── JS Direct ناجح ──
    m = re.search(r"JS.*Direct.*@(\S+)", msg)
    if m and "✅" in msg:
        return f"[✅] اتصل بـ Direct: @{m.group(1)}"

    # ── رسائل المتابعة ──
    m = re.search(r"✅.*متابعة @(\S+)", msg)
    if m:
        return f"[👤] متابعة: @{m.group(1)} | الحالة: ناجح"

    # ── رسائل الخطأ ──
    if "❌" in msg or "خطأ" in msg.lower() or "error" in msg.lower():
        short = msg.strip()[:100]
        return f"[❌] {short}"

    # ── رسائل التحذير ──
    if "⚠" in msg or "🚫" in msg or "⛔" in msg:
        return f"[⚠️] {msg.strip()[:100]}"

    # ── تخطي حقيقي: مُرسل مسبقاً فقط ──
    # (لا يشمل "الرد التلقائي معطّل" بعد تغيير إيموجيه لـ 🔕)
    if ("⏭" in msg or "تخطي" in msg) and (
        "مسبقاً" in msg or "مُرسل" in msg or "تخطي @" in msg
    ):
        m = re.search(r"@(\S+)", msg)
        u = f"@{m.group(1)}" if m else ""
        return f"[⏭] تخطي: {u} (مُرسل مسبقاً)"

    # ── الرد التلقائي معطّل — ليس تخطي حقيقي ──
    if "الرد التلقائي معطّل" in msg or "🔕" in msg:
        return None  # تجاهل تماماً من الـ UI

    # ── حساب خاص ──
    if "خاص" in msg and "@" in msg:
        m = re.search(r"@(\S+)", msg)
        u = f"@{m.group(1)}" if m else ""
        return f"[🔒] حساب خاص: {u} | طلب متابعة مُرسل"

    # ── باقي الرسائل مختصرة ──
    return msg.strip()[:120]


def _log_html() -> str:
    lines = st.session_state.log_lines[-150:]
    html = []
    for line in lines:
        low = line.lower()
        # ── سطور LEAD_ المختصرة ──
        if line.startswith("✅"):
            cls = "log-success"
        elif line.startswith("⏭"):
            cls = "log-warn"
        elif line.startswith("⏳"):
            cls = "log-info"
        elif "❌" in line or "خطأ" in line or "error" in low:
            cls = "log-error"
        elif "⚠" in line or "⛔" in line or "🔒" in line:
            cls = "log-warn"
        elif any(k in line for k in ("─", "═", "🚀", "🔍", "📋")):
            cls = "log-dim"
        else:
            cls = "log-info"
        safe = line.replace("<", "&lt;").replace(">", "&gt;")
        html.append(f'<div class="{cls}">{safe}</div>')
    return "\n".join(html)


def _rest_remaining() -> int:
    rest_until = float(st.session_state.get("rest_until", 0.0) or 0.0)
    if rest_until <= 0:
        return 0
    remaining = max(int(rest_until - time.time()), 0)
    if remaining == 0:
        st.session_state.rest_until = 0.0
        st.session_state.rest_seconds = 0
    return remaining


def _format_seconds(seconds: int) -> str:
    minutes, secs = divmod(max(int(seconds), 0), 60)
    return f"{minutes:02d}:{secs:02d}"


def _keywords_to_text(kw) -> str:
    if isinstance(kw, str): return kw
    return "\n".join(str(k).strip() for k in kw if str(k).strip())


def _text_to_list(text: str) -> list[str]:
    return [l.strip() for l in text.replace(",", "\n").splitlines() if l.strip()]


def _templates_to_text(t) -> str:
    if isinstance(t, str): return t
    return "\n\n".join(str(x).strip() for x in t if str(x).strip())


def _text_to_templates(text: str) -> list[str]:
    blocks = [p.strip() for p in text.split("\n\n") if p.strip()]
    if len(blocks) > 1: return blocks
    def _pipe(s):
        parts, depth, cur = [], 0, []
        for ch in s:
            if ch == '{': depth += 1; cur.append(ch)
            elif ch == '}': depth -= 1; cur.append(ch)
            elif ch == '|' and depth == 0:
                p = ''.join(cur).strip()
                if p: parts.append(p); cur = []
            else: cur.append(ch)
        last = ''.join(cur).strip()
        if last: parts.append(last)
        return parts
    return _pipe(text) if blocks else _text_to_list(text)


def _load_leads_from_db() -> list[dict]:
    db = _dir / "leads.db"
    if not db.exists(): return []
    try:
        conn = sqlite3.connect(str(db))
        conn.row_factory = sqlite3.Row
        rows = [dict(r) for r in conn.execute("SELECT * FROM leads ORDER BY created_at DESC").fetchall()]
        conn.close()
        return rows
    except Exception:
        return []


def _leads_to_csv(leads: list[dict]) -> str:
    if not leads: return ""
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=leads[0].keys())
    w.writeheader(); w.writerows(leads)
    return out.getvalue()


def _leads_to_excel(leads: list[dict]) -> bytes:
    try:
        import openpyxl
        wb = openpyxl.Workbook(); ws = wb.active; ws.title = "العملاء"
        if leads:
            h = list(leads[0].keys()); ws.append(h)
            for l in leads: ws.append([l.get(k, "") for k in h])
        buf = io.BytesIO(); wb.save(buf); return buf.getvalue()
    except Exception: return b""


def _sanitize_cookies(raw_json: str):
    """تنظيف وتحويل الكوكيز من JSON إلى صيغة Playwright"""
    data = json.loads(raw_json)
    if isinstance(data, list):
        cookies = []
        for c in data:
            ck = {
                "name":     c.get("name", ""),
                "value":    c.get("value", ""),
                "domain":   c.get("domain", ".instagram.com"),
                "path":     c.get("path", "/"),
                "expires":  float(c.get("expirationDate", c.get("expires", -1))),
                "httpOnly": bool(c.get("httpOnly", False)),
                "secure":   bool(c.get("secure", True)),
                "sameSite": c.get("sameSite", "None"),
            }
            # تصحيح domain
            if not ck["domain"].startswith("."):
                ck["domain"] = ".instagram.com"
            if ck["name"] and ck["value"]:
                cookies.append(ck)
        return {"cookies": cookies, "origins": []}
    elif isinstance(data, dict) and "cookies" in data:
        return data
    raise ValueError("صيغة غير معروفة")


# ══════════════════════════════════════════════════════════════════
#  Thread starters
# ══════════════════════════════════════════════════════════════════

def _run_scrape(username, password, urls, settings, log_q, stop_ev):
    import traceback as tb
    try:
        from bot_runner import BotRunner
    except ImportError as e:
        log_q.put_nowait(f"❌ خطأ: {e}"); return
    settings["username"] = username; settings["password"] = password
    stop_ev.clear()
    try:
        r = BotRunner(settings=settings, target_posts=urls,
                      log_queue=log_q, stop_event=stop_ev,
                      on_finish=None, scrape_only=True)
        r.run_in_thread()
    except Exception as e:
        log_q.put_nowait(f"❌ {e}\n{tb.format_exc()}")


def _run_turbo(username, password, settings, log_q, stop_ev, leads):
    import traceback as tb
    try:
        from bot_runner import BotRunner
    except ImportError as e:
        log_q.put_nowait(f"❌ خطأ: {e}"); return
    settings["username"] = username; settings["password"] = password
    stop_ev.clear()
    try:
        r = BotRunner(settings=settings, target_posts=[],
                      log_queue=log_q, stop_event=stop_ev,
                      on_finish=None, turbo_mode=True,
                      pre_selected_leads=leads)
        r.run_in_thread()
    except Exception as e:
        log_q.put_nowait(f"❌ {e}\n{tb.format_exc()}")


# ══════════════════════════════════════════════════════════════════
#  Guard: عرض بوابة الدخول لو المستخدم غير مسجل
# ══════════════════════════════════════════════════════════════════

if not st.session_state.site_user:
    # إخفاء الشريط الجانبي كلياً أثناء صفحة الدخول
    st.markdown("""
    <style>
    [data-testid="stSidebar"] { display: none !important; }
    [data-testid="collapsedControl"] { display: none !important; }
    </style>
    """, unsafe_allow_html=True)
    _show_login_portal()
    st.stop()

# ══════════════════════════════════════════════════════════════════
#  شريط الجانب – الإعدادات
# ══════════════════════════════════════════════════════════════════

with st.sidebar:
    st.markdown("### ⚡ Instagram Predator v7.0")
    st.markdown('<hr style="border-color:#1f2d3d;margin:8px 0 10px">', unsafe_allow_html=True)

    # ── معلومات المستخدم المسجل ──
    _su = st.session_state.site_user or ""
    _sd = st.session_state.site_user_data or {}
    _plan_color = {"unlimited": "#34d399", "trial": "#fbbf24"}.get(_sd.get("plan","trial"), "#60a5fa")
    st.markdown(f"""
    <div style="
      background:#0d1117; border:1px solid #1f2d3d; border-radius:12px;
      padding:12px 14px; margin-bottom:10px;
    ">
      <div style="color:#f1f5f9; font-weight:700; font-size:0.9rem;">👤 @{_su}</div>
      <div style="color:{_plan_color}; font-size:0.75rem; margin-top:3px;">
        ● {(_sd.get('plan','trial') or 'trial').upper()}
      </div>
    </div>
    """, unsafe_allow_html=True)

    if st.button("🚪 تسجيل الخروج", use_container_width=True, key="btn_logout"):
        st.session_state.site_user      = None
        st.session_state.site_user_data = None
        st.session_state.settings_mgr   = SettingsManager()
        st.session_state.is_running     = False
        st.rerun()

    # ── لوحة الأدمن ──
    _is_admin = bool(_sd.get("is_admin", 0)) if _sd else (_su == "admin")
    if _is_admin:
        st.markdown('<hr style="border-color:#1e3a5f;margin:6px 0 10px">', unsafe_allow_html=True)
        _admin_mode = st.session_state.get("admin_panel_open", False)
        _btn_label  = "✖️ إغلاق لوحة الإدارة" if _admin_mode else "🛠️ لوحة إدارة المستخدمين"
        if st.button(_btn_label, use_container_width=True, key="btn_admin_toggle"):
            st.session_state.admin_panel_open = not _admin_mode
            st.rerun()

    st.markdown('<hr style="border-color:#1f2d3d;margin:8px 0 16px">', unsafe_allow_html=True)

    # ── حالة التشغيل ──
    if st.session_state.is_running:
        if st.session_state.current_step == 1 or st.session_state.scraped_leads == []:
            badge_html = '<span class="status-badge badge-scraping pulse">🔍 يسحب...</span>'
        else:
            badge_html = '<span class="status-badge badge-running pulse">⚡ يرسل...</span>'
    else:
        badge_html = '<span class="status-badge badge-stopped">⏹ متوقف</span>'
    st.markdown(badge_html, unsafe_allow_html=True)
    st.markdown("")

    # ── بيانات الدخول ──
    st.markdown('<p class="stitle">🔐 بيانات الدخول</p>', unsafe_allow_html=True)
    username_input = st.text_input("اسم المستخدم", value=mgr.get("username", ""),
                                   placeholder="instagram_username", key="inp_user")
    password_input = st.text_input("كلمة المرور",  value=mgr.get("password", ""),
                                   type="password", key="inp_pass")

    # ── حقن الكوكيز ──
    with st.expander("🍪 حقن الجلسة (كوكيز)"):
        cookies_raw = st.text_area("الصق كوكيز JSON", height=110,
                                   placeholder='[{"name":"sessionid","value":"..."}]',
                                   key="cookies_json_raw")
        c1, c2 = st.columns(2)
        with c1:
            if st.button("💉 حفظ", key="btn_inj"):
                raw = (cookies_raw or "").strip()
                if not raw:
                    st.error("الصق الكوكيز أولاً")
                else:
                    try:
                        sess = _sanitize_cookies(raw)
                        sp = _dir / "session_state.json"
                        with open(sp, "w", encoding="utf-8") as f:
                            json.dump(sess, f, ensure_ascii=False, indent=2)
                        st.success(f"✅ {len(sess.get('cookies',[]))} كوكيز محفوظة")
                    except Exception as e:
                        st.error(f"❌ {e}")
        with c2:
            if st.button("🗑 حذف", key="btn_del_sess"):
                sp = _dir / "session_state.json"
                sp.unlink(missing_ok=True)
                st.success("✅ حُذفت الجلسة")

        sp = _dir / "session_state.json"
        if sp.exists():
            try:
                cnt = len(json.loads(sp.read_text()).get("cookies", []))
                st.success(f"🍪 جلسة نشطة: {cnt} كوكيز")
            except Exception:
                st.warning("⚠️ ملف الجلسة تالف")
        else:
            st.info("ℹ️ لا توجد جلسة")

    # ── قوالب الرسائل ──
    st.markdown('<p class="stitle">✉️ قوالب الرسائل</p>', unsafe_allow_html=True)
    msg_text = st.text_area("القوالب (افصل بسطر فارغ أو |)",
                             value=_templates_to_text(mgr.get("message_templates", [])),
                             height=150, key="msg_tmpl")

    # ── الكلمات المفتاحية ──
    with st.expander("🔑 الكلمات المفتاحية للفلترة"):
        kw_text = st.text_area("كلمة في كل سطر",
                               value=_keywords_to_text(mgr.get("keywords", [])),
                               height=120, key="kw_inp")

    # ── الحدود والتأخيرات ──
    with st.expander("⏱ حدود وتأخيرات"):
        max_dm     = st.number_input("حد DM يومي",     min_value=1, max_value=200, value=int(mgr.get("max_dm_per_day", 20)))
        max_follow = st.number_input("حد متابعات يومي", min_value=1, max_value=200, value=int(mgr.get("max_follows_per_day", 30)))
        max_scroll = st.number_input("تمريرات التعليقات",min_value=1, max_value=50,  value=int(mgr.get("max_comments_scroll", 15)))
        d_min_msg  = st.number_input("تأخير رسالة (أدنى)", min_value=1, max_value=300, value=int(mgr.get("delay_min_message", 15)))
        d_max_msg  = st.number_input("تأخير رسالة (أقصى)", min_value=1, max_value=600, value=int(mgr.get("delay_max_message", 35)))
        headless   = st.checkbox("Headless (بدون نافذة)", value=bool(mgr.get("headless_mode", True)))

    # ── إعدادات الأمان والذكاء ──
    with st.expander("🛡️ الأمان والذكاء"):
        mobile_emu = st.checkbox(
            "📱 محاكاة الموبايل (iPhone)",
            value=bool(mgr.get("mobile_emulation", True)),
            help="iPhone 15 Pro Max user-agent + touch viewport 390×844"
        )
        competitor_filter = st.checkbox(
            "🚫 فلترة المنافسين (Bio)",
            value=bool(mgr.get("competitor_filter", True)),
            help="يتخطى الحسابات التي تحتوي بيوغرافيتها كلمات مثل: عقارات، broker، شركة..."
        )
        comp_kw_text = st.text_area(
            "كلمات المنافسين (سطر لكل كلمة)",
            value="\n".join(mgr.get("competitor_keywords", [
                "broker", "real estate", "realtor", "property", "developer",
                "عقارات", "شركة", "تسويق", "وسيط", "بروكر", "عقار", "مطور",
            ])),
            height=100,
            disabled=not competitor_filter,
            key="comp_kw_inp"
        )

    # ── الردود التلقائية ──
    with st.expander("💬 ردود تلقائية"):
        pub_reply  = st.checkbox("رد على الحسابات العامة",  value=bool(mgr.get("public_auto_reply", True)))
        pub_text   = st.text_input("نص الرد (عام)",  value=mgr.get("comment_reply_text", "تم التواصل ✅"), disabled=not pub_reply)
        priv_reply = st.checkbox("رد على الحسابات الخاصة", value=bool(mgr.get("private_auto_reply", False)))
        priv_text  = st.text_input("نص الرد (خاص)", value=mgr.get("private_reply_text", "مرسلنا التفاصيل ✅"), disabled=not priv_reply)

    # ── زر الحفظ ──
    if st.button("💾 حفظ الإعدادات", use_container_width=True, type="primary"):
        mgr.update({
            "username": username_input, "password": password_input,
            "max_dm_per_day": max_dm, "max_follows_per_day": max_follow,
            "max_comments_scroll": max_scroll,
            "delay_min_message": d_min_msg, "delay_max_message": d_max_msg,
            "headless_mode": headless,
            "public_auto_reply": pub_reply, "comment_reply_text": pub_text,
            "private_auto_reply": priv_reply, "private_reply_text": priv_text,
            "message_templates": _text_to_templates(msg_text),
            "keywords": _text_to_list(kw_text),
            "mobile_emulation": mobile_emu,
            "competitor_filter": competitor_filter,
            "competitor_keywords": [k.strip() for k in comp_kw_text.splitlines() if k.strip()],
        })
        st.success("✅ تم الحفظ")

    # ── Follow-up: إرسال للمقبولين ──
    st.markdown('<hr style="border-color:#1f2d3d;margin:16px 0 10px">', unsafe_allow_html=True)
    st.markdown('<p class="stitle">🔔 متابعة الحسابات الخاصة</p>', unsafe_allow_html=True)
    if st.button("📬 إرسال للمقبولين (Follow-up)",
                 use_container_width=True,
                 disabled=st.session_state.is_running,
                 key="btn_followup"):
        _uname = mgr.get("username", username_input)
        _pwd   = mgr.get("password", password_input)
        if not _uname or not _pwd:
            st.error("أدخل بيانات الدخول أولاً")
        else:
            st.session_state.is_running = True
            st.session_state.current_step = 3
            st.session_state.log_lines.clear()
            import traceback as _tb
            try:
                from bot_runner import BotRunner
                _settings = mgr.get_all()
                _settings["username"] = _uname
                _settings["password"] = _pwd
                st.session_state.stop_event.clear()
                _runner = BotRunner(
                    settings=_settings,
                    target_posts=[],
                    log_queue=st.session_state.log_queue,
                    stop_event=st.session_state.stop_event,
                    on_finish=lambda: None,
                )
                import threading as _thr
                _t = _thr.Thread(target=_runner.run_followup_in_thread, daemon=True)
                _t.start()
                st.success("✅ Follow-up بدأ! راجع اللوج...")
            except Exception as _e:
                st.error(f"❌ {_e}")
                st.session_state.is_running = False
            st.rerun()

    # ── إيقاف طارئ ──
    st.markdown('<hr style="border-color:#1f2d3d;margin:16px 0 10px">', unsafe_allow_html=True)
    if st.button("⛔ إيقاف طارئ", use_container_width=True,
                 disabled=not st.session_state.is_running, key="btn_stop_sidebar"):
        st.session_state.stop_event.set()
        st.session_state.is_running = False
        st.session_state.log_lines.append(
            f"[{datetime.now().strftime('%H:%M:%S')}]  🛑 إيقاف طارئ - جارٍ إغلاق المتصفح"
        )
        st.rerun()


# ══════════════════════════════════════════════════════════════════
#  Main Area
# ══════════════════════════════════════════════════════════════════

_drain_queue()

# ══════════════════════════════════════════════════════════════════
#  لوحة إدارة المستخدمين (أدمن فقط)
# ══════════════════════════════════════════════════════════════════

_cur_user_data = st.session_state.site_user_data or {}
_cur_is_admin  = bool(_cur_user_data.get("is_admin", 0)) or st.session_state.site_user == "admin"

if _cur_is_admin and st.session_state.get("admin_panel_open", False):

    st.markdown("""
    <div style="
      background: linear-gradient(135deg,#0d1117,#111827);
      border:1px solid #6366f1; border-radius:18px;
      padding:28px 32px; margin-bottom:28px;
    ">
      <div style="font-size:1.35rem;font-weight:800;color:#f1f5f9;margin-bottom:4px;">
        🛠️ لوحة إدارة المستخدمين
      </div>
      <div style="color:#64748b;font-size:0.8rem;">إضافة وإدارة حسابات المستخدمين</div>
    </div>
    """, unsafe_allow_html=True)

    # ── إضافة مستخدم جديد ──
    with st.expander("➕ إضافة مستخدم جديد", expanded=False):
        with st.form("add_user_form_main"):
            _ca, _cb, _cc = st.columns(3)
            _new_u   = _ca.text_input("👤 اسم المستخدم",       key="adm_u")
            _new_p   = _cb.text_input("🔑 كلمة المرور", type="password", key="adm_p")
            _new_e   = _cc.text_input("📧 الإيميل",            key="adm_e")
            _cd, _ce = st.columns(2)
            _new_pl  = _cd.selectbox("📋 الخطة", ["trial","monthly","yearly","unlimited"], key="adm_pl")
            _new_end = _ce.text_input("📅 تاريخ الانتهاء (YYYY-MM-DD)", key="adm_end")
            if st.form_submit_button("➕ إضافة المستخدم", type="primary", use_container_width=True):
                if _new_u and _new_p:
                    ok = sdb.add_user(_new_u, _new_p, _new_e, _new_pl, _new_end.strip() or None)
                    if ok:
                        st.success(f"✅ تم إضافة المستخدم @{_new_u} بنجاح")
                        st.rerun()
                    else:
                        st.error("❌ اسم المستخدم موجود بالفعل")
                else:
                    st.warning("⚠️ أدخل اسم المستخدم وكلمة المرور على الأقل")

    st.markdown("<br>", unsafe_allow_html=True)

    # ── جدول المستخدمين ──
    _users = sdb.list_users()
    _total = len(_users)
    _active_cnt = sum(1 for u in _users if u.get("is_active"))
    _m1, _m2, _m3 = st.columns(3)
    _m1.metric("إجمالي المستخدمين", _total)
    _m2.metric("المستخدمون النشطون", _active_cnt)
    _m3.metric("المعطّلون", _total - _active_cnt)

    st.markdown("<br>", unsafe_allow_html=True)

    _plan_badge = {
        "unlimited": ("🟢", "#34d399"),
        "yearly":    ("🔵", "#60a5fa"),
        "monthly":   ("🟡", "#fbbf24"),
        "trial":     ("⚪", "#94a3b8"),
    }

    for _uu in _users:
        _uname    = _uu.get("username","")
        _uemail   = _uu.get("email","—") or "—"
        _uplan    = _uu.get("plan","trial") or "trial"
        _uend     = _uu.get("subscription_end","—") or "—"
        _ulast    = (_uu.get("last_login","—") or "—")[:16]
        _ucreated = (_uu.get("created_at","—") or "—")[:10]
        _uactive  = bool(_uu.get("is_active", 1))
        _uisadm   = bool(_uu.get("is_admin", 0))
        _uid      = _uu.get("id", 0)
        _badge_ic, _badge_color = _plan_badge.get(_uplan, ("⚪","#94a3b8"))
        _status_color = "#34d399" if _uactive else "#f87171"
        _status_text  = "نشط" if _uactive else "معطّل"
        _adm_color = "#f59e0b" if _uisadm else "#475569"
        _adm_text  = "أدمن" if _uisadm else "مستخدم"

        # بيانات إنستجرام من ملف الإعدادات
        _ig = sdb.get_instagram_credentials(_uname)
        _ig_u = _ig.get("ig_username","") or "—"
        _ig_p_raw = _ig.get("ig_password","") or ""
        _show_pass_key = f"show_pass_{_uid}"
        _pass_visible  = st.session_state.get(_show_pass_key, False)
        _ig_p = _ig_p_raw if (_pass_visible and _ig_p_raw) else ("●" * min(len(_ig_p_raw), 8) if _ig_p_raw else "—")

        with st.container():
            st.markdown(f"""
            <div style="
              background:#0d1117; border:1px solid #1f2d3d; border-radius:14px;
              padding:16px 20px; margin-bottom:6px;
              display:flex; flex-wrap:wrap; gap:14px; align-items:center;
            ">
              <div style="min-width:110px;">
                <div style="color:#94a3b8;font-size:0.65rem;margin-bottom:2px;">اسم المستخدم</div>
                <div style="color:#f1f5f9;font-weight:700;font-size:0.9rem;">@{_uname}</div>
                <div style="color:{_adm_color};font-size:0.68rem;margin-top:2px;">● {_adm_text}</div>
              </div>
              <div style="min-width:130px;">
                <div style="color:#94a3b8;font-size:0.65rem;margin-bottom:2px;">الإيميل</div>
                <div style="color:#cbd5e1;font-size:0.8rem;">{_uemail}</div>
              </div>
              <div style="min-width:120px;">
                <div style="color:#94a3b8;font-size:0.65rem;margin-bottom:2px;">📸 يوزر انستجرام</div>
                <div style="color:#38bdf8;font-size:0.82rem;font-weight:600;">{_ig_u}</div>
              </div>
              <div style="min-width:110px;">
                <div style="color:#94a3b8;font-size:0.65rem;margin-bottom:2px;">🔑 باسورد انستجرام</div>
                <div style="color:#818cf8;font-size:0.82rem;font-family:'Courier New',monospace;">{_ig_p}</div>
              </div>
              <div style="min-width:85px;">
                <div style="color:#94a3b8;font-size:0.65rem;margin-bottom:2px;">الخطة</div>
                <div style="color:{_badge_color};font-weight:700;font-size:0.8rem;">{_badge_ic} {_uplan.upper()}</div>
              </div>
              <div style="min-width:95px;">
                <div style="color:#94a3b8;font-size:0.65rem;margin-bottom:2px;">تاريخ الانتهاء</div>
                <div style="color:#cbd5e1;font-size:0.8rem;">{_uend}</div>
              </div>
              <div style="min-width:115px;">
                <div style="color:#94a3b8;font-size:0.65rem;margin-bottom:2px;">آخر دخول</div>
                <div style="color:#cbd5e1;font-size:0.8rem;">{_ulast}</div>
              </div>
              <div style="min-width:85px;">
                <div style="color:#94a3b8;font-size:0.65rem;margin-bottom:2px;">تاريخ الإنشاء</div>
                <div style="color:#cbd5e1;font-size:0.8rem;">{_ucreated}</div>
              </div>
              <div style="min-width:65px;">
                <div style="color:#94a3b8;font-size:0.65rem;margin-bottom:2px;">الحالة</div>
                <div style="color:{_status_color};font-weight:700;font-size:0.8rem;">● {_status_text}</div>
              </div>
            </div>
            """, unsafe_allow_html=True)

            _btn_col1, _btn_col2, _btn_col3, _btn_col_eye, _btn_col4 = st.columns([1.2, 1.2, 1.5, 0.8, 3])
            _tog_label = "🔴 تعطيل" if _uactive else "🟢 تفعيل"
            if _btn_col1.button(_tog_label, key=f"tog_{_uid}", use_container_width=True):
                sdb.set_active(_uname, not _uactive)
                st.rerun()
            _adm_btn = "👑 إلغاء أدمن" if _uisadm else "👑 تعيين أدمن"
            if _btn_col2.button(_adm_btn, key=f"adm_{_uid}", use_container_width=True,
                                disabled=(_uname == "admin")):
                sdb.set_admin(_uname, not _uisadm)
                st.rerun()
            _eye_label = "🙈 إخفاء" if _pass_visible else "👁️ إظهار"
            if _btn_col_eye.button(_eye_label, key=f"eye_{_uid}", use_container_width=True,
                                   disabled=(not _ig_p_raw)):
                st.session_state[_show_pass_key] = not _pass_visible
                st.rerun()
            with _btn_col3.popover("✏️ تعديل", use_container_width=True):
                with st.form(f"edit_user_{_uid}"):
                    _ep = st.text_input("كلمة مرور البوابة الجديدة (اتركها فارغة للإبقاء)", type="password", key=f"ep_{_uid}")
                    _epl = st.selectbox("الخطة", ["trial","monthly","yearly","unlimited"],
                                        index=["trial","monthly","yearly","unlimited"].index(_uplan),
                                        key=f"epl_{_uid}")
                    _eend = st.text_input("تاريخ الانتهاء (YYYY-MM-DD)", value=_uend if _uend != "—" else "", key=f"eend_{_uid}")
                    if st.form_submit_button("💾 حفظ التعديلات", use_container_width=True):
                        sdb.update_subscription(_uname, _epl, _eend.strip() or None)
                        if _ep.strip():
                            sdb.update_password(_uname, _ep.strip())
                        st.success("✅ تم الحفظ")
                        st.rerun()

    st.markdown('<hr style="border-color:#1e3a5f;margin:24px 0 8px">', unsafe_allow_html=True)
    st.stop()

# ── ASCII Hero Header ──
st.markdown("""
<div style="
    background: linear-gradient(135deg, #060b14 0%, #0d1117 100%);
    border: 1px solid #1e3a5f;
    border-radius: 18px;
    padding: 28px 32px 20px;
    margin-bottom: 24px;
    position: relative;
    overflow: hidden;
">
  <div style="
    position: absolute; top: 0; left: 0; right: 0; bottom: 0;
    background: radial-gradient(ellipse at 20% 50%, rgba(99,102,241,0.06) 0%, transparent 60%),
                radial-gradient(ellipse at 80% 50%, rgba(16,185,129,0.05) 0%, transparent 60%);
    pointer-events: none;
  "></div>
  <pre style="
    font-family: 'Courier New', monospace;
    font-size: 0.72rem;
    line-height: 1.3;
    margin: 0 0 8px;
    background: linear-gradient(90deg, #38bdf8, #818cf8, #34d399);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    letter-spacing: 0.05em;
  ">
 ██╗███╗   ██╗███████╗████████╗ █████╗       ██╗     ███████╗ █████╗ ██████╗
 ██║████╗  ██║██╔════╝╚══██╔══╝██╔══██╗      ██║     ██╔════╝██╔══██╗██╔══██╗
 ██║██╔██╗ ██║███████╗   ██║   ███████║█████╗██║     █████╗  ███████║██║  ██║
 ██║██║╚██╗██║╚════██║   ██║   ██╔══██║╚════╝██║     ██╔══╝  ██╔══██║██║  ██║
 ██║██║ ╚████║███████║   ██║   ██║  ██║      ███████╗███████╗██║  ██║██████╔╝
 ╚═╝╚═╝  ╚═══╝╚══════╝   ╚═╝   ╚═╝  ╚═╝      ╚══════╝╚══════╝╚═╝  ╚═╝╚═════╝ </pre>
  <div style="display:flex; align-items:center; justify-content:space-between; margin-top: 4px;">
    <span style="color:#475569; font-size:0.78rem; letter-spacing:0.12em; font-family:'Courier New',monospace;">
      ▸ Developed by <span style="color:#38bdf8; font-weight:700;">Amir Emad</span>
      &nbsp;|&nbsp; v7.0 Stealth Edition
    </span>
    <span style="
      background: linear-gradient(90deg, #059669, #10b981);
      color: #fff;
      font-size: 0.68rem;
      font-weight: 700;
      padding: 3px 10px;
      border-radius: 20px;
      letter-spacing: 0.08em;
    ">● ONLINE</span>
  </div>
</div>
""", unsafe_allow_html=True)

# ── Stepper Bar ──
step = st.session_state.current_step

def _dot(n):
    if n < step:   return "done"
    if n == step:  return "active"
    return "waiting"

def _icon(n):
    if n < step: return "✓"
    return str(n)

st.markdown(f"""
<div class="stepper-bar">
  <div class="stepper-step">
    <div class="stepper-dot {_dot(1)}">{_icon(1)}</div>
    <div class="stepper-label {_dot(1)}">سحب<br>البيانات</div>
  </div>
  <div class="stepper-line {_dot(1)}"></div>
  <div class="stepper-step">
    <div class="stepper-dot {_dot(2)}">{_icon(2)}</div>
    <div class="stepper-label {_dot(2)}">فلترة<br>واختيار</div>
  </div>
  <div class="stepper-line {_dot(2)}"></div>
  <div class="stepper-step">
    <div class="stepper-dot {_dot(3)}">{_icon(3)}</div>
    <div class="stepper-label {_dot(3)}">تنفيذ<br>الإرسال</div>
  </div>
</div>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════
#  STEP 1 – SCRAPE
# ══════════════════════════════════════════════════════════════════

if step == 1:
    st.markdown(f"""
    <div class="step-header">
      <div class="step-badge active">🔍</div>
      <div>
        <div class="step-title">الخطوة 1: سحب بيانات التعليقات</div>
        <div class="step-sub">أدخل رابط المنشور وابدأ جلب التعليقات تلقائياً</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    post_url = st.text_input(
        "🔗 رابط المنشور أو الريل",
        placeholder="https://www.instagram.com/p/XXX  أو  https://www.instagram.com/reel/XXX",
        key="step1_url",
    )

    # عرض الروابط المحفوظة
    saved_urls = mgr.get("target_posts", [])
    if saved_urls:
        with st.expander(f"📌 روابط محفوظة ({len(saved_urls)})"):
            for i, u in enumerate(saved_urls, 1):
                c1, c2 = st.columns([6, 1])
                c1.caption(f"{i}. {u}")
                if c2.button("×", key=f"del_url_{i}"):
                    saved_urls.pop(i - 1)
                    mgr.update({"target_posts": saved_urls})
                    st.rerun()

    col_add, col_scrape = st.columns([1, 2])
    with col_add:
        if st.button("➕ إضافة الرابط", use_container_width=True):
            url = (post_url or "").strip()
            if url and ("instagram.com/p/" in url or "instagram.com/reel" in url):
                if url not in saved_urls:
                    saved_urls.append(url)
                    mgr.update({"target_posts": saved_urls})
                    st.success("✅ تمت الإضافة")
                    st.rerun()
            elif url:
                st.warning("الرابط غير صالح - يجب أن يحتوي على /p/ أو /reel/")

    with col_scrape:
        scrape_disabled = st.session_state.is_running or (not saved_urls and not post_url.strip())
        if st.button(
            "⏳ جارٍ السحب..." if st.session_state.is_running else "🔍 ابدأ سحب البيانات",
            disabled=scrape_disabled,
            type="primary",
            use_container_width=True,
            key="btn_scrape",
        ):
            u = mgr.get("username", username_input)
            p = mgr.get("password", password_input)
            if not u or not p:
                st.error("⚠️ أدخل اسم المستخدم وكلمة المرور في الشريط الجانبي أولاً")
            else:
                urls = saved_urls.copy()
                cur = (post_url or "").strip()
                if cur and cur not in urls:
                    urls.append(cur)
                if not urls:
                    st.error("أضف رابطاً واحداً على الأقل")
                else:
                    st.session_state.scraped_leads = []
                    st.session_state.scrape_done   = False
                    st.session_state.log_lines     = []
                    st.session_state.is_running    = True
                    st.session_state.stop_event    = threading.Event()
                    st.session_state.log_queue     = queue.Queue()
                    settings_dict = mgr.get_all()
                    settings_dict.update({
                        "username": u, "password": p,
                        "max_comments_scroll": int(mgr.get("max_comments_scroll", 15)),
                        "headless_mode": bool(mgr.get("headless_mode", True)),
                        "keywords": _text_to_list(kw_text) if kw_text.strip() else mgr.get("keywords", []),
                        "session_file": sdb.get_session_file(st.session_state.site_user or "default"),
                    })
                    t = threading.Thread(
                        target=_run_scrape,
                        args=(u, p, urls, settings_dict,
                              st.session_state.log_queue,
                              st.session_state.stop_event),
                        daemon=True, name="ScrapeThread",
                    )
                    st.session_state.bot_thread = t
                    t.start()
                    st.rerun()

    # Progress & Log أثناء السحب
    if st.session_state.is_running:
        st.markdown("")
        total = max(st.session_state.comments_total, 0)
        checked = max(st.session_state.comments_checked, 0)
        ratio = min(checked / total, 1.0) if total else 0
        st.progress(ratio, text=f"🔍 فحص {checked} تعليق من {total}...")
        st.markdown("")

    if st.session_state.log_lines:
        st.markdown('<p class="stitle">📋 سجل السحب</p>', unsafe_allow_html=True)
        log_html = _log_html() or '<div class="log-dim">جارٍ الانتظار...</div>'
        st.markdown(f'<div class="log-box">{log_html}</div>', unsafe_allow_html=True)

    if st.session_state.scrape_done and st.session_state.scraped_leads:
        st.success(f"✅ اكتمل السحب! تم جمع {len(st.session_state.scraped_leads)} تعليق.")
        if st.button("التالي: فلترة واختيار العملاء ➡️", type="primary", use_container_width=True):
            st.session_state.current_step = 2
            st.rerun()

    elif st.session_state.scrape_done and not st.session_state.scraped_leads:
        st.warning("لم يُعثر على تعليقات مطابقة. جرّب منشوراً آخر.")

    # لقطات التشخيص
    if st.session_state.debug_screenshots:
        with st.expander("📸 لقطات تشخيصية"):
            for s in reversed(st.session_state.debug_screenshots):
                p = Path(s)
                if p.exists(): st.image(str(p), caption=p.name, use_container_width=True)


# ══════════════════════════════════════════════════════════════════
#  STEP 2 – FILTER
# ══════════════════════════════════════════════════════════════════

elif step == 2:
    st.markdown(f"""
    <div class="step-header">
      <div class="step-badge active">✅</div>
      <div>
        <div class="step-title">الخطوة 2: فلترة واختيار العملاء</div>
        <div class="step-sub">راجع التعليقات المسحوبة واختر من تريد إرسال الرسائل إليهم</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    logged_user = (mgr.get("username", "") or "").strip().lower()
    leads_raw = st.session_state.scraped_leads

    # بناء قائمة مع استبعاد الحساب الحالي
    table = []
    for lead in leads_raw:
        uname = (lead.get("username") or "").strip()
        if uname.lower() == logged_user:
            continue
        table.append({
            "username": uname,
            "comment":  lead.get("comment_text", "")[:150],
            "_raw":     lead,
        })

    nav_col1, nav_col2 = st.columns([1, 4])
    with nav_col1:
        if st.button("⬅️ العودة للسحب", key="back_to_1"):
            st.session_state.current_step = 1
            st.rerun()

    if not table:
        st.info("لا يوجد تعليقات بعد الفلترة. العودة وتجربة منشور آخر.")
    else:
        st.markdown(f'<div class="info-box">📋 تم سحب <strong>{len(table)}</strong> تعليق (بعد استبعاد حسابك تلقائياً)</div>',
                    unsafe_allow_html=True)

        c1, c2, c3 = st.columns([1, 1, 3])
        with c1:
            if st.button("☑ تحديد الكل", key="sel_all"):
                for i in range(len(table)):
                    st.session_state[f"chk2_{i}"] = True
                st.rerun()
        with c2:
            if st.button("☐ إلغاء الكل", key="desel_all"):
                for i in range(len(table)):
                    st.session_state[f"chk2_{i}"] = False
                st.rerun()
        with c3:
            if st.button("🗑 مسح النتائج وإعادة السحب", key="clear_scrape"):
                st.session_state.scraped_leads = []
                st.session_state.scrape_done   = False
                st.session_state.current_step  = 1
                st.rerun()

        # جدول التعليقات
        selected_leads = []
        for i, row in enumerate(table):
            default = st.session_state.get(f"chk2_{i}", True)
            col_chk, col_av, col_user, col_comment = st.columns([0.3, 0.3, 1.2, 5])
            with col_chk:
                checked = st.checkbox("", value=default, key=f"chk2_{i}", label_visibility="collapsed")
            with col_av:
                initial = row["username"][0].upper() if row["username"] else "?"
                st.markdown(f'<div class="lead-avatar">{initial}</div>', unsafe_allow_html=True)
            with col_user:
                color = "#93c5fd" if checked else "#475569"
                st.markdown(f'<span style="color:{color};font-weight:700;">@{row["username"]}</span>',
                            unsafe_allow_html=True)
            with col_comment:
                st.caption(row["comment"] or "(بدون نص)")
            if checked:
                selected_leads.append(row["_raw"])

        st.markdown(f"**المحددون: {len(selected_leads)} من {len(table)}**")
        st.markdown("")

        # حفظ المحددين في الحالة
        st.session_state["_selected_for_turbo"] = selected_leads

        if st.button(
            f"Next: إعداد الإرسال ➡️ ({len(selected_leads)} عميل)",
            type="primary",
            use_container_width=True,
            disabled=len(selected_leads) == 0,
            key="btn_to_step3",
        ):
            st.session_state.current_step = 3
            st.rerun()


# ══════════════════════════════════════════════════════════════════
#  STEP 3 – EXECUTE (Turbo Mode)
# ══════════════════════════════════════════════════════════════════

elif step == 3:
    selected_leads = st.session_state.get("_selected_for_turbo", [])

    st.markdown(f"""
    <div class="step-header">
      <div class="step-badge {'active' if not st.session_state.is_running else 'done'}">⚡</div>
      <div>
        <div class="step-title">الخطوة 3: تنفيذ الإرسال الجماعي – Turbo Mode</div>
        <div class="step-sub">{len(selected_leads)} عميل محدد | تأخيرات عشوائية 15-25 ث وراحة بعد كل 10 رسائل</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Live Stats Dashboard ──
    _dm   = st.session_state.dm_count
    _skip = st.session_state.skip_count
    _tot  = len(selected_leads)
    _done = _dm + _skip
    _rate = int((_dm / _done) * 100) if _done > 0 else 0
    _elapsed_s = int(time.time() - st.session_state.bot_start_time) if st.session_state.bot_start_time else 0
    _elapsed   = f"{_elapsed_s // 60:02d}:{_elapsed_s % 60:02d}"

    st.markdown(f"""
    <div style="
      background: linear-gradient(135deg, #0d1117 0%, #111827 100%);
      border: 1px solid #1e3a5f;
      border-radius: 16px;
      padding: 20px 24px 16px;
      margin-bottom: 18px;
    ">
      <div style="color:#38bdf8; font-size:0.7rem; font-weight:700; letter-spacing:0.12em; margin-bottom:14px;">
        📊 LIVE STATS DASHBOARD
      </div>
      <div style="display:grid; grid-template-columns: repeat(4,1fr); gap:12px;">
        <div style="background:#060b14; border:1px solid #1f2d3d; border-radius:12px; padding:14px; text-align:center;">
          <div style="font-size:2rem; font-weight:900; color:#60a5fa; line-height:1;">{_tot}</div>
          <div style="font-size:0.72rem; color:#64748b; margin-top:5px;">📈 الإجمالي المستهدف</div>
        </div>
        <div style="background:#060b14; border:1px solid #1f2d3d; border-radius:12px; padding:14px; text-align:center;">
          <div style="font-size:2rem; font-weight:900; color:#34d399; line-height:1;">{_dm}</div>
          <div style="font-size:0.72rem; color:#64748b; margin-top:5px;">✅ ناجح</div>
        </div>
        <div style="background:#060b14; border:1px solid #1f2d3d; border-radius:12px; padding:14px; text-align:center;">
          <div style="font-size:2rem; font-weight:900; color:#fb923c; line-height:1;">{_skip}</div>
          <div style="font-size:0.72rem; color:#64748b; margin-top:5px;">⏭️ تخطي</div>
        </div>
        <div style="background:#060b14; border:1px solid #1f2d3d; border-radius:12px; padding:14px; text-align:center;">
          <div style="font-size:2rem; font-weight:900; color:#a78bfa; line-height:1;">{_rate}%</div>
          <div style="font-size:0.72rem; color:#64748b; margin-top:5px;">🔥 معدل النجاح</div>
        </div>
      </div>
      <div style="display:flex; justify-content:space-between; margin-top:12px; padding-top:10px; border-top:1px solid #1f2d3d;">
        <span style="color:#475569; font-size:0.74rem;">⏱ الوقت المنقضي: <span style="color:#94a3b8;">{_elapsed}</span></span>
        <span style="color:#475569; font-size:0.74rem;">متابعات: <span style="color:#94a3b8;">{st.session_state.follow_count}</span></span>
        <span style="color:#475569; font-size:0.74rem;">متبقي يومي: <span style="color:#94a3b8;">{max(int(mgr.get("max_dm_per_day", 20)) - _dm, 0)}</span></span>
      </div>
    </div>
    """, unsafe_allow_html=True)

    total_for_progress = st.session_state.execute_total or len(selected_leads)
    current_for_progress = min(st.session_state.execute_current, total_for_progress) if total_for_progress else 0
    progress_ratio = (current_for_progress / total_for_progress) if total_for_progress else 0
    rest_remaining = _rest_remaining()
    batch_sent = min(int(st.session_state.batch_sent), int(st.session_state.batch_total))
    batch_total = int(st.session_state.batch_total)

    st.markdown('<p class="stitle">📡 Live Progress Tracker</p>', unsafe_allow_html=True)
    p1, p2 = st.columns(2)
    with p1:
        st.info(f"Batch Status: تم إرسال {batch_sent} من أصل {batch_total} في المجموعة الحالية")
    with p2:
        if rest_remaining > 0:
            st.warning(f"Rest Countdown: {_format_seconds(rest_remaining)} قبل استئناف العمل")
        else:
            st.success("Rest Countdown: لا توجد راحة حالياً")

    progress_text = f"Visual Progress: {current_for_progress} / {total_for_progress} عميل"
    if st.session_state.execute_username:
        progress_text += f" | الحالي: @{st.session_state.execute_username}"
    st.progress(progress_ratio, text=progress_text)

    # ── Action Details: السطر اللحظي ──
    _cur_action = st.session_state.get("current_action", "")
    if _cur_action and st.session_state.is_running:
        st.markdown(f"""
        <div style="
          background: #0d1d30;
          border: 1px solid #1e3a5f;
          border-left: 3px solid #38bdf8;
          border-radius: 10px;
          padding: 10px 16px;
          margin: 8px 0 12px;
          font-family: 'Courier New', monospace;
          font-size: 0.85rem;
          color: #93c5fd;
          display: flex;
          align-items: center;
          gap: 10px;
        ">
          <span class="pulse" style="color:#38bdf8;">▶</span>
          <span>{_cur_action}</span>
        </div>
        """, unsafe_allow_html=True)

    # ── Checkpoint Banner ──
    _ckpt = sdb.get_checkpoint(st.session_state.site_user or "") if st.session_state.site_user else None
    if _ckpt and not st.session_state.is_running:
        _ckpt_remaining = _ckpt.get("remaining_leads", [])
        _ckpt_idx       = _ckpt.get("lead_index", 0)
        if _ckpt_remaining:
            st.markdown(f"""
            <div style="
              background: linear-gradient(90deg, #1a1a2e, #16213e);
              border: 1px solid #f59e0b;
              border-radius: 14px;
              padding: 16px 20px;
              margin-bottom: 14px;
              display: flex; align-items: center; gap: 14px;
            ">
              <div style="font-size:1.8rem;">⏸️</div>
              <div>
                <div style="color:#fbbf24; font-weight:700; font-size:0.95rem;">
                  جلسة سابقة متوقفة — تم إرسال {_ckpt_idx} عميل
                </div>
                <div style="color:#94a3b8; font-size:0.78rem; margin-top:3px;">
                  متبقي <strong style="color:#f1f5f9;">{len(_ckpt_remaining)}</strong> عميل لم يُعالَجوا بعد
                </div>
              </div>
            </div>
            """, unsafe_allow_html=True)
            _cr1, _cr2 = st.columns([2, 1])
            with _cr1:
                if st.button(
                    f"▶️ استكمال من حيث توقف ({len(_ckpt_remaining)} عميل متبقي)",
                    type="primary",
                    use_container_width=True,
                    key="btn_resume",
                ):
                    u = mgr.get("username", username_input)
                    p = mgr.get("password", password_input)
                    if not u or not p:
                        st.error("أدخل بيانات الدخول في الشريط الجانبي")
                    else:
                        st.session_state.dm_count        = 0
                        st.session_state.follow_count    = 0
                        st.session_state.lead_count      = 0
                        st.session_state.skip_count      = 0
                        st.session_state.execute_total   = len(_ckpt_remaining)
                        st.session_state.execute_current = 0
                        st.session_state.execute_username = ""
                        st.session_state.batch_sent      = 0
                        st.session_state.batch_total     = 10
                        st.session_state.rest_until      = 0.0
                        st.session_state.rest_seconds    = 0
                        st.session_state.log_lines       = []
                        st.session_state.bot_start_time  = 0.0
                        st.session_state.bot_finished    = False
                        st.session_state.current_action  = ""
                        st.session_state.is_running      = True
                        st.session_state.stop_event      = threading.Event()
                        st.session_state.log_queue       = queue.Queue()
                        _rs = mgr.get_all()
                        _rs.update({
                            "username": u, "password": p,
                            "headless_mode": bool(mgr.get("headless_mode", True)),
                            "session_file": sdb.get_session_file(st.session_state.site_user or "default"),
                            "site_username": st.session_state.site_user or "",
                        })
                        _rt = threading.Thread(
                            target=_run_turbo,
                            args=(u, p, _rs,
                                  st.session_state.log_queue,
                                  st.session_state.stop_event,
                                  _ckpt_remaining),
                            daemon=True, name="TurboResumeThread",
                        )
                        st.session_state.bot_thread = _rt
                        _rt.start()
                        st.rerun()
            with _cr2:
                if st.button("🗑️ مسح الـ Checkpoint", use_container_width=True, key="btn_clear_ckpt"):
                    sdb.clear_checkpoint(st.session_state.site_user)
                    st.rerun()

    # ── أزرار التحكم ──
    c_back, c_start, c_stop = st.columns([1, 3, 1])
    with c_back:
        if st.button("⬅️ رجوع", key="back_to_2",
                     disabled=st.session_state.is_running):
            st.session_state.current_step = 2
            st.rerun()

    with c_start:
        if st.button(
            "⏳ جارٍ الإرسال..." if st.session_state.is_running else f"⚡ بدء الإرسال الجماعي ({len(selected_leads)} عميل)",
            type="primary",
            use_container_width=True,
            disabled=st.session_state.is_running or len(selected_leads) == 0,
            key="btn_turbo",
        ):
            u = mgr.get("username", username_input)
            p = mgr.get("password", password_input)
            if not u or not p:
                st.error("أدخل بيانات الدخول في الشريط الجانبي")
            else:
                st.session_state.dm_count        = 0
                st.session_state.follow_count    = 0
                st.session_state.lead_count      = 0
                st.session_state.skip_count      = 0
                st.session_state.execute_total   = len(selected_leads)
                st.session_state.execute_current = 0
                st.session_state.execute_username = ""
                st.session_state.batch_sent      = 0
                st.session_state.batch_total     = 10
                st.session_state.rest_until      = 0.0
                st.session_state.rest_seconds    = 0
                st.session_state.log_lines       = []
                st.session_state.bot_start_time  = 0.0
                st.session_state.bot_finished    = False
                st.session_state.current_action  = ""
                st.session_state.is_running      = True
                st.session_state.stop_event     = threading.Event()
                st.session_state.log_queue      = queue.Queue()
                settings_dict = mgr.get_all()
                settings_dict.update({
                    "username": u, "password": p,
                    "max_dm_per_day": int(mgr.get("max_dm_per_day", 20)),
                    "max_follows_per_day": int(mgr.get("max_follows_per_day", 30)),
                    "delay_min_message": int(mgr.get("delay_min_message", 15)),
                    "delay_max_message": int(mgr.get("delay_max_message", 35)),
                    "headless_mode": bool(mgr.get("headless_mode", True)),
                    "message_templates": _text_to_templates(msg_text) if msg_text.strip() else mgr.get("message_templates", []),
                    "comment_reply_text": pub_text,
                    "private_auto_reply": priv_reply,
                    "private_reply_text": priv_text,
                    "public_auto_reply": pub_reply,
                    "session_file":   sdb.get_session_file(st.session_state.site_user or "default"),
                    "site_username":  st.session_state.site_user or "",
                })
                t = threading.Thread(
                    target=_run_turbo,
                    args=(u, p, settings_dict,
                          st.session_state.log_queue,
                          st.session_state.stop_event,
                          selected_leads),
                    daemon=True, name="TurboThread",
                )
                st.session_state.bot_thread = t
                t.start()
                st.rerun()

    with c_stop:
        if st.button("⛔ إيقاف", key="btn_stop3",
                     disabled=not st.session_state.is_running):
            st.session_state.stop_event.set()
            st.session_state.is_running = False
            st.rerun()

    # ── سجل Turbo النظيف ──
    st.markdown('<p class="stitle">📋 سجل الإرسال اللحظي</p>', unsafe_allow_html=True)
    log_html = _log_html() or '<div class="log-dim">في انتظار بدء الإرسال...</div>'
    st.markdown(
        f'<div class="log-box" id="turbo-log">{log_html}</div>'
        '<script>const lb=document.getElementById("turbo-log");if(lb)lb.scrollTop=lb.scrollHeight;</script>',
        unsafe_allow_html=True,
    )

    # ── Finish Summary ──
    _is_done = (
        not st.session_state.is_running
        and st.session_state.execute_total > 0
        and st.session_state.bot_start_time > 0
    )
    if _is_done:
        _f_dm    = st.session_state.dm_count
        _f_skip  = st.session_state.skip_count
        _f_tot   = st.session_state.execute_total
        _f_done  = _f_dm + _f_skip
        _f_rate  = int((_f_dm / _f_done) * 100) if _f_done > 0 else 0
        _f_elaps = int(time.time() - st.session_state.bot_start_time)
        _f_min   = _f_elaps // 60
        _f_sec   = _f_elaps % 60
        _avg     = int(_f_elaps / _f_done) if _f_done > 0 else 0
        st.markdown(f"""
        <div style="
          background: linear-gradient(135deg, #052e16 0%, #064e3b 100%);
          border: 1px solid #059669;
          border-radius: 18px;
          padding: 28px 32px;
          margin: 20px 0;
          position: relative;
          overflow: hidden;
        ">
          <div style="position:absolute;top:-20px;right:-20px;font-size:6rem;opacity:0.05;">🏆</div>
          <div style="color:#34d399; font-size:0.72rem; font-weight:700; letter-spacing:0.15em; margin-bottom:16px;">
            🏆 CAMPAIGN COMPLETE — FINAL SUMMARY
          </div>
          <div style="display:grid; grid-template-columns: repeat(3,1fr); gap:16px; margin-bottom:20px;">
            <div style="text-align:center;">
              <div style="font-size:2.4rem; font-weight:900; color:#34d399;">{_f_dm}</div>
              <div style="color:#6ee7b7; font-size:0.78rem;">✅ رسائل ناجحة</div>
            </div>
            <div style="text-align:center;">
              <div style="font-size:2.4rem; font-weight:900; color:#fb923c;">{_f_skip}</div>
              <div style="color:#fdba74; font-size:0.78rem;">⏭️ تم تخطيها</div>
            </div>
            <div style="text-align:center;">
              <div style="font-size:2.4rem; font-weight:900; color:#a78bfa;">{_f_rate}%</div>
              <div style="color:#c4b5fd; font-size:0.78rem;">🔥 معدل النجاح</div>
            </div>
          </div>
          <div style="border-top:1px solid #065f46; padding-top:14px; display:flex; justify-content:space-between; flex-wrap:wrap; gap:8px;">
            <span style="color:#6ee7b7; font-size:0.8rem;">📋 إجمالي مُعالَج: <strong style="color:#fff;">{_f_done} / {_f_tot}</strong></span>
            <span style="color:#6ee7b7; font-size:0.8rem;">⏱ الوقت الكلي: <strong style="color:#fff;">{_f_min:02d}:{_f_sec:02d}</strong></span>
            <span style="color:#6ee7b7; font-size:0.8rem;">⚡ متوسط/عميل: <strong style="color:#fff;">{_avg}ث</strong></span>
          </div>
        </div>
        """, unsafe_allow_html=True)

    # ── نتائج قاعدة البيانات ──
    if not st.session_state.is_running:
        with st.expander("📊 نتائج قاعدة البيانات"):
            leads_db = _load_leads_from_db()
            if leads_db:
                st.dataframe(leads_db, use_container_width=True, height=300)
                col_csv, col_xls = st.columns(2)
                with col_csv:
                    st.download_button("📄 CSV", _leads_to_csv(leads_db),
                                       f"leads_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                                       "text/csv", use_container_width=True)
                with col_xls:
                    st.download_button("📊 Excel", _leads_to_excel(leads_db),
                                       f"leads_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                       use_container_width=True)
            else:
                st.info("لا يوجد بيانات في قاعدة البيانات بعد.")

        # زر بدء جديد
        if st.button("🔄 بدء حملة جديدة من أول", use_container_width=True):
            st.session_state.current_step  = 1
            st.session_state.scraped_leads = []
            st.session_state.scrape_done   = False
            st.session_state.log_lines     = []
            st.session_state.dm_count      = 0
            st.session_state.follow_count  = 0
            st.session_state.lead_count    = 0
            st.session_state.execute_total = 0
            st.session_state.execute_current = 0
            st.session_state.execute_username = ""
            st.session_state.batch_sent = 0
            st.session_state.batch_total = 10
            st.session_state.rest_until = 0.0
            st.session_state.rest_seconds = 0
            st.rerun()

    # لقطات التشخيص
    if st.session_state.debug_screenshots:
        with st.expander("📸 لقطات تشخيصية"):
            for s in reversed(st.session_state.debug_screenshots):
                p = Path(s)
                if p.exists(): st.image(str(p), caption=p.name, use_container_width=True)


# ══════════════════════════════════════════════════════════════════
#  تحديث تلقائي أثناء التشغيل
# ══════════════════════════════════════════════════════════════════

if st.session_state.is_running:
    bt = st.session_state.get("bot_thread")
    if bt and not bt.is_alive():
        st.session_state.is_running = False
        _drain_queue()
    time.sleep(1.5)
    st.rerun()
