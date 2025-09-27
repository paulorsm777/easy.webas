import os
import asyncio
import aiofiles
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, List
import structlog

from app.config import settings
from app.models import VideoInfo
from app.logger import execution_logger

logger = structlog.get_logger()


class VideoService:
    """Service for managing video recordings"""

    def __init__(self):
        self.base_video_path = Path("./data/videos")
        self.video_cache: Dict[str, VideoInfo] = {}

    async def initialize(self):
        """Initialize video service"""
        # Create video directories
        self.base_video_path.mkdir(parents=True, exist_ok=True)

        # Create base video directory only
        pass

        logger.info("Video service initialized", base_path=str(self.base_video_path))

    def get_video_path(self, request_id: str, date: Optional[datetime] = None) -> Path:
        """Get video file path for a request"""
        return self.base_video_path / f"{request_id}.webm"

    def get_video_directory(self, date: Optional[datetime] = None) -> Path:
        """Get video directory for a specific date"""
        return self.base_video_path

    async def save_video_info(
        self, request_id: str, video_path: str, duration_seconds: float = 0.0
    ):
        """Save video information to cache"""
        try:
            if os.path.exists(video_path):
                stat = os.stat(video_path)
                size_mb = stat.st_size / 1024 / 1024
                created_at = datetime.fromtimestamp(stat.st_ctime)

                video_info = VideoInfo(
                    request_id=request_id,
                    duration_seconds=duration_seconds,
                    size_mb=size_mb,
                    created_at=created_at,
                    width=settings.VIDEO_WIDTH,
                    height=settings.VIDEO_HEIGHT,
                )

                self.video_cache[request_id] = video_info

                execution_logger.log_video_event(
                    "saved",
                    request_id=request_id,
                    video_path=video_path,
                    video_size_mb=size_mb,
                )

                return video_info

        except Exception as e:
            logger.error(
                "Failed to save video info", request_id=request_id, error=str(e)
            )

        return None

    async def get_video_info(self, request_id: str) -> Optional[VideoInfo]:
        """Get video information"""
        # Check cache first
        if request_id in self.video_cache:
            return self.video_cache[request_id]

        # Search for video file
        video_path = await self.find_video_file(request_id)
        if video_path and os.path.exists(video_path):
            return await self.save_video_info(request_id, video_path)

        return None

    async def find_video_file(self, request_id: str) -> Optional[str]:
        """Find video file by request ID"""
        video_path = self.get_video_path(request_id)
        if video_path.exists():
            return str(video_path)
        return None

    async def serve_video_file(self, request_id: str) -> Optional[str]:
        """Get video file path for serving"""
        video_path = await self.find_video_file(request_id)
        if video_path and os.path.exists(video_path):
            return video_path
        return None

    async def delete_video(self, request_id: str) -> bool:
        """Delete a specific video"""
        try:
            video_path = await self.find_video_file(request_id)
            if video_path and os.path.exists(video_path):
                os.remove(video_path)

                # Remove from cache
                self.video_cache.pop(request_id, None)

                execution_logger.log_video_event(
                    "deleted", request_id=request_id, video_path=video_path
                )
                return True

        except Exception as e:
            logger.error("Failed to delete video", request_id=request_id, error=str(e))

        return False

    async def cleanup_old_videos(self, retention_days: int = None) -> Dict[str, Any]:
        """Cleanup videos older than retention period"""
        if retention_days is None:
            retention_days = settings.VIDEO_RETENTION_DAYS

        cutoff_date = datetime.now() - timedelta(days=retention_days)
        deleted_count = 0
        deleted_size_mb = 0.0
        errors = []

        try:
            # Check all video files directly in the base directory
            for video_file in self.base_video_path.glob("*.webm"):
                try:
                    stat = video_file.stat()
                    file_date = datetime.fromtimestamp(stat.st_ctime)

                    if file_date < cutoff_date:
                        file_size = stat.st_size / 1024 / 1024
                        video_file.unlink()
                        deleted_count += 1
                        deleted_size_mb += file_size

                        # Remove from cache
                        request_id = video_file.stem
                        self.video_cache.pop(request_id, None)

                except Exception as e:
                    errors.append(f"Failed to delete {video_file}: {str(e)}")

        except Exception as e:
            errors.append(f"Cleanup error: {str(e)}")

        result = {
            "deleted_count": deleted_count,
            "deleted_size_mb": deleted_size_mb,
            "retention_days": retention_days,
            "cutoff_date": cutoff_date.isoformat(),
            "errors": errors,
        }

        if deleted_count > 0:
            execution_logger.log_video_event(
                "cleanup_completed",
                request_id="bulk",
                deleted_count=deleted_count,
                deleted_size_mb=deleted_size_mb,
            )

        return result

    async def get_storage_stats(self) -> Dict[str, Any]:
        """Get video storage statistics"""
        total_files = 0
        total_size_mb = 0.0
        oldest_video = None
        newest_video = None

        try:
            for video_file in self.base_video_path.glob("*.webm"):
                if video_file.is_file():
                    stat = video_file.stat()
                    total_files += 1
                    total_size_mb += stat.st_size / 1024 / 1024

                    file_time = datetime.fromtimestamp(stat.st_ctime)
                    if oldest_video is None or file_time < oldest_video:
                        oldest_video = file_time
                    if newest_video is None or file_time > newest_video:
                        newest_video = file_time

        except Exception as e:
            logger.error("Failed to get storage stats", error=str(e))

        return {
            "total_files": total_files,
            "total_size_mb": round(total_size_mb, 2),
            "total_size_gb": round(total_size_mb / 1024, 2),
            "oldest_video": oldest_video.isoformat() if oldest_video else None,
            "newest_video": newest_video.isoformat() if newest_video else None,
            "retention_days": settings.VIDEO_RETENTION_DAYS,
        }

    async def list_videos_by_date(
        self, date: datetime, limit: int = 100
    ) -> List[Dict[str, Any]]:
        """List videos for a specific date"""
        videos = []

        try:
            # Filter videos by creation date
            video_files = []
            for video_file in self.base_video_path.glob("*.webm"):
                try:
                    stat = video_file.stat()
                    file_date = datetime.fromtimestamp(stat.st_ctime).date()
                    if file_date == date.date():
                        video_files.append(video_file)
                except Exception:
                    continue

            # Limit results
            video_files = video_files[:limit]

            for video_file in video_files:
                try:
                    stat = video_file.stat()
                    request_id = video_file.stem

                    videos.append(
                        {
                            "request_id": request_id,
                            "file_path": str(video_file),
                            "size_mb": round(stat.st_size / 1024 / 1024, 2),
                            "created_at": datetime.fromtimestamp(
                                stat.st_ctime
                            ).isoformat(),
                            "width": settings.VIDEO_WIDTH,
                            "height": settings.VIDEO_HEIGHT,
                        }
                    )

                except Exception as e:
                    logger.error(
                        "Failed to process video file",
                        file=str(video_file),
                        error=str(e),
                    )

        except Exception as e:
            logger.error("Failed to list videos", date=date.isoformat(), error=str(e))

        return sorted(videos, key=lambda x: x["created_at"], reverse=True)

    async def get_recent_videos(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get most recent videos across all dates"""
        videos = []

        try:
            video_files = list(self.base_video_path.glob("*.webm"))

            for video_file in video_files:
                try:
                    stat = video_file.stat()
                    request_id = video_file.stem

                    videos.append(
                        {
                            "request_id": request_id,
                            "file_path": str(video_file),
                            "size_mb": round(stat.st_size / 1024 / 1024, 2),
                            "created_at": datetime.fromtimestamp(
                                stat.st_ctime
                            ).isoformat(),
                            "width": settings.VIDEO_WIDTH,
                            "height": settings.VIDEO_HEIGHT,
                        }
                    )

                except Exception as e:
                    logger.error(
                        "Failed to process video file",
                        file=str(video_file),
                        error=str(e),
                    )

        except Exception as e:
            logger.error("Failed to get recent videos", error=str(e))

        # Sort by creation time and limit
        videos.sort(key=lambda x: x["created_at"], reverse=True)
        return videos[:limit]

    async def validate_video_access(self, request_id: str, api_key_id: int) -> bool:
        """Validate that API key can access specific video"""
        # For now, allow access to any video with valid API key
        # In production, you might want to check if the API key was used for this execution
        video_info = await self.get_video_info(request_id)
        return video_info is not None

    async def create_video_url(
        self, request_id: str, api_key: str, base_url: str = "http://localhost:8000"
    ) -> str:
        """Create video access URL"""
        return f"{base_url}/video/{request_id}/{api_key}"

    async def estimate_disk_usage(self) -> Dict[str, Any]:
        """Estimate disk usage and projection"""
        stats = await self.get_storage_stats()

        # Estimate daily growth (based on recent videos)
        today_videos = await self.list_videos_by_date(datetime.now())
        yesterday_videos = await self.list_videos_by_date(
            datetime.now() - timedelta(days=1)
        )

        daily_growth_mb = 0.0
        if today_videos:
            daily_growth_mb = sum(v["size_mb"] for v in today_videos)
        elif yesterday_videos:
            daily_growth_mb = sum(v["size_mb"] for v in yesterday_videos)

        # Project future usage
        projected_30_days_mb = stats["total_size_mb"] + (daily_growth_mb * 30)
        projected_90_days_mb = stats["total_size_mb"] + (daily_growth_mb * 90)

        return {
            "current_usage": stats,
            "daily_growth_mb": round(daily_growth_mb, 2),
            "projected_30_days_mb": round(projected_30_days_mb, 2),
            "projected_90_days_mb": round(projected_90_days_mb, 2),
            "retention_days": settings.VIDEO_RETENTION_DAYS,
            "max_retention_size_mb": round(
                daily_growth_mb * settings.VIDEO_RETENTION_DAYS, 2
            ),
        }


# Global video service instance
video_service = VideoService()
