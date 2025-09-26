import sys
import json
from datetime import datetime
from typing import Any, Dict
import structlog
from structlog.stdlib import LoggerFactory


def add_timestamp(logger, method_name, event_dict):
    """Add timestamp to log entries"""
    event_dict["timestamp"] = datetime.utcnow().isoformat() + "Z"
    return event_dict


def add_logger_name(logger, method_name, event_dict):
    """Add logger name to log entries"""
    event_dict["logger"] = logger.name
    return event_dict


def serialize_datetime(obj):
    """JSON serializer for datetime objects"""
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def json_serializer(obj: Dict[str, Any], **kwargs) -> str:
    """Custom JSON serializer"""
    return json.dumps(obj, default=serialize_datetime, ensure_ascii=False)


def setup_logging():
    """Setup structured logging"""
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            add_timestamp,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer(serializer=json_serializer)
        ],
        context_class=dict,
        logger_factory=LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )


class RequestLogger:
    """Custom request logger for FastAPI"""

    def __init__(self):
        self.logger = structlog.get_logger("request")

    async def log_request(self, request, call_next):
        """Log HTTP requests"""
        start_time = datetime.utcnow()

        # Log request start
        self.logger.info(
            "Request started",
            method=request.method,
            url=str(request.url),
            client_ip=self._get_client_ip(request),
            user_agent=request.headers.get("user-agent", "unknown")
        )

        try:
            response = await call_next(request)
            end_time = datetime.utcnow()
            duration = (end_time - start_time).total_seconds()

            # Log request completion
            self.logger.info(
                "Request completed",
                method=request.method,
                url=str(request.url),
                status_code=response.status_code,
                duration_seconds=duration,
                client_ip=self._get_client_ip(request)
            )

            return response

        except Exception as e:
            end_time = datetime.utcnow()
            duration = (end_time - start_time).total_seconds()

            # Log request error
            self.logger.error(
                "Request failed",
                method=request.method,
                url=str(request.url),
                duration_seconds=duration,
                client_ip=self._get_client_ip(request),
                error=str(e),
                error_type=type(e).__name__
            )

            raise

    def _get_client_ip(self, request) -> str:
        """Extract client IP from request"""
        x_forwarded_for = request.headers.get("X-Forwarded-For")
        if x_forwarded_for:
            return x_forwarded_for.split(",")[0].strip()

        x_real_ip = request.headers.get("X-Real-IP")
        if x_real_ip:
            return x_real_ip

        return request.client.host if request.client else "unknown"


class ExecutionLogger:
    """Logger for script executions"""

    def __init__(self):
        self.logger = structlog.get_logger("executor")

    def log_execution_start(self, request_id: str, api_key_id: int, script_hash: str,
                           queue_position: int, priority: int, tags: list):
        """Log execution start"""
        self.logger.info(
            "Script execution started",
            event="script_execution_start",
            request_id=request_id,
            api_key_id=api_key_id,
            script_hash=script_hash[:16] + "...",
            queue_position=queue_position,
            priority=priority,
            tags=tags
        )

    def log_execution_complete(self, request_id: str, success: bool, execution_time: float,
                              error: str = None, result_size: int = 0):
        """Log execution completion"""
        self.logger.info(
            "Script execution completed",
            event="script_execution_complete",
            request_id=request_id,
            success=success,
            execution_time=execution_time,
            error=error,
            result_size_bytes=result_size
        )

    def log_queue_event(self, event: str, queue_size: int, active_executions: int, **kwargs):
        """Log queue events"""
        self.logger.info(
            f"Queue {event}",
            event=f"queue_{event}",
            queue_size=queue_size,
            active_executions=active_executions,
            **kwargs
        )

    def log_browser_event(self, event: str, browser_id: str = None, **kwargs):
        """Log browser pool events"""
        self.logger.info(
            f"Browser {event}",
            event=f"browser_{event}",
            browser_id=browser_id,
            **kwargs
        )

    def log_video_event(self, event: str, request_id: str, video_path: str = None,
                       video_size_mb: float = None, **kwargs):
        """Log video recording events"""
        self.logger.info(
            f"Video {event}",
            event=f"video_{event}",
            request_id=request_id,
            video_path=video_path,
            video_size_mb=video_size_mb,
            **kwargs
        )


class SystemLogger:
    """Logger for system events"""

    def __init__(self):
        self.logger = structlog.get_logger("system")

    def log_startup(self, component: str, **kwargs):
        """Log component startup"""
        self.logger.info(
            f"{component} started",
            event="component_startup",
            component=component,
            **kwargs
        )

    def log_shutdown(self, component: str, **kwargs):
        """Log component shutdown"""
        self.logger.info(
            f"{component} stopped",
            event="component_shutdown",
            component=component,
            **kwargs
        )

    def log_health_check(self, component: str, healthy: bool, **kwargs):
        """Log health check results"""
        level = "info" if healthy else "warning"
        getattr(self.logger, level)(
            f"{component} health check",
            event="health_check",
            component=component,
            healthy=healthy,
            **kwargs
        )

    def log_cleanup(self, cleaned_items: int, cleaned_size_mb: float = None, **kwargs):
        """Log cleanup operations"""
        self.logger.info(
            "Cleanup completed",
            event="cleanup_complete",
            cleaned_items=cleaned_items,
            cleaned_size_mb=cleaned_size_mb,
            **kwargs
        )

    def log_resource_warning(self, resource: str, current_value: float, threshold: float, **kwargs):
        """Log resource usage warnings"""
        self.logger.warning(
            f"High {resource} usage",
            event="resource_warning",
            resource=resource,
            current_value=current_value,
            threshold=threshold,
            **kwargs
        )


# Global logger instances
request_logger = RequestLogger()
execution_logger = ExecutionLogger()
system_logger = SystemLogger()


# Initialize logging on import
setup_logging()