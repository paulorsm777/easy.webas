import structlog
import logging
import sys
from datetime import datetime
from typing import Any, Dict


def setup_logging():
    """Configure structured logging"""

    # Configure structlog
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Configure standard library logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=logging.INFO,
    )


class Logger:
    def __init__(self, name: str):
        self.logger = structlog.get_logger(name)

    def info(self, event: str, **kwargs):
        self.logger.info(event, **kwargs)

    def error(self, event: str, **kwargs):
        self.logger.error(event, **kwargs)

    def warning(self, event: str, **kwargs):
        self.logger.warning(event, **kwargs)

    def debug(self, event: str, **kwargs):
        self.logger.debug(event, **kwargs)

    def execution_start(
        self,
        request_id: str,
        api_key_id: int,
        script_hash: str,
        queue_position: int,
        priority: int,
        estimated_duration: int = None,
        tags: list = None,
    ):
        self.logger.info(
            "script_execution_start",
            request_id=request_id,
            api_key_id=api_key_id,
            script_hash=script_hash,
            queue_position=queue_position,
            priority=priority,
            estimated_duration=estimated_duration,
            tags=tags or [],
        )

    def execution_complete(
        self,
        request_id: str,
        success: bool,
        execution_time: float,
        memory_peak_mb: float = None,
        cpu_time_ms: int = None,
        video_size_mb: float = None,
        error: str = None,
    ):
        self.logger.info(
            "script_execution_complete",
            request_id=request_id,
            success=success,
            execution_time=execution_time,
            memory_peak_mb=memory_peak_mb,
            cpu_time_ms=cpu_time_ms,
            video_size_mb=video_size_mb,
            error=error,
        )

    def queue_event(
        self,
        event_type: str,
        queue_size: int,
        active_executions: int,
        request_id: str = None,
        priority: int = None,
    ):
        self.logger.info(
            f"queue_{event_type}",
            queue_size=queue_size,
            active_executions=active_executions,
            request_id=request_id,
            priority=priority,
        )

    def browser_event(
        self,
        event_type: str,
        browser_id: str = None,
        context_id: str = None,
        pool_size: int = None,
        available_browsers: int = None,
    ):
        self.logger.info(
            f"browser_{event_type}",
            browser_id=browser_id,
            context_id=context_id,
            pool_size=pool_size,
            available_browsers=available_browsers,
        )

    def api_request(
        self,
        method: str,
        endpoint: str,
        api_key_id: int,
        status_code: int,
        response_time_ms: float,
        request_id: str = None,
    ):
        self.logger.info(
            "api_request",
            method=method,
            endpoint=endpoint,
            api_key_id=api_key_id,
            status_code=status_code,
            response_time_ms=response_time_ms,
            request_id=request_id,
        )

    def security_event(
        self,
        event_type: str,
        api_key_id: int = None,
        ip_address: str = None,
        details: Dict[str, Any] = None,
    ):
        self.logger.warning(
            f"security_{event_type}",
            api_key_id=api_key_id,
            ip_address=ip_address,
            details=details or {},
        )

    def system_event(self, event_type: str, **kwargs):
        self.logger.info(f"system_{event_type}", **kwargs)


# Initialize logging
setup_logging()

# Global loggers for different components
main_logger = Logger("main")
executor_logger = Logger("executor")
auth_logger = Logger("auth")
video_logger = Logger("video")
dashboard_logger = Logger("dashboard")
cleanup_logger = Logger("cleanup")
webhook_logger = Logger("webhook")
