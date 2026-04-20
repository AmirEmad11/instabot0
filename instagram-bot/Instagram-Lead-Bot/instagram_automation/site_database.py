"""
قاعدة بيانات مستخدمي البوابة (SaaS Portal)
- تشفير آمن PBKDF2-HMAC-SHA256 (310,000 iteration)
- إدارة كاملة للمستخدمين والاشتراكات
- مسار جلسات إنستجرام منفصل لكل مستخدم
"""

import hashlib
import secrets
import sqlite3
from datetime import date, datetime
from pathlib import Path

_BASE_DIR   = Path(__file__).parent
DB_FILE     = _BASE_DIR / "site_users.db"
SESSIONS_DIR = _BASE_DIR / "sessions"
SESSIONS_DIR.mkdir(exist_ok=True)


# ══════════════════════════════════════════════════════════════════
#  تهيئة قاعدة البيانات
# ══════════════════════════════════════════════════════════════════

def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_FILE), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS site_users (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                username         TEXT    UNIQUE NOT NULL,
                password_hash    TEXT    NOT NULL,
                salt             TEXT    NOT NULL,
                email            TEXT    DEFAULT '',
                plan             TEXT    DEFAULT 'trial',
                subscription_end DATE,
                created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_login       TIMESTAMP,
                is_active        INTEGER DEFAULT 1,
                is_admin         INTEGER DEFAULT 0
            )
        """)
        conn.commit()
        # أضف العمود للجداول القديمة إن لم يكن موجوداً
        try:
            conn.execute("ALTER TABLE site_users ADD COLUMN is_admin INTEGER DEFAULT 0")
            conn.commit()
        except Exception:
            pass

    if not get_user("admin"):
        add_user(
            username="admin",
            password="admin1234",
            email="admin@insta-lead.com",
            plan="unlimited",
        )
    # تأكد أن admin دائماً is_admin=1
    with _get_conn() as conn:
        conn.execute("UPDATE site_users SET is_admin=1 WHERE username='admin'")
        conn.commit()


# ══════════════════════════════════════════════════════════════════
#  تشفير كلمات المرور
# ══════════════════════════════════════════════════════════════════

def _hash_password(password: str, salt: str = None) -> tuple[str, str]:
    if salt is None:
        salt = secrets.token_hex(32)
    key = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        310_000,
    )
    return key.hex(), salt


# ══════════════════════════════════════════════════════════════════
#  العمليات الأساسية
# ══════════════════════════════════════════════════════════════════

def add_user(
    username: str,
    password: str,
    email: str = "",
    plan: str = "trial",
    subscription_end: str = None,
    is_active: int = 1,
) -> bool:
    username = username.strip().lower()
    try:
        pwd_hash, salt = _hash_password(password)
        with _get_conn() as conn:
            conn.execute(
                """INSERT INTO site_users
                   (username, password_hash, salt, email, plan, subscription_end, is_active)
                   VALUES (?,?,?,?,?,?,?)""",
                (username, pwd_hash, salt, email, plan, subscription_end, int(is_active)),
            )
            conn.commit()
        (SESSIONS_DIR / username).mkdir(parents=True, exist_ok=True)
        return True
    except sqlite3.IntegrityError:
        return False


def verify_password(username: str, password: str) -> dict | None:
    user = get_user(username)
    if not user or not user.get("is_active"):
        return None
    key, _ = _hash_password(password, user["salt"])
    if secrets.compare_digest(key, user["password_hash"]):
        with _get_conn() as conn:
            conn.execute(
                "UPDATE site_users SET last_login=? WHERE username=?",
                (datetime.now().isoformat(), username.strip().lower()),
            )
            conn.commit()
        (SESSIONS_DIR / username.strip().lower()).mkdir(parents=True, exist_ok=True)
        return dict(user)
    return None


def get_user(username: str) -> dict | None:
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM site_users WHERE username=?",
            (username.strip().lower(),),
        ).fetchone()
        return dict(row) if row else None


def update_subscription(username: str, plan: str, subscription_end: str):
    with _get_conn() as conn:
        conn.execute(
            "UPDATE site_users SET plan=?, subscription_end=? WHERE username=?",
            (plan, subscription_end, username.strip().lower()),
        )
        conn.commit()


def update_password(username: str, new_password: str) -> bool:
    user = get_user(username)
    if not user:
        return False
    pwd_hash, salt = _hash_password(new_password)
    with _get_conn() as conn:
        conn.execute(
            "UPDATE site_users SET password_hash=?, salt=? WHERE username=?",
            (pwd_hash, salt, username.strip().lower()),
        )
        conn.commit()
    return True


def set_active(username: str, active: bool):
    with _get_conn() as conn:
        conn.execute(
            "UPDATE site_users SET is_active=? WHERE username=?",
            (int(active), username.strip().lower()),
        )
        conn.commit()


def set_admin(username: str, admin: bool):
    with _get_conn() as conn:
        conn.execute(
            "UPDATE site_users SET is_admin=? WHERE username=?",
            (int(admin), username.strip().lower()),
        )
        conn.commit()


def is_admin_user(username: str) -> bool:
    user = get_user(username)
    if not user:
        return False
    return bool(user.get("is_admin", 0))


def get_instagram_credentials(username: str) -> dict:
    """يقرأ يوزر وباسورد الإنستجرام من ملف إعدادات المستخدم"""
    import json
    settings_path = Path(get_settings_file(username))
    if settings_path.exists():
        try:
            data = json.loads(settings_path.read_text(encoding="utf-8"))
            return {
                "ig_username": data.get("username", ""),
                "ig_password": data.get("password", ""),
            }
        except Exception:
            pass
    return {"ig_username": "", "ig_password": ""}


def list_users() -> list[dict]:
    with _get_conn() as conn:
        rows = conn.execute(
            """SELECT id, username, email, plan, subscription_end,
                      created_at, last_login, is_active, is_admin
               FROM site_users ORDER BY created_at DESC"""
        ).fetchall()
        return [dict(r) for r in rows]


def is_subscription_active(username: str) -> bool:
    user = get_user(username)
    if not user or not user.get("is_active"):
        return False
    if user["plan"] == "unlimited":
        return True
    # تنظيف قيمة تاريخ الانتهاء
    sub_end = user.get("subscription_end") or ""
    if isinstance(sub_end, str):
        sub_end = sub_end.strip()
    # لو مفيش تاريخ انتهاء → الحساب نشط بغض النظر عن الخطة
    if not sub_end:
        return True
    # لو في تاريخ انتهاء → تحقق منه
    try:
        end = date.fromisoformat(str(sub_end))
        return date.today() <= end
    except Exception:
        # لو التاريخ مش صالح → اعتبر الحساب نشط (أمان)
        return True


# ══════════════════════════════════════════════════════════════════
#  Checkpoint – حفظ واستئناف تقدم Turbo Mode
# ══════════════════════════════════════════════════════════════════

def save_checkpoint(username: str, lead_index: int, remaining_leads: list):
    """يحفظ نقطة استكمال بعد كل عميل يُعالَج"""
    import json
    path = SESSIONS_DIR / username.strip().lower() / "checkpoint.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"lead_index": lead_index, "remaining_leads": remaining_leads},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def get_checkpoint(username: str) -> dict | None:
    """يرجع الـ checkpoint المحفوظ أو None"""
    import json
    path = SESSIONS_DIR / username.strip().lower() / "checkpoint.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return None


def clear_checkpoint(username: str):
    """يحذف الـ checkpoint بعد اكتمال التنفيذ أو الإلغاء"""
    path = SESSIONS_DIR / username.strip().lower() / "checkpoint.json"
    if path.exists():
        path.unlink(missing_ok=True)


def get_session_file(username: str) -> str:
    path = SESSIONS_DIR / username.strip().lower() / "session_state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


def get_settings_file(username: str) -> str:
    path = SESSIONS_DIR / username.strip().lower() / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


init_db()
