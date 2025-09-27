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
    title="Playwright Automation Server",
    description="Advanced Playwright script execution with queue management, video recording, and monitoring",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
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


@app.post("/execute", response_model=ScriptResponse)
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


@app.post("/validate")
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


@app.get("/templates", response_model=List[ScriptTemplate])
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


@app.get("/templates/{template_name}", response_model=ScriptTemplate)
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


@app.get("/templates/categories")
async def get_template_categories(api_key=Depends(get_current_api_key)):
    """Get template categories with counts"""
    try:
        categories = await template_service.get_template_categories()
        return {"categories": categories}

    except Exception as e:
        logger.error("Failed to get template categories", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


# ADMIN ENDPOINTS


@app.post("/admin/api-keys", response_model=ApiKeyResponse)
async def create_new_api_key(key_data: ApiKeyCreate, admin_key=Depends(require_admin)):
    """Create a new API key (admin only)"""
    try:
        api_key = await create_api_key(key_data)
        logger.info("API key created", key_id=api_key.id, key_name=api_key.name)
        return api_key

    except Exception as e:
        logger.error("Failed to create API key", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/admin/api-keys", response_model=List[ApiKeyResponse])
async def list_all_api_keys(admin_key=Depends(require_admin)):
    """List all API keys (admin only)"""
    try:
        return await list_api_keys()

    except Exception as e:
        logger.error("Failed to list API keys", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/admin/api-keys/{key_id}", response_model=ApiKeyResponse)
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


@app.delete("/admin/api-keys/{key_id}")
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


@app.get("/admin/analytics")
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


@app.delete("/admin/videos/cleanup")
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


@app.post("/admin/templates")
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


@app.get("/health", response_model=HealthResponse)
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


@app.get("/metrics")
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


@app.get("/queue/status")
async def get_queue_status(api_key=Depends(get_current_api_key)):
    """Get queue status"""
    try:
        status = await executor.get_queue_status()
        return status

    except Exception as e:
        logger.error("Failed to get queue status", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


# VIDEO ENDPOINTS


@app.get("/video/{request_id}/{api_key_value}")
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


@app.get("/video/{request_id}/info", response_model=VideoInfo)
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


@app.get("/dashboard")
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


@app.post("/admin/webhook/test")
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
