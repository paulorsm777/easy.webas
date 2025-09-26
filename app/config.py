import os
from pathlib import Path
from typing import List, Optional
from pydantic import BaseSettings


class Settings(BaseSettings):
    # Admin Access
    admin_api_key: str = "admin-super-secret-key-2024"

    # Execution Limits
    max_concurrent_executions: int = 10
    max_queue_size: int = 100
    max_script_size: int = 50000
    max_execution_time: int = 300
    emergency_timeout_multiplier: int = 2

    # Video Settings (720p only)
    video_retention_days: int = 7
    video_cleanup_hour: int = 2
    video_width: int = 1280
    video_height: int = 720

    # Rate Limiting
    global_rate_limit_per_minute: int = 60
    per_key_rate_limit_per_minute: int = 30

    # Database
    database_path: str = "./data/database.db"

    # Browser Pool
    browser_pool_size: int = 10
    browser_warmup_pages: int = 3

    # Dashboard
    dashboard_refresh_interval: int = 5

    # Webhooks
    max_webhook_retries: int = 3
    webhook_timeout: int = 10

    # Resource Limits
    max_memory_mb_per_execution: int = 512
    max_cpu_percent_per_execution: int = 50

    # Security
    allowed_domains: str = "*"
    script_timeout_grace_period: int = 30

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


# Global settings instance
settings = Settings()

# Ensure data directory exists
data_dir = Path(settings.database_path).parent
data_dir.mkdir(exist_ok=True, parents=True)

# Ensure videos directory exists
videos_dir = data_dir / "videos"
videos_dir.mkdir(exist_ok=True, parents=True)
