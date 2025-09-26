import asyncio
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, List
import shutil

from .config import settings
from .database import db
from .logger import cleanup_logger


class SystemCleaner:
    def __init__(self):
        self.running = False
        self._cleanup_task = None

    async def start_cleanup_scheduler(self):
        """Start the background cleanup scheduler"""
        if self.running:
            cleanup_logger.warning("cleanup_scheduler_already_running")
            return

        self.running = True
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        cleanup_logger.info("cleanup_scheduler_started")

    async def stop_cleanup_scheduler(self):
        """Stop the background cleanup scheduler"""
        if not self.running:
            return

        self.running = False
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        cleanup_logger.info("cleanup_scheduler_stopped")

    async def _cleanup_loop(self):
        """Main cleanup loop that runs periodically"""
        while self.running:
            try:
                # Calculate next cleanup time (daily at configured hour)
                now = datetime.now()
                next_cleanup = now.replace(
                    hour=settings.video_cleanup_hour, minute=0, second=0, microsecond=0
                )

                # If we've passed today's cleanup time, schedule for tomorrow
                if now >= next_cleanup:
                    next_cleanup += timedelta(days=1)

                # Wait until cleanup time
                wait_seconds = (next_cleanup - now).total_seconds()
                cleanup_logger.info(
                    "cleanup_scheduled",
                    next_cleanup=next_cleanup.isoformat(),
                    wait_hours=round(wait_seconds / 3600, 2),
                )

                # Sleep with periodic checks to allow cancellation
                while wait_seconds > 0 and self.running:
                    sleep_time = min(3600, wait_seconds)  # Check every hour max
                    await asyncio.sleep(sleep_time)
                    wait_seconds -= sleep_time

                if not self.running:
                    break

                # Perform comprehensive cleanup
                cleanup_result = await self.perform_full_cleanup()
                cleanup_logger.info("scheduled_cleanup_completed", **cleanup_result)

            except asyncio.CancelledError:
                break
            except Exception as e:
                cleanup_logger.error("cleanup_loop_error", error=str(e))
                # Wait 1 hour before retrying on error
                if self.running:
                    await asyncio.sleep(3600)

    async def perform_full_cleanup(self, force: bool = False) -> Dict[str, Any]:
        """Perform comprehensive system cleanup"""
        cleanup_logger.info("cleanup_started", force=force)
        start_time = time.time()

        results = {
            "start_time": datetime.now().isoformat(),
            "force": force,
            "total_freed_mb": 0,
            "components": {},
        }

        try:
            # 1. Clean old videos
            video_result = await self._cleanup_old_videos()
            results["components"]["videos"] = video_result
            results["total_freed_mb"] += video_result.get("freed_mb", 0)

            # 2. Clean old execution records
            db_result = await self._cleanup_old_executions()
            results["components"]["database"] = db_result

            # 3. Clean temporary files
            temp_result = await self._cleanup_temp_files()
            results["components"]["temp_files"] = temp_result
            results["total_freed_mb"] += temp_result.get("freed_mb", 0)

            # 4. Optimize database
            optimize_result = await self._optimize_database()
            results["components"]["database_optimize"] = optimize_result

            # 5. System resource check
            resource_result = await self._check_system_resources()
            results["components"]["resources"] = resource_result

            results["success"] = True
            results["execution_time"] = time.time() - start_time

            cleanup_logger.info(
                "cleanup_completed",
                total_freed_mb=results["total_freed_mb"],
                execution_time=results["execution_time"],
            )

        except Exception as e:
            results["success"] = False
            results["error"] = str(e)
            results["execution_time"] = time.time() - start_time
            cleanup_logger.error("cleanup_failed", error=str(e))

        return results

    async def _cleanup_old_videos(self) -> Dict[str, Any]:
        """Clean up videos older than retention period"""
        cutoff_date = datetime.now() - timedelta(days=settings.video_retention_days)

        deleted_files = 0
        freed_bytes = 0
        errors = []

        video_base_dir = Path("data/videos")
        if not video_base_dir.exists():
            return {
                "deleted_files": 0,
                "freed_mb": 0,
                "errors": [],
                "message": "Video directory does not exist",
            }

        try:
            # Find and delete old video files
            for video_file in video_base_dir.rglob("*.webm"):
                try:
                    file_stat = video_file.stat()
                    file_date = datetime.fromtimestamp(file_stat.st_mtime)

                    if file_date < cutoff_date:
                        file_size = file_stat.st_size
                        video_file.unlink()

                        deleted_files += 1
                        freed_bytes += file_size

                        # Update database to mark video as deleted
                        request_id = video_file.stem
                        await self._mark_video_deleted(request_id)

                        cleanup_logger.info(
                            "video_file_deleted",
                            file_path=str(video_file),
                            file_age_days=(datetime.now() - file_date).days,
                            file_size_mb=round(file_size / 1024 / 1024, 2),
                        )

                except Exception as e:
                    error_msg = f"Failed to delete {video_file}: {str(e)}"
                    errors.append(error_msg)
                    cleanup_logger.error("video_deletion_failed", error=error_msg)

            # Clean up empty directories
            await self._cleanup_empty_directories(video_base_dir)

        except Exception as e:
            error_msg = f"Video cleanup failed: {str(e)}"
            errors.append(error_msg)
            cleanup_logger.error("video_cleanup_error", error=error_msg)

        return {
            "deleted_files": deleted_files,
            "freed_mb": round(freed_bytes / 1024 / 1024, 2),
            "errors": errors,
            "cutoff_date": cutoff_date.isoformat(),
        }

    async def _cleanup_old_executions(self) -> Dict[str, Any]:
        """Clean up old execution records from database"""
        # Keep execution records for longer than videos (30 days default)
        retention_days = max(30, settings.video_retention_days * 2)
        cutoff_date = datetime.now() - timedelta(days=retention_days)

        try:
            async with db.get_connection() as conn:
                # Count records to be deleted
                cursor = await conn.execute(
                    "SELECT COUNT(*) FROM executions WHERE created_at < ?",
                    (cutoff_date.isoformat(),),
                )
                count_result = await cursor.fetchone()
                records_to_delete = count_result[0] if count_result else 0

                # Delete old execution records
                await conn.execute(
                    "DELETE FROM executions WHERE created_at < ?",
                    (cutoff_date.isoformat(),),
                )
                await conn.commit()

                cleanup_logger.info(
                    "execution_records_cleaned",
                    deleted_records=records_to_delete,
                    cutoff_date=cutoff_date.isoformat(),
                )

                return {
                    "deleted_records": records_to_delete,
                    "cutoff_date": cutoff_date.isoformat(),
                    "success": True,
                }

        except Exception as e:
            error_msg = f"Database cleanup failed: {str(e)}"
            cleanup_logger.error("database_cleanup_error", error=error_msg)
            return {"success": False, "error": error_msg}

    async def _cleanup_temp_files(self) -> Dict[str, Any]:
        """Clean up temporary files and directories"""
        deleted_files = 0
        freed_bytes = 0
        errors = []

        temp_directories = [
            "/tmp",
            "/var/tmp",
            "data/temp",
            "data/logs",
        ]

        for temp_dir in temp_directories:
            temp_path = Path(temp_dir)
            if not temp_path.exists():
                continue

            try:
                # Clean files older than 24 hours
                cutoff_time = time.time() - (24 * 60 * 60)

                for item in temp_path.iterdir():
                    try:
                        if item.is_file() and item.stat().st_mtime < cutoff_time:
                            # Only delete files that look like temp files
                            if any(
                                pattern in item.name.lower()
                                for pattern in [
                                    "tmp",
                                    "temp",
                                    "cache",
                                    ".log",
                                    "playwright-",
                                ]
                            ):
                                file_size = item.stat().st_size
                                item.unlink()
                                deleted_files += 1
                                freed_bytes += file_size

                    except Exception as e:
                        error_msg = f"Failed to delete temp file {item}: {str(e)}"
                        errors.append(error_msg)

            except Exception as e:
                error_msg = f"Failed to clean temp directory {temp_dir}: {str(e)}"
                errors.append(error_msg)

        return {
            "deleted_files": deleted_files,
            "freed_mb": round(freed_bytes / 1024 / 1024, 2),
            "errors": errors,
        }

    async def _optimize_database(self) -> Dict[str, Any]:
        """Optimize database performance"""
        try:
            async with db.get_connection() as conn:
                # Run VACUUM to optimize database
                await conn.execute("VACUUM")

                # Update statistics
                await conn.execute("ANALYZE")

                # Get database size
                cursor = await conn.execute("PRAGMA page_count")
                page_count = (await cursor.fetchone())[0]

                cursor = await conn.execute("PRAGMA page_size")
                page_size = (await cursor.fetchone())[0]

                db_size_mb = (page_count * page_size) / 1024 / 1024

                cleanup_logger.info(
                    "database_optimized",
                    db_size_mb=round(db_size_mb, 2),
                )

                return {
                    "success": True,
                    "db_size_mb": round(db_size_mb, 2),
                    "operations": ["VACUUM", "ANALYZE"],
                }

        except Exception as e:
            error_msg = f"Database optimization failed: {str(e)}"
            cleanup_logger.error("database_optimization_error", error=error_msg)
            return {"success": False, "error": error_msg}

    async def _check_system_resources(self) -> Dict[str, Any]:
        """Check system resource usage and warn if needed"""
        try:
            import psutil
            import shutil

            # Memory usage
            memory = psutil.virtual_memory()
            memory_percent = memory.percent

            # Disk usage
            disk_usage = shutil.disk_usage(".")
            disk_free_gb = disk_usage.free / (1024**3)
            disk_total_gb = disk_usage.total / (1024**3)
            disk_percent = (
                (disk_usage.total - disk_usage.free) / disk_usage.total
            ) * 100

            # CPU usage (average over 1 second)
            cpu_percent = psutil.cpu_percent(interval=1)

            # Warnings
            warnings = []
            if memory_percent > 90:
                warnings.append("High memory usage detected")
            if disk_percent > 90:
                warnings.append("High disk usage detected")
            if disk_free_gb < 1:
                warnings.append("Low disk space - less than 1GB free")
            if cpu_percent > 95:
                warnings.append("High CPU usage detected")

            resource_info = {
                "memory_percent": round(memory_percent, 1),
                "disk_free_gb": round(disk_free_gb, 1),
                "disk_total_gb": round(disk_total_gb, 1),
                "disk_percent": round(disk_percent, 1),
                "cpu_percent": round(cpu_percent, 1),
                "warnings": warnings,
            }

            if warnings:
                cleanup_logger.warning(
                    "resource_warnings", warnings=warnings, **resource_info
                )
            else:
                cleanup_logger.info("resource_check_ok", **resource_info)

            return resource_info

        except Exception as e:
            error_msg = f"Resource check failed: {str(e)}"
            cleanup_logger.error("resource_check_error", error=error_msg)
            return {"error": error_msg}

    async def _cleanup_empty_directories(self, base_path: Path):
        """Remove empty directories recursively"""
        try:
            for dirpath in sorted(
                base_path.rglob("*"), key=lambda p: len(p.parts), reverse=True
            ):
                if dirpath.is_dir() and dirpath != base_path:
                    try:
                        if not any(dirpath.iterdir()):
                            dirpath.rmdir()
                            cleanup_logger.debug(
                                "empty_directory_removed", path=str(dirpath)
                            )
                    except OSError:
                        # Directory not empty or permission error
                        pass
        except Exception as e:
            cleanup_logger.error("directory_cleanup_error", error=str(e))

    async def _mark_video_deleted(self, request_id: str):
        """Mark video as deleted in database"""
        try:
            async with db.get_connection() as conn:
                await conn.execute(
                    "UPDATE executions SET video_path = NULL WHERE request_id = ?",
                    (request_id,),
                )
                await conn.commit()
        except Exception as e:
            cleanup_logger.error(
                "video_deletion_mark_failed", request_id=request_id, error=str(e)
            )

    async def get_cleanup_stats(self) -> Dict[str, Any]:
        """Get cleanup statistics and system info"""
        try:
            # Video statistics
            video_dir = Path("data/videos")
            video_stats = {"total_files": 0, "total_size_mb": 0}

            if video_dir.exists():
                for video_file in video_dir.rglob("*.webm"):
                    try:
                        size = video_file.stat().st_size
                        video_stats["total_files"] += 1
                        video_stats["total_size_mb"] += size
                    except:
                        continue
                video_stats["total_size_mb"] = round(
                    video_stats["total_size_mb"] / 1024 / 1024, 2
                )

            # Database statistics
            async with db.get_connection() as conn:
                cursor = await conn.execute("SELECT COUNT(*) FROM executions")
                total_executions = (await cursor.fetchone())[0]

                cursor = await conn.execute(
                    "SELECT COUNT(*) FROM executions WHERE video_path IS NOT NULL"
                )
                executions_with_video = (await cursor.fetchone())[0]

            return {
                "video_files": video_stats,
                "database": {
                    "total_executions": total_executions,
                    "executions_with_video": executions_with_video,
                },
                "scheduler_running": self.running,
                "next_cleanup": self._get_next_cleanup_time().isoformat()
                if self.running
                else None,
            }

        except Exception as e:
            cleanup_logger.error("cleanup_stats_error", error=str(e))
            return {"error": str(e)}

    def _get_next_cleanup_time(self) -> datetime:
        """Calculate next cleanup time"""
        now = datetime.now()
        next_cleanup = now.replace(
            hour=settings.video_cleanup_hour, minute=0, second=0, microsecond=0
        )
        if now >= next_cleanup:
            next_cleanup += timedelta(days=1)
        return next_cleanup


# Global cleanup instance
system_cleaner = SystemCleaner()


# Convenience functions for backward compatibility
async def start_cleanup_scheduler():
    """Start the cleanup scheduler"""
    await system_cleaner.start_cleanup_scheduler()


async def stop_cleanup_scheduler():
    """Stop the cleanup scheduler"""
    await system_cleaner.stop_cleanup_scheduler()


async def perform_cleanup(force: bool = False):
    """Perform immediate cleanup"""
    return await system_cleaner.perform_full_cleanup(force=force)
