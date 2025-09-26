import asyncio
import psutil
import os
from datetime import datetime
from typing import Dict, Any
import structlog

from app.config import settings
from app.models import HealthStatus, HealthResponse, HealthServices, HealthMetrics, BrowserPoolStatus
from app.database import get_api_key_by_value
from app.video_service import video_service

logger = structlog.get_logger()

class HealthChecker:
    """Comprehensive health checking system"""

    def __init__(self):
        self.startup_time = datetime.now()

    async def check_database(self) -> bool:
        """Check database connectivity"""
        try:
            # Try to fetch admin key as a simple database test
            admin_key = await get_api_key_by_value(settings.ADMIN_API_KEY)
            return admin_key is not None
        except Exception as e:
            logger.error("Database health check failed", error=str(e))
            return False

    async def check_browser_pool(self) -> bool:
        """Check browser pool health"""
        try:
            from app.executor import executor
            health = await executor.browser_pool.health_check()
            return health["healthy_browsers"] > 0
        except Exception as e:
            logger.error("Browser pool health check failed", error=str(e))
            return False

    async def check_queue(self) -> bool:
        """Check execution queue health"""
        try:
            from app.executor import executor
            queue_status = await executor.get_queue_status()
            # Queue is healthy if it's not completely full
            return queue_status["total_queued"] < settings.MAX_QUEUE_SIZE
        except Exception as e:
            logger.error("Queue health check failed", error=str(e))
            return False

    async def check_disk_space(self) -> bool:
        """Check available disk space"""
        try:
            # Check disk space for data directory
            statvfs = os.statvfs('./data')
            free_bytes = statvfs.f_frsize * statvfs.f_bavail
            free_gb = free_bytes / (1024 ** 3)

            # Consider healthy if more than 1GB free
            return free_gb > 1.0
        except Exception as e:
            logger.error("Disk space health check failed", error=str(e))
            return False

    async def get_system_metrics(self) -> HealthMetrics:
        """Get system metrics"""
        try:
            from app.executor import executor

            # Queue metrics
            queue_status = await executor.get_queue_status()
            active_executions = queue_status["total_running"]
            queue_size = queue_status["total_queued"]

            # Video storage metrics
            video_stats = await video_service.get_storage_stats()

            # System metrics
            memory = psutil.virtual_memory()
            cpu_percent = psutil.cpu_percent(interval=1)

            # Disk usage for data directory
            disk_usage = psutil.disk_usage('./data')
            disk_usage_gb = (disk_usage.total - disk_usage.free) / (1024 ** 3)

            # Uptime
            uptime_seconds = (datetime.now() - self.startup_time).total_seconds()

            # API keys count (simplified)
            try:
                from app.database import list_api_keys
                api_keys = await list_api_keys()
                total_api_keys = len(api_keys)
            except:
                total_api_keys = 0

            return HealthMetrics(
                active_executions=active_executions,
                queue_size=queue_size,
                total_api_keys=total_api_keys,
                videos_stored=video_stats["total_files"],
                disk_usage_gb=round(disk_usage_gb, 2),
                memory_usage_mb=round(memory.used / (1024 ** 2), 0),
                cpu_usage_percent=round(cpu_percent, 1),
                uptime_seconds=int(uptime_seconds)
            )

        except Exception as e:
            logger.error("Failed to get system metrics", error=str(e))
            # Return default metrics on error
            return HealthMetrics(
                active_executions=0,
                queue_size=0,
                total_api_keys=0,
                videos_stored=0,
                disk_usage_gb=0.0,
                memory_usage_mb=0,
                cpu_usage_percent=0.0,
                uptime_seconds=0
            )

    async def get_browser_pool_status(self) -> BrowserPoolStatus:
        """Get browser pool status"""
        try:
            from app.executor import executor
            health = await executor.browser_pool.health_check()

            return BrowserPoolStatus(
                total_browsers=health["total_browsers"],
                available_browsers=health["available_browsers"],
                warm_browsers=health.get("healthy_browsers", 0)
            )

        except Exception as e:
            logger.error("Failed to get browser pool status", error=str(e))
            return BrowserPoolStatus(
                total_browsers=0,
                available_browsers=0,
                warm_browsers=0
            )

    async def perform_health_check(self) -> HealthResponse:
        """Perform comprehensive health check"""
        # Check all services
        database_healthy = await self.check_database()
        browser_pool_healthy = await self.check_browser_pool()
        queue_healthy = await self.check_queue()
        disk_space_healthy = await self.check_disk_space()

        services = HealthServices(
            database=database_healthy,
            browser_pool=browser_pool_healthy,
            queue=queue_healthy,
            disk_space=disk_space_healthy
        )

        # Determine overall status
        all_healthy = all([
            database_healthy,
            browser_pool_healthy,
            queue_healthy,
            disk_space_healthy
        ])

        if all_healthy:
            status = HealthStatus.HEALTHY
        elif database_healthy and browser_pool_healthy:
            # Core services are up, but some issues
            status = HealthStatus.DEGRADED
        else:
            status = HealthStatus.UNHEALTHY

        # Get metrics
        metrics = await self.get_system_metrics()
        browser_pool = await self.get_browser_pool_status()

        return HealthResponse(
            status=status,
            timestamp=datetime.now(),
            services=services,
            metrics=metrics,
            browser_pool=browser_pool
        )

    async def check_resource_limits(self) -> Dict[str, Any]:
        """Check if system is approaching resource limits"""
        warnings = []

        try:
            # Memory check
            memory = psutil.virtual_memory()
            memory_percent = memory.percent
            if memory_percent > 90:
                warnings.append({
                    "type": "memory",
                    "message": f"High memory usage: {memory_percent:.1f}%",
                    "current": memory_percent,
                    "threshold": 90
                })

            # CPU check
            cpu_percent = psutil.cpu_percent(interval=1)
            if cpu_percent > 80:
                warnings.append({
                    "type": "cpu",
                    "message": f"High CPU usage: {cpu_percent:.1f}%",
                    "current": cpu_percent,
                    "threshold": 80
                })

            # Disk check
            disk_usage = psutil.disk_usage('./data')
            disk_percent = (disk_usage.used / disk_usage.total) * 100
            if disk_percent > 85:
                warnings.append({
                    "type": "disk",
                    "message": f"High disk usage: {disk_percent:.1f}%",
                    "current": disk_percent,
                    "threshold": 85
                })

            # Queue check
            from app.executor import executor
            queue_status = await executor.get_queue_status()
            queue_percent = (queue_status["total_queued"] / settings.MAX_QUEUE_SIZE) * 100
            if queue_percent > 80:
                warnings.append({
                    "type": "queue",
                    "message": f"Queue nearly full: {queue_percent:.1f}%",
                    "current": queue_percent,
                    "threshold": 80
                })

            # Browser pool check
            browser_health = await executor.browser_pool.health_check()
            available_percent = (browser_health["available_browsers"] / browser_health["total_browsers"]) * 100
            if available_percent < 20:
                warnings.append({
                    "type": "browser_pool",
                    "message": f"Low browser availability: {available_percent:.1f}%",
                    "current": available_percent,
                    "threshold": 20
                })

        except Exception as e:
            logger.error("Failed to check resource limits", error=str(e))
            warnings.append({
                "type": "system",
                "message": f"Health check error: {str(e)}",
                "current": 0,
                "threshold": 0
            })

        return {
            "warnings": warnings,
            "warning_count": len(warnings),
            "status": "critical" if len(warnings) > 3 else "warning" if warnings else "ok"
        }

    async def get_detailed_status(self) -> Dict[str, Any]:
        """Get detailed system status for dashboard"""
        health = await self.perform_health_check()
        resource_warnings = await self.check_resource_limits()

        # Get additional stats
        video_stats = await video_service.get_storage_stats()

        try:
            from app.executor import executor
            queue_status = await executor.get_queue_status()
        except:
            queue_status = {"total_queued": 0, "total_running": 0, "queue_items": []}

        return {
            "health": health.dict(),
            "resource_warnings": resource_warnings,
            "video_storage": video_stats,
            "queue_details": queue_status,
            "last_check": datetime.now().isoformat()
        }


# Global health checker instance
health_checker = HealthChecker()