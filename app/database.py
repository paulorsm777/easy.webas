import sqlite3
import aiosqlite
import hashlib
import secrets
import json
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from app.config import settings
from app.models import ApiKeyCreate, ApiKeyResponse, ApiKeyUpdate, ExecutionStatus
import structlog

logger = structlog.get_logger()


async def init_database():
    """Initialize database with all required tables"""
    async with aiosqlite.connect(settings.DATABASE_PATH) as db:
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

        # Rate limiting table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS rate_limits (
                key_id TEXT PRIMARY KEY,
                requests INTEGER DEFAULT 0,
                window_start DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await db.commit()

        # Insert default script templates
        await insert_default_templates(db)

        logger.info("Database initialized successfully")


async def insert_default_templates(db: aiosqlite.Connection):
    """Insert default script templates"""
    templates = [
        {
            "name": "google_search",
            "description": "Busca no Google e retorna resultados",
            "category": "web_scraping",
            "script_content": """
async def main():
    await page.goto('https://google.com')
    await page.fill('input[name="q"]', 'playwright automation')
    await page.press('input[name="q"]', 'Enter')
    await page.wait_for_selector('.g')
    results = await page.query_selector_all('.g h3')
    return [await r.inner_text() for r in results[:5]]
"""
        },
        {
            "name": "form_filling",
            "description": "Preenche formulário e submete",
            "category": "automation",
            "script_content": """
async def main():
    await page.goto('https://httpbin.org/forms/post')
    await page.fill('input[name="custname"]', 'Test User')
    await page.fill('input[name="custtel"]', '123456789')
    await page.fill('input[name="custemail"]', 'test@example.com')
    await page.click('input[type="submit"]')
    await page.wait_for_load_state('networkidle')
    return await page.text_content('body')
"""
        },
        {
            "name": "screenshot_capture",
            "description": "Navega e captura informações da página",
            "category": "testing",
            "script_content": """
async def main():
    await page.goto('https://example.com')
    title = await page.title()
    content = await page.text_content('body')
    return {
        'title': title,
        'content_length': len(content),
        'url': page.url,
        'viewport': await page.viewport_size()
    }
"""
        }
    ]

    for template in templates:
        await db.execute("""
            INSERT OR IGNORE INTO script_templates (name, description, category, script_content)
            VALUES (?, ?, ?, ?)
        """, (template["name"], template["description"], template["category"], template["script_content"]))


def generate_api_key() -> str:
    """Generate a secure API key"""
    return f"pk_{''.join(secrets.choice('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789') for _ in range(48))}"


async def create_api_key(key_data: ApiKeyCreate) -> ApiKeyResponse:
    """Create a new API key"""
    async with aiosqlite.connect(settings.DATABASE_PATH) as db:
        key_value = generate_api_key()
        scopes_str = ",".join(key_data.scopes)

        cursor = await db.execute("""
            INSERT INTO api_keys (key_value, name, rate_limit_per_minute, scopes, expires_at, webhook_url, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            key_value, key_data.name, key_data.rate_limit_per_minute,
            scopes_str, key_data.expires_at, key_data.webhook_url, key_data.notes
        ))

        key_id = cursor.lastrowid
        await db.commit()

        # Fetch the created key
        async with db.execute("SELECT * FROM api_keys WHERE id = ?", (key_id,)) as cursor:
            row = await cursor.fetchone()

        return _row_to_api_key_response(row)


async def get_api_key_by_value(key_value: str) -> Optional[ApiKeyResponse]:
    """Get API key by its value"""
    async with aiosqlite.connect(settings.DATABASE_PATH) as db:
        async with db.execute("SELECT * FROM api_keys WHERE key_value = ?", (key_value,)) as cursor:
            row = await cursor.fetchone()

        if row:
            return _row_to_api_key_response(row)
        return None


async def get_api_key_by_id(key_id: int) -> Optional[ApiKeyResponse]:
    """Get API key by its ID"""
    async with aiosqlite.connect(settings.DATABASE_PATH) as db:
        async with db.execute("SELECT * FROM api_keys WHERE id = ?", (key_id,)) as cursor:
            row = await cursor.fetchone()

        if row:
            return _row_to_api_key_response(row)
        return None


async def list_api_keys() -> List[ApiKeyResponse]:
    """List all API keys"""
    async with aiosqlite.connect(settings.DATABASE_PATH) as db:
        async with db.execute("SELECT * FROM api_keys ORDER BY created_at DESC") as cursor:
            rows = await cursor.fetchall()

        return [_row_to_api_key_response(row) for row in rows]


async def update_api_key(key_id: int, update_data: ApiKeyUpdate) -> Optional[ApiKeyResponse]:
    """Update an API key"""
    async with aiosqlite.connect(settings.DATABASE_PATH) as db:
        # Build update query dynamically
        update_fields = []
        values = []

        if update_data.name is not None:
            update_fields.append("name = ?")
            values.append(update_data.name)

        if update_data.is_active is not None:
            update_fields.append("is_active = ?")
            values.append(update_data.is_active)

        if update_data.rate_limit_per_minute is not None:
            update_fields.append("rate_limit_per_minute = ?")
            values.append(update_data.rate_limit_per_minute)

        if update_data.scopes is not None:
            update_fields.append("scopes = ?")
            values.append(",".join(update_data.scopes))

        if update_data.expires_at is not None:
            update_fields.append("expires_at = ?")
            values.append(update_data.expires_at)

        if update_data.webhook_url is not None:
            update_fields.append("webhook_url = ?")
            values.append(update_data.webhook_url)

        if update_data.notes is not None:
            update_fields.append("notes = ?")
            values.append(update_data.notes)

        if not update_fields:
            return await get_api_key_by_id(key_id)

        values.append(key_id)
        query = f"UPDATE api_keys SET {', '.join(update_fields)} WHERE id = ?"

        await db.execute(query, values)
        await db.commit()

        return await get_api_key_by_id(key_id)


async def delete_api_key(key_id: int) -> bool:
    """Delete an API key"""
    async with aiosqlite.connect(settings.DATABASE_PATH) as db:
        cursor = await db.execute("DELETE FROM api_keys WHERE id = ?", (key_id,))
        await db.commit()
        return cursor.rowcount > 0


async def update_api_key_usage(key_value: str):
    """Update API key last used timestamp and request count"""
    async with aiosqlite.connect(settings.DATABASE_PATH) as db:
        await db.execute("""
            UPDATE api_keys
            SET last_used = CURRENT_TIMESTAMP, total_requests = total_requests + 1
            WHERE key_value = ?
        """, (key_value,))
        await db.commit()


async def record_execution(request_id: str, api_key_id: int, script_hash: str,
                          script_size: int, priority: int, tags: List[str]):
    """Record a new execution"""
    async with aiosqlite.connect(settings.DATABASE_PATH) as db:
        await db.execute("""
            INSERT INTO executions (request_id, api_key_id, status, script_hash, script_size, priority, tags)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (request_id, api_key_id, ExecutionStatus.QUEUED, script_hash, script_size, priority, json.dumps(tags)))
        await db.commit()


