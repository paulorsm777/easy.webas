import asyncio
import schedule
import time
from datetime import datetime, timedelta
from typing import Dict, Any
import structlog

from app.config import settings
from app.video_service import video_service
from app.logger import system_logger

logger = structlog.get_logger()


class CleanupService:
    """Background service for cleaning up old data"""

    def __init__(self):
        self.running = False
        self.cleanup_task = None

    async def start(self):
        """Start the cleanup service"""
        if self.running:
            return

        self.running = True

        # Schedule cleanup tasks
        schedule.every().day.at(f"{settings.VIDEO_CLEANUP_HOUR:02d}:00").do(
            self._schedule_video_cleanup
        )

        # Schedule hourly maintenance
        schedule.every().hour.do(self._schedule_maintenance)

        # Start background task
        self.cleanup_task = asyncio.create_task(self._cleanup_worker())

        system_logger.log_startup("cleanup_service")
        logger.info("Cleanup service started",
                   video_cleanup_hour=settings.VIDEO_CLEANUP_HOUR,
                   video_retention_days=settings.VIDEO_RETENTION_DAYS)

    async def stop(self):
        """Stop the cleanup service"""
        self.running = False

        if self.cleanup_task:
            self.cleanup_task.cancel()
            try:
                await self.cleanup_task
            except asyncio.CancelledError:
                pass

        system_logger.log_shutdown("cleanup_service")
        logger.info("Cleanup service stopped")

    def _schedule_video_cleanup(self):
        """Schedule video cleanup (called by schedule)"""
        asyncio.create_task(self.cleanup_old_videos())

    def _schedule_maintenance(self):
        """Schedule general maintenance (called by schedule)"""
        asyncio.create_task(self.perform_maintenance())

    async def _cleanup_worker(self):
        """Background worker that runs scheduled tasks"""
        logger.info("Cleanup worker started")

        while self.running:
            try:
                # Run pending scheduled tasks
                schedule.run_pending()

                # Sleep for 1 minute
                await asyncio.sleep(60)

            except Exception as e:
                logger.error("Cleanup worker error", error=str(e))
                await asyncio.sleep(60)

        logger.info("Cleanup worker stopped")

    async def cleanup_old_videos(self) -> Dict[str, Any]:
        """Clean up old video files"""
        try:
            logger.info("Starting video cleanup",
                       retention_days=settings.VIDEO_RETENTION_DAYS)

            result = await video_service.cleanup_old_videos(settings.VIDEO_RETENTION_DAYS)

            system_logger.log_cleanup(
                cleaned_items=result["deleted_count"],
                cleaned_size_mb=result["deleted_size_mb"]
            )

            logger.info("Video cleanup completed", **result)
            return result

        except Exception as e:
            logger.error("Video cleanup failed", error=str(e))
            return {
                "deleted_count": 0,
                "deleted_size_mb": 0.0,
                "retention_days": settings.VIDEO_RETENTION_DAYS,
                "error": str(e)
            }

    async def cleanup_old_executions(self, retention_days: int = 30) -> Dict[str, Any]:
        """Clean up old execution records from database"""
        try:
            import aiosqlite
            from app.config import settings

            cutoff_date = datetime.now() - timedelta(days=retention_days)

            async with aiosqlite.connect(settings.DATABASE_PATH) as db:
                # Count executions to be deleted
                async with db.execute("""
                    SELECT COUNT(*) FROM executions
                    WHERE created_at < ?
                """, (cutoff_date,)) as cursor:
                    count_result = await cursor.fetchone()
                    count_to_delete = count_result[0] if count_result else 0

                # Delete old executions
                await db.execute("""
                    DELETE FROM executions
                    WHERE created_at < ?
                """, (cutoff_date,))

                await db.commit()

            logger.info("Execution cleanup completed",
                       deleted_count=count_to_delete,
                       retention_days=retention_days)

            return {
                "deleted_count": count_to_delete,
                "retention_days": retention_days,
                "cutoff_date": cutoff_date.isoformat()
            }

        except Exception as e:
            logger.error("Execution cleanup failed", error=str(e))
            return {
                "deleted_count": 0,
                "retention_days": retention_days,
                "error": str(e)
            }

    async def cleanup_rate_limit_data(self) -> Dict[str, Any]:
        """Clean up old rate limiting data"""
        try:
            import aiosqlite
            from app.config import settings

            # Clean up rate limit entries older than 24 hours
            cutoff_time = datetime.now() - timedelta(hours=24)

            async with aiosqlite.connect(settings.DATABASE_PATH) as db:
                # Count entries to be deleted
                async with db.execute("""
                    SELECT COUNT(*) FROM rate_limits
                    WHERE window_start < ?
                """, (cutoff_time,)) as cursor:
                    count_result = await cursor.fetchone()
                    count_to_delete = count_result[0] if count_result else 0

                # Delete old rate limit data
                await db.execute("""
                    DELETE FROM rate_limits
                    WHERE window_start < ?
                """, (cutoff_time,))

                await db.commit()

            logger.info("Rate limit cleanup completed",
                       deleted_count=count_to_delete)

            return {
                "deleted_count": count_to_delete,
                "cutoff_time": cutoff_time.isoformat()
            }

        except Exception as e:
            logger.error("Rate limit cleanup failed", error=str(e))
            return {
                "deleted_count": 0,
                "error": str(e)
            }

    async def update_daily_stats(self) -> Dict[str, Any]:
        """Update daily statistics"""
        try:
            import aiosqlite
            from app.config import settings

            yesterday = (datetime.now() - timedelta(days=1)).date()

            async with aiosqlite.connect(settings.DATABASE_PATH) as db:
                # Get execution stats for yesterday
                async with db.execute("""
                    SELECT
                        COUNT(*) as total_executions,
                        SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as successful_executions,
                        SUM(CASE WHEN status IN ('failed', 'timeout') THEN 1 ELSE 0 END) as failed_executions,
                        SUM(execution_time) as total_execution_time,
                        SUM(queue_wait_time) as total_queue_time,
                        COUNT(DISTINCT api_key_id) as unique_api_keys
                    FROM executions
                    WHERE DATE(created_at) = ?
                """, (yesterday,)) as cursor:
                    stats = await cursor.fetchone()

                if stats and stats[0] > 0:
                    # Insert or update daily stats
                    await db.execute("""
                        INSERT OR REPLACE INTO daily_stats
                        (date, total_executions, successful_executions, failed_executions,
                         total_execution_time, total_queue_time, unique_api_keys)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (yesterday, stats[0], stats[1], stats[2], stats[3], stats[4], stats[5]))

                    await db.commit()

                    logger.info("Daily stats updated",
                               date=yesterday.isoformat(),
                               total_executions=stats[0])

                    return {
                        "date": yesterday.isoformat(),
                        "total_executions": stats[0],
                        "successful_executions": stats[1],
                        "failed_executions": stats[2]
                    }

            return {"message": "No executions to aggregate"}

        except Exception as e:
            logger.error("Daily stats update failed", error=str(e))
            return {"error": str(e)}

    async def vacuum_database(self) -> Dict[str, Any]:
        """Vacuum database to reclaim space"""
        try:
            import aiosqlite
            from app.config import settings

            async with aiosqlite.connect(settings.DATABASE_PATH) as db:
                await db.execute("VACUUM")

            logger.info("Database vacuum completed")
            return {"message": "Database vacuum completed"}

        except Exception as e:
            logger.error("Database vacuum failed", error=str(e))
            return {"error": str(e)}

    async def perform_maintenance(self) -> Dict[str, Any]:
        """Perform general maintenance tasks"""
        try:
            logger.info("Starting maintenance tasks")

            maintenance_results = {}

            # Clean up rate limit data
            rate_limit_result = await self.cleanup_rate_limit_data()
            maintenance_results["rate_limit_cleanup"] = rate_limit_result

            # Update daily stats
            stats_result = await self.update_daily_stats()
            maintenance_results["daily_stats"] = stats_result

            # Vacuum database (once per day)
            current_hour = datetime.now().hour
            if current_hour == settings.VIDEO_CLEANUP_HOUR:
                vacuum_result = await self.vacuum_database()
                maintenance_results["database_vacuum"] = vacuum_result

            logger.info("Maintenance tasks completed", results=maintenance_results)
            return maintenance_results

        except Exception as e:
            logger.error("Maintenance tasks failed", error=str(e))
            return {"error": str(e)}

    async def get_cleanup_status(self) -> Dict[str, Any]:
        """Get status of cleanup service"""
        return {
            "running": self.running,
            "video_retention_days": settings.VIDEO_RETENTION_DAYS,
            "cleanup_hour": settings.VIDEO_CLEANUP_HOUR,
            "next_video_cleanup": self._get_next_cleanup_time(),
            "pending_tasks": len(schedule.jobs)
        }

    def _get_next_cleanup_time(self) -> str:
        """Get next scheduled cleanup time"""
        try:
            next_run = schedule.next_run()
            if next_run:
                return next_run.isoformat()
            return "Not scheduled"
        except:
            return "Unknown"

    async def force_full_cleanup(self) -> Dict[str, Any]:
        """Force a complete cleanup (admin function)"""
        try:
            logger.info("Starting forced full cleanup")

            results = {}

            # Video cleanup
            video_result = await self.cleanup_old_videos()
            results["video_cleanup"] = video_result

            # Execution cleanup (keep last 30 days)
            execution_result = await self.cleanup_old_executions(30)
            results["execution_cleanup"] = execution_result

            # Rate limit cleanup
            rate_limit_result = await self.cleanup_rate_limit_data()
            results["rate_limit_cleanup"] = rate_limit_result

            # Database vacuum
            vacuum_result = await self.vacuum_database()
            results["database_vacuum"] = vacuum_result

            logger.info("Forced full cleanup completed", results=results)
            return results

        except Exception as e:
            logger.error("Forced cleanup failed", error=str(e))
            return {"error": str(e)}


# Global cleanup service instance
cleanup_service = CleanupService()


# Convenience functions for startup
async def start_cleanup_scheduler():
    """Start the cleanup scheduler"""
    await cleanup_service.start()


async def stop_cleanup_scheduler():
    """Stop the cleanup scheduler"""
    await cleanup_service.stop()