import json
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from fastapi import Request, HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.responses import JSONResponse

from .config import settings
from .models import ApiKeyResponse
from .logger import dashboard_logger


class DashboardManager:
    def __init__(self):
        self.templates = Jinja2Templates(directory="templates")

    async def render_dashboard(
        self, request: Request, api_key: ApiKeyResponse
    ) -> HTMLResponse:
        """Render main dashboard page"""
        dashboard_logger.info("dashboard_accessed", api_key_id=api_key.id)

        # Get dashboard data
        dashboard_data = await self._get_dashboard_data(api_key)

        return self.templates.TemplateResponse(
            "dashboard.html",
            {
                "request": request,
                "api_key": api_key,
                "data": dashboard_data,
                "refresh_interval": settings.dashboard_refresh_interval,
            },
        )

    async def get_dashboard_data(self, api_key: ApiKeyResponse) -> Dict[str, Any]:
        """Get dashboard data as JSON"""
        return await self._get_dashboard_data(api_key)

    async def _get_dashboard_data(self, api_key: ApiKeyResponse) -> Dict[str, Any]:
        """Get comprehensive dashboard data"""
        from .executor import executor
        from .health import health_checker
        from .metrics import metrics_collector
        from .video_service import video_manager
        from .database import db

        # Get current system status
        health_status = await health_checker.get_health_status()

        # Get queue status
        queue_status = await executor.get_queue_status()

        # Get analytics data
        analytics_data = metrics_collector.get_analytics_data()

        # Get recent executions for this API key
        recent_executions = await self._get_recent_executions(api_key.id)

        # Get video storage info
        storage_stats = await video_manager.get_storage_stats()

        # Get API key usage stats
        api_key_stats = await self._get_api_key_stats(api_key.id)

        return {
            "timestamp": datetime.now().isoformat(),
            "system": {
                "status": health_status.status,
                "uptime_seconds": health_status.metrics.uptime_seconds,
                "memory_usage_mb": health_status.metrics.memory_usage_mb,
                "cpu_usage_percent": health_status.metrics.cpu_usage_percent,
                "disk_usage_gb": health_status.metrics.disk_usage_gb,
            },
            "queue": {
                "size": queue_status["total_in_queue"],
                "active_executions": queue_status["active_executions"],
                "average_wait_time": queue_status["average_wait_time"],
                "recent_items": queue_status["queue_items"][:5],  # Show top 5
            },
            "browser_pool": {
                "total": health_status.browser_pool.total_browsers,
                "available": health_status.browser_pool.available_browsers,
                "warm": health_status.browser_pool.warm_browsers,
            },
            "analytics": analytics_data,
            "executions": {
                "recent": recent_executions,
                "total_today": api_key_stats["today_count"],
                "success_rate": api_key_stats["success_rate"],
            },
            "storage": {
                "total_videos": storage_stats["total_files"],
                "total_size_mb": storage_stats["total_size_mb"],
                "total_size_gb": storage_stats["total_size_gb"],
            },
            "api_key": {
                "name": api_key.name,
                "requests_today": api_key_stats["today_count"],
                "rate_limit": api_key.rate_limit_per_minute,
                "last_used": api_key.last_used.isoformat()
                if api_key.last_used
                else None,
            },
        }

    async def _get_recent_executions(
        self, api_key_id: int, limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Get recent executions for an API key"""
        from .database import db

        async with db.get_connection() as conn:
            cursor = await conn.execute(
                """
                SELECT request_id, created_at, completed_at, status, execution_time,
                       error_message, video_path, tags, priority
                FROM executions
                WHERE api_key_id = ?
                ORDER BY created_at DESC
                LIMIT ?
            """,
                (api_key_id, limit),
            )

            rows = await cursor.fetchall()
            executions = []

            for row in rows:
                execution = {
                    "request_id": row["request_id"],
                    "created_at": row["created_at"],
                    "completed_at": row["completed_at"],
                    "status": row["status"],
                    "execution_time": row["execution_time"],
                    "error_message": row["error_message"],
                    "has_video": bool(row["video_path"]),
                    "tags": json.loads(row["tags"]) if row["tags"] else [],
                    "priority": row["priority"],
                }

                # Add video URL if available
                if row["video_path"]:
                    execution["video_url"] = f"/video/{row['request_id']}"

                executions.append(execution)

            return executions

    async def _get_api_key_stats(self, api_key_id: int) -> Dict[str, Any]:
        """Get statistics for an API key"""
        from .database import db

        async with db.get_connection() as conn:
            # Today's stats
            cursor = await conn.execute(
                """
                SELECT
                    COUNT(*) as total_today,
                    SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as successful_today
                FROM executions
                WHERE api_key_id = ?
                AND DATE(created_at) = DATE('now')
            """,
                (api_key_id,),
            )

            today_stats = await cursor.fetchone()

            # Last 7 days stats
            cursor = await conn.execute(
                """
                SELECT
                    DATE(created_at) as date,
                    COUNT(*) as total,
                    SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as successful,
                    AVG(execution_time) as avg_execution_time
                FROM executions
                WHERE api_key_id = ?
                AND created_at >= DATE('now', '-7 days')
                GROUP BY DATE(created_at)
                ORDER BY date
            """,
                (api_key_id,),
            )

            weekly_stats = await cursor.fetchall()

            today_count = today_stats["total_today"] or 0
            today_successful = today_stats["successful_today"] or 0
            success_rate = (
                (today_successful / today_count * 100) if today_count > 0 else 0
            )

            return {
                "today_count": today_count,
                "today_successful": today_successful,
                "success_rate": round(success_rate, 1),
                "weekly_stats": [dict(row) for row in weekly_stats],
            }

    async def render_queue_status(
        self, request: Request, api_key: ApiKeyResponse
    ) -> HTMLResponse:
        """Render queue status page"""
        from .executor import executor

        queue_data = await executor.get_queue_status()

        return self.templates.TemplateResponse(
            "queue_status.html",
            {"request": request, "api_key": api_key, "queue_data": queue_data},
        )

    async def render_api_keys_page(
        self, request: Request, admin_key: ApiKeyResponse
    ) -> HTMLResponse:
        """Render API keys management page (admin only)"""
        from .database import db

        # Get all API keys
        api_keys = await db.list_api_keys()

        # Get usage stats for each key
        keys_with_stats = []
        for key in api_keys:
            stats = await self._get_api_key_stats(key.id)
            keys_with_stats.append({"key": key, "stats": stats})

        return self.templates.TemplateResponse(
            "api_keys.html",
            {"request": request, "admin_key": admin_key, "api_keys": keys_with_stats},
        )

    async def get_system_metrics(self) -> Dict[str, Any]:
        """Get system metrics for API"""
        from .health import health_checker
        from .metrics import metrics_collector

        health_status = await health_checker.get_health_status()
        analytics_data = metrics_collector.get_analytics_data()

        return {
            "system_health": {
                "status": health_status.status,
                "services": {
                    "database": health_status.services.database,
                    "browser_pool": health_status.services.browser_pool,
                    "queue": health_status.services.queue,
                    "disk_space": health_status.services.disk_space,
                },
                "metrics": {
                    "uptime_seconds": health_status.metrics.uptime_seconds,
                    "memory_usage_mb": health_status.metrics.memory_usage_mb,
                    "cpu_usage_percent": health_status.metrics.cpu_usage_percent,
                    "active_executions": health_status.metrics.active_executions,
                    "queue_size": health_status.metrics.queue_size,
                },
            },
            "analytics": analytics_data,
        }

    async def get_execution_logs(
        self, api_key_id: int, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Get execution logs for an API key"""
        return await self._get_recent_executions(api_key_id, limit)

    async def get_video_list(
        self, api_key_id: int, limit: int = 20
    ) -> List[Dict[str, Any]]:
        """Get video list for an API key"""
        from .video_service import video_manager

        videos = await video_manager.list_videos_by_api_key(api_key_id, limit)
        return videos

    async def search_executions(
        self, api_key_id: int, filters: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Search executions with filters"""
        from .database import db

        # Build query with filters
        where_conditions = ["api_key_id = ?"]
        params = [api_key_id]

        if filters.get("status"):
            where_conditions.append("status = ?")
            params.append(filters["status"])

        if filters.get("start_date"):
            where_conditions.append("created_at >= ?")
            params.append(filters["start_date"])

        if filters.get("end_date"):
            where_conditions.append("created_at <= ?")
            params.append(filters["end_date"])

        if filters.get("has_video"):
            if filters["has_video"]:
                where_conditions.append("video_path IS NOT NULL")
            else:
                where_conditions.append("video_path IS NULL")

        if filters.get("tags"):
            # Search in tags JSON
            where_conditions.append("tags LIKE ?")
            params.append(f"%{filters['tags']}%")

        where_clause = " AND ".join(where_conditions)
        limit = min(filters.get("limit", 50), 100)  # Cap at 100

        async with db.get_connection() as conn:
            cursor = await conn.execute(
                f"""
                SELECT request_id, created_at, completed_at, status, execution_time,
                       error_message, video_path, tags, priority
                FROM executions
                WHERE {where_clause}
                ORDER BY created_at DESC
                LIMIT ?
            """,
                params + [limit],
            )

            rows = await cursor.fetchall()

            return [
                {
                    "request_id": row["request_id"],
                    "created_at": row["created_at"],
                    "completed_at": row["completed_at"],
                    "status": row["status"],
                    "execution_time": row["execution_time"],
                    "error_message": row["error_message"],
                    "has_video": bool(row["video_path"]),
                    "tags": json.loads(row["tags"]) if row["tags"] else [],
                    "priority": row["priority"],
                    "video_url": f"/video/{row['request_id']}"
                    if row["video_path"]
                    else None,
                }
                for row in rows
            ]

    async def get_webhook_stats(self) -> Dict[str, Any]:
        """Get webhook statistics"""
        from .webhooks import webhook_manager

        return await webhook_manager.get_webhook_stats()


# Global dashboard manager
dashboard_manager = DashboardManager()
