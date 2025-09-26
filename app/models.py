from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from enum import Enum


class ExecutionStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"


class HealthStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class WebhookStatus(str, Enum):
    SENT = "sent"
    FAILED = "failed"
    NOT_CONFIGURED = "not_configured"


class ScriptRequest(BaseModel):
    script: str = Field(..., max_length=50000, description="Playwright script code")
    timeout: int = Field(60, ge=10, le=600, description="Execution timeout in seconds")
    webhook_url: Optional[str] = Field(None, description="Callback URL for notifications")
    priority: int = Field(1, ge=1, le=5, description="Execution priority (1-5, higher = more priority)")
    tags: List[str] = Field(default_factory=list, description="Tags for analytics")
    user_agent: Optional[str] = Field(None, description="Custom user agent")


class BrowserInfo(BaseModel):
    version: str
    user_agent: str
    viewport: str


class ResourceUsage(BaseModel):
    memory_peak_mb: float
    cpu_time_ms: int
    video_size_mb: Optional[float] = None
    network_requests: int = 0
    page_loads: int = 0


class ScriptAnalysis(BaseModel):
    estimated_complexity: str
    detected_operations: List[str]
    security_warnings: List[str]


class ScriptResponse(BaseModel):
    request_id: str
    success: bool
    result: Optional[Any] = None
    error: Optional[str] = None
    video_url: Optional[str] = None
    execution_time: float
    queue_wait_time: float
    queue_position: int
    priority: int
    browser_info: Optional[BrowserInfo] = None
    resource_usage: Optional[ResourceUsage] = None
    script_analysis: Optional[ScriptAnalysis] = None


class HealthServices(BaseModel):
    database: bool
    browser_pool: bool
    queue: bool
    disk_space: bool


class HealthMetrics(BaseModel):
    active_executions: int
    queue_size: int
    total_api_keys: int
    videos_stored: int
    disk_usage_gb: float
    memory_usage_mb: int
    cpu_usage_percent: float
    uptime_seconds: int


class BrowserPoolStatus(BaseModel):
    total_browsers: int
    available_browsers: int
    warm_browsers: int


class HealthResponse(BaseModel):
    status: HealthStatus
    timestamp: datetime
    services: HealthServices
    metrics: HealthMetrics
    browser_pool: BrowserPoolStatus


class ApiKeyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    scopes: List[str] = Field(default=["execute", "videos"])
    rate_limit_per_minute: int = Field(30, ge=1, le=1000)
    expires_at: Optional[datetime] = None
    webhook_url: Optional[str] = None
    notes: Optional[str] = None


class ApiKeyUpdate(BaseModel):
    name: Optional[str] = None
    is_active: Optional[bool] = None
    rate_limit_per_minute: Optional[int] = None
    scopes: Optional[List[str]] = None
    expires_at: Optional[datetime] = None
    webhook_url: Optional[str] = None
    notes: Optional[str] = None


class ApiKeyResponse(BaseModel):
    id: int
    key_value: str
    name: str
    created_at: datetime
    last_used: Optional[datetime]
    is_active: bool
    rate_limit_per_minute: int
    total_requests: int
    scopes: List[str]
    expires_at: Optional[datetime]
    webhook_url: Optional[str]
    notes: Optional[str]


class QueueStatus(BaseModel):
    total_queued: int
    total_running: int
    estimated_wait_time: float
    queue_items: List[Dict[str, Any]]


class VideoInfo(BaseModel):
    request_id: str
    duration_seconds: float
    size_mb: float
    created_at: datetime
    width: int
    height: int


class ScriptTemplate(BaseModel):
    name: str
    description: str
    category: str
    script_content: str
    usage_count: int = 0


class ExecutionAnalytics(BaseModel):
    api_key_id: int
    total_executions: int
    successful_executions: int
    failed_executions: int
    avg_execution_time: float
    total_video_size_mb: float