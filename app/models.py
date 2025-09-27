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
    script: str = Field(
        ...,
        max_length=50000,
        description="Playwright script code to execute",
        example="""from playwright.async_api import async_playwright

async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.goto('https://example.com')
        title = await page.title()
        await page.screenshot(path='screenshot.png')
        await browser.close()
        return {"title": title, "url": page.url}

await run()""",
    )
    timeout: int = Field(
        60,
        ge=10,
        le=600,
        description="Maximum execution time in seconds (10-600)",
        example=120,
    )
    webhook_url: Optional[str] = Field(
        None,
        description="HTTP(S) URL for execution status notifications",
        example="https://your-app.com/webhooks/playwright",
    )
    priority: int = Field(
        1, ge=1, le=5, description="Execution priority: 1=lowest, 5=highest", example=3
    )
    tags: List[str] = Field(
        default_factory=list,
        description="Custom tags for analytics and filtering",
        example=["web-scraping", "production", "daily-report"],
    )
    user_agent: Optional[str] = Field(
        None,
        description="Custom User-Agent string for browser",
        example="Mozilla/5.0 (compatible; MyBot/1.0)",
    )


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
    estimated_duration: int = Field(
        description="Estimated execution time in seconds", example=45
    )
    complexity_score: float = Field(
        description="Script complexity rating (0-10)", example=3.5
    )
    resource_requirements: Dict[str, Any] = Field(
        description="Estimated resource usage",
        example={"memory_mb": 256, "cpu_percent": 15, "network_requests": 5},
    )
    safety_score: float = Field(description="Script safety rating (0-10)", example=8.5)
    detected_operations: List[str] = Field(
        description="List of detected browser operations",
        example=["navigation", "screenshot", "form_interaction", "download"],
    )


class ApiKeyCreate(BaseModel):
    name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Human-readable name for the API key",
        example="Production Web Scraper",
    )
    description: Optional[str] = Field(
        None,
        max_length=500,
        description="Optional description of the key's purpose",
        example="API key for automated daily data collection scripts",
    )
    scopes: List[str] = Field(
        ...,
        description="List of permissions granted to this key",
        example=["execute", "videos", "dashboard"],
    )
    rate_limit_per_minute: int = Field(
        30, ge=1, le=1000, description="Maximum requests per minute", example=60
    )
    expires_at: Optional[datetime] = Field(
        None,
        description="Optional expiration date (ISO format)",
        example="2024-12-31T23:59:59Z",
    )


class ApiKeyUpdate(BaseModel):
    name: Optional[str] = Field(
        None,
        min_length=1,
        max_length=100,
        description="Update the key name",
        example="Updated Production Scraper",
    )
    description: Optional[str] = Field(
        None, max_length=500, description="Update the key description"
    )
    scopes: Optional[List[str]] = Field(
        None, description="Update granted permissions", example=["execute", "videos"]
    )
    rate_limit_per_minute: Optional[int] = Field(
        None, ge=1, le=1000, description="Update rate limit"
    )
    expires_at: Optional[datetime] = Field(None, description="Update expiration date")
    is_active: Optional[bool] = Field(
        None, description="Enable or disable the key", example=True
    )


class ApiKeyResponse(BaseModel):
    id: int = Field(description="Unique key identifier", example=123)
    name: str = Field(description="Key name", example="Production Web Scraper")
    description: Optional[str] = Field(description="Key description")
    key_value: Optional[str] = Field(
        description="The actual API key (only shown on creation)",
        example="pw_live_1234567890abcdef",
    )
    scopes: List[str] = Field(
        description="Granted permissions", example=["execute", "videos"]
    )
    rate_limit_per_minute: int = Field(description="Rate limit", example=30)
    is_active: bool = Field(description="Whether the key is active", example=True)
    created_at: datetime = Field(description="Creation timestamp")
    expires_at: Optional[datetime] = Field(description="Expiration timestamp")
    last_used_at: Optional[datetime] = Field(description="Last usage timestamp")
    usage_count: int = Field(description="Total number of requests", example=1547)


class ScriptResponse(BaseModel):
    request_id: str = Field(
        description="Unique identifier for tracking execution",
        example="exec_2024_03_15_14_30_45_abc123",
    )
    status: ExecutionStatus = Field(
        description="Current execution status", example="queued"
    )
    message: str = Field(
        description="Status message", example="Script queued successfully for execution"
    )
    estimated_completion: datetime = Field(
        description="Expected completion time", example="2024-03-15T14:32:30Z"
    )
    queue_wait_time: float = Field(
        description="Estimated wait time in seconds", example=45.5
    )
    queue_position: int = Field(description="Position in execution queue", example=3)
    priority: int = Field(description="Execution priority level", example=3)
    video_url: Optional[str] = Field(
        description="URL to download video recording (available after completion)",
        example="/video/exec_2024_03_15_14_30_45_abc123/your-api-key",
    )
    webhook_status: WebhookStatus = Field(
        description="Webhook notification status", example="sent"
    )
    script_analysis: Optional[ScriptAnalysis] = Field(
        description="Analysis of the submitted script"
    )
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
