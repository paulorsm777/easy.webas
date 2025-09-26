import asyncio
import time
from datetime import datetime
from typing import Optional, Dict, Any
import httpx
import json

from .config import settings
from .models import WebhookPayload
from .logger import webhook_logger


class WebhookManager:
    def __init__(self):
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.webhook_timeout),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=5),
        )
        self._retry_queue = []
        self._retry_task = None

    async def start(self):
        """Start webhook manager"""
        webhook_logger.info("webhook_manager_starting")

        # Start retry processor
        self._retry_task = asyncio.create_task(self._process_retry_queue())

        webhook_logger.info("webhook_manager_started")

    async def stop(self):
        """Stop webhook manager"""
        webhook_logger.info("webhook_manager_stopping")

        # Stop retry processor
        if self._retry_task:
            self._retry_task.cancel()
            try:
                await self._retry_task
            except asyncio.CancelledError:
                pass

        # Close HTTP client
        await self.client.aclose()

        webhook_logger.info("webhook_manager_stopped")

    async def send_webhook(
        self, webhook_url: str, payload: WebhookPayload, retry_count: int = 0
    ) -> bool:
        """Send webhook notification"""
        if not webhook_url:
            return False

        webhook_logger.info(
            "webhook_sending",
            url=webhook_url,
            request_id=payload.request_id,
            status=payload.status,
            retry_count=retry_count,
        )

        try:
            # Prepare payload
            payload_dict = {
                "request_id": payload.request_id,
                "api_key_id": payload.api_key_id,
                "status": payload.status,
                "execution_time": payload.execution_time,
                "video_url": payload.video_url,
                "result": payload.result,
                "error": payload.error,
                "timestamp": payload.timestamp.isoformat(),
            }

            # Send webhook
            response = await self.client.post(
                webhook_url,
                json=payload_dict,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "PlaywrightServer/1.0",
                    "X-Webhook-Event": "execution_completed",
                },
            )

            # Check response
            if response.status_code < 300:
                webhook_logger.info(
                    "webhook_success",
                    url=webhook_url,
                    request_id=payload.request_id,
                    status_code=response.status_code,
                    response_time_ms=(response.elapsed.total_seconds() * 1000),
                )
                return True
            else:
                webhook_logger.warning(
                    "webhook_failed_status",
                    url=webhook_url,
                    request_id=payload.request_id,
                    status_code=response.status_code,
                    response_text=response.text[:200],
                )

                # Queue for retry if retriable status
                if (
                    self._is_retriable_status(response.status_code)
                    and retry_count < settings.max_webhook_retries
                ):
                    await self._queue_for_retry(webhook_url, payload, retry_count + 1)

                return False

        except httpx.TimeoutException:
            webhook_logger.warning(
                "webhook_timeout",
                url=webhook_url,
                request_id=payload.request_id,
                timeout=settings.webhook_timeout,
            )

            # Queue for retry
            if retry_count < settings.max_webhook_retries:
                await self._queue_for_retry(webhook_url, payload, retry_count + 1)

            return False

        except Exception as e:
            webhook_logger.error(
                "webhook_error",
                url=webhook_url,
                request_id=payload.request_id,
                error=str(e),
            )

            # Queue for retry for network errors
            if retry_count < settings.max_webhook_retries and self._is_retriable_error(
                e
            ):
                await self._queue_for_retry(webhook_url, payload, retry_count + 1)

            return False

    async def send_execution_webhook(
        self,
        request_id: str,
        api_key_id: int,
        status: str,
        execution_time: float,
        video_url: Optional[str] = None,
        result: Any = None,
        error: Optional[str] = None,
        webhook_url: Optional[str] = None,
    ) -> bool:
        """Send webhook for execution completion"""

        # Get webhook URL from API key if not provided
        if not webhook_url:
            from .database import db

            api_key = await db.get_api_key_by_id(api_key_id)
            if api_key and api_key.webhook_url:
                webhook_url = api_key.webhook_url

        if not webhook_url:
            webhook_logger.debug("webhook_skipped_no_url", request_id=request_id)
            return False

        # Create payload
        payload = WebhookPayload(
            request_id=request_id,
            api_key_id=api_key_id,
            status=status,
            execution_time=execution_time,
            video_url=video_url,
            result=result,
            error=error,
            timestamp=datetime.now(),
        )

        # Send webhook
        success = await self.send_webhook(webhook_url, payload)

        # Update database with webhook status
        from .database import db

        webhook_status = "sent" if success else "failed"
        await db.update_execution_status(
            request_id=request_id,
            status=None,  # Don't change execution status
            webhook_status=webhook_status,
        )

        return success

    def _is_retriable_status(self, status_code: int) -> bool:
        """Check if HTTP status code is retriable"""
        # Retry on server errors and rate limiting
        return status_code >= 500 or status_code == 429

    def _is_retriable_error(self, error: Exception) -> bool:
        """Check if error is retriable"""
        # Retry on network errors
        return isinstance(error, (httpx.ConnectError, httpx.NetworkError))

    async def _queue_for_retry(
        self, webhook_url: str, payload: WebhookPayload, retry_count: int
    ):
        """Queue webhook for retry"""
        # Calculate retry delay with exponential backoff
        delay = min(60, 2**retry_count)  # Cap at 60 seconds
        retry_time = time.time() + delay

        self._retry_queue.append(
            {
                "webhook_url": webhook_url,
                "payload": payload,
                "retry_count": retry_count,
                "retry_time": retry_time,
            }
        )

        webhook_logger.info(
            "webhook_queued_for_retry",
            request_id=payload.request_id,
            retry_count=retry_count,
            retry_delay=delay,
        )

    async def _process_retry_queue(self):
        """Process webhook retry queue"""
        while True:
            try:
                if not self._retry_queue:
                    await asyncio.sleep(5)
                    continue

                current_time = time.time()
                ready_items = []

                # Find items ready for retry
                for item in self._retry_queue[:]:
                    if item["retry_time"] <= current_time:
                        ready_items.append(item)
                        self._retry_queue.remove(item)

                # Process ready items
                for item in ready_items:
                    try:
                        await self.send_webhook(
                            item["webhook_url"], item["payload"], item["retry_count"]
                        )
                    except Exception as e:
                        webhook_logger.error(
                            "webhook_retry_failed",
                            request_id=item["payload"].request_id,
                            error=str(e),
                        )

                await asyncio.sleep(1)

            except Exception as e:
                webhook_logger.error("retry_queue_processor_error", error=str(e))
                await asyncio.sleep(5)

    async def test_webhook_url(self, webhook_url: str) -> Dict[str, Any]:
        """Test a webhook URL with a sample payload"""
        webhook_logger.info("webhook_testing", url=webhook_url)

        # Create test payload
        test_payload = WebhookPayload(
            request_id="test-" + str(int(time.time())),
            api_key_id=0,
            status="completed",
            execution_time=15.5,
            video_url=None,
            result={"test": True, "message": "This is a test webhook"},
            error=None,
            timestamp=datetime.now(),
        )

        start_time = time.time()

        try:
            payload_dict = {
                "request_id": test_payload.request_id,
                "api_key_id": test_payload.api_key_id,
                "status": test_payload.status,
                "execution_time": test_payload.execution_time,
                "video_url": test_payload.video_url,
                "result": test_payload.result,
                "error": test_payload.error,
                "timestamp": test_payload.timestamp.isoformat(),
                "test": True,
            }

            response = await self.client.post(
                webhook_url,
                json=payload_dict,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "PlaywrightServer/1.0",
                    "X-Webhook-Event": "test",
                    "X-Webhook-Test": "true",
                },
            )

            response_time = (time.time() - start_time) * 1000

            result = {
                "success": response.status_code < 300,
                "status_code": response.status_code,
                "response_time_ms": round(response_time, 2),
                "response_headers": dict(response.headers),
                "response_body": response.text[:500] if response.text else None,
            }

            webhook_logger.info(
                "webhook_test_completed",
                url=webhook_url,
                success=result["success"],
                status_code=result["status_code"],
                response_time=result["response_time_ms"],
            )

            return result

        except httpx.TimeoutException:
            result = {
                "success": False,
                "error": "timeout",
                "message": f"Request timed out after {settings.webhook_timeout} seconds",
            }

            webhook_logger.warning("webhook_test_timeout", url=webhook_url)
            return result

        except Exception as e:
            result = {"success": False, "error": "connection_error", "message": str(e)}

            webhook_logger.error("webhook_test_error", url=webhook_url, error=str(e))
            return result

    async def get_webhook_stats(self) -> Dict[str, Any]:
        """Get webhook statistics"""
        from .database import db

        # Get webhook statistics from database
        async with db.get_connection() as conn:
            # Total webhooks by status
            cursor = await conn.execute("""
                SELECT webhook_status, COUNT(*) as count
                FROM executions
                WHERE webhook_status IS NOT NULL
                GROUP BY webhook_status
            """)
            status_stats = {
                row["webhook_status"]: row["count"] for row in await cursor.fetchall()
            }

            # Recent webhook activity
            cursor = await conn.execute("""
                SELECT webhook_status, COUNT(*) as count
                FROM executions
                WHERE webhook_status IS NOT NULL
                AND created_at > datetime('now', '-24 hours')
                GROUP BY webhook_status
            """)
            recent_stats = {
                row["webhook_status"]: row["count"] for row in await cursor.fetchall()
            }

            # Failed webhooks needing attention
            cursor = await conn.execute("""
                SELECT COUNT(*) as count
                FROM executions
                WHERE webhook_status = 'failed'
                AND created_at > datetime('now', '-1 hour')
            """)
            recent_failures = (await cursor.fetchone())["count"]

        return {
            "total_webhooks": sum(status_stats.values()),
            "status_breakdown": status_stats,
            "last_24h": recent_stats,
            "recent_failures": recent_failures,
            "retry_queue_size": len(self._retry_queue),
            "settings": {
                "max_retries": settings.max_webhook_retries,
                "timeout_seconds": settings.webhook_timeout,
            },
        }


# Global webhook manager
webhook_manager = WebhookManager()
