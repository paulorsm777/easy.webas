import asyncio
import time
import uuid
import psutil
import json
from datetime import datetime
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, field
from pathlib import Path
import tempfile
import subprocess

from playwright.async_api import async_playwright, Browser, BrowserContext, Page
import aiofiles

from .config import settings
from .database import db
from .models import (
    ScriptRequest,
    ScriptResponse,
    BrowserInfo,
    ResourceUsage,
    ScriptAnalysis,
)
from .logger import executor_logger
from .validation import validator


@dataclass
class QueueItem:
    request_id: str
    api_key_id: int
    script: str
    timeout: int
    priority: int
    tags: List[str]
    webhook_url: Optional[str]
    user_agent: Optional[str]
    created_at: float = field(default_factory=time.time)
    queue_position: int = 0


@dataclass
class ExecutionResult:
    success: bool
    result: Any = None
    error: str = None
    execution_time: float = 0
    memory_peak_mb: float = 0
    cpu_time_ms: int = 0
    video_path: str = None
    video_size_mb: float = 0
    browser_info: BrowserInfo = None
    resource_usage: ResourceUsage = None
    script_analysis: ScriptAnalysis = None


class BrowserPool:
    def __init__(self, pool_size: int = 10):
        self.pool_size = pool_size
        self.browsers: List[Browser] = []
        self.available_browsers: asyncio.Queue = asyncio.Queue()
        self.browser_contexts: Dict[str, BrowserContext] = {}
        self.playwright = None
        self._lock = asyncio.Lock()

    async def initialize(self):
        """Initialize browser pool"""
        executor_logger.info("browser_pool_initializing", pool_size=self.pool_size)

        self.playwright = await async_playwright().start()

        for i in range(self.pool_size):
            try:
                browser = await self.playwright.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-gpu",
                        "--disable-web-security",
                        "--disable-features=VizDisplayCompositor",
                        "--memory-pressure-off",
                    ],
                )
                self.browsers.append(browser)
                await self.available_browsers.put(browser)

                executor_logger.browser_event(
                    "created", browser_id=f"browser_{i}", pool_size=len(self.browsers)
                )

            except Exception as e:
                executor_logger.error(
                    "browser_creation_failed", browser_id=f"browser_{i}", error=str(e)
                )

        # Pre-warm browsers
        await self._warm_browsers()

        executor_logger.info(
            "browser_pool_initialized",
            total_browsers=len(self.browsers),
            available_browsers=self.available_browsers.qsize(),
        )

    async def _warm_browsers(self):
        """Pre-warm browsers with basic pages"""
        executor_logger.info("browser_pool_warming")

        for _ in range(min(settings.browser_warmup_pages, len(self.browsers))):
            try:
                browser = await self.get_browser()
                context = await browser.new_context(
                    viewport={
                        "width": settings.video_width,
                        "height": settings.video_height,
                    },
                    record_video_dir=None,  # No recording for warmup
                )
                page = await context.new_page()
                await page.goto("about:blank")
                await context.close()
                await self.return_browser(browser)
            except Exception as e:
                executor_logger.error("browser_warmup_failed", error=str(e))

    async def get_browser(self) -> Browser:
        """Get an available browser from the pool"""
        try:
            browser = await asyncio.wait_for(self.available_browsers.get(), timeout=30)
            executor_logger.browser_event(
                "acquired", available_browsers=self.available_browsers.qsize()
            )
            return browser
        except asyncio.TimeoutError:
            executor_logger.error("browser_acquisition_timeout")
            raise Exception("No browser available in pool")

    async def return_browser(self, browser: Browser):
        """Return browser to the pool"""
        try:
            # Health check
            if await self._is_browser_healthy(browser):
                await self.available_browsers.put(browser)
                executor_logger.browser_event(
                    "returned", available_browsers=self.available_browsers.qsize()
                )
            else:
                # Replace unhealthy browser
                await self._replace_browser(browser)
        except Exception as e:
            executor_logger.error("browser_return_failed", error=str(e))

    async def _is_browser_healthy(self, browser: Browser) -> bool:
        """Check if browser is still healthy"""
        try:
            contexts = browser.contexts
            return len(contexts) == 0  # Should have no active contexts
        except:
            return False

    async def _replace_browser(self, old_browser: Browser):
        """Replace an unhealthy browser"""
        try:
            await old_browser.close()

            new_browser = await self.playwright.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--disable-web-security",
                    "--disable-features=VizDisplayCompositor",
                ],
            )

            # Update the browser list
            if old_browser in self.browsers:
                index = self.browsers.index(old_browser)
                self.browsers[index] = new_browser

            await self.available_browsers.put(new_browser)
            executor_logger.browser_event("replaced")

        except Exception as e:
            executor_logger.error("browser_replacement_failed", error=str(e))

    async def close(self):
        """Close all browsers in the pool"""
        executor_logger.info("browser_pool_closing")

        for browser in self.browsers:
            try:
                await browser.close()
            except Exception as e:
                executor_logger.error("browser_close_failed", error=str(e))

        if self.playwright:
            await self.playwright.stop()


