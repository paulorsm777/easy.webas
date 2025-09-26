import os
from typing import List, Optional
from pydantic import BaseSettings


class Settings(BaseSettings):
    # Admin Access
    ADMIN_API_KEY: str = "admin-super-secret-key-2024"

    # Execution Limits
    MAX_CONCURRENT_EXECUTIONS: int = 10
    MAX_QUEUE_SIZE: int = 100
    MAX_SCRIPT_SIZE: int = 50000
    MAX_EXECUTION_TIME: int = 300
    EMERGENCY_TIMEOUT_MULTIPLIER: int = 2

    # Video Settings
    VIDEO_RETENTION_DAYS: int = 7
    VIDEO_CLEANUP_HOUR: int = 2
    VIDEO_WIDTH: int = 1280
    VIDEO_HEIGHT: int = 720

    # Rate Limiting
    GLOBAL_RATE_LIMIT_PER_MINUTE: int = 60
    PER_KEY_RATE_LIMIT_PER_MINUTE: int = 30

    # Database
    DATABASE_PATH: str = "./data/database.db"

    # Browser Pool
    BROWSER_POOL_SIZE: int = 10
    BROWSER_WARMUP_PAGES: int = 3

    # Dashboard
    DASHBOARD_REFRESH_INTERVAL: int = 5

    # Webhooks
    MAX_WEBHOOK_RETRIES: int = 3
    WEBHOOK_TIMEOUT: int = 10

    # Resource Limits
    MAX_MEMORY_MB_PER_EXECUTION: int = 512
    MAX_CPU_PERCENT_PER_EXECUTION: int = 50

    # Security
    ALLOWED_DOMAINS: str = "*"
    SCRIPT_TIMEOUT_GRACE_PERIOD: int = 30

    class Config:
        env_file = ".env"
        case_sensitive = True

    def get_allowed_domains(self) -> List[str]:
        if self.ALLOWED_DOMAINS == "*":
            return []
        return [domain.strip() for domain in self.ALLOWED_DOMAINS.split(",")]


settings = Settings()