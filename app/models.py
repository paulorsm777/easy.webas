from datetime import datetime
from typing import List, Optional, Dict, Any, Literal
from pydantic import BaseModel, Field
import uuid


class ScriptRequest(BaseModel):
    script: str = Field(..., max_length=50000, description="Playwright script code")
    timeout: int = Field(60, ge=10, le=300, description="Execution timeout in seconds")
    webhook_url: Optional[str] = Field(
        None, description="Callback URL for completion notification"
    )
    priority: int = Field(
        1, ge=1, le=5, description="Execution priority (1-5, higher = more priority)"
    )
    tags: List[str] = Field(default_factory=list, description="Tags for analytics")
    user_agent: Optional[str] = Field(None, description="Custom user agent")


class BrowserInfo(BaseModel):
    version: str
    user_agent: str
    viewport: str


class ResourceUsage(BaseModel):
    memory_peak_mb: float
    cpu_time_ms: int
    video_size_mb: float
    network_requests: int
    page_loads: int


class ScriptAnalysis(BaseModel):
    estimated_complexity: Literal["low", "medium", "high"]
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


class ApiKeyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    scopes: List[str] = Field(
        default=["execute", "videos"], description="Allowed scopes"
    )
    rate_limit_per_minute: int = Field(30, ge=1, le=1000)
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


class ApiKeyUpdate(BaseModel):
    name: Optional[str] = None
    is_active: Optional[bool] = None
    rate_limit_per_minute: Optional[int] = None
    scopes: Optional[List[str]] = None
    expires_at: Optional[datetime] = None
    webhook_url: Optional[str] = None
    notes: Optional[str] = None


class QueueStatus(BaseModel):
    total_in_queue: int
    active_executions: int
    average_wait_time: float
    queue_items: List[Dict[str, Any]]


class ServiceStatus(BaseModel):
    database: bool
    browser_pool: bool
    queue: bool
    disk_space: bool


class SystemMetrics(BaseModel):
    active_executions: int
    queue_size: int
    total_api_keys: int
    videos_stored: int
    disk_usage_gb: float
    memory_usage_mb: float
    cpu_usage_percent: float
    uptime_seconds: int


class BrowserPoolStatus(BaseModel):
    total_browsers: int
    available_browsers: int
    warm_browsers: int


class HealthResponse(BaseModel):
    status: Literal["healthy", "degraded", "unhealthy"]
    timestamp: datetime
    services: ServiceStatus
    metrics: SystemMetrics
    browser_pool: BrowserPoolStatus


class VideoInfo(BaseModel):
    request_id: str
    duration_seconds: float
    size_mb: float
    created_at: datetime
    resolution: str
    format: str


class ExecutionStats(BaseModel):
    total_executions: int
    successful_executions: int
    failed_executions: int
    average_execution_time: float
    average_queue_time: float


class ApiKeyAnalytics(BaseModel):
    api_key_id: int
    api_key_name: str
    stats: ExecutionStats
    last_7_days: List[Dict[str, Any]]
    top_tags: List[Dict[str, Any]]


class WebhookPayload(BaseModel):
    request_id: str
    api_key_id: int
    status: Literal["completed", "failed"]
    execution_time: float
    video_url: Optional[str]
    result: Optional[Any]
    error: Optional[str]
    timestamp: datetime


class ScriptTemplate(BaseModel):
    id: Optional[int] = None
    name: str
    description: str
    script_content: str
    category: str
    created_at: Optional[datetime] = None
    usage_count: int = 0


class ValidationResult(BaseModel):
    is_valid: bool
    errors: List[str]
    warnings: List[str]
    estimated_complexity: Literal["low", "medium", "high"]
    estimated_duration: int
    detected_operations: List[str]
