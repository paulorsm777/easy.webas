import os
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, Optional, List
import aiofiles

from .config import settings
from .database import db
from .models import VideoInfo
from .logger import video_logger


class VideoManager:
    def __init__(self):
        self.base_video_dir = Path("data/videos")
        self.base_video_dir.mkdir(parents=True, exist_ok=True)

    async def get_video_path(self, request_id: str) -> Optional[str]:
        """Get video file path for a request"""
        execution = await db.get_execution_by_request_id(request_id)
        if execution and execution["video_path"]:
            video_path = Path(execution["video_path"])
            if video_path.exists():
                return str(video_path)
        return None

    async def get_video_info(self, request_id: str) -> Optional[VideoInfo]:
        """Get video metadata"""
        execution = await db.get_execution_by_request_id(request_id)
        if not execution or not execution["video_path"]:
            return None

        video_path = Path(execution["video_path"])
        if not video_path.exists():
            return None

        try:
            # Get file stats
            stat = video_path.stat()
            file_size_mb = stat.st_size / 1024 / 1024
            created_at = datetime.fromtimestamp(stat.st_ctime)

            # Estimate duration based on file size (rough estimate)
            # WebM 720p @ 30fps averages ~1MB per 10 seconds
            estimated_duration = (file_size_mb * 10) if file_size_mb > 0 else 0

            return VideoInfo(
                request_id=request_id,
                duration_seconds=estimated_duration,
                size_mb=round(file_size_mb, 2),
                created_at=created_at,
                resolution=f"{settings.video_width}x{settings.video_height}",
                format="webm",
            )
        except Exception as e:
            video_logger.error("video_info_failed", request_id=request_id, error=str(e))
            return None

    async def serve_video(self, request_id: str, api_key_id: int) -> Optional[tuple]:
        """Serve video file with access control"""
        # Verify access - user can only access videos from their own executions
        execution = await db.get_execution_by_request_id(request_id)
        if not execution:
            video_logger.security_event(
                "video_access_denied",
                api_key_id=api_key_id,
                request_id=request_id,
                reason="execution_not_found",
            )
            return None

        if execution["api_key_id"] != api_key_id:
            video_logger.security_event(
                "video_access_denied",
                api_key_id=api_key_id,
                request_id=request_id,
                reason="unauthorized_access",
            )
            return None

        video_path = await self.get_video_path(request_id)
        if not video_path:
            return None

        try:
            # Read video file
            async with aiofiles.open(video_path, "rb") as f:
                content = await f.read()

            video_logger.info(
                "video_served",
                request_id=request_id,
                api_key_id=api_key_id,
                file_size_mb=len(content) / 1024 / 1024,
            )

            return content, "video/webm"

        except Exception as e:
            video_logger.error(
                "video_serve_failed", request_id=request_id, error=str(e)
            )
            return None

    async def list_videos_by_api_key(
        self, api_key_id: int, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """List recent videos for an API key"""
        async with db.get_connection() as conn:
            cursor = await conn.execute(
                """
                SELECT request_id, created_at, video_path, video_size_mb, execution_time, status
                FROM executions
                WHERE api_key_id = ? AND video_path IS NOT NULL
                ORDER BY created_at DESC
                LIMIT ?
            """,
                (api_key_id, limit),
            )

            rows = await cursor.fetchall()
            videos = []

            for row in rows:
                video_info = await self.get_video_info(row["request_id"])
                if video_info:
                    videos.append(
                        {
                            "request_id": row["request_id"],
                            "created_at": row["created_at"],
                            "size_mb": video_info.size_mb,
                            "duration_seconds": video_info.duration_seconds,
                            "execution_time": row["execution_time"],
                            "status": row["status"],
                            "video_url": f"/video/{row['request_id']}",
                        }
                    )

            return videos

    async def get_storage_stats(self) -> Dict[str, Any]:
        """Get video storage statistics"""
        total_size = 0
        total_files = 0

        for video_file in self.base_video_dir.rglob("*.webm"):
            try:
                size = video_file.stat().st_size
                total_size += size
                total_files += 1
            except:
                continue

        return {
            "total_files": total_files,
            "total_size_mb": round(total_size / 1024 / 1024, 2),
            "total_size_gb": round(total_size / 1024 / 1024 / 1024, 2),
        }

    async def cleanup_old_videos(self, force: bool = False) -> Dict[str, Any]:
        """Clean up videos older than retention period"""
        cutoff_date = datetime.now() - timedelta(days=settings.video_retention_days)

        if not force:
            # Check if it's cleanup time
            current_hour = datetime.now().hour
            if current_hour != settings.video_cleanup_hour:
                return {"status": "skipped", "reason": "not_cleanup_time"}

        video_logger.info("video_cleanup_started", cutoff_date=cutoff_date.isoformat())

        deleted_files = 0
        deleted_size = 0
        errors = []

        for video_file in self.base_video_dir.rglob("*.webm"):
            try:
                file_stat = video_file.stat()
                file_date = datetime.fromtimestamp(file_stat.st_mtime)

                if file_date < cutoff_date:
                    file_size = file_stat.st_size
                    video_file.unlink()

                    deleted_files += 1
                    deleted_size += file_size

                    # Also update database to mark video as deleted
                    request_id = video_file.stem
                    await db.update_execution_video_deleted(request_id)

                    video_logger.info(
                        "video_deleted",
                        file_path=str(video_file),
                        file_age_days=(datetime.now() - file_date).days,
                        file_size_mb=file_size / 1024 / 1024,
                    )

            except Exception as e:
                errors.append(f"Failed to delete {video_file}: {str(e)}")
                video_logger.error(
                    "video_deletion_failed", file_path=str(video_file), error=str(e)
                )

        # Clean up empty directories
        await self._cleanup_empty_directories()

        result = {
            "status": "completed",
            "deleted_files": deleted_files,
            "deleted_size_mb": round(deleted_size / 1024 / 1024, 2),
            "errors": errors,
            "cutoff_date": cutoff_date.isoformat(),
        }

        video_logger.info("video_cleanup_completed", **result)
        return result

    async def _cleanup_empty_directories(self):
        """Remove empty video directories"""
        for year_dir in self.base_video_dir.iterdir():
            if year_dir.is_dir():
                for month_dir in year_dir.iterdir():
                    if month_dir.is_dir():
                        for day_dir in month_dir.iterdir():
                            if day_dir.is_dir() and not any(day_dir.iterdir()):
                                try:
                                    day_dir.rmdir()
                                    video_logger.debug(
                                        "empty_directory_removed", path=str(day_dir)
                                    )
                                except:
                                    pass

                        # Check if month directory is empty
                        if not any(month_dir.iterdir()):
                            try:
                                month_dir.rmdir()
                                video_logger.debug(
                                    "empty_directory_removed", path=str(month_dir)
                                )
                            except:
                                pass

                # Check if year directory is empty
                if not any(year_dir.iterdir()):
                    try:
                        year_dir.rmdir()
                        video_logger.debug(
                            "empty_directory_removed", path=str(year_dir)
                        )
                    except:
                        pass

    async def validate_video_access(self, request_id: str, api_key_id: int) -> bool:
        """Validate if API key can access the video"""
        execution = await db.get_execution_by_request_id(request_id)
        if not execution:
            return False

        return execution["api_key_id"] == api_key_id

    async def get_video_url(self, request_id: str, api_key_id: int) -> Optional[str]:
        """Get public video URL if access is allowed"""
        if await self.validate_video_access(request_id, api_key_id):
            # Get API key value for URL
            api_key_obj = await db.get_api_key_by_id(api_key_id)
            if api_key_obj:
                return (
                    f"http://localhost:8000/video/{request_id}/{api_key_obj.key_value}"
                )
        return None


class VideoCleanupScheduler:
    def __init__(self, video_manager: VideoManager):
        self.video_manager = video_manager
        self._cleanup_task = None

    async def start(self):
        """Start the cleanup scheduler"""
        if self._cleanup_task:
            return

        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        video_logger.info("video_cleanup_scheduler_started")

    async def stop(self):
        """Stop the cleanup scheduler"""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None

        video_logger.info("video_cleanup_scheduler_stopped")

    async def _cleanup_loop(self):
        """Main cleanup loop"""
        while True:
            try:
                # Calculate next cleanup time
                now = datetime.now()
                next_cleanup = now.replace(
                    hour=settings.video_cleanup_hour, minute=0, second=0, microsecond=0
                )

                # If we've passed today's cleanup time, schedule for tomorrow
                if now >= next_cleanup:
                    next_cleanup += timedelta(days=1)

                # Wait until cleanup time
                wait_seconds = (next_cleanup - now).total_seconds()
                video_logger.info(
                    "video_cleanup_scheduled",
                    next_cleanup=next_cleanup.isoformat(),
                    wait_hours=wait_seconds / 3600,
                )

                await asyncio.sleep(wait_seconds)

                # Perform cleanup
                result = await self.video_manager.cleanup_old_videos(force=True)
                video_logger.info("scheduled_cleanup_completed", **result)

            except asyncio.CancelledError:
                break
            except Exception as e:
                video_logger.error("cleanup_scheduler_error", error=str(e))
                # Wait 1 hour before retrying
                await asyncio.sleep(3600)


# Global video manager instance
video_manager = VideoManager()

# Global cleanup scheduler
cleanup_scheduler = VideoCleanupScheduler(video_manager)
