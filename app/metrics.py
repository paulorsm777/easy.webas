import time
from typing import Dict, Any, List
from collections import defaultdict, deque
from prometheus_client import (
    Counter,
    Histogram,
    Gauge,
    CollectorRegistry,
    generate_latest,
)
import asyncio

from .logger import Logger

logger = Logger("metrics")


class MetricsCollector:
    def __init__(self):
        # Create custom registry
        self.registry = CollectorRegistry()

        # Execution metrics
        self.executions_total = Counter(
            "playwright_executions_total",
            "Total number of script executions",
            ["status", "api_key_id"],
            registry=self.registry,
        )

        self.execution_duration = Histogram(
            "playwright_execution_duration_seconds",
            "Time spent executing scripts",
            ["api_key_id"],
            registry=self.registry,
        )

        self.queue_wait_duration = Histogram(
            "playwright_queue_wait_duration_seconds",
            "Time spent waiting in queue",
            ["priority"],
            registry=self.registry,
        )

        # Queue metrics
        self.queue_size = Gauge(
            "playwright_queue_size",
            "Current number of items in execution queue",
            registry=self.registry,
        )

        self.active_executions = Gauge(
            "playwright_active_executions",
            "Current number of active executions",
            registry=self.registry,
        )

        # Browser pool metrics
        self.browser_pool_total = Gauge(
            "playwright_browser_pool_total",
            "Total number of browsers in pool",
            registry=self.registry,
        )

        self.browser_pool_available = Gauge(
            "playwright_browser_pool_available",
            "Number of available browsers in pool",
            registry=self.registry,
        )

        # API key metrics
        self.api_key_requests = Counter(
            "playwright_api_key_requests_total",
            "Total requests per API key",
            ["key_id", "endpoint"],
            registry=self.registry,
        )

        self.rate_limit_hits = Counter(
            "playwright_rate_limit_hits_total",
            "Number of rate limit hits",
            ["key_id", "limit_type"],
            registry=self.registry,
        )

        # Video metrics
        self.video_storage_bytes = Gauge(
            "playwright_video_storage_bytes",
            "Total bytes used for video storage",
            registry=self.registry,
        )

        self.videos_created = Counter(
            "playwright_videos_created_total",
            "Total number of videos created",
            registry=self.registry,
        )

        self.videos_deleted = Counter(
            "playwright_videos_deleted_total",
            "Total number of videos deleted",
            registry=self.registry,
        )

        # System metrics
        self.memory_usage_bytes = Gauge(
            "playwright_memory_usage_bytes",
            "Current memory usage in bytes",
            registry=self.registry,
        )

        self.cpu_usage_percent = Gauge(
            "playwright_cpu_usage_percent",
            "Current CPU usage percentage",
            registry=self.registry,
        )

        # Error metrics
        self.errors_total = Counter(
            "playwright_errors_total",
            "Total number of errors",
            ["error_type", "component"],
            registry=self.registry,
        )

        # Webhook metrics
        self.webhook_attempts = Counter(
            "playwright_webhook_attempts_total",
            "Total webhook delivery attempts",
            ["status"],
            registry=self.registry,
        )

        # Custom metrics for analytics
        self._request_times = deque(maxlen=1000)  # Keep last 1000 requests
        self._hourly_stats = defaultdict(
            lambda: {"requests": 0, "successes": 0, "failures": 0, "total_duration": 0}
        )

        # Start metrics update task
        self._update_task = None

    async def start(self):
        """Start metrics collection"""
        logger.info("metrics_collector_starting")

        # Start background update task
        self._update_task = asyncio.create_task(self._update_metrics_loop())

        logger.info("metrics_collector_started")

    async def stop(self):
        """Stop metrics collection"""
        if self._update_task:
            self._update_task.cancel()
            try:
                await self._update_task
            except asyncio.CancelledError:
                pass

        logger.info("metrics_collector_stopped")

    def record_execution_start(self, api_key_id: int, priority: int):
        """Record execution start"""
        current_time = time.time()
        self._request_times.append(current_time)

    def record_execution_complete(
        self,
        api_key_id: int,
        status: str,
        execution_time: float,
        queue_wait_time: float,
        priority: int = 1,
    ):
        """Record execution completion"""
        # Update counters
        self.executions_total.labels(status=status, api_key_id=str(api_key_id)).inc()

        # Update histograms
        self.execution_duration.labels(api_key_id=str(api_key_id)).observe(
            execution_time
        )

        self.queue_wait_duration.labels(priority=str(priority)).observe(queue_wait_time)

        # Update hourly stats
        hour_key = time.strftime("%Y-%m-%d %H:00:00")
        self._hourly_stats[hour_key]["requests"] += 1
        self._hourly_stats[hour_key]["total_duration"] += execution_time

        if status == "completed":
            self._hourly_stats[hour_key]["successes"] += 1
        else:
            self._hourly_stats[hour_key]["failures"] += 1

    def record_api_request(self, api_key_id: int, endpoint: str):
        """Record API request"""
        self.api_key_requests.labels(key_id=str(api_key_id), endpoint=endpoint).inc()

    def record_rate_limit_hit(self, api_key_id: int, limit_type: str):
        """Record rate limit hit"""
        self.rate_limit_hits.labels(key_id=str(api_key_id), limit_type=limit_type).inc()

    def record_video_created(self, size_bytes: int):
        """Record video creation"""
        self.videos_created.inc()

    def record_video_deleted(self, size_bytes: int):
        """Record video deletion"""
        self.videos_deleted.inc()

    def record_error(self, error_type: str, component: str):
        """Record error occurrence"""
        self.errors_total.labels(error_type=error_type, component=component).inc()

    def record_webhook_attempt(self, status: str):
        """Record webhook delivery attempt"""
        self.webhook_attempts.labels(status=status).inc()

    async def _update_metrics_loop(self):
        """Background task to update gauge metrics"""
        while True:
            try:
                await self._update_system_metrics()
                await self._update_queue_metrics()
                await self._update_browser_metrics()
                await self._update_storage_metrics()

                await asyncio.sleep(10)  # Update every 10 seconds

            except Exception as e:
                logger.error("metrics_update_failed", error=str(e))
                await asyncio.sleep(30)  # Wait longer on error

    async def _update_system_metrics(self):
        """Update system-level metrics"""
        try:
            import psutil

            process = psutil.Process()

            # Memory usage
            memory_bytes = process.memory_info().rss
            self.memory_usage_bytes.set(memory_bytes)

            # CPU usage
            cpu_percent = process.cpu_percent()
            self.cpu_usage_percent.set(cpu_percent)

        except Exception as e:
            logger.error("system_metrics_update_failed", error=str(e))

    async def _update_queue_metrics(self):
        """Update queue-related metrics"""
        try:
            from .executor import executor

            # Queue size
            queue_size = len(executor.queue)
            self.queue_size.set(queue_size)

            # Active executions
            active_count = len(executor.active_executions)
            self.active_executions.set(active_count)

        except Exception as e:
            logger.error("queue_metrics_update_failed", error=str(e))

    async def _update_browser_metrics(self):
        """Update browser pool metrics"""
        try:
            from .executor import executor

            # Total browsers
            total_browsers = len(executor.browser_pool.browsers)
            self.browser_pool_total.set(total_browsers)

            # Available browsers
            available_browsers = executor.browser_pool.available_browsers.qsize()
            self.browser_pool_available.set(available_browsers)

        except Exception as e:
            logger.error("browser_metrics_update_failed", error=str(e))

    async def _update_storage_metrics(self):
        """Update storage-related metrics"""
        try:
            from .video_service import video_manager

            # Get storage stats
            stats = await video_manager.get_storage_stats()
            storage_bytes = stats["total_size_mb"] * 1024 * 1024

            self.video_storage_bytes.set(storage_bytes)

        except Exception as e:
            logger.error("storage_metrics_update_failed", error=str(e))

    def get_prometheus_metrics(self) -> bytes:
        """Get metrics in Prometheus format"""
        return generate_latest(self.registry)

    def get_analytics_data(self) -> Dict[str, Any]:
        """Get analytics data for dashboard"""
        # Request rate (last minute)
        current_time = time.time()
        minute_ago = current_time - 60
        recent_requests = sum(
            1 for req_time in self._request_times if req_time > minute_ago
        )

        # Hourly stats (last 24 hours)
        hourly_data = []
        for hour in sorted(self._hourly_stats.keys())[-24:]:
            stats = self._hourly_stats[hour]
            hourly_data.append(
                {
                    "hour": hour,
                    "requests": stats["requests"],
                    "successes": stats["successes"],
                    "failures": stats["failures"],
                    "avg_duration": stats["total_duration"] / max(stats["requests"], 1),
                }
            )

        return {
            "current_metrics": {
                "requests_per_minute": recent_requests,
                "queue_size": self.queue_size._value._value,
                "active_executions": self.active_executions._value._value,
                "available_browsers": self.browser_pool_available._value._value,
                "memory_usage_mb": round(
                    self.memory_usage_bytes._value._value / 1024 / 1024, 2
                ),
                "cpu_usage_percent": round(self.cpu_usage_percent._value._value, 1),
            },
            "hourly_stats": hourly_data,
            "totals": {
                "total_requests": len(self._request_times),
                "total_hours_tracked": len(self._hourly_stats),
            },
        }

    def get_api_key_stats(self, api_key_id: int) -> Dict[str, Any]:
        """Get statistics for a specific API key"""
        try:
            # Get metrics for this API key
            execution_samples = []
            for sample in self.execution_duration.labels(
                api_key_id=str(api_key_id)
            )._value.get_sample():
                execution_samples.append(sample)

            request_count = 0
            for sample in self.api_key_requests.labels(
                key_id=str(api_key_id), endpoint="execute"
            )._value.get():
                request_count += sample.value

            return {
                "total_requests": request_count,
                "execution_samples": len(execution_samples),
                "avg_execution_time": sum(s.value for s in execution_samples)
                / max(len(execution_samples), 1),
            }
        except Exception as e:
            logger.error("api_key_stats_failed", api_key_id=api_key_id, error=str(e))
            return {
                "total_requests": 0,
                "execution_samples": 0,
                "avg_execution_time": 0,
            }

    def reset_hourly_stats(self, hours_to_keep: int = 168):  # Keep 1 week
        """Clean up old hourly stats"""
        current_time = time.time()
        cutoff_time = current_time - (hours_to_keep * 3600)

        keys_to_remove = []
        for hour_key in self._hourly_stats.keys():
            try:
                hour_timestamp = time.mktime(
                    time.strptime(hour_key, "%Y-%m-%d %H:%M:%S")
                )
                if hour_timestamp < cutoff_time:
                    keys_to_remove.append(hour_key)
            except:
                keys_to_remove.append(hour_key)  # Remove malformed keys

        for key in keys_to_remove:
            del self._hourly_stats[key]

        if keys_to_remove:
            logger.info("hourly_stats_cleaned", removed_count=len(keys_to_remove))


# Global metrics collector
metrics_collector = MetricsCollector()
