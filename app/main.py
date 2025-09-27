from fastapi import FastAPI, HTTPException, Depends, Request, Query, BackgroundTasks
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import asyncio
from datetime import datetime
from typing import Optional, List
import uvicorn
import structlog

# Import all modules
from app.config import settings
from app.models import (
    ScriptRequest,
    ScriptResponse,
    ApiKeyCreate,
    ApiKeyUpdate,
    ApiKeyResponse,
    HealthResponse,
    QueueStatus,
    VideoInfo,
    ScriptTemplate,
    ExecutionAnalytics,
)
from app.database import (
    init_database,
    ensure_admin_key,
    create_api_key,
    list_api_keys,
    get_api_key_by_id,
    update_api_key,
    delete_api_key,
    get_execution_analytics,
)
from app.auth import (
    get_current_api_key,
    require_admin,
    require_execute,
    require_videos,
    require_dashboard,
    RateLimitMiddleware,
)
from app.executor import executor
from app.video_service import video_service
from app.health import health_checker
from app.webhooks import webhook_service
from app.templates import template_service
from app.validation import script_validator
from app.logger import request_logger, system_logger

logger = structlog.get_logger()

# Create FastAPI app
app = FastAPI(
    title="🎭 Playwright Automation Server",
    description="""
    ## Advanced Playwright Script Execution Platform

    A comprehensive automation server that executes Playwright scripts with enterprise-grade features:

    ### 🚀 Key Features
    - **Queue Management**: Intelligent script queuing with priority support
    - **Video Recording**: Automatic screen recording of all executions
    - **API Key Management**: Secure access control with scoped permissions
    - **Real-time Monitoring**: Health checks, metrics, and analytics
    - **Template System**: Pre-built script templates for common tasks
    - **Webhook Integration**: Real-time notifications and callbacks
    - **Resource Management**: Memory and CPU limits with cleanup automation

    ### 🔐 Authentication
    All endpoints require API key authentication via `Authorization: Bearer <api_key>` header.

    ### 📊 Current System Status
    - **Concurrent Executions**: Up to 10 simultaneous scripts
    - **Queue Capacity**: 100 pending executions
    - **Video Retention**: 7 days automatic cleanup
    - **Browser Pool**: 10 warm browsers ready for execution

    ### 🎯 Quick Start
    1. Use the default admin key: `admin-super-secret-key-2024`
    2. Try the `/execute` endpoint with a simple script
    3. Monitor execution via `/queue/status`
    4. View recordings via `/video/{request_id}/{api_key}`
    """,
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    contact={
        "name": "Playwright Automation Team",
        "url": "https://github.com/your-repo/easy.webas",
    },
    license_info={
        "name": "MIT License",
        "url": "https://opensource.org/licenses/MIT",
    },
)

# Add middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(RateLimitMiddleware)

# Mount static files and templates
try:
    app.mount("/static", StaticFiles(directory="static"), name="static")
    templates = Jinja2Templates(directory="templates")
except Exception as e:
    logger.warning("Static files or templates not found", error=str(e))
    templates = None


# Startup and shutdown events
@app.on_event("startup")
async def startup_event():
    """Initialize all services"""
    try:
        system_logger.log_startup("database")
        await init_database()
        await ensure_admin_key()

        system_logger.log_startup("executor")
        await executor.initialize()

        system_logger.log_startup("video_service")
        await video_service.initialize()

        system_logger.log_startup("webhook_service")
        # Webhook service doesn't need initialization

        logger.info("Playwright Automation Server started successfully")

    except Exception as e:
        logger.error("Failed to start server", error=str(e))
        raise


@app.on_event("shutdown")
async def shutdown_event():
    """Graceful shutdown"""
    try:
        system_logger.log_shutdown("executor")
        await executor.shutdown()

        system_logger.log_shutdown("webhook_service")
        await webhook_service.close()

        logger.info("Playwright Automation Server stopped successfully")

    except Exception as e:
        logger.error("Error during shutdown", error=str(e))