class PlaywrightExecutor:
    def __init__(self):
        self.queue: List[QueueItem] = []
        self.active_executions: Dict[str, asyncio.Task] = {}
        self.browser_pool = BrowserPool(settings.browser_pool_size)
        self.circuit_breaker: Dict[str, int] = {}  # script_hash -> failure_count
        self._queue_lock = asyncio.Lock()
        self._metrics = {
            "total_executions": 0,
            "successful_executions": 0,
            "failed_executions": 0,
            "queue_additions": 0,
        }

    async def initialize(self):
        """Initialize the executor"""
        executor_logger.info("executor_initializing")
        await self.browser_pool.initialize()

        # Start queue processor
        asyncio.create_task(self._process_queue())
        executor_logger.info("executor_initialized")

    async def add_to_queue(self, request: ScriptRequest, api_key_id: int) -> str:
        """Add script execution to queue"""
        request_id = str(uuid.uuid4())

        # Validate script first
        validation_result = await validator.validate_script(request.script)
        if not validation_result.is_valid:
            raise ValueError(
                f"Script validation failed: {'; '.join(validation_result.errors)}"
            )

        async with self._queue_lock:
            # Check queue size limit
            if len(self.queue) >= settings.max_queue_size:
                raise Exception("Queue is full. Please try again later.")

            # Check circuit breaker
            script_hash = self._get_script_hash(request.script)
            if self.circuit_breaker.get(script_hash, 0) >= 5:
                raise Exception(
                    "Script has failed too many times and is temporarily blocked"
                )

            # Create queue item
            queue_item = QueueItem(
                request_id=request_id,
                api_key_id=api_key_id,
                script=request.script,
                timeout=request.timeout,
                priority=request.priority,
                tags=request.tags,
                webhook_url=request.webhook_url,
                user_agent=request.user_agent,
            )

            # Insert based on priority
            self.queue.append(queue_item)
            self.queue.sort(key=lambda x: (-x.priority, x.created_at))

            # Update queue positions
            for i, item in enumerate(self.queue):
                item.queue_position = i

            # Create execution record
            await db.create_execution(
                request_id, api_key_id, request.script, request.priority, request.tags
            )

            self._metrics["queue_additions"] += 1

            executor_logger.queue_event(
                "item_added",
                queue_size=len(self.queue),
                active_executions=len(self.active_executions),
                request_id=request_id,
                priority=request.priority,
            )

        return request_id

    async def get_queue_status(self) -> Dict[str, Any]:
        """Get current queue status"""
        async with self._queue_lock:
            queue_items = []
            for item in self.queue[:20]:  # Show top 20
                queue_items.append(
                    {
                        "request_id": item.request_id,
                        "priority": item.priority,
                        "tags": item.tags,
                        "queue_position": item.queue_position,
                        "wait_time": time.time() - item.created_at,
                    }
                )

            return {
                "total_in_queue": len(self.queue),
                "active_executions": len(self.active_executions),
                "average_wait_time": self._calculate_average_wait_time(),
                "queue_items": queue_items,
                "metrics": self._metrics.copy(),
            }

    async def _process_queue(self):
        """Main queue processing loop"""
        while True:
            try:
                # Check if we can start new executions
                if (
                    len(self.active_executions) < settings.max_concurrent_executions
                    and len(self.queue) > 0
                ):
                    async with self._queue_lock:
                        if self.queue:
                            item = self.queue.pop(0)

                            # Update remaining queue positions
                            for i, remaining_item in enumerate(self.queue):
                                remaining_item.queue_position = i

                    # Start execution
                    task = asyncio.create_task(self._execute_script(item))
                    self.active_executions[item.request_id] = task

                    executor_logger.queue_event(
                        "execution_started",
                        queue_size=len(self.queue),
                        active_executions=len(self.active_executions),
                        request_id=item.request_id,
                    )

                await asyncio.sleep(1)  # Check every second

            except Exception as e:
                executor_logger.error("queue_processor_error", error=str(e))
                await asyncio.sleep(5)

    async def _execute_script(self, item: QueueItem) -> ExecutionResult:
        """Execute a single script"""
        start_time = time.time()
        queue_wait_time = start_time - item.created_at
        browser = None
        context = None

        try:
            # Update status to running
            await db.update_execution_status(
                item.request_id, "running", queue_wait_time=queue_wait_time
            )

            executor_logger.execution_start(
                item.request_id,
                item.api_key_id,
                self._get_script_hash(item.script),
                item.queue_position,
                item.priority,
                item.timeout,
                item.tags,
            )

            # Get browser from pool
            browser = await self.browser_pool.get_browser()

            # Create video directory
            video_dir = await self._create_video_directory()

            # Create browser context with video recording
            context = await browser.new_context(
                viewport={
                    "width": settings.video_width,
                    "height": settings.video_height,
                },
                user_agent=item.user_agent,
                record_video_dir=video_dir,
                record_video_size={
                    "width": settings.video_width,
                    "height": settings.video_height,
                },
            )

            page = await context.new_page()

            # Monitor resource usage
            process = psutil.Process()
            memory_start = process.memory_info().rss / 1024 / 1024  # MB
            cpu_start = process.cpu_times()

            # Execute the script
            result = await self._run_user_script(page, item.script, item.timeout)

            # Calculate resource usage
            memory_end = process.memory_info().rss / 1024 / 1024  # MB
            cpu_end = process.cpu_times()

            memory_peak = memory_end - memory_start
            cpu_time = (
                cpu_end.user - cpu_start.user + cpu_end.system - cpu_start.system
            ) * 1000  # ms

            execution_time = time.time() - start_time

            # Close context to finalize video
            await context.close()

            # Get video file
            video_path, video_size = await self._get_video_file(
                video_dir, item.request_id
            )

            # Create execution result
            execution_result = ExecutionResult(
                success=True,
                result=result,
                execution_time=execution_time,
                memory_peak_mb=memory_peak,
                cpu_time_ms=int(cpu_time),
                video_path=video_path,
                video_size_mb=video_size,
                browser_info=BrowserInfo(
                    version=browser.version,
                    user_agent=item.user_agent or "Default",
                    viewport=f"{settings.video_width}x{settings.video_height}",
                ),
            )

            # Update database
            await db.update_execution_status(
                item.request_id,
                "completed",
                execution_time=execution_time,
                queue_wait_time=queue_wait_time,
                video_path=video_path,
                video_size_mb=video_size,
                memory_peak_mb=memory_peak,
                cpu_time_ms=int(cpu_time),
            )

            # Reset circuit breaker
            script_hash = self._get_script_hash(item.script)
            self.circuit_breaker.pop(script_hash, None)

            self._metrics["successful_executions"] += 1

            executor_logger.execution_complete(
                item.request_id,
                True,
                execution_time,
                memory_peak,
                int(cpu_time),
                video_size,
            )

            return execution_result

        except Exception as e:
            execution_time = time.time() - start_time
            error_msg = str(e)

            # Update circuit breaker
            script_hash = self._get_script_hash(item.script)
            self.circuit_breaker[script_hash] = (
                self.circuit_breaker.get(script_hash, 0) + 1
            )

            # Update database
            await db.update_execution_status(
                item.request_id,
                "failed",
                execution_time=execution_time,
                queue_wait_time=queue_wait_time,
                error_message=error_msg,
            )

            self._metrics["failed_executions"] += 1

            executor_logger.execution_complete(
                item.request_id, False, execution_time, error=error_msg
            )

            return ExecutionResult(
                success=False, error=error_msg, execution_time=execution_time
            )

        finally:
            # Clean up
            try:
                if context:
                    await context.close()
                if browser:
                    await self.browser_pool.return_browser(browser)
            except Exception as e:
                executor_logger.error("execution_cleanup_failed", error=str(e))

            # Remove from active executions
            self.active_executions.pop(item.request_id, None)
            self._metrics["total_executions"] += 1

    async def _run_user_script(self, page: Page, script: str, timeout: int) -> Any:
        """Execute user script safely"""
        # Create a safe execution environment
        safe_globals = {
            "page": page,
            "print": print,
            "len": len,
            "str": str,
            "int": int,
            "float": float,
            "bool": bool,
            "list": list,
            "dict": dict,
            "tuple": tuple,
            "set": set,
            "range": range,
            "enumerate": enumerate,
            "zip": zip,
            "json": json,
            "time": __import__("time"),
            "datetime": __import__("datetime"),
            "asyncio": asyncio,
            "__builtins__": {
                "__name__": "__main__",
                "Exception": Exception,
                "ValueError": ValueError,
                "TypeError": TypeError,
                "KeyError": KeyError,
                "IndexError": IndexError,
                "AttributeError": AttributeError,
            },
        }

        # Execute with timeout
        try:
            exec(script, safe_globals)

            if "main" in safe_globals and callable(safe_globals["main"]):
                result = await asyncio.wait_for(safe_globals["main"](), timeout=timeout)
                return result
            else:
                raise Exception("Script must define an async main() function")

        except asyncio.TimeoutError:
            raise Exception(f"Script execution timed out after {timeout} seconds")

    async def _create_video_directory(self) -> str:
        """Create directory for video recording"""
        today = datetime.now()
        video_dir = (
            Path("data/videos")
            / str(today.year)
            / f"{today.month:02d}"
            / f"{today.day:02d}"
        )
        video_dir.mkdir(parents=True, exist_ok=True)
        return str(video_dir)

    async def _get_video_file(self, video_dir: str, request_id: str) -> tuple:
        """Get the recorded video file"""
        video_dir_path = Path(video_dir)
        video_files = list(video_dir_path.glob("*.webm"))

        if video_files:
            video_file = video_files[0]
            new_video_path = video_dir_path / f"{request_id}.webm"
            video_file.rename(new_video_path)

            # Get file size
            file_size_mb = new_video_path.stat().st_size / 1024 / 1024

            return str(new_video_path), file_size_mb

        return None, 0

    def _get_script_hash(self, script: str) -> str:
        """Get hash of script for circuit breaker"""
        import hashlib

        return hashlib.sha256(script.encode()).hexdigest()[:16]

    def _calculate_average_wait_time(self) -> float:
        """Calculate average wait time for items in queue"""
        if not self.queue:
            return 0.0

        now = time.time()
        total_wait = sum(now - item.created_at for item in self.queue)
        return total_wait / len(self.queue)

    async def close(self):
        """Clean shutdown"""
        executor_logger.info("executor_shutting_down")

        # Wait for active executions to complete
        if self.active_executions:
            await asyncio.gather(
                *self.active_executions.values(), return_exceptions=True
            )

        await self.browser_pool.close()
        executor_logger.info("executor_shutdown_complete")


# Global executor instance
executor = PlaywrightExecutor()
