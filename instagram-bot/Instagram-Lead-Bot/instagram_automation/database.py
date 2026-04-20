"""
وحدة إدارة قاعدة البيانات SQLite
تُعالج تسجيل العملاء المحتملين وحالاتهم
"""

import aiosqlite
import sqlite3
import logging
from datetime import datetime
from config import DATABASE_FILE

logger = logging.getLogger(__name__)


class DatabaseManager:

    def __init__(self, db_path: str = DATABASE_FILE):
        self.db_path = db_path

    async def initialize(self):
        """إنشاء جدول العملاء المحتملين وترقية الأعمدة إذا لزم"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS leads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    post_url TEXT,
                    comment_text TEXT,
                    dm_sent INTEGER DEFAULT 0,
                    followed INTEGER DEFAULT 0,
                    comment_replied INTEGER DEFAULT 0,
                    account_type TEXT DEFAULT 'unknown',
                    status TEXT DEFAULT 'pending',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            # ترقية الجداول القديمة بإضافة العمود الجديد إذا لم يكن موجوداً
            try:
                await db.execute("ALTER TABLE leads ADD COLUMN account_type TEXT DEFAULT 'unknown'")
            except Exception:
                pass  # العمود موجود مسبقاً
            await db.commit()
        logger.info("تم تهيئة قاعدة البيانات بنجاح")

    async def lead_exists(self, username: str) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT id FROM leads WHERE username = ?", (username,)
            )
            row = await cursor.fetchone()
            return row is not None

    async def dm_already_sent(self, username: str) -> bool:
        """التحقق من إرسال DM مسبقاً لهذا المستخدم - يمنع التكرار"""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT id FROM leads WHERE username = ? AND dm_sent = 1",
                (username,),
            )
            row = await cursor.fetchone()
            return row is not None

    async def add_lead(self, username: str, post_url: str, comment_text: str) -> bool:
        now = datetime.now().isoformat()
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    """
                    INSERT INTO leads (username, post_url, comment_text, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (username, post_url, comment_text, now, now),
                )
                await db.commit()
            logger.info(f"تمت إضافة العميل الجديد: @{username}")
            return True
        except aiosqlite.IntegrityError:
            return False

    async def update_lead_status(
        self,
        username: str,
        dm_sent: bool = None,
        followed: bool = None,
        comment_replied: bool = None,
        account_type: str = None,
        status: str = None,
    ):
        now = datetime.now().isoformat()
        updates = []
        values = []

        if dm_sent is not None:
            updates.append("dm_sent = ?")
            values.append(int(dm_sent))
        if followed is not None:
            updates.append("followed = ?")
            values.append(int(followed))
        if comment_replied is not None:
            updates.append("comment_replied = ?")
            values.append(int(comment_replied))
        if account_type is not None:
            updates.append("account_type = ?")
            values.append(account_type)
        if status is not None:
            updates.append("status = ?")
            values.append(status)

        if not updates:
            return

        updates.append("updated_at = ?")
        values.append(now)
        values.append(username)

        query = f"UPDATE leads SET {', '.join(updates)} WHERE username = ?"

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(query, values)
            await db.commit()

    async def get_daily_dm_count(self) -> int:
        today = datetime.now().date().isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT COUNT(*) FROM leads WHERE dm_sent = 1 AND date(updated_at) = ?",
                (today,),
            )
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def get_private_pending_leads(self) -> list:
        """جلب الحسابات الخاصة التي أُرسل لها طلب متابعة ولم يُرسل لها DM بعد"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """SELECT * FROM leads
                   WHERE status = 'private_pending'
                   AND dm_sent = 0
                   AND followed = 1
                   ORDER BY updated_at ASC"""
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_all_leads(self) -> list:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM leads ORDER BY created_at DESC")
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    @staticmethod
    def get_all_leads_sync(db_path: str = DATABASE_FILE) -> list:
        """قراءة متزامنة لاستخدامها من واجهة Streamlit"""
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT * FROM leads ORDER BY created_at DESC")
            rows = [dict(row) for row in cursor.fetchall()]
            conn.close()
            return rows
        except Exception as e:
            logger.error(f"خطأ في قراءة قاعدة البيانات: {e}")
            return []