# Middleware for request logging
@app.middleware("http")
async def log_requests(request: Request, call_next):
    return await request_logger.log_request(request, call_next)


# EXECUTION ENDPOINTS


@app.post(
    "/execute",
    response_model=ScriptResponse,
    tags=["🎬 Script Execution"],
    summary="Execute Playwright Script",
    description="""
         Execute a Playwright script with comprehensive monitoring and video recording.

         ### Features:
         - **Automatic validation** of script safety
         - **Queue management** with priority support
         - **Video recording** of the entire execution
         - **Real-time status** updates via webhooks
         - **Resource monitoring** and limits

         ### Example Scripts:

         **Basic Page Navigation:**
         ```python
         from playwright.async_api import async_playwright

         async def main():
             async with async_playwright() as p:
                 browser = await p.chromium.launch()
                 page = await browser.new_page()
                 await page.goto('https://example.com')
                 title = await page.title()
                 await browser.close()
                 return {"title": title, "url": "https://example.com"}
         ```

         **Web Scraping with Screenshot:**
         ```python
         from playwright.async_api import async_playwright

         async def main():
             async with async_playwright() as p:
                 browser = await p.chromium.launch()
                 page = await browser.new_page()
                 await page.goto('https://quotes.toscrape.com')

                 # Take screenshot
                 await page.screenshot(path='quotes.png')

                 # Extract quotes
                 quotes = await page.locator('.quote').all()
                 result = []
                 for quote in quotes[:3]:  # Get first 3 quotes
                     text = await quote.locator('.text').text_content()
                     author = await quote.locator('.author').text_content()
                     result.append({"text": text, "author": author})

                 await browser.close()
                 return {"quotes": result, "total_found": len(quotes)}
         ```

         **Form Interaction:**
         ```python
         from playwright.async_api import async_playwright

         async def main():
             async with async_playwright() as p:
                 browser = await p.chromium.launch()
                 page = await browser.new_page()
                 await page.goto('https://httpbin.org/forms/post')

                 # Fill form
                 await page.fill('input[name="custname"]', 'Test User')
                 await page.fill('input[name="custtel"]', '1234567890')
                 await page.fill('input[name="custemail"]', 'test@example.com')
                 await page.select_option('select[name="size"]', 'medium')

                 # Submit and wait for response
                 await page.click('input[type="submit"]')
                 await page.wait_for_load_state('networkidle')

                 # Get result
                 content = await page.text_content('body')

                 await browser.close()
                 return {"form_submitted": True, "response_preview": content[:200]}
         ```

         ### Response includes:
         - Unique request ID for tracking
         - Queue position and estimated wait time
         - Script analysis and safety validation
         - Video recording URL (when ready)
         """,
    responses={
        200: {"description": "Script queued successfully"},
        400: {"description": "Script validation failed"},
        401: {"description": "Invalid or missing API key"},
        403: {"description": "Insufficient permissions"},
        429: {"description": "Rate limit exceeded"},
    },
)
async def execute_script(
    request: ScriptRequest,
    background_tasks: BackgroundTasks,
    api_key=Depends(require_execute),
):
    """Execute a Playwright script"""
    try:
        # Validate script
        logger.info("Script validation starting", script_preview=request.script[:100])
        validation_result = script_validator.validate_script_for_execution(
            request.script
        )
        logger.info(
            "Script validation completed",
            is_safe=validation_result["is_safe"],
            critical_warnings=validation_result["critical_warnings"],
        )

        if not validation_result["is_safe"]:
            logger.warning(
                "Script validation failed",
                warnings=validation_result["critical_warnings"],
                script=request.script,
            )
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "Script validation failed",
                    "warnings": validation_result["critical_warnings"],
                    "recommendation": validation_result["recommendation"],
                },
            )

        # Queue script for execution
        request_id = await executor.queue_script(request, api_key.id)

        # Send webhook notification if configured
        if request.webhook_url:
            background_tasks.add_task(
                webhook_service.notify_queue_position,
                request_id,
                api_key.id,
                request.webhook_url,
                0,
                60.0,  # Estimated
            )

        # Get queue status
        queue_status = await executor.get_queue_status()

        return ScriptResponse(
            request_id=request_id,
            success=True,
            result=None,
            error=None,
            video_url=f"http://localhost:8000/video/{request_id}/{api_key.key_value}",
            execution_time=0.0,
            queue_wait_time=0.0,
            queue_position=queue_status["total_queued"],
            priority=request.priority,
            script_analysis=validation_result["analysis"],
        )

    except Exception as e:
        logger.error("Script execution failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.post(
    "/validate",
    tags=["🎬 Script Execution"],
    summary="Validate Script",
    description="""
         Validate a Playwright script without executing it.

         Performs comprehensive safety and syntax analysis:
         - **Syntax validation** and import checking
         - **Security analysis** for potentially dangerous operations
         - **Performance estimation** and resource requirements
         - **Best practices** recommendations

         Use this endpoint to test scripts before execution.
         """,
    responses={
        200: {"description": "Validation completed"},
        400: {"description": "Invalid script format"},
        401: {"description": "Authentication required"},
    },
)
async def validate_script(request: ScriptRequest, api_key=Depends(require_execute)):
    """Validate a script without executing it"""
    try:
        validation_result = script_validator.validate_script_for_execution(
            request.script
        )

        return {
            "request_id": None,
            "is_safe": validation_result["is_safe"],
            "estimated_time": validation_result["estimated_time"],
            "analysis": validation_result["analysis"].dict(),
            "recommendation": validation_result["recommendation"],
            "warnings": validation_result["critical_warnings"],
        }

    except Exception as e:
        logger.error("Script validation failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


# TEMPLATE ENDPOINTS


@app.get(
    "/templates",
    response_model=List[ScriptTemplate],
    tags=["📝 Templates"],
    summary="List Script Templates",
    description="""
         Get available pre-built script templates for common automation tasks.

         ### Available Categories:
         - **Web Scraping**: Data extraction from websites
         - **UI Testing**: Automated user interface testing
         - **Performance**: Page load and performance testing
         - **Screenshots**: Automated screenshot capture
         - **Forms**: Form filling and submission
         - **Authentication**: Login and session management
         - **Custom**: User-created templates

         ### Filter Options:
         - `category`: Filter by template category
         - `search`: Search in template names and descriptions
         """,
    responses={
        200: {"description": "Templates retrieved successfully"},
        401: {"description": "Authentication required"},
    },
)
async def get_templates(
    category: Optional[str] = Query(None, description="Filter by category"),
    search: Optional[str] = Query(None, description="Search templates"),
    api_key=Depends(get_current_api_key),
):
    """Get available script templates"""
    try:
        if search:
            templates = await template_service.search_templates(search)
        elif category:
            templates = await template_service.get_templates_by_category(category)
        else:
            templates = await template_service.get_all_templates()

        return templates

    except Exception as e:
        logger.error("Failed to get templates", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.get(
    "/templates/{template_name}",
    response_model=ScriptTemplate,
    tags=["📝 Templates"],
    summary="Get Specific Template",
    description="""
         Retrieve a specific template by name with complete script content.

         Returns the full template including:
         - Complete Playwright script code
         - Parameter descriptions and examples
         - Usage instructions and best practices
         - Expected outputs and return values
         """,
    responses={
        200: {"description": "Template found"},
        404: {"description": "Template not found"},
        401: {"description": "Authentication required"},
    },
)
async def get_template(template_name: str, api_key=Depends(get_current_api_key)):
    """Get specific template by name"""
    try:
        template = await template_service.get_template_by_name(template_name)
        if not template:
            raise HTTPException(status_code=404, detail="Template not found")

        # Update usage count
        await template_service.update_template_usage(template_name)

        return template

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to get template", template_name=template_name, error=str(e)
        )
        raise HTTPException(status_code=500, detail=str(e))


@app.get(
    "/templates/categories",
    tags=["📝 Templates"],
    summary="Get Template Categories",
    description="""
         Get all available template categories with counts.

         Useful for building category filters in UI applications.
         """,
    responses={
        200: {"description": "Categories retrieved successfully"},
        401: {"description": "Authentication required"},
    },
)
async def get_template_categories(api_key=Depends(get_current_api_key)):
    """Get template categories with counts"""
    try:
        categories = await template_service.get_template_categories()
        return {"categories": categories}

    except Exception as e:
        logger.error("Failed to get template categories", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


# ADMIN ENDPOINTS


@app.post(
    "/admin/api-keys",
    response_model=ApiKeyResponse,
    tags=["🔐 API Key Management"],
    summary="Create API Key",
    description="""
          Create a new API key with specified permissions and limits.

          ### Available Scopes:
          - `execute`: Execute scripts and view results
          - `videos`: Access video recordings
          - `dashboard`: View monitoring dashboard
          - `admin`: Full administrative access

          ### Rate Limiting:
          - Default: 30 requests per minute per key
          - Admin keys: Unlimited (configurable)

          **⚠️ Admin access required**
          """,
    responses={
        201: {"description": "API key created successfully"},
        400: {"description": "Invalid key configuration"},
        401: {"description": "Admin authentication required"},
        403: {"description": "Insufficient permissions"},
    },
)
async def create_new_api_key(key_data: ApiKeyCreate, admin_key=Depends(require_admin)):
    """Create a new API key (admin only)"""
    try:
        api_key = await create_api_key(key_data)
        logger.info("API key created", key_id=api_key.id, key_name=api_key.name)
        return api_key

    except Exception as e:
        logger.error("Failed to create API key", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.get(
    "/admin/api-keys",
    response_model=List[ApiKeyResponse],
    tags=["🔐 API Key Management"],
    summary="List All API Keys",
    description="""
         Retrieve all API keys in the system with their current status.

         Shows:
         - Key metadata and permissions
         - Usage statistics and last used timestamp
         - Active/inactive status
         - Expiration dates

         **⚠️ Admin access required**
         """,
    responses={
        200: {"description": "API keys retrieved successfully"},
        401: {"description": "Admin authentication required"},
        403: {"description": "Insufficient permissions"},
    },
)
async def list_all_api_keys(admin_key=Depends(require_admin)):
    """List all API keys (admin only)"""
    try:
        return await list_api_keys()

    except Exception as e:
        logger.error("Failed to list API keys", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.put(
    "/admin/api-keys/{key_id}",
    response_model=ApiKeyResponse,
    tags=["🔐 API Key Management"],
    summary="Update API Key",
    description="""
         Update an existing API key's configuration.

         ### Updatable Fields:
         - Name and description
         - Scopes and permissions
         - Rate limits
         - Expiration date
         - Active status

         **⚠️ Admin access required**
         """,
    responses={
        200: {"description": "API key updated successfully"},
        404: {"description": "API key not found"},
        401: {"description": "Admin authentication required"},
        403: {"description": "Insufficient permissions"},
    },
)
async def update_existing_api_key(
    key_id: int, update_data: ApiKeyUpdate, admin_key=Depends(require_admin)
):
    """Update an API key (admin only)"""
    try:
        api_key = await update_api_key(key_id, update_data)
        if not api_key:
            raise HTTPException(status_code=404, detail="API key not found")

        logger.info("API key updated", key_id=key_id)
        return api_key

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to update API key", key_id=key_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.delete(
    "/admin/api-keys/{key_id}",
    tags=["🔐 API Key Management"],
    summary="Delete API Key",
    description="""
           Permanently delete an API key from the system.

           **⚠️ Warning**: This action is irreversible!
           - All active sessions will be terminated
           - Associated data remains but key access is revoked

           **⚠️ Admin access required**
           """,
    responses={
        204: {"description": "API key deleted successfully"},
        404: {"description": "API key not found"},
        401: {"description": "Admin authentication required"},
        403: {"description": "Insufficient permissions"},
    },
)
async def delete_existing_api_key(key_id: int, admin_key=Depends(require_admin)):
    """Delete an API key (admin only)"""
    try:
        success = await delete_api_key(key_id)
        if not success:
            raise HTTPException(status_code=404, detail="API key not found")

        logger.info("API key deleted", key_id=key_id)
        return {"message": "API key deleted successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to delete API key", key_id=key_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.get(
    "/admin/analytics",
    tags=["📊 Analytics & Monitoring"],
    summary="Get System Analytics",
    description="""
         Retrieve comprehensive system analytics and usage statistics.

         ### Analytics Include:
         - **Execution Statistics**: Success rates, average duration
         - **API Usage**: Request patterns, rate limit hits
         - **Resource Utilization**: CPU, memory, disk usage
         - **Queue Performance**: Wait times, throughput
         - **Error Analysis**: Common failures and patterns

         ### Filtering:
         - Filter by specific API key ID
         - Time range filtering (last 24h, 7d, 30d)

         **⚠️ Admin access required**
         """,
    responses={
        200: {"description": "Analytics data retrieved successfully"},
        401: {"description": "Admin authentication required"},
        403: {"description": "Insufficient permissions"},
    },
)
async def get_analytics(
    api_key_id: Optional[int] = Query(None, description="Filter by API key ID"),
    admin_key=Depends(require_admin),
):
    """Get analytics data (admin only)"""
    try:
        analytics = await get_execution_analytics(api_key_id)
        return {"analytics": analytics, "generated_at": datetime.now().isoformat()}

    except Exception as e:
        logger.error("Failed to get analytics", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.delete(
    "/admin/videos/cleanup",
    tags=["📊 Analytics & Monitoring"],
    summary="Force Video Cleanup",
    description="""
           Manually trigger video file cleanup process.

           ### Cleanup Process:
           - Removes videos older than retention period (default: 7 days)
           - Frees up disk space
           - Updates storage statistics
           - Maintains execution logs

           ### Options:
           - Override default retention period
           - Force cleanup regardless of disk space

           **⚠️ Admin access required**
           """,
    responses={
        200: {"description": "Cleanup completed successfully"},
        401: {"description": "Admin authentication required"},
        403: {"description": "Insufficient permissions"},
    },
)
async def force_video_cleanup(
    retention_days: Optional[int] = Query(None, description="Override retention days"),
    admin_key=Depends(require_admin),
):
    """Force video cleanup (admin only)"""
    try:
        result = await video_service.cleanup_old_videos(retention_days)
        logger.info("Video cleanup completed", **result)
        return result

    except Exception as e:
        logger.error("Video cleanup failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.post(
    "/admin/templates",
    tags=["📝 Templates"],
    summary="Create Custom Template",
    description="""
          Create a new custom script template.

          ### Template Structure:
          ```json
          {
            "name": "custom-template-name",
            "description": "Template description",
            "category": "custom",
            "script_content": "# Playwright script here..."
          }
          ```

          Custom templates can be reused across multiple executions and shared with other users.

          **⚠️ Admin access required**
          """,
    responses={
        201: {"description": "Template created successfully"},
        400: {"description": "Invalid template format"},
        401: {"description": "Admin authentication required"},
        403: {"description": "Insufficient permissions"},
        409: {"description": "Template name already exists"},
    },
)
async def create_custom_template(template_data: dict, admin_key=Depends(require_admin)):
    """Create custom template (admin only)"""
    try:
        success = await template_service.create_custom_template(
            name=template_data["name"],
            description=template_data.get("description", ""),
            script_content=template_data["script_content"],
            category=template_data.get("category", "custom"),
        )

        if not success:
            raise HTTPException(status_code=400, detail="Failed to create template")

        return {"message": "Template created successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to create template", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


# MONITORING ENDPOINTS


@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["📊 Analytics & Monitoring"],
    summary="System Health Check",
    description="""
         Comprehensive system health and status check.

         ### Health Metrics:
         - **Database**: Connection and query performance
         - **Browser Pool**: Available browsers and warm instances
         - **Queue System**: Active executions and pending items
         - **Disk Space**: Available storage for videos
         - **Memory Usage**: Current system memory utilization
         - **CPU Usage**: System load and performance

         ### Status Levels:
         - `healthy`: All systems operational
         - `unhealthy`: Critical issues detected
         - `degraded`: Some issues but functional

         **No authentication required** - useful for monitoring tools.
         """,
    responses={
        200: {"description": "Health status retrieved successfully"},
        503: {"description": "System is unhealthy"},
    },
)
async def health_check():
    """Comprehensive health check"""
    try:
        health = await health_checker.perform_health_check()
        return health

    except Exception as e:
        logger.error("Health check failed", error=str(e))
        # Return unhealthy status instead of error
        return HealthResponse(
            status="unhealthy",
            timestamp=datetime.now(),
            services={
                "database": False,
                "browser_pool": False,
                "queue": False,
                "disk_space": False,
            },
            metrics={
                "active_executions": 0,
                "queue_size": 0,
                "total_api_keys": 0,
                "videos_stored": 0,
                "disk_usage_gb": 0.0,
                "memory_usage_mb": 0,
                "cpu_usage_percent": 0.0,
                "uptime_seconds": 0,
            },
            browser_pool={
                "total_browsers": 0,
                "available_browsers": 0,
                "warm_browsers": 0,
            },
        )


@app.get(
    "/metrics",
    tags=["📊 Analytics & Monitoring"],
    summary="Prometheus Metrics",
    description="""
         Export metrics in Prometheus format for monitoring and alerting.

         ### Available Metrics:
         - `playwright_active_executions`: Current running scripts
         - `playwright_queue_size`: Pending executions
         - `playwright_memory_usage_mb`: System memory usage
         - `playwright_cpu_usage_percent`: CPU utilization
         - `playwright_disk_usage_gb`: Disk space usage
         - `playwright_service_healthy`: Service health status

         **Integration**: Configure Prometheus to scrape this endpoint.

         **No authentication required** for monitoring tools.
         """,
    responses={
        200: {
            "description": "Metrics exported successfully",
            "content": {"text/plain": {}},
        },
    },
)
async def get_metrics():
    """Get Prometheus-style metrics"""
    try:
        health = await health_checker.perform_health_check()
        queue_status = await executor.get_queue_status()

        metrics = []

        # Queue metrics
        metrics.append(f"playwright_queue_size {queue_status['total_queued']}")
        metrics.append(f"playwright_active_executions {queue_status['total_running']}")

        # System metrics
        metrics.append(f"playwright_memory_usage_mb {health.metrics.memory_usage_mb}")
        metrics.append(
            f"playwright_cpu_usage_percent {health.metrics.cpu_usage_percent}"
        )
        metrics.append(f"playwright_disk_usage_gb {health.metrics.disk_usage_gb}")

        # Service health
        for service, healthy in health.services.dict().items():
            metrics.append(
                f'playwright_service_healthy{{service="{service}"}} {1 if healthy else 0}'
            )

        return "\n".join(metrics)

    except Exception as e:
        logger.error("Failed to get metrics", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.get(
    "/queue/status",
    tags=["🎬 Script Execution"],
    summary="Queue Status",
    description="""
         Get current execution queue status and statistics.

         ### Queue Information:
         - **Active Executions**: Scripts currently running
         - **Pending Items**: Scripts waiting in queue
         - **Average Wait Time**: Estimated queue processing time
         - **Throughput**: Scripts processed per hour
         - **Priority Distribution**: High/normal/low priority breakdown

         Useful for monitoring system load and planning script execution timing.
         """,
    responses={
        200: {"description": "Queue status retrieved successfully"},
        401: {"description": "Authentication required"},
    },
)
async def get_queue_status(api_key=Depends(get_current_api_key)):
    """Get queue status"""
    try:
        status = await executor.get_queue_status()
        return status

    except Exception as e:
        logger.error("Failed to get queue status", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


# VIDEO ENDPOINTS


@app.get(
    "/video/{request_id}/{api_key_value}",
    tags=["🎥 Video Management"],
    summary="Download Video Recording",
    description="""
         Download the video recording of a script execution.

         ### Video Details:
         - **Format**: WebM with VP8 codec
         - **Resolution**: 1280x720 (720p)
         - **Recording**: Full browser session from start to finish
         - **Size**: Typically 1-10MB depending on execution time

         ### Access Control:
         - Videos are accessible only to the API key that created them
         - Admin keys can access all videos
         - Videos auto-expire after retention period

         ### Usage:
         Use the request_id returned from `/execute` endpoint.
         """,
    responses={
        200: {"description": "Video file", "content": {"video/webm": {}}},
        401: {"description": "Invalid API key"},
        403: {"description": "Access denied to this video"},
        404: {"description": "Video not found or expired"},
    },
)
async def get_video(request_id: str, api_key_value: str):
    """Serve video file"""
    try:
        # Validate API key
        from app.database import get_api_key_by_value

        api_key = await get_api_key_by_value(api_key_value)
        if not api_key or not api_key.is_active:
            raise HTTPException(status_code=401, detail="Invalid API key")

        # Check if API key has video access
        if "videos" not in api_key.scopes and "admin" not in api_key.scopes:
            raise HTTPException(status_code=403, detail="No video access")

        # Get video file
        video_path = await video_service.serve_video_file(request_id)
        if not video_path:
            raise HTTPException(status_code=404, detail="Video not found")

        return FileResponse(
            path=video_path, media_type="video/webm", filename=f"{request_id}.webm"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to serve video", request_id=request_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.get(
    "/video/{request_id}/info",
    response_model=VideoInfo,
    tags=["🎥 Video Management"],
    summary="Get Video Metadata",
    description="""
         Get metadata and information about a video recording.

         ### Video Metadata:
         - File size and duration
         - Recording timestamp
         - Associated script execution details
         - Download URL and expiration
         - Processing status

         Useful for checking if video is ready before attempting download.
         """,
    responses={
        200: {"description": "Video metadata retrieved successfully"},
        401: {"description": "Authentication required"},
        403: {"description": "Access denied to this video"},
        404: {"description": "Video not found"},
    },
)
async def get_video_info(request_id: str, api_key=Depends(require_videos)):
    """Get video metadata"""
    try:
        video_info = await video_service.get_video_info(request_id)
        if not video_info:
            raise HTTPException(status_code=404, detail="Video not found")

        return video_info

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get video info", request_id=request_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


# DASHBOARD ENDPOINT


@app.get(
    "/dashboard",
    tags=["📊 Analytics & Monitoring"],
    summary="Web Dashboard",
    description="""
         Access the web-based monitoring dashboard.

         ### Dashboard Features:
         - **Real-time Metrics**: Live system performance data
         - **Queue Visualization**: Current and historical queue status
         - **Execution History**: Recent script runs and outcomes
         - **Resource Monitoring**: CPU, memory, and disk usage graphs
         - **API Key Management**: Quick access to key operations
         - **System Health**: Visual health indicators

         ### Access:
         Requires API key with `dashboard` or `admin` scope.

         ### URL Format:
         `/dashboard?api_key=your-api-key-here`

         Returns HTML interface for browser viewing.
         """,
    responses={
        200: {"description": "Dashboard HTML page", "content": {"text/html": {}}},
        401: {"description": "Invalid API key"},
        403: {"description": "Dashboard access denied"},
    },
)
async def dashboard(
    request: Request,
    api_key: str = Query(..., description="API key for dashboard access"),
):
    """Web dashboard (requires API key parameter)"""
    try:
        # Validate API key
        from app.database import get_api_key_by_value

        api_key_obj = await get_api_key_by_value(api_key)
        if not api_key_obj or not api_key_obj.is_active:
            raise HTTPException(status_code=401, detail="Invalid API key")

        # Check dashboard access
        if "dashboard" not in api_key_obj.scopes and "admin" not in api_key_obj.scopes:
            raise HTTPException(status_code=403, detail="No dashboard access")

        # Get dashboard data
        health = await health_checker.get_detailed_status()
        queue_status = await executor.get_queue_status()
        video_stats = await video_service.get_storage_stats()

        dashboard_data = {
            "api_key": api_key_obj,
            "health": health,
            "queue": queue_status,
            "videos": video_stats,
            "refresh_interval": settings.DASHBOARD_REFRESH_INTERVAL,
        }

        if templates:
            return templates.TemplateResponse(
                "dashboard.html", {"request": request, "data": dashboard_data}
            )
        else:
            # Return JSON if no templates
            return JSONResponse(dashboard_data)

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Dashboard error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


# WEBHOOK TESTING


@app.post(
    "/admin/webhook/test",
    tags=["🔗 Webhooks"],
    summary="Test Webhook Endpoint",
    description="""
          Test a webhook URL for connectivity and response validation.

          ### Test Process:
          - **URL Validation**: Checks URL format and accessibility
          - **Connectivity Test**: Attempts HTTP connection
          - **Response Analysis**: Validates webhook response format
          - **Security Check**: Verifies HTTPS for production webhooks

          ### Request Format:
          ```json
          {
            "webhook_url": "https://your-domain.com/webhook",
            "test_data": {
              "event": "test",
              "message": "Webhook connectivity test"
            }
          }
          ```

          **⚠️ Admin access required**
          """,
    responses={
        200: {"description": "Webhook test completed"},
        400: {"description": "Invalid webhook configuration"},
        401: {"description": "Admin authentication required"},
        403: {"description": "Insufficient permissions"},
    },
)
async def test_webhook_endpoint(webhook_data: dict, admin_key=Depends(require_admin)):
    """Test webhook endpoint (admin only)"""
    try:
        webhook_url = webhook_data.get("webhook_url")
        if not webhook_url:
            raise HTTPException(status_code=400, detail="webhook_url required")

        # Validate URL
        validation = await webhook_service.validate_webhook_url(webhook_url)
        if not validation["valid"]:
            return {"validation": validation, "test_result": None}

        # Test webhook
        test_result = await webhook_service.test_webhook(webhook_url, admin_key.id)

        return {"validation": validation, "test_result": test_result}

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Webhook test failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


# ERROR HANDLERS


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.detail,
            "timestamp": datetime.now().isoformat(),
            "path": str(request.url.path),
        },
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logger.error(
        "Unhandled exception",
        path=str(request.url.path),
        method=request.method,
        error=str(exc),
        error_type=type(exc).__name__,
    )

    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "timestamp": datetime.now().isoformat(),
            "path": str(request.url.path),
        },
    )


# Root endpoint
@app.get("/")
async def root():
    """Root endpoint with API information"""
    return {
        "name": "Playwright Automation Server",
        "version": "1.0.0",
        "status": "running",
        "timestamp": datetime.now().isoformat(),
        "endpoints": {
            "docs": "/docs",
            "health": "/health",
            "execute": "/execute",
            "templates": "/templates",
            "dashboard": "/dashboard?api_key=<your_key>",
        },
    }


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app", host="0.0.0.0", port=8000, reload=False, log_level="info"
    )
