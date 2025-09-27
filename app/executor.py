import asyncio
import uuid
import hashlib
import json
import time
import psutil
import ast
import os
import shutil
from datetime import datetime
from typing import Dict, Any, Optional, List, Callable
from dataclasses import dataclass, field
from playwright.async_api import async_playwright, Browser, BrowserContext, Page
import structlog

from app.config import settings
from app.models import (
    ScriptRequest,
    ScriptResponse,
    ExecutionStatus,
    BrowserInfo,
    ResourceUsage,
    ScriptAnalysis,
)
from app.database import record_execution, update_execution_status
from app.logger import execution_logger
from app.video_service import VideoService


logger = structlog.get_logger()


@dataclass
class QueueItem:
    request_id: str
    script: str
    timeout: int
    priority: int
    api_key_id: int
    webhook_url: Optional[str]
    tags: List[str]
    user_agent: Optional[str]
    created_at: float
    position: int = 0
    estimated_duration: float = 60.0

    def __lt__(self, other):
        # Higher priority first, then FIFO
        if self.priority != other.priority:
            return self.priority > other.priority
        return self.created_at < other.created_at


@dataclass
class ExecutionResult:
    success: bool
    result: Any = None
    error: str = None
    execution_time: float = 0.0
    video_path: str = None
    video_size_mb: float = 0.0
    memory_peak_mb: float = 0.0
    cpu_time_ms: int = 0
    browser_info: Optional[BrowserInfo] = None
    script_analysis: Optional[ScriptAnalysis] = None


class BrowserPool:
    """Pool of pre-warmed browsers"""

    def __init__(self, pool_size: int = 10):
        self.pool_size = pool_size
        self.browsers: List[Browser] = []
        self.available_browsers: List[Browser] = []
        self.playwright = None
        self._lock = asyncio.Lock()

    async def initialize(self):
        """Initialize browser pool"""
        self.playwright = await async_playwright().start()

        for i in range(self.pool_size):
            try:
                browser = await self._create_browser()
                self.browsers.append(browser)
                self.available_browsers.append(browser)
                execution_logger.log_browser_event("created", f"browser_{i}")
            except Exception as e:
                logger.error("Failed to create browser", browser_index=i, error=str(e))

        logger.info(
            "Browser pool initialized",
            total_browsers=len(self.browsers),
            available_browsers=len(self.available_browsers),
        )

    async def _create_browser(self) -> Browser:
        """Create a new browser instance"""
        return await self.playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-web-security",
                "--disable-features=VizDisplayCompositor",
                "--disable-background-timer-throttling",
                "--disable-backgrounding-occluded-windows",
                "--disable-renderer-backgrounding",
            ],
        )

    async def get_browser(self) -> Browser:
        """Get an available browser from the pool"""
        async with self._lock:
            if self.available_browsers:
                browser = self.available_browsers.pop()
                execution_logger.log_browser_event(
                    "acquired", browser_id=str(id(browser))
                )
                return browser

            # If no browsers available, create a new one
            try:
                browser = await self._create_browser()
                execution_logger.log_browser_event(
                    "created_on_demand", browser_id=str(id(browser))
                )
                return browser
            except Exception as e:
                logger.error("Failed to create browser on demand", error=str(e))
                raise

    async def return_browser(self, browser: Browser):
        """Return a browser to the pool"""
        async with self._lock:
            try:
                # Check if browser is still healthy
                if not browser.is_connected():
                    await browser.close()
                    # Replace with new browser
                    new_browser = await self._create_browser()
                    self.available_browsers.append(new_browser)
                    execution_logger.log_browser_event(
                        "replaced",
                        old_browser_id=str(id(browser)),
                        new_browser_id=str(id(new_browser)),
                    )
                else:
                    self.available_browsers.append(browser)
                    execution_logger.log_browser_event(
                        "returned", browser_id=str(id(browser))
                    )

            except Exception as e:
                logger.error("Failed to return browser", error=str(e))
                # Close the problematic browser
                try:
                    await browser.close()
                except:
                    pass

    async def health_check(self) -> Dict[str, Any]:
        """Check health of browser pool"""
        healthy_browsers = 0
        for browser in self.browsers:
            try:
                if browser.is_connected():
                    healthy_browsers += 1
            except:
                pass

        return {
            "total_browsers": len(self.browsers),
            "available_browsers": len(self.available_browsers),
            "healthy_browsers": healthy_browsers,
        }

    async def close(self):
        """Close all browsers and cleanup"""
        for browser in self.browsers:
            try:
                await browser.close()
            except:
                pass

        if self.playwright:
            await self.playwright.stop()


