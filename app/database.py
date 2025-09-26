import sqlite3
import aiosqlite
import json
import hashlib
import secrets
from datetime import datetime, date
from typing import List, Optional, Dict, Any
from pathlib import Path

from .config import settings
from .models import ApiKeyCreate, ApiKeyResponse, ApiKeyUpdate


class DatabaseManager:
    def __init__(self, db_path: str = None):
        self.db_path = db_path or settings.database_path
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

    async def init_database(self):
        """Initialize database with all required tables"""
        async with aiosqlite.connect(self.db_path) as db:
            # API Keys table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS api_keys (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key_value TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    last_used DATETIME,
                    is_active BOOLEAN DEFAULT TRUE,
                    rate_limit_per_minute INTEGER DEFAULT 30,
                    total_requests INTEGER DEFAULT 0,
                    scopes TEXT DEFAULT 'execute,videos',
                    expires_at DATETIME,
                    webhook_url TEXT,
                    notes TEXT
                )
            """)

            # Executions table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS executions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_id TEXT UNIQUE NOT NULL,
                    api_key_id INTEGER,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    completed_at DATETIME,
                    status TEXT CHECK(status IN ('queued', 'running', 'completed', 'failed', 'timeout')),
                    script_hash TEXT,
                    script_size INTEGER,
                    execution_time REAL,
                    queue_wait_time REAL,
                    video_path TEXT,
                    video_size_mb REAL,
                    memory_peak_mb REAL,
                    cpu_time_ms REAL,
                    error_message TEXT,
                    tags TEXT,
                    priority INTEGER DEFAULT 1,
                    webhook_status TEXT,
                    FOREIGN KEY (api_key_id) REFERENCES api_keys (id)
                )
            """)

            # Daily stats table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS daily_stats (
                    date DATE PRIMARY KEY,
                    total_executions INTEGER DEFAULT 0,
                    successful_executions INTEGER DEFAULT 0,
                    failed_executions INTEGER DEFAULT 0,
                    total_execution_time REAL DEFAULT 0,
                    total_queue_time REAL DEFAULT 0,
                    unique_api_keys INTEGER DEFAULT 0,
                    videos_created INTEGER DEFAULT 0,
                    videos_deleted INTEGER DEFAULT 0
                )
            """)

            # Script templates table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS script_templates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    description TEXT,
                    script_content TEXT NOT NULL,
                    category TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    usage_count INTEGER DEFAULT 0
                )
            """)

            await db.commit()

    async def create_api_key(self, key_data: ApiKeyCreate) -> ApiKeyResponse:
        """Create a new API key"""
        key_value = f"pk_{secrets.token_urlsafe(32)}"
        scopes_str = ",".join(key_data.scopes)

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                INSERT INTO api_keys (key_value, name, rate_limit_per_minute, scopes, expires_at, webhook_url, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    key_value,
                    key_data.name,
                    key_data.rate_limit_per_minute,
                    scopes_str,
                    key_data.expires_at,
                    key_data.webhook_url,
                    key_data.notes,
                ),
            )

            key_id = cursor.lastrowid
            await db.commit()

            return await self.get_api_key_by_id(key_id)

    async def get_api_key_by_value(self, key_value: str) -> Optional[ApiKeyResponse]:
        """Get API key by its value"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM api_keys WHERE key_value = ?", (key_value,)
            )
            row = await cursor.fetchone()

            if row:
                return self._row_to_api_key(row)
            return None

    async def get_api_key_by_id(self, key_id: int) -> Optional[ApiKeyResponse]:
        """Get API key by ID"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM api_keys WHERE id = ?", (key_id,))
            row = await cursor.fetchone()

            if row:
                return self._row_to_api_key(row)
            return None

    async def list_api_keys(self) -> List[ApiKeyResponse]:
        """List all API keys"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM api_keys ORDER BY created_at DESC")
            rows = await cursor.fetchall()

            return [self._row_to_api_key(row) for row in rows]

    async def update_api_key(
        self, key_id: int, update_data: ApiKeyUpdate
    ) -> Optional[ApiKeyResponse]:
        """Update an API key"""
        update_fields = []
        update_values = []

        for field, value in update_data.dict(exclude_unset=True).items():
            if field == "scopes" and value is not None:
                update_fields.append("scopes = ?")
                update_values.append(",".join(value))
            else:
                update_fields.append(f"{field} = ?")
                update_values.append(value)

        if not update_fields:
            return await self.get_api_key_by_id(key_id)

        update_values.append(key_id)

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                f"UPDATE api_keys SET {', '.join(update_fields)} WHERE id = ?",
                update_values,
            )
            await db.commit()

            return await self.get_api_key_by_id(key_id)

    async def delete_api_key(self, key_id: int) -> bool:
        """Delete an API key"""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("DELETE FROM api_keys WHERE id = ?", (key_id,))
            await db.commit()
            return cursor.rowcount > 0

    async def update_api_key_usage(self, key_id: int):
        """Update API key last used timestamp and request count"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                UPDATE api_keys
                SET last_used = CURRENT_TIMESTAMP, total_requests = total_requests + 1
                WHERE id = ?
            """,
                (key_id,),
            )
            await db.commit()

    async def create_execution(
        self,
        request_id: str,
        api_key_id: int,
        script: str,
        priority: int = 1,
        tags: List[str] = None,
    ) -> int:
        """Create a new execution record"""
        script_hash = hashlib.sha256(script.encode()).hexdigest()
        tags_json = json.dumps(tags or [])

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                INSERT INTO executions (request_id, api_key_id, status, script_hash, script_size, tags, priority)
                VALUES (?, ?, 'queued', ?, ?, ?, ?)
            """,
                (request_id, api_key_id, script_hash, len(script), tags_json, priority),
            )

            execution_id = cursor.lastrowid
            await db.commit()
            return execution_id

    async def update_execution_status(
        self,
        request_id: str,
        status: str,
        execution_time: float = None,
        queue_wait_time: float = None,
        error_message: str = None,
        video_path: str = None,
        video_size_mb: float = None,
        memory_peak_mb: float = None,
        cpu_time_ms: int = None,
        webhook_status: str = None,
    ):
        """Update execution status and metrics"""
        update_fields = ["status = ?", "completed_at = CURRENT_TIMESTAMP"]
        update_values = [status]

        if execution_time is not None:
            update_fields.append("execution_time = ?")
            update_values.append(execution_time)

        if queue_wait_time is not None:
            update_fields.append("queue_wait_time = ?")
            update_values.append(queue_wait_time)

        if error_message is not None:
            update_fields.append("error_message = ?")
            update_values.append(error_message)

        if video_path is not None:
            update_fields.append("video_path = ?")
            update_values.append(video_path)

        if video_size_mb is not None:
            update_fields.append("video_size_mb = ?")
            update_values.append(video_size_mb)

        if memory_peak_mb is not None:
            update_fields.append("memory_peak_mb = ?")
            update_values.append(memory_peak_mb)

        if cpu_time_ms is not None:
            update_fields.append("cpu_time_ms = ?")
            update_values.append(cpu_time_ms)

        if webhook_status is not None:
            update_fields.append("webhook_status = ?")
            update_values.append(webhook_status)

        update_values.append(request_id)

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                f"UPDATE executions SET {', '.join(update_fields)} WHERE request_id = ?",
                update_values,
            )
            await db.commit()

    async def get_execution_by_request_id(
        self, request_id: str
    ) -> Optional[Dict[str, Any]]:
        """Get execution by request ID"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM executions WHERE request_id = ?", (request_id,)
            )
            row = await cursor.fetchone()

            if row:
                return dict(row)
            return None

    async def get_queue_metrics(self) -> Dict[str, Any]:
        """Get queue status metrics"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row

            # Get queue stats
            cursor = await db.execute("""
                SELECT
                    COUNT(*) as total_in_queue,
                    AVG(JULIANDAY('now') - JULIANDAY(created_at)) * 24 * 60 as avg_wait_minutes
                FROM executions
                WHERE status = 'queued'
            """)
            queue_stats = await cursor.fetchone()

            # Get active executions
            cursor = await db.execute(
                "SELECT COUNT(*) as active FROM executions WHERE status = 'running'"
            )
            active_stats = await cursor.fetchone()

            # Get queue items
            cursor = await db.execute("""
                SELECT request_id, priority, created_at, tags
                FROM executions
                WHERE status = 'queued'
                ORDER BY priority DESC, created_at ASC
                LIMIT 20
            """)
            queue_items = await cursor.fetchall()

            return {
                "total_in_queue": queue_stats["total_in_queue"],
                "active_executions": active_stats["active"],
                "average_wait_time": queue_stats["avg_wait_minutes"] or 0.0,
                "queue_items": [dict(row) for row in queue_items],
            }

    async def ensure_admin_key(self):
        """Ensure admin API key exists"""
        admin_key = await self.get_api_key_by_value(settings.admin_api_key)
        if not admin_key:
            # Create admin key manually
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    """
                    INSERT INTO api_keys (key_value, name, rate_limit_per_minute, scopes, is_active)
                    VALUES (?, 'Admin Key', 1000, 'execute,videos,admin,dashboard', TRUE)
                """,
                    (settings.admin_api_key,),
                )
                await db.commit()

    def _row_to_api_key(self, row) -> ApiKeyResponse:
        """Convert database row to ApiKeyResponse"""
        return ApiKeyResponse(
            id=row["id"],
            key_value=row["key_value"],
            name=row["name"],
            created_at=datetime.fromisoformat(row["created_at"]),
            last_used=datetime.fromisoformat(row["last_used"])
            if row["last_used"]
            else None,
            is_active=bool(row["is_active"]),
            rate_limit_per_minute=row["rate_limit_per_minute"],
            total_requests=row["total_requests"],
            scopes=row["scopes"].split(",") if row["scopes"] else [],
            expires_at=datetime.fromisoformat(row["expires_at"])
            if row["expires_at"]
            else None,
            webhook_url=row["webhook_url"],
            notes=row["notes"],
        )


# Global database instance
db = DatabaseManager()


async def init_database():
    """Initialize database tables"""
    await db.init_database()


async def ensure_admin_key():
    """Ensure admin API key exists"""
    await db.ensure_admin_key()