async def update_execution_status(request_id: str, status: ExecutionStatus,
                                error_message: Optional[str] = None,
                                execution_time: Optional[float] = None,
                                queue_wait_time: Optional[float] = None,
                                video_path: Optional[str] = None,
                                video_size_mb: Optional[float] = None,
                                memory_peak_mb: Optional[float] = None,
                                cpu_time_ms: Optional[int] = None):
    """Update execution status and metrics"""
    async with aiosqlite.connect(settings.DATABASE_PATH) as db:
        update_fields = ["status = ?"]
        values = [status]

        if status in [ExecutionStatus.COMPLETED, ExecutionStatus.FAILED, ExecutionStatus.TIMEOUT]:
            update_fields.append("completed_at = CURRENT_TIMESTAMP")

        if error_message:
            update_fields.append("error_message = ?")
            values.append(error_message)

        if execution_time is not None:
            update_fields.append("execution_time = ?")
            values.append(execution_time)

        if queue_wait_time is not None:
            update_fields.append("queue_wait_time = ?")
            values.append(queue_wait_time)

        if video_path:
            update_fields.append("video_path = ?")
            values.append(video_path)

        if video_size_mb is not None:
            update_fields.append("video_size_mb = ?")
            values.append(video_size_mb)

        if memory_peak_mb is not None:
            update_fields.append("memory_peak_mb = ?")
            values.append(memory_peak_mb)

        if cpu_time_ms is not None:
            update_fields.append("cpu_time_ms = ?")
            values.append(cpu_time_ms)

        values.append(request_id)
        query = f"UPDATE executions SET {', '.join(update_fields)} WHERE request_id = ?"

        await db.execute(query, values)
        await db.commit()


async def get_execution_analytics(api_key_id: Optional[int] = None) -> Dict[str, Any]:
    """Get execution analytics"""
    async with aiosqlite.connect(settings.DATABASE_PATH) as db:
        base_query = """
            SELECT
                COUNT(*) as total_executions,
                SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as successful_executions,
                SUM(CASE WHEN status IN ('failed', 'timeout') THEN 1 ELSE 0 END) as failed_executions,
                AVG(execution_time) as avg_execution_time,
                SUM(video_size_mb) as total_video_size_mb
            FROM executions
        """

        if api_key_id:
            base_query += " WHERE api_key_id = ?"
            values = (api_key_id,)
        else:
            values = ()

        async with db.execute(base_query, values) as cursor:
            row = await cursor.fetchone()

        return {
            "total_executions": row[0] or 0,
            "successful_executions": row[1] or 0,
            "failed_executions": row[2] or 0,
            "avg_execution_time": row[3] or 0.0,
            "total_video_size_mb": row[4] or 0.0
        }


async def ensure_admin_key():
    """Ensure admin API key exists"""
    admin_key = await get_api_key_by_value(settings.ADMIN_API_KEY)
    if not admin_key:
        async with aiosqlite.connect(settings.DATABASE_PATH) as db:
            await db.execute("""
                INSERT INTO api_keys (key_value, name, scopes, rate_limit_per_minute)
                VALUES (?, ?, ?, ?)
            """, (settings.ADMIN_API_KEY, "Admin Key", "admin,execute,videos,dashboard", 1000))
            await db.commit()
            logger.info("Admin API key created")


def _row_to_api_key_response(row) -> ApiKeyResponse:
    """Convert database row to ApiKeyResponse"""
    scopes = row[8].split(",") if row[8] else []
    return ApiKeyResponse(
        id=row[0],
        key_value=row[1],
        name=row[2],
        created_at=datetime.fromisoformat(row[3]),
        last_used=datetime.fromisoformat(row[4]) if row[4] else None,
        is_active=bool(row[5]),
        rate_limit_per_minute=row[6],
        total_requests=row[7],
        scopes=scopes,
        expires_at=datetime.fromisoformat(row[9]) if row[9] else None,
        webhook_url=row[10],
        notes=row[11]
    )