class ScriptValidator:
    """Validates scripts for security and performance"""

    FORBIDDEN_IMPORTS = {
        "os",
        "subprocess",
        "sys",
        "eval",
        "exec",
        "__import__",
        "open",
        "file",
        "input",
        "raw_input",
        "compile",
    }

    DANGEROUS_FUNCTIONS = {
        "eval",
        "exec",
        "compile",
        "getattr",
        "setattr",
        "delattr",
        "globals",
        "locals",
        "vars",
        "__import__",
    }

    def validate(self, script: str) -> ScriptAnalysis:
        """Validate script and return analysis"""
        warnings = []
        detected_operations = []
        complexity = "low"

        try:
            tree = ast.parse(script)

            # Check for forbidden imports
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name in self.FORBIDDEN_IMPORTS:
                            warnings.append(f"Forbidden import: {alias.name}")

                elif isinstance(node, ast.ImportFrom):
                    if node.module in self.FORBIDDEN_IMPORTS:
                        warnings.append(f"Forbidden import: {node.module}")

                elif isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Name):
                        if node.func.id in self.DANGEROUS_FUNCTIONS:
                            warnings.append(f"Dangerous function: {node.func.id}")

                # Detect operations
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    method = node.func.attr
                    if method in ["goto", "navigate"]:
                        detected_operations.append("navigation")
                    elif method in ["fill", "type", "press"]:
                        detected_operations.append("form_filling")
                    elif method in ["click", "tap"]:
                        detected_operations.append("interaction")
                    elif method in ["wait_for_selector", "wait_for"]:
                        detected_operations.append("waiting")
                    elif method in ["screenshot", "pdf"]:
                        detected_operations.append("capture")

            # Estimate complexity
            node_count = len(list(ast.walk(tree)))
            if node_count > 100:
                complexity = "high"
            elif node_count > 50:
                complexity = "medium"

        except SyntaxError as e:
            warnings.append(f"Syntax error: {str(e)}")

        return ScriptAnalysis(
            estimated_complexity=complexity,
            detected_operations=list(set(detected_operations)),
            security_warnings=warnings,
        )


