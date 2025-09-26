import asyncio
import time
import psutil
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, Any

from .config import settings
from .models import HealthResponse, ServiceStatus, SystemMetrics, BrowserPoolStatus
from .logger import Logger

logger = Logger("health")


class HealthChecker:
    def __init__(self):
        self.startup_time = time.time()
        self._last_check = {}
        self._check_cache_ttl = 30  # Cache health checks for 30 seconds

    async def get_health_status(self, force_check: bool = False) -> HealthResponse:
        """Get comprehensive health status"""
        now = time.time()

        # Use cached result if recent and not forced
        if not force_check and "full_health" in self._last_check:
            last_check_time = self._last_check["full_health"]["time"]
            if now - last_check_time < self._check_cache_ttl:
                return self._last_check["full_health"]["result"]

        logger.info("health_check_starting", force_check=force_check)

        # Check individual services
        services = await self._check_services()
        metrics = await self._get_system_metrics()
        browser_pool = await self._check_browser_pool()

        # Determine overall status
        overall_status = self._determine_overall_status(services, metrics, browser_pool)

        health_response = HealthResponse(
            status=overall_status,
            timestamp=datetime.now(),
            services=services,
            metrics=metrics,
            browser_pool=browser_pool,
        )

        # Cache result
        self._last_check["full_health"] = {"time": now, "result": health_response}

        logger.info(
            "health_check_completed",
            status=overall_status,
            services_healthy=all(
                [
                    services.database,
                    services.browser_pool,
                    services.queue,
                    services.disk_space,
                ]
            ),
        )

        return health_response

    async def _check_services(self) -> ServiceStatus:
        """Check status of core services"""
        database_ok = await self._check_database()
        browser_pool_ok = await self._check_browser_pool_service()
        queue_ok = await self._check_queue_service()
        disk_space_ok = await self._check_disk_space()

        return ServiceStatus(
            database=database_ok,
            browser_pool=browser_pool_ok,
            queue=queue_ok,
            disk_space=disk_space_ok,
        )

    async def _check_database(self) -> bool:
        """Check database connectivity"""
        try:
            from .database import db

            async with db.get_connection() as conn:
                cursor = await conn.execute("SELECT 1")
                await cursor.fetchone()

            return True
        except Exception as e:
            logger.error("database_health_check_failed", error=str(e))
            return False

    async def _check_browser_pool_service(self) -> bool:
        """Check browser pool health"""
        try:
            from .executor import executor

            # Check if browser pool is initialized
            if not executor.browser_pool.playwright:
                return False

            # Check if we have available browsers
            available = executor.browser_pool.available_browsers.qsize()
            total = len(executor.browser_pool.browsers)

            return total > 0 and available >= 0
        except Exception as e:
            logger.error("browser_pool_health_check_failed", error=str(e))
            return False

    async def _check_queue_service(self) -> bool:
        """Check queue service health"""
        try:
            from .executor import executor

            # Queue should be accessible
            queue_size = len(executor.queue)
            active_executions = len(executor.active_executions)

            # Check for queue overflow
            if queue_size >= settings.max_queue_size:
                logger.warning(
                    "queue_health_degraded", reason="queue_full", size=queue_size
                )
                return False

            # Check for too many active executions
            if active_executions >= settings.max_concurrent_executions:
                logger.warning(
                    "queue_health_degraded",
                    reason="max_concurrent",
                    active=active_executions,
                )
                return False

            return True
        except Exception as e:
            logger.error("queue_health_check_failed", error=str(e))
            return False

    async def _check_disk_space(self) -> bool:
        """Check available disk space"""
        try:
            # Check main data directory
            data_dir = Path("data")
            if data_dir.exists():
                usage = shutil.disk_usage(data_dir)
                free_gb = usage.free / (1024**3)

                # Require at least 1GB free space
                if free_gb < 1.0:
                    logger.warning("disk_space_low", free_gb=free_gb)
                    return False

            return True
        except Exception as e:
            logger.error("disk_space_check_failed", error=str(e))
            return False

    async def _get_system_metrics(self) -> SystemMetrics:
        """Get system performance metrics"""
        try:
            from .executor import executor
            from .video_service import video_manager
            from .database import db

            # Get process info
            process = psutil.Process()
            memory_mb = process.memory_info().rss / 1024 / 1024
            cpu_percent = process.cpu_percent()

            # Get queue metrics
            queue_size = len(executor.queue)
            active_executions = len(executor.active_executions)

            # Get API key count
            async with db.get_connection() as conn:
                cursor = await conn.execute(
                    "SELECT COUNT(*) as count FROM api_keys WHERE is_active = 1"
                )
                api_keys_count = (await cursor.fetchone())["count"]

            # Get video storage info
            storage_stats = await video_manager.get_storage_stats()

            # Calculate uptime
            uptime_seconds = int(time.time() - self.startup_time)

            # Get disk usage
            data_dir = Path("data")
            disk_usage_gb = 0
            if data_dir.exists():
                usage = shutil.disk_usage(data_dir)
                disk_usage_gb = (usage.used) / (1024**3)

            return SystemMetrics(
                active_executions=active_executions,
                queue_size=queue_size,
                total_api_keys=api_keys_count,
                videos_stored=storage_stats["total_files"],
                disk_usage_gb=round(disk_usage_gb, 2),
                memory_usage_mb=round(memory_mb, 2),
                cpu_usage_percent=round(cpu_percent, 1),
                uptime_seconds=uptime_seconds,
            )

        except Exception as e:
            logger.error("system_metrics_failed", error=str(e))
            # Return safe defaults
            return SystemMetrics(
                active_executions=0,
                queue_size=0,
                total_api_keys=0,
                videos_stored=0,
                disk_usage_gb=0,
                memory_usage_mb=0,
                cpu_usage_percent=0,
                uptime_seconds=0,
            )

    async def _check_browser_pool(self) -> BrowserPoolStatus:
        """Get browser pool status"""
        try:
            from .executor import executor

            total_browsers = len(executor.browser_pool.browsers)
            available_browsers = executor.browser_pool.available_browsers.qsize()

            # Estimate warm browsers (browsers that have been used recently)
            warm_browsers = min(total_browsers, available_browsers + 2)

            return BrowserPoolStatus(
                total_browsers=total_browsers,
                available_browsers=available_browsers,
                warm_browsers=warm_browsers,
            )
        except Exception as e:
            logger.error("browser_pool_status_failed", error=str(e))
            return BrowserPoolStatus(
                total_browsers=0, available_browsers=0, warm_browsers=0
            )

    def _determine_overall_status(
        self,
        services: ServiceStatus,
        metrics: SystemMetrics,
        browser_pool: BrowserPoolStatus,
    ) -> str:
        """Determine overall system health status"""

        # Critical service failures
        if not services.database:
            return "unhealthy"

        # Check for degraded conditions
        degraded_conditions = []

        if not services.browser_pool or browser_pool.available_browsers == 0:
            degraded_conditions.append("browser_pool")

        if not services.queue or metrics.queue_size > settings.max_queue_size * 0.8:
            degraded_conditions.append("queue_congestion")

        if not services.disk_space:
            degraded_conditions.append("disk_space")

        if metrics.memory_usage_mb > 1500:  # 1.5GB
            degraded_conditions.append("high_memory")

        if metrics.cpu_usage_percent > 80:
            degraded_conditions.append("high_cpu")

        if degraded_conditions:
            logger.warning("system_health_degraded", conditions=degraded_conditions)
            return "degraded"

        return "healthy"

    async def get_quick_status(self) -> Dict[str, Any]:
        """Get quick health status without full checks"""
        try:
            from .executor import executor

            return {
                "status": "healthy",
                "timestamp": datetime.now().isoformat(),
                "uptime_seconds": int(time.time() - self.startup_time),
                "queue_size": len(executor.queue),
                "active_executions": len(executor.active_executions),
                "available_browsers": executor.browser_pool.available_browsers.qsize(),
            }
        except Exception as e:
            logger.error("quick_status_failed", error=str(e))
            return {
                "status": "unhealthy",
                "timestamp": datetime.now().isoformat(),
                "error": str(e),
            }

    async def run_diagnostic(self) -> Dict[str, Any]:
        """Run comprehensive diagnostic checks"""
        logger.info("diagnostic_starting")

        diagnostic_results = {"timestamp": datetime.now().isoformat(), "checks": {}}

        # Database diagnostics
        try:
            from .database import db

            async with db.get_connection() as conn:
                # Check tables exist
                cursor = await conn.execute("""
                    SELECT name FROM sqlite_master WHERE type='table'
                """)
                tables = [row["name"] for row in await cursor.fetchall()]

                # Check recent activity
                cursor = await conn.execute("""
                    SELECT COUNT(*) as count FROM executions
                    WHERE created_at > datetime('now', '-1 hour')
                """)
                recent_executions = (await cursor.fetchone())["count"]

                diagnostic_results["checks"]["database"] = {
                    "status": "healthy",
                    "tables_found": len(tables),
                    "tables": tables,
                    "recent_executions": recent_executions,
                }
        except Exception as e:
            diagnostic_results["checks"]["database"] = {
                "status": "failed",
                "error": str(e),
            }

        # Browser pool diagnostics
        try:
            from .executor import executor

            total_browsers = len(executor.browser_pool.browsers)
            available = executor.browser_pool.available_browsers.qsize()

            # Test browser creation
            test_browser = None
            try:
                test_browser = await executor.browser_pool.get_browser()
                context = await test_browser.new_context()
                page = await context.new_page()
                await page.goto("about:blank")
                await context.close()
                browser_test_passed = True
            except Exception as e:
                browser_test_passed = False
                browser_test_error = str(e)
            finally:
                if test_browser:
                    await executor.browser_pool.return_browser(test_browser)

            diagnostic_results["checks"]["browser_pool"] = {
                "status": "healthy" if browser_test_passed else "failed",
                "total_browsers": total_browsers,
                "available_browsers": available,
                "test_passed": browser_test_passed,
                "test_error": browser_test_error if not browser_test_passed else None,
            }

        except Exception as e:
            diagnostic_results["checks"]["browser_pool"] = {
                "status": "failed",
                "error": str(e),
            }

        # System resources
        try:
            process = psutil.Process()
            memory_info = process.memory_info()

            diagnostic_results["checks"]["system"] = {
                "status": "healthy",
                "memory_rss_mb": round(memory_info.rss / 1024 / 1024, 2),
                "memory_vms_mb": round(memory_info.vms / 1024 / 1024, 2),
                "cpu_percent": process.cpu_percent(),
                "num_threads": process.num_threads(),
                "open_files": len(process.open_files()),
                "connections": len(process.connections()),
            }
        except Exception as e:
            diagnostic_results["checks"]["system"] = {
                "status": "failed",
                "error": str(e),
            }

        logger.info(
            "diagnostic_completed",
            checks_count=len(diagnostic_results["checks"]),
            failed_checks=[
                k
                for k, v in diagnostic_results["checks"].items()
                if v["status"] == "failed"
            ],
        )

        return diagnostic_results


# Global health checker
health_checker = HealthChecker()
