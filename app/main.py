import asyncio
import uuid
from datetime import datetime
from typing import List, Optional, Dict, Any
from pathlib import Path

from fastapi import FastAPI, HTTPException, Depends, Request, Query, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer
import uvicorn

from .config import settings
from .models import (
    ScriptRequest,
    ScriptResponse,
    ApiKeyCreate,
    ApiKeyResponse,
    ApiKeyUpdate,
    HealthResponse,
    QueueStatus,
    ValidationResult,
    ScriptTemplate,
    VideoInfo,
)
from .database import db, init_database, ensure_admin_key
from .auth import (
    auth_manager,
    require_execute_scope,
    require_admin_scope,
    require_dashboard_scope,
    require_videos_scope,
)
from .executor import executor
from .validation import validator
from .video_service import video_manager, cleanup_scheduler
from .templates import template_manager
from .webhooks import webhook_manager
from .health import health_checker
from .metrics import metrics_collector
from .dashboard import dashboard_manager
from .logger import main_logger


# Create FastAPI app
app = FastAPI(
    title="Playwright Automation Server",
    description="A powerful server for executing Playwright scripts with queue management, video recording, and comprehensive monitoring",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

security = HTTPBearer()


@app.on_event("startup")
async def startup_event():
    """Initialize all services on startup"""
    main_logger.info("server_starting")

    try:
        # Initialize database
        await init_database()
        await ensure_admin_key()
        main_logger.info("database_initialized")

        # Initialize template manager
        await template_manager.initialize()
        main_logger.info("templates_initialized")

        # Initialize executor
        await executor.initialize()
        main_logger.info("executor_initialized")

        # Start webhook manager
        await webhook_manager.start()
        main_logger.info("webhook_manager_started")

        # Start metrics collector
        await metrics_collector.start()
        main_logger.info("metrics_collector_started")

        # Start video cleanup scheduler
        await cleanup_scheduler.start()
        main_logger.info("cleanup_scheduler_started")

        main_logger.info("server_startup_complete")

    except Exception as e:
        main_logger.error("startup_failed", error=str(e))
        raise


@app.on_event("shutdown")
async def shutdown_event():
    """Clean shutdown of all services"""
    main_logger.info("server_shutting_down")

    try:
        # Stop services in reverse order
        await cleanup_scheduler.stop()
        await metrics_collector.stop()
        await webhook_manager.stop()
        await executor.close()

        main_logger.info("server_shutdown_complete")

    except Exception as e:
        main_logger.error("shutdown_failed", error=str(e))


# ==================== EXECUTION ENDPOINTS ====================


@app.post("/execute", response_model=ScriptResponse)
async def execute_script(
    request: ScriptRequest,
    background_tasks: BackgroundTasks,
    api_key: ApiKeyResponse = Depends(require_execute_scope),
):
    """Execute a Playwright script"""
    request_id = str(uuid.uuid4())

    main_logger.info(
        "script_execution_requested",
        request_id=request_id,
        api_key_id=api_key.id,
        script_length=len(request.script),
        priority=request.priority,
    )

    try:
        # Record metrics
        metrics_collector.record_execution_start(api_key.id, request.priority)
        metrics_collector.record_api_request(api_key.id, "execute")

        # Add to execution queue
        queue_request_id = await executor.add_to_queue(request, api_key.id)

        # Get initial queue position
        queue_status = await executor.get_queue_status()
        queue_position = next(
            (
                i
                for i, item in enumerate(queue_status["queue_items"])
                if item["request_id"] == request_id
            ),
            0,
        )

        # Start background webhook task if needed
        if request.webhook_url:
            background_tasks.add_task(
                webhook_manager.send_execution_webhook,
                request_id,
                api_key.id,
                "queued",
                0,
                webhook_url=request.webhook_url,
            )

        return ScriptResponse(
            request_id=request_id,
            success=True,
            result="Script queued for execution",
            execution_time=0,
            queue_wait_time=0,
            queue_position=queue_position,
            priority=request.priority,
            video_url=f"http://localhost:8000/video/{request_id}/{api_key.key_value}",
        )

    except ValueError as e:
        # Validation error
        main_logger.warning(
            "script_validation_failed", request_id=request_id, error=str(e)
        )
        raise HTTPException(status_code=400, detail=str(e))

    except Exception as e:
        # Queue full or other error
        main_logger.error(
            "script_execution_failed", request_id=request_id, error=str(e)
        )
        raise HTTPException(status_code=503, detail=str(e))


@app.post("/validate", response_model=ValidationResult)
async def validate_script(
    request: ScriptRequest, api_key: ApiKeyResponse = Depends(require_execute_scope)
):
    """Validate a script without executing it"""
    main_logger.info(
        "script_validation_requested",
        api_key_id=api_key.id,
        script_length=len(request.script),
    )

    try:
        metrics_collector.record_api_request(api_key.id, "validate")

        validation_result = await validator.validate_script(request.script)

        main_logger.info(
            "script_validation_completed",
            api_key_id=api_key.id,
            is_valid=validation_result.is_valid,
            complexity=validation_result.estimated_complexity,
        )

        return validation_result

    except Exception as e:
        main_logger.error("script_validation_error", error=str(e))
        raise HTTPException(status_code=500, detail="Validation failed")


# ==================== TEMPLATE ENDPOINTS ====================


@app.get("/templates", response_model=List[ScriptTemplate])
async def get_templates(
    category: Optional[str] = Query(None, description="Filter by category"),
    api_key: ApiKeyResponse = Depends(require_execute_scope),
):
    """Get available script templates"""
    try:
        metrics_collector.record_api_request(api_key.id, "templates")

        if category:
            templates = await template_manager.get_templates_by_category(category)
        else:
            templates = await template_manager.get_all_templates()

        return templates

    except Exception as e:
        main_logger.error("templates_fetch_failed", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to fetch templates")


@app.get("/templates/{template_name}", response_model=ScriptTemplate)
async def get_template(
    template_name: str, api_key: ApiKeyResponse = Depends(require_execute_scope)
):
    """Get a specific template"""
    try:
        metrics_collector.record_api_request(api_key.id, "template_get")

        template = await template_manager.get_template_by_name(template_name)
        if not template:
            raise HTTPException(status_code=404, detail="Template not found")

        # Increment usage counter
        await template_manager.increment_template_usage(template_name)

        return template

    except HTTPException:
        raise
    except Exception as e:
        main_logger.error(
            "template_fetch_failed", template_name=template_name, error=str(e)
        )
        raise HTTPException(status_code=500, detail="Failed to fetch template")


@app.get("/templates/categories", response_model=List[str])
async def get_template_categories(
    api_key: ApiKeyResponse = Depends(require_execute_scope),
):
    """Get available template categories"""
    try:
        categories = await template_manager.get_template_categories()
        return categories
    except Exception as e:
        main_logger.error("categories_fetch_failed", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to fetch categories")


# ==================== ADMIN ENDPOINTS ====================


@app.post("/admin/api-keys", response_model=ApiKeyResponse)
async def create_api_key(
    key_data: ApiKeyCreate, admin_key: ApiKeyResponse = Depends(require_admin_scope)
):
    """Create a new API key"""
    try:
        api_key = await db.create_api_key(key_data)

        main_logger.info(
            "api_key_created",
            new_key_id=api_key.id,
            new_key_name=api_key.name,
            admin_key_id=admin_key.id,
        )

        return api_key

    except Exception as e:
        main_logger.error("api_key_creation_failed", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to create API key")


@app.get("/admin/api-keys", response_model=List[ApiKeyResponse])
async def list_api_keys(admin_key: ApiKeyResponse = Depends(require_admin_scope)):
    """List all API keys"""
    try:
        api_keys = await db.list_api_keys()
        return api_keys
    except Exception as e:
        main_logger.error("api_keys_list_failed", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to list API keys")


@app.put("/admin/api-keys/{key_id}", response_model=ApiKeyResponse)
async def update_api_key(
    key_id: int,
    update_data: ApiKeyUpdate,
    admin_key: ApiKeyResponse = Depends(require_admin_scope),
):
    """Update an API key"""
    try:
        updated_key = await db.update_api_key(key_id, update_data)
        if not updated_key:
            raise HTTPException(status_code=404, detail="API key not found")

        # Invalidate auth cache for this key
        auth_manager.invalidate_cache(updated_key.key_value)

        main_logger.info("api_key_updated", key_id=key_id, admin_key_id=admin_key.id)

        return updated_key

    except HTTPException:
        raise
    except Exception as e:
        main_logger.error("api_key_update_failed", key_id=key_id, error=str(e))
        raise HTTPException(status_code=500, detail="Failed to update API key")


@app.delete("/admin/api-keys/{key_id}")
async def delete_api_key(
    key_id: int, admin_key: ApiKeyResponse = Depends(require_admin_scope)
):
    """Delete an API key"""
    try:
        # Get the key before deletion to invalidate cache
        target_key = await db.get_api_key_by_id(key_id)

        deleted = await db.delete_api_key(key_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="API key not found")

        # Invalidate auth cache
        if target_key:
            auth_manager.invalidate_cache(target_key.key_value)

        main_logger.info("api_key_deleted", key_id=key_id, admin_key_id=admin_key.id)

        return {"message": "API key deleted successfully"}

    except HTTPException:
        raise
    except Exception as e:
        main_logger.error("api_key_deletion_failed", key_id=key_id, error=str(e))
        raise HTTPException(status_code=500, detail="Failed to delete API key")


@app.get("/admin/analytics")
async def get_analytics(admin_key: ApiKeyResponse = Depends(require_admin_scope)):
    """Get system analytics"""
    try:
        analytics_data = metrics_collector.get_analytics_data()
        return analytics_data
    except Exception as e:
        main_logger.error("analytics_fetch_failed", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to fetch analytics")


# ==================== MONITORING ENDPOINTS ====================


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Comprehensive health check"""
    try:
        health_status = await health_checker.get_health_status()
        return health_status
    except Exception as e:
        main_logger.error("health_check_failed", error=str(e))
        raise HTTPException(status_code=500, detail="Health check failed")


@app.get("/health/quick")
async def quick_health_check():
    """Quick health check for load balancers"""
    try:
        status = await health_checker.get_quick_status()
        return status
    except Exception as e:
        return JSONResponse(
            status_code=503, content={"status": "unhealthy", "error": str(e)}
        )


@app.get("/metrics")
async def get_metrics():
    """Prometheus metrics endpoint"""
    try:
        metrics_data = metrics_collector.get_prometheus_metrics()
        return Response(
            content=metrics_data, media_type="text/plain; version=0.0.4; charset=utf-8"
        )
    except Exception as e:
        main_logger.error("metrics_fetch_failed", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to fetch metrics")


@app.get("/queue/status", response_model=Dict[str, Any])
async def get_queue_status(api_key: ApiKeyResponse = Depends(require_execute_scope)):
    """Get current queue status"""
    try:
        metrics_collector.record_api_request(api_key.id, "queue_status")
        queue_status = await executor.get_queue_status()
        return queue_status
    except Exception as e:
        main_logger.error("queue_status_failed", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to get queue status")


# ==================== DASHBOARD ENDPOINTS ====================


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request, api_key: ApiKeyResponse = Depends(require_dashboard_scope)
):
    """Main dashboard page"""
    return await dashboard_manager.render_dashboard(request, api_key)


@app.get("/dashboard/data")
async def dashboard_data(api_key: ApiKeyResponse = Depends(require_dashboard_scope)):
    """Get dashboard data as JSON"""
    try:
        data = await dashboard_manager.get_dashboard_data(api_key)
        return data
    except Exception as e:
        main_logger.error("dashboard_data_failed", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to fetch dashboard data")


# ==================== VIDEO ENDPOINTS ====================


@app.get("/video/{request_id}/{api_key_value}")
async def get_video(request_id: str, api_key_value: str):
    """Get video file with access control"""
    try:
        # Validate API key
        api_key = await auth_manager.get_api_key(api_key_value)
        if not api_key or not api_key.is_active:
            raise HTTPException(status_code=401, detail="Invalid API key")

        # Check if user can access this video
        video_content = await video_manager.serve_video(request_id, api_key.id)
        if not video_content:
            raise HTTPException(
                status_code=404, detail="Video not found or access denied"
            )

        content, media_type = video_content

        return StreamingResponse(
            io.BytesIO(content),
            media_type=media_type,
            headers={
                "Content-Disposition": f"inline; filename={request_id}.webm",
                "Cache-Control": "private, max-age=3600",
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        main_logger.error("video_serve_failed", request_id=request_id, error=str(e))
        raise HTTPException(status_code=500, detail="Failed to serve video")


@app.get("/video/{request_id}/info", response_model=VideoInfo)
async def get_video_info(
    request_id: str, api_key: ApiKeyResponse = Depends(require_videos_scope)
):
    """Get video metadata"""
    try:
        # Check access
        if not await video_manager.validate_video_access(request_id, api_key.id):
            raise HTTPException(status_code=403, detail="Access denied")

        video_info = await video_manager.get_video_info(request_id)
        if not video_info:
            raise HTTPException(status_code=404, detail="Video not found")

        return video_info

    except HTTPException:
        raise
    except Exception as e:
        main_logger.error("video_info_failed", request_id=request_id, error=str(e))
        raise HTTPException(status_code=500, detail="Failed to get video info")


@app.delete("/admin/videos/cleanup")
async def force_video_cleanup(admin_key: ApiKeyResponse = Depends(require_admin_scope)):
    """Force video cleanup"""
    try:
        result = await video_manager.cleanup_old_videos(force=True)

        main_logger.info(
            "video_cleanup_forced",
            admin_key_id=admin_key.id,
            deleted_files=result.get("deleted_files", 0),
        )

        return result

    except Exception as e:
        main_logger.error("video_cleanup_failed", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to cleanup videos")


# ==================== DIAGNOSTIC ENDPOINTS ====================


@app.get("/admin/diagnostics")
async def run_diagnostics(admin_key: ApiKeyResponse = Depends(require_admin_scope)):
    """Run comprehensive system diagnostics"""
    try:
        diagnostics = await health_checker.run_diagnostic()
        return diagnostics
    except Exception as e:
        main_logger.error("diagnostics_failed", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to run diagnostics")


# ==================== ERROR HANDLERS ====================


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Custom HTTP exception handler"""
    main_logger.warning(
        "http_exception",
        status_code=exc.status_code,
        detail=exc.detail,
        path=request.url.path,
    )

    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "timestamp": datetime.now().isoformat()},
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle unexpected exceptions"""
    main_logger.error("unhandled_exception", error=str(exc), path=request.url.path)

    return JSONResponse(
        status_code=500,
        content={
            "detail": "Internal server error",
            "timestamp": datetime.now().isoformat(),
        },
    )


# ==================== MAIN ====================

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app", host="0.0.0.0", port=8000, reload=False, log_level="info"
    )