class PlaywrightExecutor:
    """Main executor for Playwright scripts"""

    def __init__(self):
        self.browser_pool = BrowserPool(settings.BROWSER_POOL_SIZE)
        self.video_service = VideoService()
        self.validator = ScriptValidator()
        self.execution_queue: asyncio.PriorityQueue = asyncio.PriorityQueue(
            maxsize=settings.MAX_QUEUE_SIZE
        )
        self.active_executions: Dict[str, asyncio.Task] = {}
        self.queue_position = 0
        self._running = False
        self._worker_tasks: List[asyncio.Task] = []

    async def initialize(self):
        """Initialize executor"""
        await self.browser_pool.initialize()
        await self.video_service.initialize()

        # Start worker tasks
        self._running = True
        for i in range(settings.MAX_CONCURRENT_EXECUTIONS):
            task = asyncio.create_task(self._worker(f"worker_{i}"))
            self._worker_tasks.append(task)

        logger.info(
            "Playwright executor initialized",
            concurrent_workers=settings.MAX_CONCURRENT_EXECUTIONS,
            queue_size=settings.MAX_QUEUE_SIZE,
        )

    async def queue_script(self, request: ScriptRequest, api_key_id: int) -> str:
        """Queue a script for execution"""
        request_id = str(uuid.uuid4())
        script_hash = hashlib.sha256(request.script.encode()).hexdigest()

        # Validate script
        script_analysis = self.validator.validate(request.script)

        if script_analysis.security_warnings:
            logger.warning(
                "Script has security warnings",
                request_id=request_id,
                warnings=script_analysis.security_warnings,
            )

        # Record in database
        await record_execution(
            request_id=request_id,
            api_key_id=api_key_id,
            script_hash=script_hash,
            script_size=len(request.script),
            priority=request.priority,
            tags=request.tags,
        )

        # Create queue item
        queue_item = QueueItem(
            request_id=request_id,
            script=request.script,
            timeout=request.timeout,
            priority=request.priority,
            api_key_id=api_key_id,
            webhook_url=request.webhook_url,
            tags=request.tags,
            user_agent=request.user_agent,
            created_at=time.time(),
            position=self.queue_position,
        )

        self.queue_position += 1

        try:
            await self.execution_queue.put(queue_item)
            execution_logger.log_queue_event(
                "item_added",
                queue_size=self.execution_queue.qsize(),
                active_executions=len(self.active_executions),
                request_id=request_id,
                priority=request.priority,
            )
        except asyncio.QueueFull:
            await update_execution_status(
                request_id, ExecutionStatus.FAILED, error_message="Queue is full"
            )
            raise Exception("Execution queue is full")

        return request_id

    async def _worker(self, worker_id: str):
        """Worker task that processes queue items"""
        logger.info("Worker started", worker_id=worker_id)

        while self._running:
            try:
                # Get next item from queue
                queue_item = await asyncio.wait_for(
                    self.execution_queue.get(), timeout=1.0
                )

                execution_logger.log_queue_event(
                    "item_processing",
                    queue_size=self.execution_queue.qsize(),
                    active_executions=len(self.active_executions),
                    request_id=queue_item.request_id,
                    worker_id=worker_id,
                )

                # Execute the script
                task = asyncio.create_task(self._execute_script(queue_item))
                self.active_executions[queue_item.request_id] = task

                try:
                    await task
                finally:
                    self.active_executions.pop(queue_item.request_id, None)
                    self.execution_queue.task_done()

            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error("Worker error", worker_id=worker_id, error=str(e))

        logger.info("Worker stopped", worker_id=worker_id)

    async def _execute_script(self, queue_item: QueueItem):
        """Execute a single script"""
        start_time = time.time()
        request_id = queue_item.request_id

        execution_logger.log_execution_start(
            request_id=request_id,
            api_key_id=queue_item.api_key_id,
            script_hash=hashlib.sha256(queue_item.script.encode()).hexdigest(),
            queue_position=queue_item.position,
            priority=queue_item.priority,
            tags=queue_item.tags,
        )

        # Update status to running
        queue_wait_time = start_time - queue_item.created_at
        await update_execution_status(
            request_id, ExecutionStatus.RUNNING, queue_wait_time=queue_wait_time
        )

        browser = None
        context = None
        page = None
        video_path = None

        try:
            # Get browser from pool
            browser = await self.browser_pool.get_browser()

            # Create context with video recording
            context_options = {
                "viewport": {
                    "width": settings.VIDEO_WIDTH,
                    "height": settings.VIDEO_HEIGHT,
                },
                "record_video_dir": "./data/videos",
                "record_video_size": {
                    "width": settings.VIDEO_WIDTH,
                    "height": settings.VIDEO_HEIGHT,
                },
            }

            if queue_item.user_agent:
                context_options["user_agent"] = queue_item.user_agent

            context = await browser.new_context(**context_options)
            page = await context.new_page()

            # Monitor resource usage
            process = psutil.Process()
            initial_memory = process.memory_info().rss / 1024 / 1024  # MB
            initial_cpu_time = process.cpu_times().user + process.cpu_times().system

            # Execute script with timeout
            result = await asyncio.wait_for(
                self._run_script(page, queue_item.script), timeout=queue_item.timeout
            )

            # Calculate resource usage
            final_memory = process.memory_info().rss / 1024 / 1024
            final_cpu_time = process.cpu_times().user + process.cpu_times().system
            memory_peak_mb = max(initial_memory, final_memory)
            cpu_time_ms = int((final_cpu_time - initial_cpu_time) * 1000)

            execution_time = time.time() - start_time

            # Close context to save video and get path
            if page.video:
                video_path = await page.video.path()
                # Rename video to use request_id
                if video_path and os.path.exists(video_path):
                    import shutil

                    new_video_path = f"./data/videos/{request_id}.webm"
                    shutil.move(video_path, new_video_path)
                    video_path = new_video_path
            else:
                video_path = None

            video_size_mb = await self._get_video_size(video_path) if video_path else 0

            # Get browser info
            browser_info = BrowserInfo(
                version=browser.version,
                user_agent=await page.evaluate("navigator.userAgent"),
                viewport=f"{settings.VIDEO_WIDTH}x{settings.VIDEO_HEIGHT}",
            )

            # Update execution status
            await update_execution_status(
                request_id=request_id,
                status=ExecutionStatus.COMPLETED,
                execution_time=execution_time,
                queue_wait_time=queue_wait_time,
                video_path=video_path,
                video_size_mb=video_size_mb,
                memory_peak_mb=memory_peak_mb,
                cpu_time_ms=cpu_time_ms,
            )

            execution_logger.log_execution_complete(
                request_id=request_id,
                success=True,
                execution_time=execution_time,
                result_size=len(str(result)) if result else 0,
            )

        except asyncio.TimeoutError:
            # Try to save video before closing context
            video_path = None
            if page and page.video:
                try:
                    video_path = await page.video.path()
                    if video_path and os.path.exists(video_path):
                        import shutil

                        new_video_path = f"./data/videos/{request_id}.webm"
                        shutil.move(video_path, new_video_path)
                        video_path = new_video_path
                except:
                    pass

            # Close context to save any recorded video
            if context:
                try:
                    await context.close()
                except:
                    pass

            execution_time = time.time() - start_time
            await update_execution_status(
                request_id=request_id,
                status=ExecutionStatus.TIMEOUT,
                error_message=f"Script timed out after {queue_item.timeout} seconds",
                execution_time=execution_time,
                queue_wait_time=queue_wait_time,
                video_path=video_path,
            )

            execution_logger.log_execution_complete(
                request_id=request_id,
                success=False,
                execution_time=execution_time,
                error="Timeout",
            )

        except Exception as e:
            # Try to save video before closing context
            video_path = None
            if page and page.video:
                try:
                    video_path = await page.video.path()
                    if video_path and os.path.exists(video_path):
                        import shutil

                        new_video_path = f"./data/videos/{request_id}.webm"
                        shutil.move(video_path, new_video_path)
                        video_path = new_video_path
                except:
                    pass

            # Close context to save any recorded video
            if context:
                try:
                    await context.close()
                except:
                    pass

            execution_time = time.time() - start_time
            error_message = str(e)

            await update_execution_status(
                request_id=request_id,
                status=ExecutionStatus.FAILED,
                error_message=error_message,
                execution_time=execution_time,
                queue_wait_time=queue_wait_time,
                video_path=video_path,
            )

            execution_logger.log_execution_complete(
                request_id=request_id,
                success=False,
                execution_time=execution_time,
                error=error_message,
            )

        finally:
            # Cleanup
            if context:
                try:
                    await context.close()
                except:
                    pass

            if browser:
                await self.browser_pool.return_browser(browser)

    async def _run_script(self, page: Page, script: str) -> Any:
        """Run the actual script in a secure namespace"""
        # Create secure namespace
        namespace = {
            "page": page,
            "asyncio": asyncio,
            "json": json,
            "datetime": datetime,
            "time": time,
        }

        # Execute script
        exec(script, namespace)

        # Call main function if it exists
        if "main" in namespace and callable(namespace["main"]):
            return await namespace["main"]()

        return None

    async def _get_video_path(self, page) -> Optional[str]:
        """Get video path from page"""
        try:
            if page.video:
                return await page.video.path()
            return None
        except:
            return None

    async def _get_video_size(self, video_path: str) -> float:
        """Get video file size in MB"""
        try:
            import os

            size_bytes = os.path.getsize(video_path)
            return size_bytes / 1024 / 1024
        except:
            return 0.0

    async def get_queue_status(self) -> Dict[str, Any]:
        """Get current queue status"""
        queue_items = []
        temp_items = []

        # Extract all items to inspect them
        try:
            while not self.execution_queue.empty():
                item = await asyncio.wait_for(
                    self.execution_queue.get_nowait(), timeout=0.1
                )
                temp_items.append(item)
                queue_items.append(
                    {
                        "request_id": item.request_id,
                        "priority": item.priority,
                        "created_at": item.created_at,
                        "estimated_duration": item.estimated_duration,
                        "tags": item.tags,
                    }
                )
        except:
            pass

        # Put items back
        for item in temp_items:
            await self.execution_queue.put(item)

        total_queued = len(queue_items)
        total_running = len(self.active_executions)

        # Estimate wait time (simplified)
        estimated_wait_time = total_queued * 60.0  # Rough estimate

        return {
            "total_queued": total_queued,
            "total_running": total_running,
            "estimated_wait_time": estimated_wait_time,
            "queue_items": queue_items[:10],  # Show first 10 items
        }

    async def health_check(self) -> Dict[str, Any]:
        """Comprehensive health check"""
        browser_health = await self.browser_pool.health_check()
        queue_status = await self.get_queue_status()

        return {
            "browser_pool": browser_health,
            "queue": {
                "size": queue_status["total_queued"],
                "active_executions": queue_status["total_running"],
                "is_healthy": queue_status["total_queued"]
                < settings.MAX_QUEUE_SIZE * 0.8,
            },
            "workers": {
                "total": len(self._worker_tasks),
                "running": sum(1 for task in self._worker_tasks if not task.done()),
            },
        }

    async def shutdown(self):
        """Graceful shutdown"""
        logger.info("Shutting down Playwright executor")

        # Stop workers
        self._running = False

        # Wait for active executions to complete (with timeout)
        if self.active_executions:
            try:
                await asyncio.wait_for(
                    asyncio.gather(
                        *self.active_executions.values(), return_exceptions=True
                    ),
                    timeout=30.0,
                )
            except asyncio.TimeoutError:
                logger.warning("Some executions didn't complete during shutdown")

        # Cancel worker tasks
        for task in self._worker_tasks:
            task.cancel()

        await asyncio.gather(*self._worker_tasks, return_exceptions=True)

        # Close browser pool
        await self.browser_pool.close()

        logger.info("Playwright executor shutdown complete")


# Global executor instance
executor = PlaywrightExecutor()
